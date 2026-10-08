UPSCALING EVAL — which enhancer the pipeline's stage 2 runs
=========================================================

The evaluation behind docs/handoffs/sprint-1/undone/dpp-enhance.txt, steps 1–3:
score each candidate enhancer on real images, look for invented detail, and
pick one by the numbers. Nothing here runs on the agent; the winner is copied
into backend/agent/cropwatcher/pipeline/stages/enhance/ as measured.


SET UP (once)

  cd ml/upscaling-eval
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
  .venv/bin/python fetch_models.py      # models → data/models/, hashes checked


RUN (per set of images)

  .venv/bin/python prepare.py --src data/originals --name camera-frames --protocol self --mask crosshair
  .venv/bin/python score.py   --set camera-frames
  .venv/bin/python sheet.py   --set camera-frames --before-after espcn-x2
  .venv/bin/python sheet.py   --set camera-frames --blind espcn-x2,fsrcnn-x2,realesrgan-x4,clahe-unsharp
  .venv/bin/python sheet.py   --set camera-frames --compare espcn-x2,espcn-x2+clahe-1.0-0.0

  When the story 4.1 photos arrive, put them in data/photos/ and run the same
  three with --src data/photos --name photos --protocol reference (no --mask).
  The camera-frames set stays as it is beside it.


WHAT IS COMMITTED, AND WHAT IS NOT

  committed   the scripts; manifests/<set>.csv (each image's name, sha256 and
              crop); before-after-<set>.jpg; RESULTS.txt once there is a winner
  gitignored  data/ — the images, the prepared sets, the models, every run's
              output, and the blind sheet's key. Datasets are never committed
              (dpp-contract.txt, MODEL FILES), and the repository is public.


THE TWO PROTOCOLS (prepare.py says more)

  reference   The image has more detail than the camera: the ticket's protocol.
              The input is the image shrunk to 324×244, the truth is the image
              at the method's output size.
  self        The image IS a camera frame. The truth is the frame; the input is
              the frame shrunk by the method's scale. Used for the 15
              screenshots of 2026-10-06, which are camera frames enlarged
              ~2.56× by a viewer: shrunk to 324×244 and enlarged back they
              return at 42–46 dB, and under 0.6 % of their energy lies above
              the 324×244 Nyquist limit. They carry no detail finer than the
              camera's, so they cannot be the reference.


THE SHEETS — sheet.py's docstring says more

  Each frame gets two zoomed rows: DETAIL, its most detailed region, where a
  method can show more; and FLAT, its smoothest unclipped region, where a
  method can only add. Texture in a FLAT zoom that the original lacks is grain
  or invented detail. --compare is for tuning (names shown); --blind is for
  the teammates' check (letters only, key kept in data/).


THE METRICS — score.py's docstring defines each column

  PSNR / SSIM against the truth, ΔPSNR / ΔSSIM against bicubic at the same
  scale, "edges kept" (sharpness on real edges) and "flat texture" (detail
  where the truth is smooth — the invented-detail check). Read flat texture
  against bicubic's own figure, not against 1.0: the truth's smooth areas are
  nearly noise-free, so even plain interpolation scores 1.2 there.


KNOWN LIMITS (2026-10-07)

  - The camera-frames truth has been through the viewer's enlargement and our
    shrink, so it is softer than a raw frame; every method is judged against
    a smooth truth, which favours methods that add nothing.
  - SR networks were trained on bicubic-shrunk photos; prepare.py shrinks by
    area averaging, closer to a sensor. The mismatch costs them a little.
  - Times are this machine's (i9-11900H, 16 threads). The ticket wants the lab
    laptop's: re-run score.py there before RESULTS.txt is final.
  - 15 images, not the ticket's 30.
