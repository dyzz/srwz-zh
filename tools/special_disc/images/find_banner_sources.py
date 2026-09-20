"""Search SP artwork for the text-free source of the Special Theatre banners.

Each banner's text-free left part is matched (normalised cross-correlation on
greyscale and on gradient magnitude, several scales) against every exported
640x448-class picture: AIDDATA art, SP texture-diff pictures and the
AIDDATA menu background. Results go to banner-sources.json.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "work/authoring/special-disc/images"
AID = ROOT / "work/analysis/sp-aiddata-images-20260912/images"
TD = ROOT / "work/analysis/sp-texture-diff-20260912/images"
BANNERS = OUT / "jobs"
# Text-free part of each banner (x0, y0, x1, y1), left of the Japanese title.
TEMPLATE_BOXES = {1: (0, 2, 262, 77), 2: (0, 2, 368, 77), 3: (0, 2, 340, 77), 4: (0, 2, 350, 77), 5: (0, 2, 340, 77)}
SCALES = [round(s, 3) for s in np.arange(0.40, 1.61, 0.05)]


def grey(path: Path) -> np.ndarray | None:
    im = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if im is None:
        return None
    if im.ndim == 3 and im.shape[2] == 4:
        alpha = im[..., 3:4].astype(np.float32) / 255.0
        im = (im[..., :3].astype(np.float32) * alpha).astype(np.uint8)
    if im.ndim == 3:
        im = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    return im


def gradient(img: np.ndarray) -> np.ndarray:
    g = img.astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(gx, gy)


def templates():
    out = {}
    for k, (x0, y0, x1, y1) in TEMPLATE_BOXES.items():
        g = grey(BANNERS / f"aid-banner-{k}" / "source.png")
        out[k] = g[y0:y1, x0:x1]
    return out


TEMPLATES = None


def search(path_str: str):
    global TEMPLATES
    if TEMPLATES is None:
        TEMPLATES = templates()
    img = grey(Path(path_str))
    if img is None or img.shape[0] < 60 or img.shape[1] < 150:
        return []
    img_g = img.astype(np.float32)
    img_d = gradient(img)
    results = []
    for k, tpl in TEMPLATES.items():
        best = (-2.0, None, None, None)
        for s in SCALES:
            h = int(round(tpl.shape[0] / s))
            w = int(round(tpl.shape[1] / s))
            if h >= img.shape[0] or w >= img.shape[1] or h < 16 or w < 32:
                continue
            t = cv2.resize(tpl, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32)
            for mode, src, tt in (("grey", img_g, t), ("invert", img_g, 255 - t), ("edge", img_d, gradient(t.astype(np.uint8)))):
                r = cv2.matchTemplate(src, tt, cv2.TM_CCOEFF_NORMED)
                _, mx, _, loc = cv2.minMaxLoc(r)
                if mx > best[0]:
                    best = (float(mx), s, mode, loc)
        results.append({"banner": k, "score": best[0], "scale": best[1], "mode": best[2],
                        "loc": list(best[3]) if best[3] else None, "image": path_str})
    return results


def main() -> None:
    paths = sorted(str(p) for p in AID.glob("block-*.png"))
    paths += sorted(str(p) for p in TD.glob("*.png"))
    extra = [p for p in sys.argv[1:]]
    paths += extra
    print("candidates", len(paths))
    allres = []
    with ProcessPoolExecutor() as pool:
        for res in pool.map(search, paths, chunksize=8):
            allres.extend(res)
    report = {}
    for k in TEMPLATE_BOXES:
        rows = sorted((r for r in allres if r["banner"] == k), key=lambda r: -r["score"])[:8]
        report[k] = rows
        print(f"banner {k}:")
        for r in rows[:5]:
            print(f"   {r['score']:.3f} scale {r['scale']} {r['mode']:6s} loc {r['loc']} {Path(r['image']).name}")
    (OUT / "banner-sources.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
