/**
 * Step ① of the Auto flow: choose the mission to fly.
 *
 *   list     every mission saved on this laptop — ready to fly, or what to fix
 *   view     one mission: its plan drawn, its points, the agent's check;
 *            Edit, Delete, or Use this mission
 *   edit     the room and the path (MissionEditor)
 *
 * "Use this mission" is what completes the step; the flow then moves to ②.
 * Every list has its four states: loading, empty, an error with a retry, and
 * content (desktop design rule, and pages-and-windows.txt).
 */

import { useCallback, useEffect, useState } from "react";
import type { Run } from "@/App";
import {
  api, AgentError, type MissionView, type PlanLimits, type RoomView, type Telemetry, type XY,
} from "@/lib/agent";
import { formatDateTime, formatDuration, formatMetres } from "@/lib/format";
import { Button, Message, Panel, SkeletonPanel, StatusDot } from "@/components/ui";
import { SmallButton } from "./fields";
import { blankMission, blankRoom, MissionEditor, outerOf, ProblemList, type Draft } from "./MissionEditor";
import { PlanCanvas } from "./PlanCanvas";

type View = { kind: "list" } | { kind: "view"; id: string } | { kind: "edit"; draft: Draft };

type Loaded = { missions: MissionView[]; rooms: RoomView[]; limits: PlanLimits };

export function dronePosition(telemetry: Telemetry | null): XY | null {
  const x = telemetry?.values["stateEstimate.x"];
  const y = telemetry?.values["stateEstimate.y"];
  return x === undefined || y === undefined ? null : [x, y];
}

export function MissionStep({ run, telemetry, selectedId, onUse, openEditor }: {
  run: Run;
  telemetry: Telemetry | null;
  selectedId: string | null;
  onUse: (mission: MissionView) => void;
  /** Harness only: open this mission's editor once loaded. */
  openEditor?: string;
}) {
  const [view, setView] = useState<View>({ kind: "list" });
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [missions, rooms, limits] = await Promise.all([api.missions(), api.rooms(), api.planLimits()]);
      setLoaded({ missions, rooms, limits });
    } catch (e) {
      setError(e instanceof AgentError ? e.message : "The saved missions could not be read.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const [opened, setOpened] = useState(false);
  useEffect(() => {
    if (!openEditor || opened || !loaded) return;
    const mission = loaded.missions.find((m) => m.id === openEditor);
    const room = mission && loaded.rooms.find((r) => r.id === mission.room_id);
    if (mission && room) {
      setView({ kind: "edit", draft: { room, mission, roomIsNew: false, missionIsNew: false } });
      setOpened(true);
    }
  }, [openEditor, opened, loaded]);

  const drone = dronePosition(telemetry);

  if (error) {
    return (
      <Panel title="Missions">
        <div className="grid gap-3">
          <Message tone="critical" text={error} />
          <div><Button onClick={() => void load()}>Try again</Button></div>
        </div>
      </Panel>
    );
  }
  if (!loaded) return <SkeletonPanel lines={4} />;

  const { missions, rooms, limits } = loaded;
  const roomOf = (id: string) => rooms.find((r) => r.id === id) ?? null;

  if (view.kind === "edit") {
    const others = missions.filter((m) => m.room_id === view.draft.room.id && m.id !== view.draft.mission.id).length;
    return (
      <MissionEditor
        draft={view.draft} limits={limits} run={run} drone={drone} missionsInRoom={others}
        onCancel={() => setView(view.draft.missionIsNew ? { kind: "list" } : { kind: "view", id: view.draft.mission.id })}
        onSaved={(saved) => { void load(); setView({ kind: "view", id: saved.id }); }}
      />
    );
  }

  if (view.kind === "view") {
    const mission = missions.find((m) => m.id === view.id);
    if (!mission) {
      return (
        <Panel title="Mission">
          <div className="grid gap-3">
            <Message tone="warning" text="That mission is no longer on this computer." />
            <div><Button onClick={() => setView({ kind: "list" })}>Back to the missions</Button></div>
          </div>
        </Panel>
      );
    }
    return (
      <MissionDetail
        mission={mission} room={roomOf(mission.room_id)} limits={limits} drone={drone} run={run}
        selected={selectedId === mission.id}
        onBack={() => setView({ kind: "list" })}
        onEdit={(room) => setView({ kind: "edit", draft: { room, mission, roomIsNew: false, missionIsNew: false } })}
        onDeleted={() => { void load(); setView({ kind: "list" }); }}
        onUse={() => onUse(mission)}
      />
    );
  }

  return (
    <MissionList
      missions={missions} rooms={rooms} limits={limits} selectedId={selectedId}
      onView={(id) => setView({ kind: "view", id })}
      onNew={(room) => {
        const fresh = room ?? blankRoom(limits);
        setView({ kind: "edit", draft: {
          room: fresh, mission: blankMission(fresh, limits), roomIsNew: room === null, missionIsNew: true,
        } });
      }}
    />
  );
}

function MissionList({ missions, rooms, limits, selectedId, onView, onNew }: {
  missions: MissionView[];
  rooms: RoomView[];
  limits: PlanLimits;
  selectedId: string | null;
  onView: (id: string) => void;
  onNew: (room: RoomView | null) => void;
}) {
  const [roomChoice, setRoomChoice] = useState<string>(rooms[0]?.id ?? "");
  const roomName = (id: string) => rooms.find((r) => r.id === id)?.name ?? "a missing room";

  return (
    <Panel
      title="Saved missions"
      note="A mission is a floor plan — the room's geofence and obstacles — and the inspection points the drone flies to, in order. Pick one to fly, or plan a new one."
      bodyClassName="grid gap-3 p-4"
    >
      <div className="flex flex-wrap items-end gap-2 border-b border-[var(--border)] pb-3">
        <label className="grid gap-1 text-xs">
          <span className="eyebrow">Plan a new mission in</span>
          <select
            value={roomChoice}
            onChange={(e) => setRoomChoice(e.target.value)}
            className="min-h-9 border border-[var(--border)] bg-[var(--surface-2)] px-2 text-sm"
          >
            {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            <option value="">A new room</option>
          </select>
        </label>
        <Button variant="primary" onClick={() => onNew(rooms.find((r) => r.id === roomChoice) ?? null)}>
          New mission
        </Button>
        <p className="w-full text-xs text-[var(--muted)]">
          {limits.outer.measured ? "Rooms are drawn inside the measured Lighthouse coverage."
            : "Coverage is not measured yet, so rooms are drawn inside the agent's default area (±2 m)."}
        </p>
      </div>

      {missions.length === 0 ? (
        <p className="text-sm">No missions yet. Plan the first one above: draw the room, then place the points.</p>
      ) : (
        <ul className="grid gap-2">
          {missions.map((m) => {
            const errors = m.problems.filter((p) => p.severity === "error").length;
            return (
              <li key={m.id}>
                <button
                  type="button"
                  onClick={() => onView(m.id)}
                  className={`grid w-full gap-1 border border-l-4 bg-[var(--surface)] px-3 py-2 text-left hover:bg-[var(--surface-2)] ${
                    selectedId === m.id ? "border-l-[var(--primary)]" : "border-l-[var(--border)]"} border-[var(--border)]`}
                >
                  <span className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="wrap-anywhere text-sm font-semibold">{m.name}</span>
                    <span className="text-xs">
                      {m.valid
                        ? <StatusDot tone="good">Ready to fly</StatusDot>
                        : <StatusDot tone="critical">{`${errors} to fix`}</StatusDot>}
                    </span>
                  </span>
                  <span className="mono text-xs text-[var(--muted)]">
                    {roomName(m.room_id)} · {m.points.length} point{m.points.length === 1 ? "" : "s"} · about {formatDuration(m.estimated_duration_s)} · revision {m.revision}
                    {m.flown_revision !== null ? ` · flown r${m.flown_revision}` : " · not flown"}
                    {selectedId === m.id ? " · selected" : ""}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

function MissionDetail({ mission, room, limits, drone, run, selected, onBack, onEdit, onDeleted, onUse }: {
  mission: MissionView;
  room: RoomView | null;
  limits: PlanLimits;
  drone: XY | null;
  run: Run;
  selected: boolean;
  onBack: () => void;
  onEdit: (room: RoomView) => void;
  onDeleted: () => void;
  onUse: () => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const outer = room ? outerOf(room, limits) : limits.outer;
  const blocking = mission.problems.filter((p) => p.severity === "error");

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <SmallButton onClick={onBack}>← All missions</SmallButton>
          <h2 className="wrap-anywhere pt-2 text-lg font-bold text-[var(--heading)]">{mission.name}</h2>
          <p className="mono text-xs text-[var(--muted)]">
            {room?.name ?? "Room missing"} · revision {mission.revision} · saved {formatDateTime(mission.updated_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {confirmDelete ? (
            <>
              <span className="text-xs">Delete this mission?</span>
              <SmallButton tone="danger" onClick={() => void run(async () => {
                await api.deleteMission(mission.id);
                onDeleted();
              }, `Delete mission ${mission.name}`)}>Delete</SmallButton>
              <SmallButton onClick={() => setConfirmDelete(false)}>Keep it</SmallButton>
            </>
          ) : (
            <SmallButton tone="danger" onClick={() => setConfirmDelete(true)}>Delete</SmallButton>
          )}
          <SmallButton disabled={!room} onClick={() => room && onEdit(room)}
                       title={room ? undefined : "Its room is missing, so there is nothing to draw it in."}>
            Edit
          </SmallButton>
          <Button
            variant="primary"
            disabled={!mission.valid}
            title={mission.valid ? undefined : "Fix what the agent's check lists first."}
            onClick={onUse}
          >
            {selected ? "Selected — continue →" : "Use this mission →"}
          </Button>
        </div>
      </div>
      {!mission.valid && (
        <Message tone="critical" text={`This mission cannot fly until ${blocking.length === 1 ? "one problem is" : `${blocking.length} problems are`} fixed. Edit it, or pick another.`} />
      )}

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.3fr)_minmax(18rem,1fr)]">
        <div className="border border-[var(--border)]">
          <PlanCanvas
            outer={outer} fence={room?.geofence ?? null} obstacles={room?.obstacles ?? []}
            home={mission.home} points={mission.points} returnToStart={mission.return_to_start}
            problems={mission.problems} drone={drone}
            label={`The plan of ${mission.name}`}
          />
        </div>
        <div className="grid content-start gap-3">
          <Panel title="Inspection points" bodyClassName="p-0">
            <table className="w-full text-xs">
              <thead className="text-left">
                <tr className="border-b border-[var(--border)]">
                  {["Point", "Where (m)", "Height", "Hold"].map((h) => (
                    <th key={h} scope="col" className="eyebrow px-3 py-2 font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="mono">
                {mission.points.map((p) => (
                  <tr key={p.id} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-3 py-1.5 font-semibold">{p.id}{p.label ? ` · ${p.label}` : ""}</td>
                    <td className="px-3 py-1.5">{p.x_m.toFixed(2)}, {p.y_m.toFixed(2)}</td>
                    <td className="px-3 py-1.5">{p.z_m.toFixed(2)} m</td>
                    <td className="px-3 py-1.5">{p.hold_s.toFixed(0)} s</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mono px-3 py-2 text-xs text-[var(--muted)]">
              Home {mission.home[0].toFixed(2)}, {mission.home[1].toFixed(2)} · cruise {formatMetres(mission.cruise_height_m)} · {mission.return_to_start ? "returns home" : "lands at the last point"}
            </p>
          </Panel>
          <ProblemList problems={mission.problems} error={null} checking={false} summary={mission} />
        </div>
      </div>
    </div>
  );
}
