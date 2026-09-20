"""Fit the user's AI-retitled Special Theatre banners 2 and 4 back into the texture.

The user delivered finished banners (Chinese already drawn by the AI tool):
影片集 (banner 2) and 战斗剧场 (banner 4), 2172x724 RGB on white. Each banner
rectangle is scaled to the 620x78 art area, aligned to the original banner on
the untouched art (ECC), and used only where the title changed; elsewhere the
original pixels are kept. The result keeps the original alpha and is quantized
to the banner's own palette bank.

Outputs in jobs/aid-banner-<k>/: final-zh.png, preview-ja.png, preview-zh.png,
rebuild.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "work/authoring/special-disc/images"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rebuild_banner1 import quantize  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from srwz.tim2 import parse_tim2  # noqa: E402
from srwz.tim2_writeback import _csm1_palette_offset  # noqa: E402

BANNER_TIM2 = ROOT / "work/analysis/sp-aiddata-images-20260912/tim2/block-002-tim2-01.tm2"
W, H = 620, 78
BANNERS = {
    2: dict(text="影片集", source="40d40959-9bda-4114-9596-b9edf8fb021a.png",
            sha256="1b23920d5c5120f6"),
    4: dict(text="战斗剧场", source="f2752f19-94ba-4884-b5d6-1e85421306eb.png",
            sha256="095c1a1ed5dfa9a4"),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def palette_bank(bank: int) -> np.ndarray:
    rec = BANNER_TIM2.read_bytes()
    q = parse_tim2(rec).pictures[0]
    a = q.offset + q.header_size + q.image_size
    clut = rec[a:a + q.clut_size][bank * 1024:(bank + 1) * 1024]
    return np.array([[*clut[_csm1_palette_offset(n) * 4:][:3], min(255, clut[_csm1_palette_offset(n) * 4 + 3] * 2)]
                     for n in range(256)], np.int32)


def banner_rect(image: np.ndarray):
    dev = (255 - image).max(-1)
    rows = np.where((dev > 30).mean(1) > 0.5)[0]
    return rows.min(), rows.max() + 1


def main() -> None:
    report = {}
    for k, meta in BANNERS.items():
        job = OUT / "jobs" / f"aid-banner-{k}"
        data = (job / "ai-final-original.png").read_bytes()
        assert sha256(data).startswith(meta["sha256"])
        ai = cv2.imread(str(job / "ai-final-original.png"))[..., ::-1].astype(np.float32)
        y0, y1 = banner_rect(ai)
        # The AI rectangle covers the full art height (rows 0-77 of the texture).
        small = cv2.resize(ai[y0:y1], (W, H), interpolation=cv2.INTER_AREA)
        texture = np.asarray(Image.open(job / "source.png").convert("RGBA")).copy()
        orig = texture[:H, :W, :3].astype(np.float32)
        alpha = texture[:H, :W, 3] > 0
        box = json.loads((OUT / "manifest.json").read_text())
        box = [j for j in box["jobs"] if j["slug"] == f"aid-banner-{k}"][0]["mask_boxes"][0]
        free = alpha.copy()
        free[:, box[0] - 40:] = False
        warp = np.eye(2, 3, dtype=np.float32)
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 500, 1e-6)
        _cc, warp = cv2.findTransformECCWithMask(
            cv2.cvtColor(orig, cv2.COLOR_RGB2GRAY), cv2.cvtColor(small, cv2.COLOR_RGB2GRAY),
            free.astype(np.uint8) * 255, np.full((H, W), 255, np.uint8), warp, cv2.MOTION_AFFINE, crit, 3)
        aligned = cv2.warpAffine(small, warp, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                 borderMode=cv2.BORDER_REPLICATE)
        # Per-channel colour match on the untouched art.
        for c in range(3):
            a, b = np.polyfit(aligned[..., c][free], orig[..., c][free], 1)
            aligned[..., c] = a * aligned[..., c] + b
        art_mae = float(np.abs(aligned - orig)[free].mean())
        # Where the title changed: large differences near the old title box, grown and feathered.
        diff = np.abs(aligned - orig).max(-1) > 24
        zone = np.zeros((H, W), bool)
        zone[max(0, box[1] - 14):H, max(0, box[0] - 70):W] = True
        changed = ndimage.binary_dilation(diff & zone, np.ones((7, 7))) & zone
        changed = ndimage.binary_closing(changed, np.ones((9, 9))) & zone
        weight = cv2.GaussianBlur(changed.astype(np.float32), (0, 0), 2.0)
        weight = np.maximum(weight, changed.astype(np.float32))[..., None]
        merged = orig * (1 - weight) + aligned * weight
        palette = palette_bank(k - 1)
        q = quantize(np.clip(merged, 0, 255), palette)
        final = texture.copy()
        region = final[:H, :W, :3]
        mask = (weight[..., 0] > 0.02) & alpha
        region[mask] = q[mask]
        assert (final[..., 3] == texture[..., 3]).all()
        opaque = {tuple(c[:3]) for c in palette if c[3] == 255}
        assert all(tuple(p) in opaque for p in final[:H, :W, :3][alpha])
        Image.fromarray(final).save(job / "final-zh.png")
        for name, img in (("preview-ja.png", texture), ("preview-zh.png", final)):
            crop = img[:H, :W]
            bg = np.full((H, W, 3), 40, np.uint8)
            vis = np.where(crop[..., 3:4] > 0, crop[..., :3], bg)
            Image.fromarray(vis).resize((W * 2, H * 2), Image.NEAREST).save(job / name)
        report[k] = dict(text=meta["text"], ai_file=f"jobs/aid-banner-{k}/ai-final-original.png", ai_sha256=sha256(data),
                         ai_rect_rows=[int(y0), int(y1)], ecc_affine=np.round(warp, 4).tolist(),
                         art_mae_after_colour_match=round(art_mae, 2), replaced_pixels=int(mask.sum()),
                         palette_bank=k - 1, final_sha256=sha256((job / "final-zh.png").read_bytes()))
        (job / "rebuild.json").write_text(json.dumps(report[k], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
