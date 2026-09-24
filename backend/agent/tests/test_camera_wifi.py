"""Putting the AI deck on the operator's Wi-Fi, against a fake drone that
answers the way firmware/drone-wifi/src/drone_wifi.c does."""

from __future__ import annotations

import threading

import pytest

from cropwatcher.camera import wifi
from cropwatcher.camera.wifi import (
    CMD_APPLY,
    CMD_KEY,
    CMD_SSID,
    CMD_STATUS,
    ConsoleWatch,
    DeckWifi,
    Phase,
    WifiError,
    packets,
    validate,
)


class Caller:
    def __init__(self) -> None:
        self.callbacks: list = []

    def add_callback(self, cb) -> None:
        self.callbacks.append(cb)

    def remove_callback(self, cb) -> None:
        self.callbacks.remove(cb)

    def call(self, *args) -> None:
        for cb in list(self.callbacks):
            cb(*args)


class FakeDrone:
    """The drone_wifi app's side of the exchange, plus the console."""

    def __init__(self, *, flashed=True, early=0, applied=False, join="ip",
                 ip="10.0.0.42") -> None:
        self.flashed = flashed
        self.early = early              # how many applies are TOO_EARLY
        self.applied = applied
        self.join = join                # "ip" | "fail" | "silent"
        self.ip = ip
        self.ssid = bytearray(32)
        self.key = bytearray(47)
        self.sent: list[bytes] = []
        outer = self

        class _App:
            packet_received = Caller()

            @staticmethod
            def send_packet(data: bytes) -> None:
                outer._receive(bytes(data))

        class _Console:
            receivedChar = Caller()

        self.appchannel = _App()
        self.console = _Console()

    def _reply(self, cmd: int, code: int) -> None:
        self.appchannel.packet_received.call(bytes([0x80 | cmd, code, int(self.applied)]))

    def _receive(self, pkt: bytes) -> None:
        self.sent.append(pkt)
        if not self.flashed:
            return                      # stock firmware: nothing listens
        cmd = pkt[0]
        if cmd in (CMD_SSID, CMD_KEY):
            buf = self.ssid if cmd == CMD_SSID else self.key
            off = pkt[1]
            buf[off:off + len(pkt) - 2] = pkt[2:]
            self._reply(cmd, 0)
        elif cmd == CMD_STATUS:
            self._reply(cmd, 0)
        elif cmd == CMD_APPLY:
            if self.applied:
                self._reply(cmd, 2)
            elif self.early > 0:
                self.early -= 1
                self._reply(cmd, 3)
            else:
                self.applied = True
                self._reply(cmd, 0)
                threading.Timer(0.05, self._join).start()

    def _join(self) -> None:
        say = self.console.receivedChar.call
        if self.join == "ip":
            say("CPX: ESP32: I (1) WIFI: got ip\nWiFi connected ")
            say(f"to ip: {self.ip}\n")
        elif self.join == "fail":
            for _ in range(wifi.MAX_DISCONNECTS):
                say("CPX: ESP32: I (1) WIFI: Disconnected from access point\n")


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(wifi, "REPLY_TIMEOUT_S", 0.2)
    monkeypatch.setattr(wifi, "JOIN_TIMEOUT_S", 1.0)


def make(**kw) -> tuple[DeckWifi, list, list]:
    states: list = []
    ips: list = []
    deck = DeckWifi(on_change=states.append, on_ip=ips.append, sleep=lambda _s: None)
    return deck, states, ips


class TestValidate:
    def test_accepts_a_normal_network(self):
        assert validate("Lab", "correct horse") == (b"Lab", b"correct horse")

    def test_an_open_network_has_no_password(self):
        assert validate("Cafe", "") == (b"Cafe", b"")

    @pytest.mark.parametrize("ssid", ["", "x" * 33])
    def test_refuses_a_name_outside_802_11_limits(self, ssid):
        with pytest.raises(WifiError):
            validate(ssid, "")

    @pytest.mark.parametrize("password", ["short", "x" * 48])
    def test_refuses_a_password_outside_what_the_deck_holds(self, password):
        """48+ is legal WPA2 but overflows the ESP32's 50-byte key buffer."""
        with pytest.raises(WifiError):
            validate("Lab", password)

    def test_a_name_is_measured_in_bytes_not_characters(self):
        with pytest.raises(WifiError):
            validate("é" * 17, "")  # 34 bytes


class TestPackets:
    def test_the_longest_password_the_deck_holds_is_accepted(self):
        assert validate("Lab", "k" * 47)[1] == b"k" * 47

    def test_every_packet_fits_the_app_channel(self):
        for pkt in packets(b"n" * 32, b"k" * 47):
            assert len(pkt) <= wifi.MTU

    def test_a_long_password_is_chunked_at_increasing_offsets(self):
        chunks = [p for p in packets(b"n", b"k" * 47) if p[0] == CMD_KEY]
        assert [c[1] for c in chunks] == [0, 28]
        assert b"".join(c[2:] for c in chunks) == b"k" * 47

    def test_an_open_network_sends_no_key_chunks(self):
        assert [p[0] for p in packets(b"Cafe", b"")] == [CMD_SSID, CMD_APPLY]

    def test_apply_carries_both_lengths(self):
        assert packets(b"Lab", b"password1")[-1] == bytes([CMD_APPLY, 3, 9])


class TestConsoleWatch:
    def test_an_address_split_across_fragments_is_found(self):
        watch = ConsoleWatch()
        for part in ("Wi", "Fi connected to ip: 192.1", "68.1.7\n"):
            watch.feed(part)
        assert watch.ip == "192.168.1.7"

    def test_an_incomplete_line_is_not_matched_yet(self):
        watch = ConsoleWatch()
        watch.feed("WiFi connected to ip: 10.0.0.4")
        assert watch.ip is None

    def test_disconnects_are_counted(self):
        watch = ConsoleWatch()
        watch.feed("WIFI: Disconnected from access point\n" * 3)
        assert watch.disconnects == 3


class TestApply:
    def test_nothing_is_sent_before_a_network_is_set(self):
        deck, _, _ = make()
        drone = FakeDrone()
        assert deck.apply(drone).phase is Phase.NOT_SET
        assert drone.sent == []

    def test_the_deck_joins_and_the_camera_is_told_where(self):
        deck, _, ips = make()
        deck.configure("Lab", "password1")
        drone = FakeDrone()
        state = deck.apply(drone)
        assert (state.phase, state.ip) == (Phase.JOINED, "10.0.0.42")
        assert ips == ["10.0.0.42"]
        assert bytes(drone.ssid[:3]) == b"Lab"
        assert bytes(drone.key[:9]) == b"password1"

    def test_stock_firmware_is_named_as_the_problem(self):
        deck, _, _ = make()
        deck.configure("Lab", "password1")
        state = deck.apply(FakeDrone(flashed=False))
        assert state.phase is Phase.FAILED
        assert "firmware" in (state.message or "")

    def test_too_early_after_boot_is_retried(self):
        deck, _, _ = make()
        deck.configure("Lab", "password1")
        assert deck.apply(FakeDrone(early=2)).phase is Phase.JOINED

    def test_a_wrong_password_ends_in_words_an_operator_can_act_on(self):
        deck, _, _ = make()
        deck.configure("Lab", "password1")
        state = deck.apply(FakeDrone(join="fail"))
        assert state.phase is Phase.FAILED
        assert "password" in (state.message or "")

    def test_a_deck_that_never_reports_times_out_rather_than_hanging(self):
        deck, _, _ = make()
        deck.configure("Lab", "password1")
        assert deck.apply(FakeDrone(join="silent")).phase is Phase.FAILED

    def test_already_applied_keeps_a_known_address(self):
        """A second link in the same power-on: the firmware refuses to re-apply
        (the ESP32 would reboot); the address from the first apply stands."""
        deck, _, _ = make()
        deck.configure("Lab", "password1")
        drone = FakeDrone()
        deck.apply(drone)
        state = deck.apply(drone)
        assert (state.phase, state.ip) == (Phase.JOINED, "10.0.0.42")

    def test_already_applied_with_no_address_asks_for_a_restart(self):
        deck, _, _ = make()
        deck.configure("Lab", "password1")
        state = deck.apply(FakeDrone(applied=True))
        assert state.phase is Phase.FAILED
        assert "Restart the drone" in (state.message or "")

    def test_listeners_are_removed_afterwards(self):
        deck, _, _ = make()
        deck.configure("Lab", "password1")
        drone = FakeDrone()
        deck.apply(drone)
        assert drone.appchannel.packet_received.callbacks == []
        assert drone.console.receivedChar.callbacks == []


class TestState:
    def test_the_password_never_appears_in_state(self):
        deck, states, _ = make()
        deck.configure("Lab", "hunter2hunter2")
        assert "hunter2" not in repr(deck.state().to_dict())
        assert all("hunter2" not in repr(s.to_dict()) for s in states)

    def test_forget_clears_the_network(self):
        deck, _, _ = make()
        deck.configure("Lab", "password1")
        assert deck.forget().phase is Phase.NOT_SET
        assert deck.state().ssid is None


class TestRememberedAddress:
    def test_a_restarted_agent_still_knows_where_the_camera_is(self, tmp_path):
        """The drone refuses a second apply until it restarts; an agent that
        restarted without it must not be left asking for a drone restart."""
        joined = tmp_path / "deck-wifi.json"
        first = DeckWifi(sleep=lambda _s: None, joined_file=joined)
        first.configure("Lab", "password1")
        drone = FakeDrone()
        assert first.apply(drone).phase is Phase.JOINED

        ips: list = []
        second = DeckWifi(on_ip=ips.append, sleep=lambda _s: None, joined_file=joined)
        second.configure("Lab", "password1")
        state = second.apply(drone)            # the same power-on: ALREADY_APPLIED
        assert (state.phase, state.ip) == (Phase.JOINED, "10.0.0.42")
        assert ips == ["10.0.0.42"]            # and the camera is pointed there

    def test_the_address_is_for_that_network_only(self, tmp_path):
        joined = tmp_path / "deck-wifi.json"
        joined.write_text('{"ssid": "Other", "ip": "10.9.9.9"}')
        deck = DeckWifi(sleep=lambda _s: None, joined_file=joined)
        deck.configure("Lab", "password1")
        assert deck.apply(FakeDrone(applied=True)).phase is Phase.FAILED

    def test_forget_removes_it(self, tmp_path):
        joined = tmp_path / "deck-wifi.json"
        joined.write_text('{"ssid": "Lab", "ip": "10.0.0.42"}')
        DeckWifi(joined_file=joined).forget()
        assert not joined.exists()

    def test_a_corrupt_file_is_ignored(self, tmp_path):
        joined = tmp_path / "deck-wifi.json"
        joined.write_text("not json")
        deck = DeckWifi(sleep=lambda _s: None, joined_file=joined)
        deck.configure("Lab", "password1")
        assert deck.apply(FakeDrone(applied=True)).phase is Phase.FAILED

    def test_the_file_never_holds_the_password(self, tmp_path):
        joined = tmp_path / "deck-wifi.json"
        deck = DeckWifi(sleep=lambda _s: None, joined_file=joined)
        deck.configure("Lab", "hunter2hunter2")
        deck.apply(FakeDrone())
        assert "hunter2" not in joined.read_text()


class TestLinkDown:
    def test_a_join_is_not_claimed_once_the_drone_is_gone(self):
        deck, _, _ = make()
        deck.configure("Lab", "password1")
        deck.apply(FakeDrone())
        state = deck.link_down()
        assert state.phase is Phase.WAITING
        assert state.ip is None
        assert "Last on Lab at 10.0.0.42" in (state.message or "")

    def test_nothing_changes_when_nothing_was_joined(self):
        deck, _, _ = make()
        deck.configure("Lab", "password1")
        assert deck.link_down().phase is Phase.WAITING
        assert deck.forget().phase is Phase.NOT_SET
        assert deck.link_down().phase is Phase.NOT_SET

    def test_the_address_is_still_remembered_for_an_already_applied_drone(self, tmp_path):
        """link_down clears what is SHOWN, not what the agent knows: a drone
        that comes back without restarting is still at its address."""
        joined = tmp_path / "deck-wifi.json"
        deck = DeckWifi(sleep=lambda _s: None, joined_file=joined)
        deck.configure("Lab", "password1")
        drone = FakeDrone()
        deck.apply(drone)
        deck.link_down()
        state = deck.apply(drone)                # ALREADY_APPLIED, same power-on
        assert (state.phase, state.ip) == (Phase.JOINED, "10.0.0.42")


class TestWatch:
    """The deck's Wi-Fi reports, followed for the life of the link — the fix for
    a page that said "joined" while the deck had dropped off (2026-09-24)."""

    def joined(self):
        ips: list = []
        deck = DeckWifi(on_ip=ips.append, sleep=lambda _s: None)
        deck.configure("VT Open WiFi", "")
        drone = FakeDrone(ip="100.96.93.94")
        stop = deck.watch(drone)
        say = drone.console.receivedChar.call
        say("CPX: ESP32: I (1) WIFI: rssi: -84\n")
        deck.apply(drone)
        return deck, drone, say, ips, stop

    def test_the_signal_is_kept_and_called_weak(self):
        deck, *_ = self.joined()
        state = deck.state()
        assert (state.phase, state.rssi) == (Phase.JOINED, -84)
        assert "-84 dBm (weak)" in (state.message or "")

    def test_a_drop_is_shown_as_rejoining_and_says_why(self):
        deck, _, say, _, _ = self.joined()
        say("CPX: ESP32: I (9) WIFI: Disconnected from access point\n")
        state = deck.state()
        assert state.phase is Phase.RECONNECTING
        assert state.ip is None
        assert "weak signal (-84 dBm)" in (state.message or "")
        say("CPX: ESP32: I (9) WIFI: Disconnected from access point\n")
        assert deck.state().drops == 2

    def test_rejoining_moves_the_camera_to_the_new_address(self):
        deck, _, say, ips, _ = self.joined()
        say("CPX: ESP32: I (9) WIFI: Disconnected from access point\n")
        say("CPX: ESP32: I (12) WIFI: got ip: 100.96.93.120\n")
        state = deck.state()
        assert (state.phase, state.ip) == (Phase.JOINED, "100.96.93.120")
        assert ips[-1] == "100.96.93.120"

    def test_the_same_address_reported_twice_is_one_event(self):
        deck, _, say, ips, _ = self.joined()
        count = len(ips)
        say("CPX: WiFi connected to ip: 100.96.93.94\n")
        assert len(ips) == count

    def test_stopping_the_watch_detaches_it(self):
        deck, drone, say, _, stop = self.joined()
        stop()
        say("CPX: ESP32: I (9) WIFI: Disconnected from access point\n")
        assert deck.state().phase is Phase.JOINED
        assert drone.console.receivedChar.callbacks == []
