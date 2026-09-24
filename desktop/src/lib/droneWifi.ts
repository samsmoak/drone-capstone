/**
 * Drone Wi-Fi: the network the AI deck joins so its camera streams over the
 * same network this laptop uses for Supabase.
 *
 * The native half lives in Rust (`src-tauri/src/wifi`): listing networks needs
 * the OS, and the password belongs in the OS secure store. The password crosses
 * this side once, when it is typed into `save`, and is never read back — Rust
 * hands it to the agent itself on `push`.
 */

import { invoke } from "@tauri-apps/api/core";
import type { CameraWifi } from "@/lib/agent";
import type { Tone } from "@/components/ui";

export type WifiBand = "2.4" | "5" | "6";
export type WifiSecurity = "open" | "personal" | "enterprise" | "other";

export type WifiNetwork = {
  ssid: string;
  bands: WifiBand[];
  security: WifiSecurity;
  /** The network this laptop is on now. */
  current: boolean;
};

export type WifiScan = {
  /** "undetermined" means the OS has not asked yet; names are hidden until it does. */
  permission: "granted" | "denied" | "undetermined" | "unsupported";
  networks: WifiNetwork[];
  error: string | null;
};

export const droneWifi = {
  /** `live: false` is the OS's last scan, instant; `live: true` scans the air
   *  and takes seconds (12.5 s measured on a MacBook Pro). */
  scan: (live: boolean) => invoke<WifiScan>("wifi_scan", { live }),
  requestPermission: () => invoke<void>("wifi_request_permission"),
  /** The saved network's name, or null. Never the password. */
  saved: () => invoke<string | null>("drone_wifi_saved"),
  save: (ssid: string, password: string) =>
    invoke<CameraWifi>("drone_wifi_save", { ssid, password }),
  /** Re-send the saved network to the agent. Null when none is saved. */
  push: () => invoke<CameraWifi | null>("drone_wifi_push"),
  forget: () => invoke<void>("drone_wifi_forget"),
};

/**
 * Why the drone cannot join this network, in words an operator can act on —
 * or null when it can. The deck's ESP32 has a 2.4 GHz radio only, and it
 * cannot do an enterprise (username + password) sign-in.
 */
export function whyNotJoinable(network: WifiNetwork): string | null {
  if (network.security === "enterprise") {
    return "Signs in with a personal username and password (like eduroam), not one shared " +
      "password. The drone's Wi-Fi chip cannot sign in that way.";
  }
  if (network.security === "other") {
    return "Uses a security type the drone cannot use.";
  }
  if (network.bands.length > 0 && !network.bands.includes("2.4")) {
    return "5 GHz only. The drone's camera needs 2.4 GHz — on a phone hotspot, turn on Maximize Compatibility.";
  }
  return null;
}

/** The same verdict in two or three words, for a list row. */
export function shortWhyNot(network: WifiNetwork): string | null {
  if (network.security === "enterprise") return "personal login (like eduroam)";
  if (network.security === "other") return "unsupported security";
  if (network.bands.length > 0 && !network.bands.includes("2.4")) return "5 GHz only";
  return null;
}

export const bandLabel = (bands: WifiBand[]) =>
  bands.length === 0 ? "" : bands.map((b) => `${b} GHz`).join(" + ");

/** The longest password the drone holds: the AI deck's ESP32 keeps it in a
 *  50-byte buffer (firmware/drone-wifi/src/wire.h), so not WPA2's 63. */
export const PASSWORD_MAX = 47;

/**
 * Go to the Drone Wi-Fi page from anywhere in the window. Navigation is owned
 * by App, and the Camera tab and the account menu sit several components away —
 * an event keeps them from threading a callback through every page in between.
 */
export const SHOW_DRONE_WIFI = "cropwatcher:show-drone-wifi";
export const showDroneWifi = () => window.dispatchEvent(new Event(SHOW_DRONE_WIFI));

export const PHASE_TONE: Record<CameraWifi["phase"], Tone> = {
  "not-set": "idle",
  waiting: "idle",
  sending: "warning",
  joining: "warning",
  joined: "good",
  reconnecting: "warning",
  failed: "critical",
};

/** What the phase means, when the agent sent no message of its own. */
export const PHASE_LABEL: Record<CameraWifi["phase"], string> = {
  "not-set": "No network set",
  waiting: "Waiting for the drone to connect",
  sending: "Sending the network to the drone",
  joining: "The drone is joining",
  joined: "On the network",
  reconnecting: "Dropped off — rejoining",
  failed: "Could not join",
};
