/* Host test: our payload, through an exact copy of the ESP32's handling. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../src/wire.h"

#define ESP_BUF 50  /* aideck-esp-firmware: static char ssid/key[MAX_SSID_SIZE] */

/* aideck-esp-firmware main/wifi.c, wifi_ctrl, verbatim in effect. */
static void esp_receive(char *buf, const uint8_t *data, size_t dataLength) {
  memcpy(buf, &data[1], dataLength - 1);
  buf[dataLength - 1 + 1] = 0;
}

static void check(const char *previous, const char *value) {
  char buf[ESP_BUF + 8];  /* +8: room to DETECT an overrun, not to allow one */
  memset(buf, 0, sizeof buf);
  strcpy(buf, previous);                       /* what the GAP8 left there */
  uint8_t pkt[1 + WIRE_VALUE_MAX + 1];
  size_t n = wireCtrlPayload(0x10, value, strlen(value), pkt);
  /* the ESP32's stray terminator lands at [n]; it must stay inside its buffer */
  assert(n < ESP_BUF);
  esp_receive(buf, pkt, n);
  if (strcmp(buf, value) != 0) {
    printf("FAIL: sent \"%s\" over \"%s\", ESP32 holds \"%s\"\n", value, previous, buf);
    assert(0);
  }
}

int main(void) {
  const char *gap8 = "WiFi streaming example";
  check(gap8, "VT Open WiFi");                    /* the measured failure */
  check(gap8, "a");
  check(gap8, "WiFi streaming exampl");           /* one shorter than the stale */
  check(gap8, "exactly-32-bytes-long-ssid-name!");
  check("", "Lab");
  char longest[WIRE_VALUE_MAX + 1];
  memset(longest, 'k', WIRE_VALUE_MAX); longest[WIRE_VALUE_MAX] = 0;
  check(gap8, longest);                           /* 47: fits the 50-byte key */

  /* And the OLD encoding really was broken — proof the test can fail. */
  char buf[ESP_BUF] = {0};
  strcpy(buf, gap8);
  uint8_t old[16] = {0x10};
  memcpy(&old[1], "VT Open WiFi", 12);
  esp_receive(buf, old, 13);
  assert(strcmp(buf, "VT Open WiFin") == 0);

  puts("wire: ok");
  return 0;
}
