//! Nearby networks on macOS, through CoreWLAN.
//!
//! macOS 14+ returns every SSID as nil unless the app holds Location
//! permission, so the permission is read first and reported with the scan. The
//! prompt itself needs a CLLocationManager created on the main thread and kept
//! alive while it is showing — hence `request_permission` dispatches there and
//! deliberately leaks the manager (one small object, only when asked).

use super::{merge, Network, Scan};
use objc2_core_location::{CLAuthorizationStatus, CLLocationManager};
use objc2_core_wlan::{CWChannelBand, CWSecurity, CWWiFiClient};

fn permission() -> &'static str {
    // The class method is deprecated in favour of the instance one, but the
    // instance one needs a CLLocationManager — a main-thread object — and this
    // runs on the scan's worker thread. The class method answers the same.
    // SAFETY: a class method with no arguments; safe on any thread.
    #[allow(deprecated)]
    let status = unsafe { CLLocationManager::authorizationStatus_class() };
    match status {
        CLAuthorizationStatus::NotDetermined => "undetermined",
        CLAuthorizationStatus::AuthorizedAlways | CLAuthorizationStatus::AuthorizedWhenInUse => "granted",
        _ => "denied",
    }
}

pub fn request_permission<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    let _ = app.run_on_main_thread(|| {
        // SAFETY: on the main thread, as CoreLocation requires.
        unsafe {
            let manager = CLLocationManager::new();
            manager.requestWhenInUseAuthorization();
            // The prompt is dismissed with the manager; keep it alive.
            std::mem::forget(manager);
        }
    });
}

fn security_of(network: &objc2_core_wlan::CWNetwork) -> &'static str {
    // SAFETY: plain property queries on a CWNetwork from a finished scan.
    let supports = |s: CWSecurity| unsafe { network.supportsSecurity(s) };
    if [CWSecurity::WPAEnterprise, CWSecurity::WPAEnterpriseMixed, CWSecurity::WPA2Enterprise,
        CWSecurity::Enterprise, CWSecurity::WPA3Enterprise]
        .into_iter().any(supports)
    {
        "enterprise"
    } else if [CWSecurity::WPAPersonal, CWSecurity::WPAPersonalMixed, CWSecurity::WPA2Personal,
               CWSecurity::Personal, CWSecurity::WPA3Personal, CWSecurity::WPA3Transition]
        .into_iter().any(supports)
    {
        "personal"
    } else if supports(CWSecurity::None) {
        "open"
    } else {
        "other"
    }
}

pub fn scan(live: bool) -> Scan {
    let permission = permission();
    // SAFETY: CoreWLAN's documented entry points; scanning off the main
    // thread is supported and is the only way not to freeze the window.
    unsafe {
        let Some(interface) = CWWiFiClient::sharedWiFiClient().interface() else {
            return Scan {
                permission,
                networks: vec![],
                error: Some("This computer has no Wi-Fi interface.".into()),
            };
        };
        let current = interface.ssid().map(|s| s.to_string());
        // The cache when asked for it and it exists; otherwise the air.
        let cached = if live { None } else { interface.cachedScanResults() };
        let found = match cached {
            Some(set) => set,
            None => match interface.scanForNetworksWithName_error(None) {
                Ok(set) => set,
                Err(e) => match interface.cachedScanResults() {
                    Some(set) => set,
                    None => {
                        return Scan {
                            permission,
                            networks: vec![],
                            error: Some(format!("The Wi-Fi scan failed: {}", e.localizedDescription())),
                        }
                    }
                },
            },
        };
        let mut raw = Vec::new();
        for network in found.iter() {
            let ssid = network.ssid().map(|s| s.to_string()).unwrap_or_default();
            let band = network.wlanChannel().map(|c| c.channelBand());
            let bands = match band {
                Some(CWChannelBand::Band2GHz) => vec!["2.4"],
                Some(CWChannelBand::Band5GHz) => vec!["5"],
                Some(CWChannelBand::Band6GHz) => vec!["6"],
                _ => vec![],
            };
            raw.push(Network {
                current: current.as_deref() == Some(ssid.as_str()),
                ssid,
                bands,
                security: security_of(&network),
            });
        }
        Scan { permission, networks: merge(raw), error: None }
    }
}
