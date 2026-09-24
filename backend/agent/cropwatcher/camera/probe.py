"""Ask the drone what it knows about the AI deck — and whether the GAP8 answers.

Frames do NOT come this way: cflib's CPX CRTPTransport is a stub (every
method is `pass`), so the deck's Wi-Fi carries the camera — see deck.py. This
probe answers the questions the radio CAN: which decks are fitted, and whether
the GAP8 answers at all.

Three questions, in the order that makes the next one worth asking:

  1. Which decks does the drone say are fitted?  deck.* params
  2. If bcAI is 0, is that detection or hardware? every deck param, plus the
     1-Wire memory count, tells them apart
  3. Does the GAP8 answer CPX at all?            the actual go / no-go

Reads only. No motors, no arming, no setpoints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: Every deck param worth reading. bcAI is the camera's; the rest place it in
#: context — if ALL of them read 0 the expansion header is the suspect, not the
#: AI deck in particular.
DECK_PARAMS = (
    "deck.bcAI",
    "deck.bcLighthouse4",
    "deck.bcFlow2",
    "deck.bcFlow",
    "deck.bcZRanger2",
    "deck.bcZRanger",
    "deck.bcMultiranger",
    "deck.bcLedRing",
    "deck.bcBuzzer",
)


@dataclass
class DeckReport:
    """What the drone said. `None` means the param could not be read at all,
    which is different from the drone saying 0."""

    decks: dict[str, bool | None] = field(default_factory=dict)
    #: How many 1-Wire memories the firmware enumerated. 0 with a deck visibly
    #: attached is the signature of a contact or blank-EEPROM problem rather
    #: than a missing board.
    ow_count: int | None = None
    #: Whether anything answered on the GAP8 over CPX.
    gap8_answered: bool | None = None
    gap8_detail: str = ""

    @property
    def any_deck(self) -> bool:
        return any(v for v in self.decks.values())

    def verdict(self) -> str:
        """One line an operator standing at the drone can act on."""
        ai = self.decks.get("deck.bcAI")
        if ai:
            if self.gap8_answered:
                return "AI deck detected and the GAP8 answers — frames are buildable over CPX."
            if self.gap8_answered is False:
                return (
                    "AI deck detected, but the GAP8 does not answer CPX. Its own firmware "
                    "is the missing piece — flash a CPX-capable app to the deck."
                )
            return "AI deck detected. The GAP8 was not probed."
        if not self.any_deck:
            return (
                "The drone reports NO decks at all. They share one expansion header, so "
                "this is one contact problem rather than several missing boards: power "
                "down, reseat firmly, power up (detection runs at boot)."
            )
        return (
            "Other decks are detected but the AI deck is not, so the header is making "
            "contact. Suspect the AI deck's own 1-Wire memory — check it in cfclient's "
            "Deck memory tab, or force the driver."
        )


def read_decks(cf: Any) -> dict[str, bool | None]:
    """Every deck param, as the drone reports it.

    None, not False, when a param cannot be read: firmware that does not publish
    one has not said "no deck", and recording a guess as a measurement is what
    CLAUDE.md #5 exists to stop.
    """
    out: dict[str, bool | None] = {}
    for name in DECK_PARAMS:
        try:
            out[name] = str(cf.param.get_value(name)) == "1"
        except Exception:
            out[name] = None
    return out


def read_ow_count(cf: Any) -> int | None:
    """How many 1-Wire memories the firmware found.

    This is the number deck detection is built on. Zero with a deck visibly
    attached says the board is there and its EEPROM was never read — which is a
    contact or a blank-memory problem, not a missing deck.
    """
    for name in ("deck.count", "system.deckCount"):
        try:
            return int(cf.param.get_value(name))
        except Exception:
            continue
    return None


def probe_gap8(scf: Any, timeout_s: float = 2.0) -> tuple[bool | None, str]:
    """Does anything answer on the GAP8 over CPX?

    THE GO / NO-GO. The camera sits behind the GAP8, and the GAP8 only speaks if
    it is running an app that does. No transport fixes a silent processor, so
    this is asked before any frame code is written.

    Returns (answered, detail). None means the probe could not run at all —
    an old cflib, or no CPX on this firmware — which is not the same as silence.
    """
    try:
        from cflib.cpx import CPXFunction, CPXPacket, CPXTarget
    except Exception as e:                                   # pragma: no cover
        return None, f"this cflib has no CPX support ({type(e).__name__})"

    cpx = getattr(scf.cf, "cpx", None)
    if cpx is None:
        return None, (
            "this firmware exposes no CPX link over CRTP — the STM32 build has to "
            "carry it for the deck to be reachable this way"
        )
    try:
        cpx.sendPacket(
            CPXPacket(
                function=CPXFunction.SYSTEM,
                destination=CPXTarget.GAP8,
                data=bytearray([0x00]),
            )
        )
        reply = cpx.receivePacket(CPXFunction.SYSTEM, timeout=timeout_s)
        return True, f"GAP8 replied with {len(reply.data)} bytes"
    except Exception as e:
        return False, f"no reply from the GAP8 in {timeout_s:.0f} s ({type(e).__name__})"


def probe(scf: Any) -> DeckReport:
    """Everything above, in one pass, against an open link."""
    cf = scf.cf
    report = DeckReport(decks=read_decks(cf), ow_count=read_ow_count(cf))
    report.gap8_answered, report.gap8_detail = probe_gap8(scf)
    return report


def main() -> int:
    """Run the probe against whatever drone the radio can find.

        python -m cropwatcher.camera.probe

    Written to be re-run in the lab after reseating a deck: it answers, in one
    pass, whether the header is making contact and whether the GAP8 is
    reachable. Reads only.
    """
    import cflib.crtp
    from cflib.crazyflie import Crazyflie
    from cflib.crazyflie.mem import MemoryElement
    from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

    logging.basicConfig(level=logging.ERROR)
    cflib.crtp.init_drivers()
    found = cflib.crtp.scan_interfaces()
    if not found:
        print("No drone answered the radio. Is it switched on, and the dongle plugged in?")
        return 1

    with SyncCrazyflie(found[0][0], cf=Crazyflie(rw_cache="./cache")) as scf:
        report = probe(scf)
        for name, value in report.decks.items():
            shown = "YES" if value else ("no" if value is False else "unreadable")
            print(f"  {name:<24} {shown}")
        try:
            owned = len(scf.cf.mem.get_mems(MemoryElement.TYPE_1W))
        except Exception:
            owned = -1
        print(f"\n  1-Wire deck memories enumerated: {owned}")
        print(f"  GAP8 over CPX: {report.gap8_answered} ({report.gap8_detail})")
        print(f"\n{report.verdict()}")
        if owned == 0:
            print(
                "\nZERO 1-Wire memories is the finding that matters: deck detection reads\n"
                "an EEPROM on each deck over a SINGLE shared pin. None were read, so the\n"
                "boards are not being seen electrically — which is one contact fault, not\n"
                "several missing decks."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
