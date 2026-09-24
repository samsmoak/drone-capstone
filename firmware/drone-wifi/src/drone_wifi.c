/**
 * drone_wifi — tell the AI deck which Wi-Fi network to join, over the radio.
 *
 * WHY THIS EXISTS. The deck's ESP32 joins a network only when it is sent three
 * CPX commands: set SSID, set key, connect. Stock firmware sends them once at
 * boot, from credentials COMPILED IN (Kconfig), and nothing on the ground can
 * reach the ESP32 over the Crazyradio — cflib's CPX-over-CRTP transport is a
 * stub. So the laptop sends the credentials to this app over the CRTP app
 * channel, and this app forwards them to the ESP32 exactly as aideck.c does.
 *
 * Built out-of-tree against the SAME release the drone runs (2025.12.1), so
 * the only difference from stock firmware is this file.
 *
 * PROTOCOL (app channel, CRTP port 13, <= 30 bytes a packet)
 *
 *   ground -> drone
 *     0x01 off  bytes...   SSID chunk at offset `off`
 *     0x02 off  bytes...   key chunk at offset `off`
 *     0x03 ssid_len key_len   apply: join that network
 *     0x04                 status
 *
 *   drone -> ground        [0x80 | cmd, code, applied]
 *     code 0 OK · 1 BAD_REQUEST · 2 ALREADY_APPLIED · 3 TOO_EARLY
 *
 * RULES THIS APP ENFORCES, and the failures they prevent
 *
 *   ONE APPLY PER POWER-ON. The ESP32 creates its station interface every time
 *   it is told to connect; a second creation fails an assert and reboots the
 *   ESP32 (aideck-esp-firmware main/wifi.c, wifi_init_sta). So a second apply
 *   is refused and the operator is told to power-cycle the drone.
 *
 *   NOT BEFORE BOOT_GRACE_MS. The GAP8 streamer raises its own access point
 *   2 s after boot. An apply that lands before it is overridden by it.
 *
 * The IP the deck gets is NOT relayed here: the stock CPX task already prints
 * "WiFi connected to ip: a.b.c.d" to the console, which the ground reads.
 */

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "app.h"
#include "app_channel.h"
#include "cpx.h"
#include "cpx_internal_router.h"

#include "FreeRTOS.h"
#include "task.h"

#define DEBUG_MODULE "DRONEWIFI"
#include "debug.h"

#define CMD_SSID   0x01
#define CMD_KEY    0x02
#define CMD_APPLY  0x03
#define CMD_STATUS 0x04

#define CODE_OK              0
#define CODE_BAD_REQUEST     1
#define CODE_ALREADY_APPLIED 2
#define CODE_TOO_EARLY       3

// The ESP32's own buffers (aideck-esp-firmware main/wifi.c).
#define WIFI_SET_SSID_CMD   0x10
#define WIFI_SET_KEY_CMD    0x11
#define WIFI_CONNECT_CMD    0x20
#define WIFI_CONNECT_AS_STA 0x00

#define SSID_MAX 32  // 802.11
#define KEY_MAX  63  // WPA2-PSK passphrase

#define BOOT_GRACE_MS 8000

static char ssid[SSID_MAX + 1];
static char key[KEY_MAX + 1];
static bool applied = false;

static CPXPacket_t cpxTx;

static void reply(uint8_t cmd, uint8_t code) {
  uint8_t out[3] = {(uint8_t)(0x80 | cmd), code, applied ? 1 : 0};
  appchannelSendDataPacketBlock(out, sizeof(out));
}

static bool store(char *dst, size_t cap, const uint8_t *pkt, size_t len) {
  if (len < 2) {
    return false;
  }
  size_t off = pkt[1];
  size_t n = len - 2;
  if (off + n > cap) {
    return false;
  }
  memcpy(dst + off, pkt + 2, n);
  return true;
}

static void sendWifiCtrl(uint8_t cmd, const char *value, size_t valueLen) {
  cpxInitRoute(CPX_T_STM32, CPX_T_ESP32, CPX_F_WIFI_CTRL, &cpxTx.route);
  cpxTx.data[0] = cmd;
  memcpy(&cpxTx.data[1], value, valueLen);
  cpxTx.dataLength = 1 + valueLen;
  cpxSendPacketBlocking(&cpxTx);
}

static uint8_t apply(uint8_t ssidLen, uint8_t keyLen) {
  if (applied) {
    return CODE_ALREADY_APPLIED;
  }
  if (ssidLen == 0 || ssidLen > SSID_MAX || keyLen > KEY_MAX || (keyLen > 0 && keyLen < 8)) {
    return CODE_BAD_REQUEST;
  }
  if (T2M(xTaskGetTickCount()) < BOOT_GRACE_MS) {
    return CODE_TOO_EARLY;
  }
  ssid[ssidLen] = 0;
  key[keyLen] = 0;

  DEBUG_PRINT("joining Wi-Fi network (%u-char name)\n", ssidLen);
  sendWifiCtrl(WIFI_SET_SSID_CMD, ssid, ssidLen);
  sendWifiCtrl(WIFI_SET_KEY_CMD, key, keyLen);

  cpxInitRoute(CPX_T_STM32, CPX_T_ESP32, CPX_F_WIFI_CTRL, &cpxTx.route);
  cpxTx.data[0] = WIFI_CONNECT_CMD;
  cpxTx.data[1] = WIFI_CONNECT_AS_STA;
  cpxTx.dataLength = 2;
  cpxSendPacketBlocking(&cpxTx);

  // The key is not needed again this power cycle; do not keep it in RAM.
  memset(key, 0, sizeof(key));
  applied = true;
  return CODE_OK;
}

void appMain() {
  DEBUG_PRINT("ready\n");
  uint8_t pkt[APPCHANNEL_MTU];

  while (1) {
    size_t len = appchannelReceiveDataPacket(pkt, sizeof(pkt), APPCHANNEL_WAIT_FOREVER);
    if (len == 0) {
      continue;
    }
    switch (pkt[0]) {
      case CMD_SSID:
        reply(CMD_SSID, store(ssid, SSID_MAX, pkt, len) ? CODE_OK : CODE_BAD_REQUEST);
        break;
      case CMD_KEY:
        reply(CMD_KEY, store(key, KEY_MAX, pkt, len) ? CODE_OK : CODE_BAD_REQUEST);
        break;
      case CMD_APPLY:
        reply(CMD_APPLY, len >= 3 ? apply(pkt[1], pkt[2]) : CODE_BAD_REQUEST);
        break;
      case CMD_STATUS:
        reply(CMD_STATUS, CODE_OK);
        break;
      default:
        reply(pkt[0], CODE_BAD_REQUEST);
        break;
    }
  }
}
