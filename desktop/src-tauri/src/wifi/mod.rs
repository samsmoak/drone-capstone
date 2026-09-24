//! Drone Wi-Fi: which network the AI deck should join, chosen on this laptop.
//!
//! Three jobs, all native, which is why they live in Rust and not the webview:
//!
//! - **List nearby networks** (CoreWLAN on macOS, the WLAN API on Windows). Both
//!   operating systems hide network NAMES from apps without Location
//!   permission — measured on this Mac: every SSID reads `<redacted>` — so the
//!   scan reports the permission state and the window falls back to typing.
//! - **Keep the password** in the OS secure store (Keychain / Credential
//!   Manager). Never a file, never Supabase, never the log.
//! - **Hand it to the agent** directly from here, so the password crosses into
//!   the webview once — when it is typed — and is never read back out.
//!
//! What the deck can join is narrower than what the laptop sees: 2.4 GHz only
//! (the ESP32 has no 5 GHz radio) and personal or open security only (no
//! enterprise sign-in). Each network carries its bands and security so the
//! window can say which will not work before anyone types a password.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[cfg(target_os = "macos")]
mod macos;
#[cfg(windows)]
mod windows;

#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct Network {
    pub ssid: String,
    /// "2.4", "5", "6" — every band this name was seen on.
    pub bands: Vec<&'static str>,
    /// "open", "personal", "enterprise" or "other" (WEP, OWE, unknown).
    pub security: &'static str,
    /// The network this laptop is on now.
    pub current: bool,
}

impl Network {
    /// Whether the AI deck's ESP32 can join it at all.
    pub fn joinable(&self) -> bool {
        self.bands.contains(&"2.4") && matches!(self.security, "open" | "personal")
    }
}

#[derive(Serialize, Debug)]
pub struct Scan {
    /// "granted", "denied", "undetermined" or "unsupported".
    pub permission: &'static str,
    pub networks: Vec<Network>,
    pub error: Option<String>,
}

/// Scan for nearby networks. Blocking — a real scan takes a second or two.
pub fn scan() -> Scan {
    #[cfg(target_os = "macos")]
    return macos::scan();
    #[cfg(windows)]
    return windows::scan();
    #[allow(unreachable_code)]
    Scan {
        permission: "unsupported",
        networks: vec![],
        error: Some("Listing networks is not supported on this system. Type the name.".into()),
    }
}

/// Ask for the permission the scan needs. macOS shows its own prompt; Windows
/// has none to show, so this opens its Location settings page instead.
pub fn request_permission<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    #[cfg(target_os = "macos")]
    macos::request_permission(app);
    #[cfg(windows)]
    windows::request_permission(app);
    let _ = app;
}

/// One entry per name: a dual-band router appears once, with both bands. The
/// current network first, then the ones the drone can join, then by name.
pub fn merge(raw: Vec<Network>) -> Vec<Network> {
    let mut by_name: BTreeMap<String, Network> = BTreeMap::new();
    for network in raw {
        if network.ssid.is_empty() {
            continue; // hidden networks have no name to show
        }
        let entry = by_name.entry(network.ssid.clone()).or_insert_with(|| Network {
            ssid: network.ssid.clone(),
            bands: vec![],
            security: network.security,
            current: false,
        });
        for band in network.bands {
            if !entry.bands.contains(&band) {
                entry.bands.push(band);
            }
        }
        entry.current |= network.current;
        if entry.security == "other" {
            entry.security = network.security;
        }
    }
    let mut out: Vec<Network> = by_name.into_values().collect();
    for network in &mut out {
        network.bands.sort_by_key(|band| match *band { "2.4" => 0, "5" => 1, _ => 2 });
    }
    out.sort_by(|a, b| {
        b.current.cmp(&a.current)
            .then(b.joinable().cmp(&a.joinable()))
            .then(a.ssid.to_lowercase().cmp(&b.ssid.to_lowercase()))
    });
    out
}

// ── the secure store ─────────────────────────────────────────────────────

const SERVICE: &str = "CropWatcher";
const ACCOUNT: &str = "drone-wifi";

#[derive(Serialize, Deserialize)]
pub struct Saved {
    pub ssid: String,
    pub password: String,
}

fn entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(SERVICE, ACCOUNT).map_err(|e| format!("secure store unavailable: {e}"))
}

pub fn load() -> Result<Option<Saved>, String> {
    match entry()?.get_password() {
        Ok(json) => serde_json::from_str(&json).map(Some).map_err(|_| "the saved drone network is unreadable".into()),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(format!("could not read the secure store: {e}")),
    }
}

pub fn save(saved: &Saved) -> Result<(), String> {
    let json = serde_json::to_string(saved).map_err(|e| e.to_string())?;
    entry()?.set_password(&json).map_err(|e| format!("could not write the secure store: {e}"))
}

pub fn forget() -> Result<(), String> {
    match entry()?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(format!("could not clear the secure store: {e}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn net(ssid: &str, bands: &[&'static str], security: &'static str, current: bool) -> Network {
        Network { ssid: ssid.into(), bands: bands.to_vec(), security, current }
    }

    #[test]
    fn a_dual_band_router_is_one_entry_with_both_bands() {
        let merged = merge(vec![net("Home", &["5"], "personal", false), net("Home", &["2.4"], "personal", false)]);
        assert_eq!(merged, vec![net("Home", &["2.4", "5"], "personal", false)]);
        assert!(merged[0].joinable());
    }

    #[test]
    fn five_ghz_only_and_enterprise_are_not_joinable() {
        assert!(!net("Fast", &["5"], "personal", false).joinable());
        assert!(!net("Campus", &["2.4", "5"], "enterprise", false).joinable());
        assert!(net("Cafe", &["2.4"], "open", false).joinable());
    }

    #[test]
    fn the_current_network_comes_first_then_joinable_ones() {
        let merged = merge(vec![
            net("b-fast", &["5"], "personal", false),
            net("a-lab", &["2.4"], "personal", false),
            net("z-mine", &["5"], "personal", true),
        ]);
        let names: Vec<&str> = merged.iter().map(|n| n.ssid.as_str()).collect();
        assert_eq!(names, ["z-mine", "a-lab", "b-fast"]);
    }

    #[test]
    fn hidden_networks_are_dropped() {
        assert!(merge(vec![net("", &["2.4"], "open", false)]).is_empty());
    }
}
