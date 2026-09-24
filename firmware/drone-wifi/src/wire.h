/**
 * The bytes drone_wifi sends to the AI deck's ESP32 — pure, so a host test
 * can check them against an exact copy of what the ESP32 does with them.
 *
 * THE ESP32 BUG THIS WORKS AROUND (aideck-esp-firmware main/wifi.c, wifi_ctrl):
 *
 *     memcpy(ssid, &data[1], dataLength - 1);
 *     ssid[dataLength - 1 + 1] = 0;          // one PAST the copied bytes
 *
 * For n copied bytes the terminator lands at [n+1], so byte [n] keeps whatever
 * the previous SSID left there. The GAP8 streamer sets "WiFi streaming example"
 * at boot, so "VT Open WiFi" (12 chars) became "VT Open WiFin" — measured
 * 2026-09-24, a network that does not exist. Every name under 22 characters
 * was affected.
 *
 * The fix: send the value WITH its NUL. Then byte [n] of the copy is our own
 * terminator, and the ESP32's stray write lands harmlessly one further on.
 *
 * THE KEY BUFFER IS 50 BYTES (`static char key[MAX_SSID_SIZE]`, not
 * MAX_PASSWD_SIZE). With the NUL sent and the stray write at [len+2], the
 * longest value that fits is 47 characters — hence WIRE_VALUE_MAX.
 */

#ifndef DRONE_WIFI_WIRE_H
#define DRONE_WIFI_WIRE_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define WIRE_SSID_MAX  32  /* 802.11 */
#define WIRE_VALUE_MAX 47  /* the ESP32's 50-byte buffer, less NUL and stray write */

/**
 * Fill `out` with one WIFI_CTRL payload: the command, the value, its NUL.
 * Returns the payload length (the CPX dataLength). `value` need not be
 * NUL-terminated; `len` is its length without one.
 */
static inline size_t wireCtrlPayload(uint8_t cmd, const char *value, size_t len, uint8_t *out) {
  out[0] = cmd;
  memcpy(&out[1], value, len);
  out[1 + len] = 0;
  return 1 + len + 1;
}

#endif
