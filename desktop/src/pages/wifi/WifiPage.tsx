/**
 * Drone Wi-Fi — which network the drone's camera is on, and changing it.
 *
 * THREE DIFFERENT "CONNECTED"s, kept apart on purpose, because running them
 * together is what made a failed join look like a success:
 *
 *   Radio    the laptop talks to the drone over the Crazyradio (flight, vitals)
 *   Network  the drone's AI deck has joined a Wi-Fi network and has an address
 *   Camera   this laptop can actually reach that address and frames arrive
 *
 * The first can be true while the other two are not; the second can be true
 * while the third is not (a network that blocks devices from each other).
 */

import { useEffect, useState } from "react";
import { api, type CameraStatus, type CameraWifi, type Session } from "@/lib/agent";
import { PHASE_LABEL, PHASE_TONE } from "@/lib/droneWifi";
import { DroneWifiForm } from "@/components/DroneWifiForm";
import { PageHeader, Panel, StatusDot } from "@/components/ui";

/** How often the camera's reachability is re-read while this page is open. */
const CAMERA_POLL_MS = 3000;

export function WifiPage({ wifi, session, onSaved }: {
  wifi: CameraWifi | null;
  session: Session | null;
  onSaved: (state: CameraWifi) => void;
}) {
  const [camera, setCamera] = useState<CameraStatus | null>(null);

  useEffect(() => {
    let stopped = false;
    const read = () => api.cameraStatus()
      .then((s) => { if (!stopped) setCamera(s); })
      .catch(() => { if (!stopped) setCamera(null); });
    void read();
    const timer = window.setInterval(read, CAMERA_POLL_MS);
    return () => { stopped = true; window.clearInterval(timer); };
  }, []);

  const phase = wifi?.phase ?? "not-set";
  const radio = Boolean(session?.drone);

  return (
    <div className="grid max-w-3xl gap-5">
      <PageHeader eyebrow="Operate" title="Drone Wi-Fi">
        The drone&apos;s camera streams over Wi-Fi. Put it on the network this laptop uses and
        the video arrives without the laptop going offline.
      </PageHeader>

      <Panel title="Now">
        <dl className="grid gap-3 text-sm sm:grid-cols-[9rem_1fr]">
          <dt className="text-[var(--muted)]">Radio</dt>
          <dd>
            <StatusDot tone={radio ? "good" : "idle"}>
              {radio ? "Drone connected" : "No drone connected"}
            </StatusDot>
          </dd>

          <dt className="text-[var(--muted)]">Drone&apos;s network</dt>
          <dd className="wrap-anywhere font-medium">{wifi?.ssid ?? "Not set"}</dd>

          <dt className="text-[var(--muted)]">Joining</dt>
          <dd>
            <StatusDot tone={PHASE_TONE[phase]}>{wifi?.message ?? PHASE_LABEL[phase]}</StatusDot>
          </dd>

          <dt className="text-[var(--muted)]">Address</dt>
          <dd className="mono">{wifi?.ip ?? "—"}</dd>

          <dt className="text-[var(--muted)]">Camera</dt>
          <dd>
            {camera === null ? (
              <StatusDot tone="idle">Not reported</StatusDot>
            ) : camera.live ? (
              <StatusDot tone="good">
                Streaming{camera.width && camera.height ? ` · ${camera.width}×${camera.height}` : ""}
              </StatusDot>
            ) : (
              <StatusDot tone="warning">{camera.reason ?? "No frames"}</StatusDot>
            )}
          </dd>
        </dl>
        <p className="mt-4 text-sm text-[var(--muted)]">
          The drone applies a network once per power-on. To switch networks after it has
          joined one, save the new network here, then restart the drone.
        </p>
      </Panel>

      <Panel title={wifi?.ssid ? "Change network" : "Choose a network"}>
        <DroneWifiForm onSaved={onSaved} />
      </Panel>
    </div>
  );
}
