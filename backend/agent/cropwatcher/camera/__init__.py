"""The camera path: where frames come from, and what is done with them.

THREE SOURCES, one shape. `NoCamera` (the default), `TestPattern`
(CROPWATCHER_CAMERA=test) and `DeckStream` (CROPWATCHER_CAMERA=deck), which
reads the AI deck's own Wi-Fi image streamer — see deck.py for the wire format
as measured from the real deck.

NOT OVER THE RADIO. The frames cannot come over CRTP. Usable throughput there is
a few KB/s and the same link carries the 50 Hz setpoint stream — the Crazyflie
drops out of the air below about 10 Hz of commands, so congesting it with image
data risks the drone. That is why the deck carries its own Wi-Fi chip. The radio
IS enough to ask whether the deck is fitted, which is a param read and is done
in flight/checks.py.
"""

from cropwatcher.camera.deck import DeckStream
from cropwatcher.camera.source import (
    CameraStatus,
    FrameSource,
    NoCamera,
    TestPattern,
)

__all__ = ["CameraStatus", "DeckStream", "FrameSource", "NoCamera", "TestPattern"]
