"""Warp the SIFT-matched sources into banner space and compare with the banners.

For each banner with a non-self hit of at least 40 inliers this writes
sift-hits/banner-<k>-check.png: banner, warped source, absolute difference, and
the source picture with the banner footprint outlined. It also prints how much
of the banner (and of its text box) the source covers, and the colour relation
between source and banner outside the text.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "work/authoring/special-disc/images"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import find_banner_sources_sift as fb  # noqa: E402

MIN_INLIERS = 40
W, H = fb.BANNER_ART[2], fb.BANNER_ART[3]


def source_rgb(source: str) -> np.ndarray:
    """Source picture as RGB uint8."""
    if source.endswith(".png"):
        im = cv2.imread(str(fb.AID / source), cv2.IMREAD_UNCHANGED)
        if im.shape[2] == 4:
            im = im[..., :3]
        return np.ascontiguousarray(im[..., ::-1])
    _member, pid = source.split(":", 1)
    inv = json.loads((fb.TD / "sp-inventory.json").read_text())
    for r in inv:
        for p in r["pictures"]:
            if p["id"] == pid:
                return np.ascontiguousarray(fb.render_rgb(p["record_sha256"] + ".tm2", p["picture"]))
    raise KeyError(source)


def banner_rgba(k: int) -> np.ndarray:
    im = cv2.imread(str(OUT / "jobs" / f"aid-banner-{k}" / "source.png"), cv2.IMREAD_UNCHANGED)
    return np.ascontiguousarray(im[:H, :W][..., [2, 1, 0, 3]])


def main() -> None:
    report = json.loads((OUT / "banner-sources-sift.json").read_text())
    fb.HITS.mkdir(exist_ok=True)
    summary = {}
    for k, rows in report.items():
        k = int(k)
        hits = [h for h in rows if not h["source"].startswith("block-002-tim2-01-") and h["inliers"] >= MIN_INLIERS]
        if not hits:
            summary[k] = None
            continue
        h = hits[0]
        A = np.array(h["affine"], np.float64)
        src = source_rgb(h["source"])
        if h["invert"]:
            src_show = 255 - src
        else:
            src_show = src
        warped = cv2.warpAffine(src_show, A, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 0, 255))
        cover = cv2.warpAffine(np.full(src.shape[:2], 255, np.uint8), A, (W, H),
                               flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderValue=0) > 0
        ban = banner_rgba(k)
        alpha = ban[..., 3] > 0
        tx0, ty0, tx1, ty1 = fb.TEXT_BOXES[k]
        text = np.zeros((H, W), bool)
        text[ty0:ty1, tx0:min(tx1, 600)] = True
        fit = alpha & cover & ~text
        # Per-channel linear fit banner ~ a*source + b outside the text box.
        coeffs, resid = [], []
        for c in range(3):
            x = warped[..., c][fit].astype(np.float64)
            y = ban[..., c][fit].astype(np.float64)
            a, b = np.polyfit(x, y, 1)
            coeffs.append((round(a, 3), round(b, 1)))
            resid.append(float(np.abs(a * x + b - y).mean()))
        summary[k] = dict(source=h["source"], inliers=h["inliers"], invert=h["invert"],
                          banner_covered=round(float((cover & alpha).sum() / alpha.sum()), 3),
                          text_box_covered=round(float((cover & text & alpha).sum() / max(1, (text & alpha).sum())), 3),
                          colour_fit=coeffs, mean_abs_residual=[round(r, 1) for r in resid])
        # Sheet.
        s = 2
        bg = np.full((H, W, 3), 40, np.uint8)
        a3 = ban[..., 3:4].astype(np.float64) / 255.0
        ban_rgb = (ban[..., :3] * a3 + bg * (1 - a3)).astype(np.uint8)
        diff = np.abs(ban_rgb.astype(np.int32) - warped.astype(np.int32)).clip(0, 255).astype(np.uint8)
        diff[~cover] = 0
        panel = np.vstack([ban_rgb, np.full((4, W, 3), 90, np.uint8), warped, np.full((4, W, 3), 90, np.uint8), diff])
        panel = cv2.resize(panel, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST)
        cv2.rectangle(panel, (tx0 * s, (2 * H + 8 + ty0) * s), (min(tx1, 600) * s, (2 * H + 8 + ty1) * s - 1),
                      (255, 255, 0), 1)
        foot = src_show.copy()
        corners = np.array([[0, 0, 1], [W, 0, 1], [W, H, 1], [0, H, 1]], np.float64) @ A.T
        cv2.polylines(foot, [corners.astype(np.int32)], True, (255, 0, 0), 2)
        tcorners = np.array([[tx0, ty0, 1], [600, ty0, 1], [600, ty1, 1], [tx0, ty1, 1]], np.float64) @ A.T
        cv2.polylines(foot, [tcorners.astype(np.int32)], True, (255, 255, 0), 2)
        fh = panel.shape[1] * foot.shape[0] // foot.shape[1]
        foot = cv2.resize(foot, (panel.shape[1], fh), interpolation=cv2.INTER_AREA)
        sheet = np.vstack([panel, np.full((8, panel.shape[1], 3), 90, np.uint8), foot])
        cv2.imwrite(str(fb.HITS / f"banner-{k}-check.png"), sheet[..., ::-1])
        cv2.imwrite(str(fb.HITS / f"banner-{k}-warped.png"), warped[..., ::-1])
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    (fb.HITS / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
