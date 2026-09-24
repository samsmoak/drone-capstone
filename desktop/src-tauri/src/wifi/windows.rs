//! Nearby networks on Windows, through the native WLAN API.
//!
//! Windows 11 (24H2 and later) gates the network list behind Location: with it
//! off, WlanGetAvailableNetworkList answers ERROR_ACCESS_DENIED. There is no
//! in-app prompt to show, so `request_permission` opens the Location page of
//! Settings instead.
//!
//! Bands come from the BSS list — each access point's centre frequency — since
//! the network list itself does not carry them.

use super::{merge, Network, Scan};
use std::ffi::c_void;
use windows::core::GUID;
use windows::Win32::Foundation::{ERROR_ACCESS_DENIED, ERROR_SUCCESS, HANDLE};
use windows::Win32::NetworkManagement::WiFi::*;

pub fn request_permission<R: tauri::Runtime>(_app: &tauri::AppHandle<R>) {
    let _ = std::process::Command::new("explorer").arg("ms-settings:privacy-location").spawn();
}

fn security_of(auth: DOT11_AUTH_ALGORITHM, secured: bool) -> &'static str {
    match auth {
        DOT11_AUTH_ALGO_80211_OPEN if !secured => "open",
        DOT11_AUTH_ALGO_WPA_PSK | DOT11_AUTH_ALGO_RSNA_PSK | DOT11_AUTH_ALGO_WPA3_SAE => "personal",
        DOT11_AUTH_ALGO_WPA | DOT11_AUTH_ALGO_RSNA | DOT11_AUTH_ALGO_WPA3 | DOT11_AUTH_ALGO_WPA3_ENT => "enterprise",
        _ => "other",
    }
}

fn band_of(khz: u32) -> &'static str {
    match khz {
        0..=3_000_000 => "2.4",
        3_000_001..=5_925_000 => "5",
        _ => "6",
    }
}

fn ssid_of(ssid: &DOT11_SSID) -> String {
    let len = (ssid.uSSIDLength as usize).min(ssid.ucSSID.len());
    String::from_utf8_lossy(&ssid.ucSSID[..len]).into_owned()
}

pub fn scan() -> Scan {
    let mut raw = Vec::new();
    // SAFETY: the WLAN API's documented call sequence; every list it allocates
    // is released with WlanFreeMemory and the handle with WlanCloseHandle.
    unsafe {
        let mut version = 0u32;
        let mut handle = HANDLE::default();
        if WlanOpenHandle(2, None, &mut version, &mut handle) != ERROR_SUCCESS.0 {
            return Scan {
                permission: "unsupported",
                networks: vec![],
                error: Some("Windows' Wi-Fi service is not running.".into()),
            };
        }
        let mut interfaces: *mut WLAN_INTERFACE_INFO_LIST = std::ptr::null_mut();
        if WlanEnumInterfaces(handle, None, &mut interfaces) != ERROR_SUCCESS.0 || interfaces.is_null() {
            WlanCloseHandle(handle, None);
            return Scan {
                permission: "unsupported",
                networks: vec![],
                error: Some("This computer has no Wi-Fi interface.".into()),
            };
        }
        let count = (*interfaces).dwNumberOfItems as usize;
        let first = (*interfaces).InterfaceInfo.as_ptr();
        let mut denied = false;
        for i in 0..count {
            let guid: GUID = (*first.add(i)).InterfaceGuid;
            let mut list: *mut WLAN_AVAILABLE_NETWORK_LIST = std::ptr::null_mut();
            let status = WlanGetAvailableNetworkList(handle, &guid, 0, None, &mut list);
            if status == ERROR_ACCESS_DENIED.0 {
                denied = true;
                continue;
            }
            if status != ERROR_SUCCESS.0 || list.is_null() {
                continue;
            }
            let n = (*list).dwNumberOfItems as usize;
            let items = (*list).Network.as_ptr();
            for j in 0..n {
                let network = &*items.add(j);
                let secured = network.bSecurityEnabled.as_bool();
                let mut bands = Vec::new();
                let mut bss: *mut WLAN_BSS_LIST = std::ptr::null_mut();
                if WlanGetNetworkBssList(handle, &guid, Some(&network.dot11Ssid), network.dot11BssType,
                                         secured, None, &mut bss) == ERROR_SUCCESS.0
                    && !bss.is_null()
                {
                    let entries = (*bss).wlanBssEntries.as_ptr();
                    for k in 0..(*bss).dwNumberOfItems as usize {
                        let band = band_of((*entries.add(k)).ulChCenterFrequency);
                        if !bands.contains(&band) {
                            bands.push(band);
                        }
                    }
                    WlanFreeMemory(bss as *const c_void);
                }
                raw.push(Network {
                    ssid: ssid_of(&network.dot11Ssid),
                    bands,
                    security: security_of(network.dot11DefaultAuthAlgorithm, secured),
                    current: network.dwFlags & WLAN_AVAILABLE_NETWORK_CONNECTED != 0,
                });
            }
            WlanFreeMemory(list as *const c_void);
        }
        WlanFreeMemory(interfaces as *const c_void);
        WlanCloseHandle(handle, None);

        if denied && raw.is_empty() {
            return Scan { permission: "denied", networks: vec![], error: None };
        }
        Scan { permission: "granted", networks: merge(raw), error: None }
    }
}
