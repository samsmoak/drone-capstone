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
  scan: () => invoke<WifiScan>("wifi_scan"),
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
    return "Needs a username sign-in (university or company Wi-Fi). The drone cannot use it.";
  }
  if (network.security === "other") {
    return "Uses a security type the drone cannot use.";
  }
  if (network.bands.length > 0 && !network.bands.includes("2.4")) {
    return "5 GHz only. The drone's camera needs 2.4 GHz — on a phone hotspot, turn on Maximize Compatibility.";
  }
  return null;
}

export const bandLabel = (bands: WifiBand[]) =>
  bands.length === 0 ? "" : bands.map((b) => `${b} GHz`).join(" + ");

/**
 * Open the Drone Wi-Fi dialog from anywhere in the window. The dialog is owned
 * by App (it is asked for after sign-in), and the Camera tab and the account
 * menu sit several components away — an event keeps them from threading a
 * callback through every page in between.
 */
export const OPEN_DRONE_WIFI = "cropwatcher:open-drone-wifi";
export const openDroneWifi = () => window.dispatchEvent(new Event(OPEN_DRONE_WIFI));
