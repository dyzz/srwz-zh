"""Read reviewed stage-title index planes without fonts or rasterization."""

from __future__ import annotations

import base64
import binascii
import hashlib
import zlib

from .stage_title_graphics import unpack_linear_4bpp


PACKED_SIZE = 512 * 64 // 2
TITLE_COUNT = 107
STATUS = "reviewed_stage_title_indexes_frozen"
METADATA_KEYS = (
    "quantization_levels", "raster_x", "raster_y", "raster_width",
    "raster_height", "natural_width", "cell_count", "latin_cell_count",
    "layout_mode",
)


class StageTitleSnapshotError(ValueError):
    """A frozen title or its authoring contract no longer matches."""


def freeze_indexes(packed: bytes) -> dict:
    """Serialize an existing index plane; never render or quantize it."""
    if len(packed) != PACKED_SIZE:
        raise StageTitleSnapshotError("stage-title packed image size drift")
    return {
        "size": len(packed),
        "sha256": hashlib.sha256(packed).hexdigest(),
        "zlib_base64": base64.b64encode(zlib.compress(packed, 9)).decode("ascii"),
    }


def thaw_indexes(reference: object) -> bytes:
    if not isinstance(reference, dict) or reference.get("size") != PACKED_SIZE:
        raise StageTitleSnapshotError("stage-title frozen image size drift")
    try:
        compressed = base64.b64decode(reference["zlib_base64"], validate=True)
        decoder = zlib.decompressobj()
        packed = decoder.decompress(compressed, PACKED_SIZE + 1)
    except (KeyError, TypeError, ValueError, binascii.Error, zlib.error) as error:
        raise StageTitleSnapshotError("stage-title frozen image is malformed") from error
    if (
        len(packed) != PACKED_SIZE
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
        or hashlib.sha256(packed).hexdigest() != reference.get("sha256")
    ):
        raise StageTitleSnapshotError("stage-title frozen image content drift")
    return packed


def load_frozen_titles(snapshot: object, entries: list[dict], policy: dict) -> list[dict]:
    """Validate every title before a production writer touches any slot."""
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("schema_version") != 1
        or snapshot.get("status") != STATUS
        or snapshot.get("update_policy") != "explicit_refreeze_from_reviewed_iso_only"
        or snapshot.get("raster_policy") != policy
    ):
        raise StageTitleSnapshotError("stage-title snapshot policy drift; explicitly refreeze reviewed images")
    titles = snapshot.get("titles")
    if not isinstance(titles, list) or len(titles) != TITLE_COUNT or len(entries) != TITLE_COUNT:
        raise StageTitleSnapshotError("stage-title snapshot must cover exactly 107 titles")
    result = []
    for ordinal, (title, entry) in enumerate(zip(titles, entries)):
        if (
            not isinstance(title, dict)
            or title.get("ordinal") != ordinal
            or title.get("entry_id") != entry["id"]
            or title.get("entry_id") != f"menu/Compdata/03/{ordinal:04d}"
            or title.get("text") != entry["translation"]
        ):
            raise StageTitleSnapshotError(f"stage-title snapshot text/identity drift: {ordinal}; explicitly refreeze")
        packed = thaw_indexes(title.get("packed_indexes"))
        indexes = unpack_linear_4bpp(packed)
        if (
            not any(indexes)
            or hashlib.sha256(indexes).hexdigest() != title.get("output_indexes_sha256")
            or any(key not in title for key in METADATA_KEYS)
            or title["quantization_levels"] not in policy["quantization_levels"]
        ):
            raise StageTitleSnapshotError(f"stage-title snapshot pixels/metadata drift: {ordinal}")
        result.append({**title, "packed": packed, "indexes": indexes})
    return result
