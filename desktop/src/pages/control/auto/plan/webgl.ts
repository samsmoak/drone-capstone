/**
 * Whether this machine can draw WebGL at all. Some Linux GPU setups cannot;
 * the room map then stays in 2-D and says why. Its own file, with no three.js
 * import, so asking does not pull the 3-D chunk into the window's start-up.
 */

let known: boolean | null = null;

export function webglAvailable(): boolean {
  if (known !== null) return known;
  try {
    const canvas = document.createElement("canvas");
    known = Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    known = false;
  }
  return known;
}
