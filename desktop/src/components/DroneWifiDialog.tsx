/**
 * The one-time question after sign-in: which network should the drone's
 * camera join?
 *
 * Only asked when nothing is saved (App.tsx). Everything after that — seeing
 * which network the drone is on, changing it — is the Drone Wi-Fi page, since a
 * setting people come back to belongs somewhere they can navigate to.
 *
 * IT CLOSES ON SAVE. The drone only joins when it next connects, which can be
 * minutes away; progress is shown on the page and in the sidebar, not in a
 * modal the operator has to sit and watch.
 *
 * Modal conventions as FullScreenOverlay: Escape closes, focus moves in and
 * back, and the backdrop is inert to clicks.
 */

import { useEffect, useRef } from "react";
import type { CameraWifi } from "@/lib/agent";
import { DroneWifiForm } from "@/components/DroneWifiForm";

export function DroneWifiDialog({ onClose, onSaved }: {
  onClose: () => void;
  onSaved: (state: CameraWifi) => void;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    opener.current = document.activeElement;
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (opener.current instanceof HTMLElement) opener.current.focus();
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={dialog}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="drone-wifi-title"
        className="flex max-h-full w-full max-w-lg flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-lg"
      >
        <div className="border-b border-[var(--border)] px-5 py-4">
          <h2 id="drone-wifi-title" className="text-lg font-semibold">Drone Wi-Fi</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            The drone&apos;s camera joins this network, so video reaches this laptop while it
            stays online. Choose the network this laptop is on. You can change it any time
            under Drone Wi-Fi in the sidebar.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <DroneWifiForm
            onSaved={(state) => { onSaved(state); onClose(); }}
            onCancel={onClose}
            cancelLabel="Not now"
          />
        </div>
      </div>
    </div>
  );
}
