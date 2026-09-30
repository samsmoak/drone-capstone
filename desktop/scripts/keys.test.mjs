// Shift reverses the arrows while held — lib/keys.ts. Node runs the .ts
// directly (type stripping, Node >= 23.6): `pnpm test`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { intentFromKeys, isShift, KEY_MAP, NO_KEYS, sameIntent } from "../src/lib/keys.ts";

const on = (...fields) => ({ ...NO_KEYS, ...Object.fromEntries(fields.map((f) => [f, true])) });

test("without Shift the keys fly as they always have", () => {
  assert.deepEqual(intentFromKeys(["ArrowUp"], false), on("forward"));
  assert.deepEqual(intentFromKeys(["ArrowLeft", "KeyW"], false), on("left", "up"));
});

test("Shift reverses every arrow", () => {
  assert.deepEqual(intentFromKeys(["ArrowUp"], true), on("back"));
  assert.deepEqual(intentFromKeys(["ArrowDown"], true), on("forward"));
  assert.deepEqual(intentFromKeys(["ArrowLeft"], true), on("right"));
  assert.deepEqual(intentFromKeys(["ArrowRight"], true), on("left"));
  assert.deepEqual(intentFromKeys(["ArrowUp", "ArrowLeft"], true), on("back", "right"));
});

test("Shift leaves height and turning alone", () => {
  assert.deepEqual(intentFromKeys(["KeyW", "KeyA"], true), on("up", "yaw_left"));
  assert.deepEqual(intentFromKeys(["KeyS", "KeyD"], true), on("down", "yaw_right"));
});

test("Shift on its own asks for nothing", () => {
  assert.deepEqual(intentFromKeys([], true), NO_KEYS);
  assert.deepEqual(intentFromKeys(["ShiftLeft"], true), NO_KEYS);
  assert.ok(isShift("ShiftLeft") && isShift("ShiftRight") && !isShift("ArrowUp"));
});

test("pressing and releasing Shift mid-hold flips the same held arrow", () => {
  const held = new Set(["ArrowUp"]);
  assert.deepEqual(intentFromKeys(held, false), on("forward"));
  assert.deepEqual(intentFromKeys(held, true), on("back"));      // Shift down
  assert.deepEqual(intentFromKeys(held, false), on("forward"));  // Shift up: as before
});

test("sameIntent compares every field", () => {
  assert.ok(sameIntent(on("forward"), on("forward")));
  assert.ok(!sameIntent(on("forward"), on("back")));
  assert.equal(Object.keys(NO_KEYS).length, new Set(Object.values(KEY_MAP)).size);
});
