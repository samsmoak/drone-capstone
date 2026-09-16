//! The desktop shell around the flight agent.
//!
//! The app's whole reason to exist is the constraint in CLAUDE.md: the
//! Crazyradio is a USB dongle, so only the machine holding it can command the
//! drone. This bundles the agent as a sidecar so an operator installs one
//! thing and never sees Python.
//!
//! Two decisions worth knowing about:
//!
//! **The sidecar is spawned from Rust, never from the webview.** Granting the
//! frontend `shell:allow-execute` would let any script in the window start a
//! process; the window has no such permission, and the only binary this app
//! can launch is the one compiled into `externalBin`.
//!
//! **The child is killed on exit, deliberately and on every path.** The agent
//! can have a drone armed. An orphaned agent holding the radio also blocks the
//! next launch, which presents as "no drone found" with a drone plainly
//! sitting there.

use std::sync::Mutex;

use tauri::{Emitter, Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// The port the agent serves on. Matches `DEFAULT_PORT` in `api/rest.py`;
/// the agent binds localhost only.
const AGENT_PORT: u16 = 8765;

/// The running agent, so it can be stopped on exit.
#[derive(Default)]
struct AgentProcess(Mutex<Option<CommandChild>>);

/// A line of agent output, forwarded to the log panel.
#[derive(Clone, serde::Serialize)]
struct LogLine {
    stream: &'static str,
    line: String,
}

#[tauri::command]
fn agent_port() -> u16 {
    AGENT_PORT
}

/// Cut the motors, whatever is happening.
///
/// Routed through the agent's own `/flight/stop`, which is documented as
/// always succeeding — a stop that can fail is not a stop. The button must
/// work even when the manual socket is the thing that has wedged, so it
/// deliberately does not go over that socket.
#[tauri::command]
async fn panic_stop() -> Result<(), String> {
    let url = format!("http://127.0.0.1:{AGENT_PORT}/flight/stop");
    let response = tauri_plugin_http::reqwest::Client::new()
        .post(&url)
        .send()
        .await
        .map_err(|e| format!("could not reach the agent: {e}"))?;

    if !response.status().is_success() {
        return Err(format!("the agent refused the stop: HTTP {}", response.status()));
    }
    Ok(())
}

/// Start the bundled agent and stream its output into the log panel.
fn spawn_agent(app: &tauri::AppHandle) -> Result<(), String> {
    let (mut rx, child) = app
        .shell()
        .sidecar("cropwatcher-agent")
        .map_err(|e| format!("the bundled agent is missing: {e}"))?
        // `--exit-with-parent` is what actually stops the agent. Killing the
        // child below only reaches PyInstaller's bootloader; the real Python
        // process is its child and survives, orphaned onto launchd, still
        // holding the radio. Measured: desktop → bootloader → python, and the
        // last one owns the port. Closing stdin is the signal that reaches it.
        .args(["serve", "--port", &AGENT_PORT.to_string(), "--exit-with-parent"])
        .spawn()
        .map_err(|e| format!("could not start the agent: {e}"))?;

    app.state::<AgentProcess>().0.lock().unwrap().replace(child);

    // The agent's own log is the only account of what the drone did. Forward
    // it to the window rather than dropping it: on a failed flight it is the
    // first thing anyone asks for, and a bundled app has no terminal.
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            let line = match event {
                CommandEvent::Stdout(bytes) => Some(("stdout", bytes)),
                CommandEvent::Stderr(bytes) => Some(("stderr", bytes)),
                CommandEvent::Terminated(status) => {
                    let _ = handle.emit(
                        "agent-log",
                        LogLine {
                            stream: "stderr",
                            line: format!(
                                "the agent exited ({}). Manual control is unavailable until the app is restarted.",
                                status.code.map_or_else(|| "signal".into(), |c| c.to_string())
                            ),
                        },
                    );
                    None
                }
                _ => None,
            };

            if let Some((stream, bytes)) = line {
                let _ = handle.emit(
                    "agent-log",
                    LogLine {
                        stream,
                        line: String::from_utf8_lossy(&bytes).trim_end().to_string(),
                    },
                );
            }
        }
    });

    Ok(())
}

/// Stop the agent. Safe to call more than once.
fn stop_agent(state: &State<'_, AgentProcess>) {
    if let Some(child) = state.0.lock().unwrap().take() {
        let _ = child.kill();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_http::init())
        .manage(AgentProcess::default())
        .invoke_handler(tauri::generate_handler![agent_port, panic_stop])
        .setup(|app| {
            if let Err(message) = spawn_agent(app.handle()) {
                // A window that silently has no agent behind it is worse than
                // one that says so: the operator would read an empty status
                // panel as "idle" rather than "not running".
                let _ = app.handle().emit(
                    "agent-log",
                    LogLine {
                        stream: "stderr",
                        line: message,
                    },
                );
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app, event| {
            // Covers the window close, the Quit menu item and a signal alike.
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                stop_agent(&app.state::<AgentProcess>());
            }
        });
}
