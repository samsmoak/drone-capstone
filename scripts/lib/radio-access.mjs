// What this computer needs before the Crazyradio can be used — once, by hand.
//
// Shared by scripts/setup.mjs and scripts/install.mjs so the words exist once.
// Both steps need an administrator, so these scripts never do them: they check
// and say exactly what to run. The agent names the same problems when it meets
// them (backend/agent/cropwatcher/flight/radio.py).
//
//   macOS    nothing to do
//   Windows  the libusb-win32 driver, installed with Zadig — cflib opens the
//            radio through libusb0 there
//   Linux    a udev rule, or only root may open the dongle. Rule and commands
//            are Bitcraze's own:
//            https://www.bitcraze.io/documentation/repository/crazyflie-lib-python/master/installation/usb_permissions/

import { spawnSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

export const BITCRAZE_RULES = `# Crazyradio (normal operation)
SUBSYSTEM=="usb", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="7777", MODE="0664", GROUP="plugdev"
# Bootloader
SUBSYSTEM=="usb", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="0101", MODE="0664", GROUP="plugdev"
# Crazyflie (over USB)
SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="5740", MODE="0664", GROUP="plugdev"`;

const RULE_DIRS = ["/etc/udev/rules.d", "/usr/lib/udev/rules.d", "/lib/udev/rules.d"];

/**
 * The installed udev rule that covers the Crazyradio, if any, and whether it
 * lets this user in: by group membership, or by a rule that needs none
 * (world-writable MODE, or systemd's uaccess tag for the logged-in user).
 */
export function linuxRadioAccess() {
  for (const dir of RULE_DIRS) {
    let files = [];
    try {
      files = readdirSync(dir).filter((f) => f.endsWith(".rules"));
    } catch {
      continue;
    }
    for (const file of files) {
      let text = "";
      try {
        text = readFileSync(join(dir, file), "utf8");
      } catch {
        continue;
      }
      const line = text.split("\n").find((l) =>
        !l.trimStart().startsWith("#") && /1915/.test(l) && /7777/.test(l));
      if (!line) continue;
      const group = /GROUP\s*=\s*"([^"]+)"/.exec(line)?.[1] ?? null;
      const open = /MODE\s*=\s*"0?666"/.test(line) || /uaccess/.test(line);
      const groups = (spawnSync("id", ["-nG"], { encoding: "utf8" }).stdout ?? "").trim().split(/\s+/);
      return { rule: join(dir, file), group, member: open || (group !== null && groups.includes(group)) };
    }
  }
  return { rule: null, group: null, member: false };
}

/** Lines to print about the radio on this computer, or [] when nothing is needed. */
export function radioAccessAdvice() {
  if (process.platform === "win32") {
    return [
      "Before the first flight, the Crazyradio needs its Windows driver, once:",
      "  1. Download Zadig from https://zadig.akeo.ie and run it.",
      '  2. Options → List All Devices, then choose "Crazyradio PA USB Dongle".',
      "  3. Pick libusb-win32 as the driver and click Install (or Replace) Driver.",
      "The app says so, too, if it finds the radio without its driver.",
    ];
  }
  if (process.platform !== "linux") return [];

  const access = linuxRadioAccess();
  if (access.rule && access.member) return [`Crazyradio access: ${access.rule} lets this user in.`];
  if (access.rule) {
    return [
      `Crazyradio access: ${access.rule} allows the "${access.group}" group, and this user`,
      "is not in it. Once, then log out and back in:",
      "",
      `  sudo usermod -a -G ${access.group} $USER`,
    ];
  }
  return [
    "Before the first flight, let this user open the Crazyradio — once, as Bitcraze",
    "describes, then log out and back in:",
    "",
    "  sudo groupadd -f plugdev",
    "  sudo usermod -a -G plugdev $USER",
    "  sudo tee /etc/udev/rules.d/99-bitcraze.rules > /dev/null <<'EOF'",
    ...BITCRAZE_RULES.split("\n"),
    "EOF",
    "  sudo udevadm control --reload-rules && sudo udevadm trigger",
    "",
    "The app says so, too, if it finds the radio but may not open it.",
  ];
}

/** Is `name` a program on PATH? For optional tools like update-desktop-database. */
export function hasProgram(name) {
  return (process.env.PATH ?? "").split(":").some((dir) => dir && existsSync(join(dir, name)));
}
