"""Retitle the SP scenario-chart banner (HSFC #105) with the main game's recipe.

SP #105 (512x256, linear PSMT8, two 256-colour banks) carries the banner
「シナリオチャート Z」 at y 192-240. It is the main game's 「シナリオチャート」 banner
(HSFC atlas @0x30CC0, already localized as 剧情流程) moved down 192 rows and made
32 px longer; SP bank 0 equals the main palette shifted by +32 entries, and bank
1 is the highlighted (cream banner, black text) state.

The main game's reviewed writeback is reused unchanged in index space:
  * the text box background is restored from clean pixels of the same row
    (the main banner rows are flat; SP row 222 has one colour step);
  * the text is rendered by the project renderer with the locked recipe
    (HarmonyOS Sans SC, 23 pt, 4x supersample, #303030 stroke 1.25) and mapped
    to the same colour ramp (main 2, 16-30 -> SP 34, 48-62) by luminance.
The recipe is first replayed on the main game and must reproduce its locked
output exactly.

Outputs in jobs/hsfc-chart-title-z/: clean.png, final-zh.png (bank 0),
final-zh-bank1.png, final-zh-indexes.npy (logical indexes), rebuild.json.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "work/authoring/special-disc/images"
sys.path.insert(0, str(ROOT / "tools"))
from srwz.imagemagick import imagemagick_version, render_grayscale_text_mask, require_imagemagick  # noqa: E402
from srwz.tim2 import parse_tim2  # noqa: E402
from srwz.tim2_writeback import _csm1_palette_offset  # noqa: E402

TD = ROOT / "work/analysis/sp-texture-diff-20260912"
JOB = OUT / "jobs" / "hsfc-chart-title-z"
MAIN_RECORD = "520c390fc47c2d82a1cc3edb7ad9aed8b00ca161e38a875a1e457b8e046b15ba"
LIBRARY = ROOT / "config/library/v0.2.0.json"
SNAPSHOT = ROOT / "config/library/scenario-chart-runtime-render-snapshot.json"
FONT_LOCK = ROOT / "config/fonts/harmonyos-sans-sc.lock.json"
SHIFT_Y = 192  # SP banner rows = main rows + 192
SHIFT_INDEX = 32  # SP bank 0 entry = main entry + 32
EXTRA_LENGTH = 32  # SP banner is this much longer
TEXT = "剧情流程 Z"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode(record_sha: str, picture: int = 0):
    rec = (TD / "tim2" / f"{record_sha}.tm2").read_bytes()
    assert sha256(rec) == record_sha
    q = parse_tim2(rec).pictures[picture]
    a = q.offset + q.header_size
    idx = np.frombuffer(rec[a:a + q.image_size], np.uint8).reshape(q.height, q.width).copy()
    pal = rec[a + q.image_size:a + q.image_size + q.clut_size]
    banks = []
    for b in range(len(pal) // 1024):
        chunk = pal[b * 1024:(b + 1) * 1024]
        colours = np.array([list(chunk[_csm1_palette_offset(n) * 4:][:4]) for n in range(256)], np.int32)
        colours[:, 3] = np.minimum(255, colours[:, 3] * 2)
        banks.append(colours)
    return idx, banks


def scenario_contract() -> dict:
    def walk(node):
        if isinstance(node, dict):
            wb = node.get("writeback")
            if isinstance(wb, dict) and any(m.get("id") == "scenario-chart-title" for m in wb.get("masks", [])):
                return node
            for value in node.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = walk(value)
                if found:
                    return found
        return None
    contract = walk(json.loads(LIBRARY.read_text(encoding="utf-8")))
    assert contract["target"]["record_sha256"] == MAIN_RECORD
    return contract


def luminance(colour) -> float:
    return 0.2126 * colour[0] + 0.7152 * colour[1] + 0.0722 * colour[2]


def paint_text(logical, mask, x, y, width, height, ramp_indexes, colours):
    ramp = [(i, luminance(colours[i])) for i in ramp_indexes]
    top = max(v for _i, v in ramp)
    tones = np.frombuffer(mask, np.uint8).reshape(height, width)
    for r in range(height):
        for c in range(width):
            tone = int(tones[r, c])
            if tone:
                target = tone * top / 255
                logical[y + r, x + c] = min(ramp, key=lambda item: (abs(item[1] - target), item[0]))[0]


def restore_rows(logical, x, y, width, height, background, glyph_indexes):
    """Replace text pixels with the nearest clean background pixel of the same row."""
    box = logical[y:y + height, x:x + width]
    glyph = np.isin(box, list(glyph_indexes))
    near = ndimage.distance_transform_edt(~glyph) < 3
    keep = np.isin(box, list(background)) & ~near
    out = box.copy()
    for r in range(height):
        cols = np.where(keep[r])[0]
        assert len(cols), f"row {y + r} has no clean pixel"
        nearest = cols[np.abs(np.arange(width)[:, None] - cols[None, :]).argmin(1)]
        out[r] = box[r, nearest]
    logical[y:y + height, x:x + width] = out


def main() -> None:
    changes = json.loads((TD / "comparison.json").read_text())["changes"]
    sp_record = changes[105]["sp"]["record_sha256"]
    contract = scenario_contract()
    wb = contract["writeback"]
    mask_cfg = wb["masks"][0]
    restore = mask_cfg["background_restore"]
    font = ROOT / json.loads(FONT_LOCK.read_text())["font"]["path"]
    assert sha256(font.read_bytes()) == json.loads(FONT_LOCK.read_text())["font"]["sha256"]
    magick = require_imagemagick()
    assert imagemagick_version(magick) == wb["imagemagick_version"]
    style = dict(point_size=wb["point_size"], stroke_gray=wb["stroke_gray"], stroke_width=float(wb["stroke_width"]),
                 fill_stroke_width=float(wb["fill_stroke_width"]), supersample_factor=wb["supersample_factor"])
    main_ramp = wb["palette_indexes"]
    main_rows = restore["row_indexes"]

    # 1. Replay on the main game: must reproduce the locked output indexes.
    midx, mbanks = decode(MAIN_RECORD)
    replay = midx.copy()
    rx, ry, rw = restore["x"], restore["y"], restore["width"]
    for r, value in enumerate(main_rows):
        replay[ry + r, rx:rx + rw] = value
    live = render_grayscale_text_mask(magick, font, "剧情流程", width=mask_cfg["width"], height=mask_cfg["height"], **style)
    snapshot = json.loads(SNAPSHOT.read_text())
    frozen = zlib.decompress(base64.b64decode(snapshot["labels"][0]["mask"]["zlib_base64"]))
    assert live == frozen, "live render differs from the locked main-game mask"
    paint_text(replay, live, mask_cfg["x"], mask_cfg["y"], mask_cfg["width"], mask_cfg["height"], main_ramp, mbanks[0])
    assert sha256(replay.tobytes()) == snapshot["output_logical_indexes_sha256"], "main-game replay drift"

    # 2. SP banner.
    sidx, sbanks = decode(sp_record)
    for main_i in [2, *range(5, 32)]:
        assert (sbanks[0][main_i + SHIFT_INDEX] == mbanks[0][main_i]).all(), main_i
    ramp = [i + SHIFT_INDEX for i in main_ramp]
    glyph_indexes = {i + SHIFT_INDEX for i in range(16, 32)} | {2 + SHIFT_INDEX}
    background = {i + SHIFT_INDEX for i in range(5, 16)}
    box = dict(x=restore["x"], y=restore["y"] + SHIFT_Y, width=restore["width"] + EXTRA_LENGTH, height=len(main_rows))
    clean = sidx.copy()
    restore_rows(clean, box["x"], box["y"], box["width"], box["height"], background, glyph_indexes)
    text_box = dict(x=mask_cfg["x"], y=mask_cfg["y"] + SHIFT_Y, width=mask_cfg["width"] + EXTRA_LENGTH, height=mask_cfg["height"])
    zh_mask = render_grayscale_text_mask(magick, font, TEXT, width=text_box["width"], height=text_box["height"], **style)
    final = clean.copy()
    paint_text(final, zh_mask, text_box["x"], text_box["y"], text_box["width"], text_box["height"], ramp, sbanks[0])
    alpha_before = sbanks[0][sidx][..., 3] > 0
    for name, idx in (("clean", clean), ("final", final)):
        assert ((sbanks[0][idx][..., 3] > 0) == alpha_before).all(), f"{name}: alpha changed"
        changed = np.argwhere(idx != sidx)
        if len(changed):
            ys, xs = changed[:, 0], changed[:, 1]
            assert ys.min() >= 192 and ys.max() < 240 and xs.max() < 300, f"{name}: change outside the banner"

    np.save(JOB / "final-zh-indexes.npy", final)  # logical indexes; both banks depend on them
    Image.fromarray(sbanks[0][clean].astype(np.uint8), "RGBA").save(JOB / "clean.png")
    Image.fromarray(sbanks[0][final].astype(np.uint8), "RGBA").save(JOB / "final-zh.png")
    Image.fromarray(sbanks[1][final].astype(np.uint8), "RGBA").save(JOB / "final-zh-bank1.png")
    Image.fromarray(sbanks[1][sidx].astype(np.uint8), "RGBA").save(JOB / "source-bank1.png")
    report = dict(
        source=dict(member="DATA/HSFC.BIN", picture=changes[105]["sp"]["location"], record_sha256=sp_record,
                    banks="bank 0 normal (blue), bank 1 highlighted (cream, black text)"),
        main_game=dict(record_sha256=MAIN_RECORD, contract=str(LIBRARY.relative_to(ROOT)),
                       replay="live render and writeback reproduce the locked main-game output exactly"),
        mapping=dict(row_shift=SHIFT_Y, palette_shift=SHIFT_INDEX, extra_length=EXTRA_LENGTH,
                     ramp_indexes=ramp, restore_box=box, text_box=text_box),
        text=TEXT, style=dict(style, font=str(font.relative_to(ROOT))),
        outputs=dict(changed_pixels=int((final != sidx).sum()),
                     final_logical_indexes_sha256=sha256(final.tobytes())),
    )
    (JOB / "rebuild.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
