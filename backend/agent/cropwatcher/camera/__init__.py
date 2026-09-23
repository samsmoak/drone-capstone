"""The camera path: where frames come from, and what is done with them.

WHY THIS EXISTS BEFORE A CAMERA DOES. The AI deck is fitted on this drone
(`deck.bcAI` reads 1) but its Wi-Fi datalink has never worked, so there is no
source of real frames. Everything downstream of that one link — serving frames
to the window, the window's content policy, writing them beside the flight CSV,
uploading them through the outbox — is ordinary work that can be built and
proven now, against a generated frame.

So the deck is the ONLY unknown. When a lab session establishes how to reach it,
one `FrameSource` implementation replaces `TestPattern` and the rest is already
running.

NOT OVER THE RADIO. The frames cannot come over CRTP. Usable throughput there is
a few KB/s and the same link carries the 50 Hz setpoint stream — the Crazyflie
drops out of the air below about 10 Hz of commands, so congesting it with image
data risks the drone. That is why the deck carries its own Wi-Fi chip. The radio
IS enough to ask whether the deck is fitted, which is a param read and is done
in flight/checks.py.
"""

from cropwatcher.camera.source import (
    CameraStatus,
    FrameSource,
    NoCamera,
    TestPattern,
)

__all__ = ["CameraStatus", "FrameSource", "NoCamera", "TestPattern"]
