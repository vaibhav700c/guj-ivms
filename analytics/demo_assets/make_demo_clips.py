"""Build demo assets for the Investigate feature, from a stock test photo
bundled with the `insightface` package itself (its own multi-face detection
test fixture — not scraped, not a named/identifiable public figure).

Not part of the pipeline — a one-time setup helper so `register-local` +
`monitor/start` have real, looping video files and a real reference photo to
use when the live Sentinel grid has no close-up faces available (traffic-
angle cameras). Everything downstream is genuinely decoded frame-by-frame and
run through the real YOLOv8 + InsightFace pipeline; nothing about the
detection result is hardcoded — only the source footage is a controlled,
repeatable clip instead of a live camera, which the project brief explicitly
allows for a demo.

`t1.jpg` (insightface's own bundled multi-face fixture, 886x1280, 6 faces) is
used instead of the also-bundled `Tom_Hanks_54745.png` for two reasons:
1. That file is a pre-cropped, pre-aligned 112x112 ArcFace *input* (the exact
   recognition-model size), not a photo — SCRFD at the pipeline's real
   det_size=(640,640) detects zero faces in it, so a demo built from it would
   never produce a single match. Confirmed by direct testing.
2. It depicts a real, named public figure — inappropriate for a "wanted
   person" police-tool demo regardless of the above.

`t1.jpg`'s 6 faces let the demo prove something more realistic than "there is
a face": that the pipeline picks the *correct* individual out of several
faces in frame, and doesn't cross-alert when a different individual appears.

Run once (from analytics/, same venv as worker.py/control_server.py):
    .venv/bin/python demo_assets/make_demo_clips.py
"""
import os

import cv2
import insightface
from insightface.app import FaceAnalysis

ASSETS_DIR = os.path.join(os.path.dirname(insightface.__file__), "data", "images")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
FPS = 5
SECONDS = 12  # long enough to comfortably span a couple of face-pass cadences
PAD_FRAC = 0.6  # extra context around a cropped face — ArcFace wants more than just the box


def _pad_crop(img, bbox, pad_frac: float):
    h, w = img.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    x1 = max(0, int(x1 - bw * pad_frac))
    y1 = max(0, int(y1 - bh * pad_frac))
    x2 = min(w, int(x2 + bw * pad_frac))
    y2 = min(h, int(y2 + bh * pad_frac))
    return img[y1:y2, x1:x2]


def write_looping_clip(img, out_name: str) -> None:
    out_path = os.path.join(OUT_DIR, out_name)
    h, w = img.shape[:2]
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (w, h))
    for _ in range(FPS * SECONDS):
        writer.write(img)
    writer.release()
    print(f"wrote {out_path} ({w}x{h}, {FPS*SECONDS} frames)")


def main() -> None:
    src = cv2.imread(os.path.join(ASSETS_DIR, "t1.jpg"))
    if src is None:
        raise SystemExit("could not read bundled asset t1.jpg")

    app = FaceAnalysis(name="buffalo_l")
    app.prepare(ctx_id=-1, det_size=(640, 640))
    faces = app.get(cv2.cvtColor(src, cv2.COLOR_BGR2RGB))
    if len(faces) < 2:
        raise SystemExit(f"expected >=2 faces in t1.jpg, found {len(faces)}")
    # Sort left-to-right so which face is "target" vs "control" is deterministic.
    faces.sort(key=lambda f: f.bbox[0])
    target, control = faces[0], faces[1]

    ref_crop = _pad_crop(src, target.bbox, PAD_FRAC)
    ref_path = os.path.join(OUT_DIR, "reference_photo.jpg")
    cv2.imwrite(ref_path, ref_crop)
    print(f"wrote {ref_path} ({ref_crop.shape[1]}x{ref_crop.shape[0]}) — upload this as the wanted-person photo")

    # The "wanted person" demo video is the FULL group photo (6 faces, one of
    # them the enrolled target) — proves the pipeline finds the right person
    # among several, not just "a" person.
    write_looping_clip(src, "wanted_person_demo.mp4")

    # The control/negative demo is a DIFFERENT individual from the same
    # source photo, cropped to their own frame — a genuinely different face,
    # not a relabeled copy of the target.
    control_crop = _pad_crop(src, control.bbox, PAD_FRAC)
    write_looping_clip(control_crop, "control_person_demo.mp4")


if __name__ == "__main__":
    main()
