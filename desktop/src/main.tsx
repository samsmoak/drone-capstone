import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { getCurrentWindow } from "@tauri-apps/api/window";
import App from "@/App";
import { api, connectToShell } from "@/lib/agent";
import "@fontsource-variable/inter";
import "@fontsource-variable/fraunces";
import "./styles.css";

/**
 * Closing the window ends the session rather than vanishing mid-flight.
 *
 * The agent would land the drone by itself when this window stops answering —
 * that safety net stays — but an operator closing the window should get the
 * same tidy ending as pressing End session: land, close the flight record, and
 * let the upload finish.
 */
const CLOSE_TIMEOUT_MS = 8000;

getCurrentWindow().onCloseRequested(async (event) => {
  event.preventDefault();
  try {
    await connectToShell();
    // Ending lands the drone if it is flying, which takes seconds — but a
    // close that can hang forever is a window that will not close. The agent
    // still lands by itself when this window stops answering.
    await Promise.race([
      api.endSession(),
      new Promise((resolve) => setTimeout(resolve, CLOSE_TIMEOUT_MS)),
    ]);
  } catch {
    // Already ended, or the agent has gone: closing is still the right outcome.
  }
  // Needs `core:window:allow-destroy`. Without it this call was refused and the
  // window ignored the close button entirely.
  await getCurrentWindow().destroy();
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
