"""Download the candidate models into data/models/, check their hashes, and
export Real-ESRGAN to ONNX — the form the agent would run it in (contract,
MODEL FILES: ONNX, run with ONNX Runtime).

    python fetch_models.py

Every model's source and licence is recorded here, and goes into MODELS.json
with the one that wins.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass

from common import MODELS, sha256


@dataclass(frozen=True)
class Download:
    file: str
    url: str
    sha256: str
    license: str


# OpenCV's dnn_superres docs link these (docs.opencv.org, "Super Resolution
# using Convolutional Neural Networks"). Hashes pinned on 2026-10-07.
DOWNLOADS = [
    Download(
        "FSRCNN_x2.pb",
        "https://github.com/Saafke/FSRCNN_Tensorflow/raw/master/models/FSRCNN_x2.pb",
        "366b33f0084c7b3f2bf6724f0a2c77bca94fcec9d7b6d72389d330073b380d5c",
        "Apache-2.0 (github.com/Saafke/FSRCNN_Tensorflow)",
    ),
    Download(
        "FSRCNN_x4.pb",
        "https://github.com/Saafke/FSRCNN_Tensorflow/raw/master/models/FSRCNN_x4.pb",
        "5c68d18db561aed8ead4ffedf1b897ea615baaf60ebf6c35f8e641f8fa4a21bf",
        "Apache-2.0 (github.com/Saafke/FSRCNN_Tensorflow)",
    ),
    Download(
        "ESPCN_x2.pb",
        "https://github.com/fannymonori/TF-ESPCN/raw/master/export/ESPCN_x2.pb",
        "59f77351e1d7c0057bf6fe088b4a8a07e42c468c8c8aebb674a6b4ea1823221d",
        "Apache-2.0 (github.com/fannymonori/TF-ESPCN)",
    ),
    Download(
        "ESPCN_x4.pb",
        "https://github.com/fannymonori/TF-ESPCN/raw/master/export/ESPCN_x4.pb",
        "e403f06309229cf36009cd8fb0da032ba7643fae9f15cf94fe562e8edf8fef47",
        "Apache-2.0 (github.com/fannymonori/TF-ESPCN)",
    ),
    Download(
        "realesr-general-x4v3.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth",
        "8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292",
        "BSD-3-Clause (github.com/xinntao/Real-ESRGAN)",
    ),
]

REALESRGAN_ONNX = "realesr-general-x4v3.onnx"


def fetch(d: Download) -> None:
    path = MODELS / d.file
    if not path.exists():
        print(f"downloading {d.file}")
        urllib.request.urlretrieve(d.url, path)
    got = sha256(path)
    if d.sha256 and got != d.sha256:
        path.unlink()
        raise SystemExit(
            f"{d.file}: sha256 {got} is not the pinned {d.sha256} — deleted; "
            "the upstream file changed, check it before re-pinning"
        )
    print(f"ok  {d.file}  {path.stat().st_size / 1e6:.2f} MB  sha256 {got}")


def export_realesrgan() -> None:
    """realesr-general-x4v3 is an SRVGGNetCompact: 32 convolutions and a pixel
    shuffle. The architecture is defined here rather than installing basicsr,
    whose only use would be this one class."""
    import torch
    from torch import nn
    from torch.nn import functional as F

    class SRVGGNetCompact(nn.Module):
        def __init__(self, num_feat: int = 64, num_conv: int = 32, upscale: int = 4) -> None:
            super().__init__()
            self.upscale = upscale
            body: list[nn.Module] = [
                nn.Conv2d(3, num_feat, 3, 1, 1),
                nn.PReLU(num_parameters=num_feat),
            ]
            for _ in range(num_conv):
                body += [nn.Conv2d(num_feat, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
            body.append(nn.Conv2d(num_feat, 3 * upscale * upscale, 3, 1, 1))
            self.body = nn.ModuleList(body)
            self.upsampler = nn.PixelShuffle(upscale)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            out = x
            for layer in self.body:
                out = layer(out)
            return self.upsampler(out) + F.interpolate(x, scale_factor=self.upscale, mode="nearest")

    out = MODELS / REALESRGAN_ONNX
    if out.exists():
        print(f"ok  {REALESRGAN_ONNX}  {out.stat().st_size / 1e6:.2f} MB  (already exported)")
        return
    state = torch.load(MODELS / "realesr-general-x4v3.pth", map_location="cpu", weights_only=True)
    net = SRVGGNetCompact()
    net.load_state_dict(state.get("params_ema", state.get("params", state)))
    net.eval()
    dummy = torch.rand(1, 3, 61, 81)
    torch.onnx.export(
        net,
        (dummy,),
        str(out),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {2: "h", 3: "w"}, "output": {2: "h4", 3: "w4"}},
        opset_version=17,
        dynamo=False,
    )
    # The export must compute what PyTorch computes, or every score below is of the wrong model.
    import numpy as np
    import onnxruntime as ort

    with torch.no_grad():
        want = net(dummy).numpy()
    got = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"]).run(
        None, {"input": dummy.numpy()}
    )[0]
    err = float(np.abs(want - got).max())
    if err > 1e-3:
        out.unlink()
        raise SystemExit(f"ONNX export disagrees with PyTorch by {err} — deleted")
    print(
        f"ok  {REALESRGAN_ONNX}  {out.stat().st_size / 1e6:.2f} MB  "
        f"(max |ONNX − PyTorch| = {err:.1e})"
    )


def main() -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    for d in DOWNLOADS:
        fetch(d)
    export_realesrgan()


if __name__ == "__main__":
    main()
