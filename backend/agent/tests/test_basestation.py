"""Base station channels over USB (flight/basestation.py).

2026-10-05: light on all four sensors and the calibration decoded, yet no
sweep became an angle — Bitcraze: every V2 station must be on a unique
channel. These pin the conversation Bitcraze's own client has with a station.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cropwatcher.flight import basestation as bs


class FakeStation:
    """A station's serial console: remembers its mode, and whether it saved."""

    def __init__(self, mode=0, obeys=True):
        self.mode, self.saved, self.obeys, self.sent = mode, False, obeys, []

    def talk(self, port, lines, wait_s):
        self.sent.extend(lines)
        out = []
        for line in lines:
            if line.startswith("mode ") and self.obeys:
                self.mode = int(line.split()[1])
            elif line == "param save":
                self.saved = True
            elif line == "mode":
                out += ["mode", f"Current mode: {self.mode}", ">"]
        return out


def port(device, vid=bs.VID, pid=bs.PID):
    return SimpleNamespace(device=device, vid=vid, pid=pid, serial_number="LHB-1")


def test_only_base_stations_are_listed_with_their_channel():
    station = FakeStation(mode=0)
    found = bs.find(talk=station.talk,
                    list_ports=lambda: [port("/dev/cu.bs"), port("/dev/cu.other", vid=0x1915)])
    assert [s.port for s in found] == ["/dev/cu.bs"]
    assert found[0].channel == 0
    assert found[0].to_dict()["supported"] is False        # 0 is not decoded


def test_setting_a_channel_saves_it_and_reads_it_back():
    station = FakeStation(mode=0)
    assert bs.set_channel("/dev/cu.bs", 2, talk=station.talk) == 2
    assert station.sent == ["mode 2", "param save", "mode"]   # cfclient's order
    assert station.saved and station.mode == 2


def test_a_station_that_does_not_confirm_is_a_failure_in_words():
    station = FakeStation(mode=1, obeys=False)
    with pytest.raises(bs.BaseStationError, match="did not confirm channel 2"):
        bs.set_channel("/dev/cu.bs", 2, talk=station.talk)


def test_channels_outside_what_the_drone_decodes_are_refused():
    with pytest.raises(bs.BaseStationError, match="1 to 16"):
        bs.set_channel("/dev/cu.bs", 0, talk=FakeStation().talk)


def test_the_reply_is_parsed_from_the_last_report():
    assert bs.parse_channel(["noise", "Current mode: 1", "Current mode: 2"]) == 2
    assert bs.parse_channel(["Current mode: x"]) is None
    assert bs.parse_channel([]) is None
