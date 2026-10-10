IMAGE CLASSIFIER — story 4.4: a frame is faulty (visible damage) or not
================================================================================
Definition of "faulty": docs/features/pipeline/classify.txt (PROVISIONAL —
visible damage to the test equipment; story 6.1 will replace it).

LAYOUT
  data/raw/                  the photos. NEVER COMMITTED (.gitignore).
  manifests/images.csv       one row per photo. Committed; this is the dataset.
  validate_manifest.py       checks the manifest against data/raw/

MANIFEST COLUMNS
  file         path under data/raw/, forward slashes (e.g. s1/IMG_0001.jpg)
  label        normal | faulty
  defect_type  what the damage is (crack, dent, tilted, missing_panel, ...);
               empty for normal. Free text for now — keep the words consistent.
  angle        where the photo was taken from (front, left, above, ...)
  session      one id per sitting (s1, s2, ...). Photos taken in one sitting
               share it. Train/test are split BY SESSION, never by photo:
               neighbouring photos are near-duplicates and a random split
               reports an accuracy the model has not earned.
  date         YYYY-MM-DD

IF THE DEFINITION OF "FAULTY" CHANGES, RELABEL. defect_type exists so that is
a column edit, not a re-photograph.

PHOTOS SHOULD LOOK LIKE WHAT THE STAGE SEES: the drone's camera is 324 x 244
grayscale. Prefer frames from the drone; check a phone photo still shows the
damage after shrinking to that size.

SETUP   python -m venv ml/image-classifier/.venv
        ml/image-classifier/.venv/Scripts/python -m pip install -r ml/image-classifier/requirements.txt
        (on macOS/Linux: .venv/bin/python)

CHECK   python ml/image-classifier/validate_manifest.py
PREPARE .venv/.../python ml/image-classifier/preprocess.py [--check] [--preview]
        data/raw/ -> data/processed/: 324 x 244 grayscale, the stage's own
        format; a screenshot's crosshair is inpainted away; each frame is
        measured with the enhancer's quality limits. to_model_input() is the
        model's input contract (1x3x224x224) and stages/classify/image.py must
        match it exactly.

KNOWN LIMIT  The crosshair removal is invisible on flat backgrounds but SMEARS
        detail under the reticle: on s1's gauge close-up of the bad reading it
        sits on the needle. A screenshot is a stopgap — replace it with the
        clean frame the agent saved (data/raw/ from a session's frames/).
