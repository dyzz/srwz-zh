"""Explicit authoring command for the frozen native event-gallery banner.

Normal builds use banner.py and the locked picture/CLUT snapshot. This command
alone reads an illustration, font and the reviewed banner-1 title recipe. It
does not run an emulator or modify an ISO.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.tim2 import parse_tim2
from srwz.tim2_writeback import _csm1_palette_offset, swizzle_psmt8, unswizzle_psmt8

TITLE = "名场面集"
WIDTH, HEIGHT = 1024, 128
ART_WIDTH, ART_HEIGHT = 620, 78
EXPECTED_INK_BOX = (405, 35, 557, 65)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def provenance(path: Path) -> dict:
    path = path.resolve()
    try:
        label = str(path.relative_to(ROOT))
    except ValueError:
        label = str(path)
    return {"path": label, "sha256": sha256(path.read_bytes())}


class _NumpyCv2:
    """The float64 separable GaussianBlur used by the original title recipe.

    OpenCV's zero-size auto kernel uses cvRound(sigma*8+1)|1 for float images,
    and its default BORDER_REFLECT_101 is NumPy's reflect padding. Keeping this
    small compatible operation avoids importing the original script's unrelated
    OpenCV/SciPy art-fitting code during simple title rendering.
    """

    @staticmethod
    def GaussianBlur(image, kernel_size, *, sigmaX, sigmaY):
        assert kernel_size == (0, 0) and image.ndim == 2
        out = np.asarray(image, np.float64)
        for axis, sigma in ((1, float(sigmaX)), (0, float(sigmaY))):
            assert sigma > 0
            length = int(round(sigma * 8 + 1)) | 1
            radius = length // 2
            positions = np.arange(-radius, radius + 1, dtype=np.float64)
            weights = np.exp(-(positions * positions) / (2 * sigma * sigma))
            weights /= weights.sum()
            padding = [(0, 0), (0, 0)]
            padding[axis] = (radius, radius)
            padded = np.pad(out, padding, mode="reflect")
            windows = np.lib.stride_tricks.sliding_window_view(padded, length, axis=axis)
            out = np.tensordot(windows, weights, axes=([-1], [0]))
        return out


def load_title_renderer(path: Path, font: Path):
    """Execute the actual reviewed mask/composition bodies, not copied variants."""
    source = path.read_text()
    parsed = ast.parse(source, filename=str(path))
    constants = {"W", "H", "SHARED", "PITCH", "RIGHT_INK", "SS", "EDGE_GAIN",
                 "UNDERLINE_ROWS", "UNDERLINE_RIGHT", "UNDERLINE_LEAD", "INK"}
    functions = {"ink_box", "calibrate", "chinese_mask", "glow_alpha", "compose"}
    selected = []
    for node in parsed.body:
        if isinstance(node, ast.Assign):
            targets = {part.id for target in node.targets for part in ast.walk(target)
                       if isinstance(part, ast.Name)}
            if targets and targets <= constants:
                selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in functions:
            selected.append(node)
    assert {node.name for node in selected if isinstance(node, ast.FunctionDef)} == functions
    namespace = {"np": np, "Image": Image, "ImageDraw": ImageDraw,
                 "ImageFont": ImageFont, "FONT": font, "cv2": _NumpyCv2}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    assert (namespace["W"], namespace["H"]) == (ART_WIDTH, ART_HEIGHT)
    assert np.array_equal(namespace["INK"], (9, 9, 8))
    return namespace


def png_bytes(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def quantize(rgba: np.ndarray, solid_ink: np.ndarray):
    """Keep transparent index 0 and exact title ink at opaque index 1."""
    opaque = rgba[..., 3] == 255
    pixels = rgba[..., :3][opaque]
    q = Image.fromarray(pixels.reshape(-1, 1, 3)).quantize(
        colors=254, method=Image.Quantize.MEDIANCUT)
    palette = np.zeros((256, 4), np.uint8)
    palette[1] = (9, 9, 8, 255)
    palette[2:, :3] = np.asarray(q.getpalette(), np.uint8).reshape(-1, 3)[:254]
    palette[2:, 3] = 255
    indexes = np.zeros((HEIGHT, WIDTH), np.uint8)
    choices = np.empty(len(pixels), np.uint8)
    colors = palette[1:, :3].astype(np.int32)
    for start in range(0, len(pixels), 2048):
        samples = pixels[start:start + 2048].astype(np.int32)
        distances = ((samples[:, None, :] - colors[None, :, :]) ** 2).sum(-1)
        choices[start:start + len(samples)] = distances.argmin(1) + 1
    indexes[opaque] = choices
    indexes[solid_ink & opaque] = 1
    assert np.all(indexes[~opaque] == 0)
    assert np.all(indexes[opaque] != 0)
    assert np.array_equal(palette[indexes, 3], rgba[..., 3])
    return indexes, palette


def author(args) -> dict:
    font_lock_path = ROOT / "config/fonts/harmonyos-sans-sc.lock.json"
    font_lock = json.loads(font_lock_path.read_text())["font"]
    font = ROOT / font_lock["path"]
    assert sha256(font.read_bytes()) == font_lock["sha256"]
    style = json.loads(args.title_style.read_text())
    assert style["chinese"]["font_sha256"] == font_lock["sha256"]
    recipe = load_title_renderer(args.renderer, font)
    stroke = round(style["chinese"]["stroke_px"] * recipe["SS"])
    calibration = recipe["calibrate"](stroke)
    assert np.allclose(calibration[:2], style["chinese"]["em_px_xy"], atol=0.01)
    y0, y1 = recipe["UNDERLINE_ROWS"]

    render_stroke = stroke if args.title_stroke_px is None else round(args.title_stroke_px * recipe["SS"])

    def render(calibration):
        mask, layout = recipe["chinese_mask"](TITLE, render_stroke, calibration)
        glyph = mask.copy()
        glyph[y0:y1] = 0
        ys, xs = np.where(glyph > 0.5)
        return mask, layout, (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

    mask, layout, ink_box = render(calibration)
    if render_stroke == stroke:
        assert ink_box == EXPECTED_INK_BOX, f"Title glyph layout drift: {ink_box}"
    else:
        layout["title_stroke_px"] = args.title_stroke_px
    if args.title_height_scale != 1.0:
        # Taller glyphs than the native entries' calibrated boxes: scale the
        # vertical em only and keep the ink bottom on the native baseline.
        em_x, em_y, pen_top = calibration
        taller = (em_x, em_y * args.title_height_scale, pen_top)
        _mask, _layout, box = render(taller)
        taller = (em_x, taller[1], pen_top + (EXPECTED_INK_BOX[3] - box[3]))
        mask, layout, ink_box = render(taller)
        assert abs(ink_box[3] - EXPECTED_INK_BOX[3]) <= 1 and ink_box[1] >= 0, f"Taller title left the art: {ink_box}"
        layout["title_height_scale"] = args.title_height_scale

    background = Image.open(args.background).convert("RGBA")
    left, top, width, height = args.crop
    box = (left, top, left + width, top + height)
    assert width > 0 and height > 0
    assert 0 <= left < box[2] <= background.width and 0 <= top < box[3] <= background.height
    crop = background.crop(box)
    # Fill the generated art's diagonal transparent edge before resampling, then
    # impose the native banner alpha. This avoids black holes inside native art.
    plate = Image.new("RGBA", crop.size, (*args.matte, 255))
    plate.alpha_composite(crop)
    plate = plate.convert("RGB").resize((ART_WIDTH, ART_HEIGHT), Image.Resampling.LANCZOS)
    title = style["title_layer"]
    assert tuple(title["ink_rgb"]) == (9, 9, 8)
    glow = [*title["glow_blur_sigma_xy"], title["glow_gain"], title["glow_max"]]
    styled = recipe["compose"](np.asarray(plate, np.float64), mask, glow,
                               np.asarray(title["glow_rgb"], np.float64))
    shape = np.asarray(Image.open(args.shape_template).convert("RGBA"))[..., 3]
    assert shape.shape == (HEIGHT, WIDTH) and set(np.unique(shape).tolist()) <= {0, 255}
    outside = shape.copy()
    outside[:ART_HEIGHT, :ART_WIDTH] = 0
    assert not outside.any(), "Native alpha extends outside the supported art rectangle"
    rgba = np.zeros((HEIGHT, WIDTH, 4), np.uint8)
    rgba[:ART_HEIGHT, :ART_WIDTH, :3] = np.clip(styled, 0, 255).astype(np.uint8)
    rgba[..., 3] = shape
    solid_ink = np.zeros((HEIGHT, WIDTH), bool)
    solid_ink[:ART_HEIGHT, :ART_WIDTH] = mask >= 1.0
    indexes, palette = quantize(rgba, solid_ink)
    pixels = swizzle_psmt8(indexes.tobytes(), WIDTH, HEIGHT)
    assert unswizzle_psmt8(pixels, WIDTH, HEIGHT) == indexes.tobytes()
    clut = bytearray(1024)
    for index, (r, g, b, alpha) in enumerate(palette):
        offset = _csm1_palette_offset(index) * 4
        clut[offset:offset + 4] = bytes((int(r), int(g), int(b), 0x80 if alpha else 0))
    assert clut[:4] == bytes(4)
    assert clut[_csm1_palette_offset(1) * 4:][:4] == bytes((9, 9, 8, 128))
    for index in range(256):
        offset = _csm1_palette_offset(index) * 4
        assert tuple(clut[offset:offset + 3]) == tuple(palette[index, :3])
        assert (clut[offset + 3] != 0) == (palette[index, 3] != 0)

    native = args.tim2_template.read_bytes()
    tim2 = parse_tim2(native)
    template = tim2.pictures[4]  # original fifth/wallpaper banner header
    assert (template.width, template.height, template.image_type,
            template.header_size, template.clut_size) == (WIDTH, HEIGHT, 5, 48, 0)
    header = native[template.offset:template.offset + template.header_size]
    assert template.total_size == len(header) + len(pixels)
    assert struct.unpack_from("<H", header, 14)[0] == 0
    final = Image.fromarray(palette[indexes])
    assert np.array_equal(np.asarray(final)[..., 3], shape)
    preview = Image.new("RGBA", (ART_WIDTH, ART_HEIGHT), (24, 28, 34, 255))
    preview.alpha_composite(final.crop((0, 0, ART_WIDTH, ART_HEIGHT)))
    outputs = {
        "event-banner-picture.bin": header + pixels,
        "event-banner-clut.bin": bytes(clut),
        "event-banner.png": png_bytes(final),
        "event-banner-preview@2x.png": png_bytes(preview.resize((ART_WIDTH * 2, ART_HEIGHT * 2), Image.Resampling.NEAREST)),
    }
    receipt = {
        "schema_version": 1, "title": TITLE, "mode": "explicit_authoring",
        "background": provenance(args.background), "crop_xywh": list(args.crop),
        "crop_box_ltrb": list(box), "transparent_background_matte_rgb": list(args.matte),
        "inputs": {"native_shape": provenance(args.shape_template),
                   "native_tim2": provenance(args.tim2_template),
                   "title_recipe": provenance(args.title_style),
                   "renderer": provenance(args.renderer), "font": provenance(font)},
        "title_render": {"font": font_lock["path"], "stroke_px": render_stroke / recipe["SS"],
                         "native_entry_stroke_px": stroke / recipe["SS"],
                         "title_height_scale": args.title_height_scale,
                         "calibration": list(calibration), "layout": layout,
                         "ink_bbox": list(ink_box), "ink_rgb": [9, 9, 8],
                         "glow": {key: title[key] for key in ("glow_blur_sigma_xy", "glow_gain", "glow_max", "glow_rgb")},
                         "implementation": "Reviewed source function bodies; NumPy float64 GaussianBlur with BORDER_REFLECT_101"},
        "banner": {"width": WIDTH, "height": HEIGHT, "visible_rect": [0, 0, ART_WIDTH, ART_HEIGHT],
                   "picture_index": 5, "palette_bank": 5, "layout": "GS-swizzled PSMT8",
                   "alpha_shape_exact": True, "swizzle_roundtrip": True,
                   "transparent_index": 0, "solid_ink_index": 1,
                   "solid_ink_stored_rgba": [9, 9, 8, 128],
                   "original_five_pictures_and_cluts": "Not read for editing or modified; banner.append preserves them"},
        "outputs": {name: sha256(payload) for name, payload in outputs.items()},
        "runtime_status": "Authoring/readback validation only; no emulator or ISO modified",
    }
    outputs["asset-receipt.json"] = (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode()
    manifest = {"schema_version": 1, "mode": "locked_indexed_snapshot", "picture": 5,
                "palette_bank": 5, "files": {name: sha256(payload) for name, payload in outputs.items()}}
    try:
        relative_source = args.background.resolve().relative_to(args.outdir.resolve())
    except ValueError:
        pass
    else:
        manifest["files"][str(relative_source)] = sha256(args.background.read_bytes())
    outputs["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    # All construction/validation is complete before writing. Write the manifest
    # last so an interrupted authoring run fails the normal build's hash checks.
    args.outdir.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        (args.outdir / name).write_bytes(payload)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", type=Path, required=True, help="Selected text-free illustration")
    parser.add_argument("--crop", type=int, nargs=4, required=True, metavar=("LEFT", "TOP", "WIDTH", "HEIGHT"),
                        help="Crop in source pixels as XYWH, not LTRB")
    parser.add_argument("--outdir", type=Path, required=True, help="Explicit destination for the frozen snapshot")
    parser.add_argument("--shape-template", type=Path,
                        default=ROOT / "config/assets/special-disc/preview/aid-banner-5/final-zh.png")
    parser.add_argument("--tim2-template", type=Path,
                        default=ROOT / "work/analysis/sp-aiddata-images-20260912/tim2/block-002-tim2-01.tm2")
    parser.add_argument("--title-style", type=Path,
                        default=ROOT / "work/authoring/special-disc/images/jobs/aid-banner-1/rebuild.json")
    parser.add_argument("--renderer", type=Path, default=ROOT / "tools/special_disc/images/rebuild_banner1.py")
    parser.add_argument("--matte", type=int, nargs=3, default=(235, 225, 207), metavar=("R", "G", "B"))
    parser.add_argument("--title-stroke-px", type=float, default=None,
                        help="Override the title stroke width in output pixels (default: the native entry style)")
    parser.add_argument("--title-height-scale", type=float, default=1.0,
                        help="Vertical em multiplier for the title glyphs (1.0 = native entry calibration)")
    args = parser.parse_args()
    assert all(0 <= channel <= 255 for channel in args.matte)
    receipt = author(args)
    print(json.dumps({"outdir": str(args.outdir), "title": receipt["title_render"],
                      "banner": receipt["banner"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
