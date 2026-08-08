"""Small deterministic ImageMagick adapter for SRWZ image workflows."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path


class ImageMagickError(RuntimeError):
    """ImageMagick is unavailable or rejected an input."""


def require_imagemagick() -> str:
    executable = shutil.which("magick")
    if executable is None:
        raise ImageMagickError("ImageMagick 'magick' was not found")
    return executable


def imagemagick_version(executable: str) -> str:
    raw = _run([executable, "-version"], "ImageMagick version query")
    first_line = raw.decode("utf-8", errors="replace").splitlines()
    if not first_line:
        raise ImageMagickError("ImageMagick returned an empty version string")
    return first_line[0]


def _run(
    command: list[str],
    context: str,
    *,
    input_data: bytes | None = None,
) -> bytes:
    process = subprocess.run(
        command,
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        message = process.stderr.decode("utf-8", errors="replace").strip()
        raise ImageMagickError(
            f"{context} failed with exit {process.returncode}: {message}"
        )
    return process.stdout


def identify_dimensions(executable: str, path: Path) -> tuple[int, int]:
    raw = _run(
        [
            executable,
            "identify",
            "-format",
            "%w %h",
            str(path),
        ],
        f"ImageMagick identify for {path}",
    )
    try:
        width_text, height_text = raw.decode("ascii").split()
        width = int(width_text)
        height = int(height_text)
    except (UnicodeDecodeError, ValueError) as error:
        raise ImageMagickError(
            f"ImageMagick returned invalid dimensions for {path}: {raw!r}"
        ) from error
    if width <= 0 or height <= 0:
        raise ImageMagickError(
            f"ImageMagick returned invalid {width}x{height} dimensions"
        )
    return width, height


def render_tim2_png8(executable: str, source: Path, output: Path) -> None:
    """Render one TIM2 without palette-color dithering into PNG8.

    ImageMagick otherwise dithers slightly colored CLUT entries while
    quantizing to PNG8.  That can map one source index to multiple RGBA
    values, which is unsuitable for a lossless indexed writeback audit.
    """

    _run(
        [
            executable,
            str(source),
            "+dither",
            f"png8:{output}",
        ],
        f"ImageMagick TIM2 render for {source}",
    )
    if not output.is_file():
        raise ImageMagickError(
            f"ImageMagick did not create the expected PNG: {output}"
        )


def read_rgba8(
    executable: str,
    path: Path,
    *,
    expected_width: int,
    expected_height: int,
) -> bytes:
    width, height = identify_dimensions(executable, path)
    if (width, height) != (expected_width, expected_height):
        raise ImageMagickError(
            f"{path} is {width}x{height}, expected "
            f"{expected_width}x{expected_height}"
        )
    pixels = _run(
        [
            executable,
            str(path),
            "-alpha",
            "on",
            "-colorspace",
            "sRGB",
            "-depth",
            "8",
            "RGBA:-",
        ],
        f"ImageMagick RGBA render for {path}",
    )
    expected_size = expected_width * expected_height * 4
    if len(pixels) != expected_size:
        raise ImageMagickError(
            f"ImageMagick returned {len(pixels)} RGBA bytes for {path}, "
            f"expected {expected_size}"
        )
    return pixels


def write_rgba8_png(
    executable: str,
    pixels: bytes,
    output: Path,
    *,
    width: int,
    height: int,
) -> None:
    """Write fixed-size RGBA bytes as a PNG through ImageMagick."""

    expected_size = width * height * 4
    if len(pixels) != expected_size:
        raise ImageMagickError(
            f"RGBA input has {len(pixels)} bytes, expected {expected_size}"
        )
    _run(
        [
            executable,
            "-size",
            f"{width}x{height}",
            "-depth",
            "8",
            "RGBA:-",
            str(output),
        ],
        f"ImageMagick RGBA PNG write for {output}",
        input_data=pixels,
    )
    if not output.is_file():
        raise ImageMagickError(
            f"ImageMagick did not create the expected PNG: {output}"
        )


def write_deterministic_rgba8_png(
    executable: str,
    pixels: bytes,
    output: Path,
    *,
    width: int,
    height: int,
) -> None:
    """Write PNG32 while removing time and other incidental metadata."""

    expected_size = width * height * 4
    if len(pixels) != expected_size:
        raise ImageMagickError(
            f"RGBA input has {len(pixels)} bytes, expected {expected_size}"
        )
    _run(
        [
            executable,
            "-size",
            f"{width}x{height}",
            "-depth",
            "8",
            "RGBA:-",
            "-strip",
            "-define",
            "png:exclude-chunks=date,time",
            f"PNG32:{output}",
        ],
        f"ImageMagick deterministic RGBA PNG write for {output}",
        input_data=pixels,
    )
    if not output.is_file():
        raise ImageMagickError(
            f"ImageMagick did not create the expected PNG: {output}"
        )


def render_grayscale_text_mask(
    executable: str,
    font: Path,
    text: str,
    *,
    width: int,
    height: int,
    point_size: int,
    stroke_gray: str,
    stroke_width: float,
    fill_stroke_width: float = 0,
    italic_shear_degrees: float = 0,
) -> bytes:
    """Render text inside one fixed-size atlas-element canvas.

    The optional horizontal shear is cropped back to the requested canvas, so
    an italic treatment cannot change the source element geometry.
    """

    if not font.is_file():
        raise ImageMagickError(f"font was not found: {font}")
    if not text or "\n" in text or "\r" in text:
        raise ImageMagickError("text must be one non-empty line")
    if width <= 0 or height <= 0 or point_size <= 0:
        raise ImageMagickError("text mask geometry must be positive")
    if stroke_width < 0 or fill_stroke_width < 0:
        raise ImageMagickError("text mask stroke widths cannot be negative")
    if (
        not isinstance(italic_shear_degrees, (int, float))
        or isinstance(italic_shear_degrees, bool)
        or not math.isfinite(float(italic_shear_degrees))
        or not -30 <= float(italic_shear_degrees) <= 30
    ):
        raise ImageMagickError(
            "text mask italic shear must be between -30 and 30 degrees"
        )
    command = [
        executable,
        "-size",
        f"{width}x{height}",
        "xc:black",
        "-font",
        str(font),
        "-pointsize",
        str(point_size),
        "-gravity",
        "center",
        "-fill",
        stroke_gray,
        "-stroke",
        stroke_gray,
        "-strokewidth",
        str(stroke_width),
        "-annotate",
        "+0+0",
        text,
        "-fill",
        "white",
        "-stroke",
        "white",
        "-strokewidth",
        str(fill_stroke_width),
        "-annotate",
        "+0+0",
        text,
    ]
    if italic_shear_degrees:
        command.extend(
            [
                "-background",
                "black",
                "-shear",
                f"{float(italic_shear_degrees):g}x0",
                "-gravity",
                "center",
                "-extent",
                f"{width}x{height}",
            ]
        )
    command.extend(
        [
            "-alpha",
            "off",
            "-colorspace",
            "Gray",
            "-depth",
            "8",
            "gray:-",
        ]
    )
    pixels = _run(
        command,
        f"ImageMagick text mask for {text!r}",
    )
    expected_size = width * height
    if len(pixels) != expected_size:
        raise ImageMagickError(
            f"ImageMagick returned {len(pixels)} mask bytes, "
            f"expected {expected_size}"
        )
    return pixels


__all__ = [
    "ImageMagickError",
    "imagemagick_version",
    "identify_dimensions",
    "read_rgba8",
    "render_grayscale_text_mask",
    "render_tim2_png8",
    "require_imagemagick",
    "write_deterministic_rgba8_png",
    "write_rgba8_png",
]
