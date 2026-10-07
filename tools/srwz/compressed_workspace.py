"""One-decode/one-compress workspace for a physical SRWZ stream."""

from __future__ import annotations

import hashlib
import json
import struct
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .codec import decode_production, reencode_changed_suffix
from .codec_contract import DecodeResult, SrwzEncodeError


@dataclass
class CompressedStreamWorkspace:
    """Keep one physical stream decoded across all ordered write stages."""

    label: str
    stored: bytes
    source: DecodeResult
    current: bytes
    write_stages: list[dict] = field(default_factory=list)
    _finalized: bool = field(default=False, init=False, repr=False)

    @classmethod
    def open(cls, label: str, stored: bytes) -> "CompressedStreamWorkspace":
        source = decode_production(stored)
        if source.consumed != len(stored):
            raise ValueError(f"{label} has trailing compressed bytes")
        return cls(label=label, stored=stored, source=source, current=source.output)

    @classmethod
    def open_zero_padded_allocation(
        cls,
        label: str,
        allocation: bytes,
    ) -> "CompressedStreamWorkspace":
        source = decode_production(allocation)
        if any(allocation[source.consumed :]):
            raise ValueError(f"{label} has nonzero compressed padding")
        return cls(
            label=label,
            stored=allocation[: source.consumed],
            source=source,
            current=source.output,
        )

    def view(self) -> DecodeResult:
        if self._finalized:
            raise ValueError(f"{self.label} is already finalized")
        return DecodeResult(
            output=self.current,
            consumed=len(self.stored),
            declared_size=len(self.current),
            flags=self.source.flags,
            header_size=self.source.header_size,
            metadata=self.source.metadata,
        )

    def replace(self, decoded: bytes, *, stage: str) -> None:
        if self._finalized:
            raise ValueError(f"{self.label} is already finalized")
        if len(decoded) != len(self.current):
            raise ValueError(f"{self.label} decoded size changed at {stage}")
        changed = sum(left != right for left, right in zip(self.current, decoded))
        self.current = decoded
        self.write_stages.append(
            {
                "stage": stage,
                "changed_byte_count": changed,
            }
        )

    def finalize(
        self,
        *,
        strategy: str,
        min_match_length: int,
        max_match_chain: int,
        lazy_matching: bool,
        max_output_size: int,
        fallback_strategy: str | None = None,
    ) -> tuple[bytes, dict]:
        if self._finalized:
            raise ValueError(f"{self.label} was already compressed")
        if strategy != "rust-fit" or fallback_strategy not in (None, "rust-maximum"):
            raise ValueError(f"{self.label} must use rust-fit")
        options = dict(
            min_match_length=min_match_length,
            max_match_chain=max_match_chain,
            lazy_matching=lazy_matching,
            max_output_size=max_output_size,
            original_result=self.source,
        )
        try:
            rebuilt = reencode_changed_suffix(self.stored, self.current, strategy=strategy, **options)
        except SrwzEncodeError:
            if fallback_strategy is None:
                raise
            rebuilt = reencode_changed_suffix(
                self.stored, self.current, strategy=fallback_strategy, **options
            )
        reread = decode_production(rebuilt)
        if (
            reread.consumed != len(rebuilt)
            or reread.output != self.current
            or reread.flags != self.source.flags
        ):
            raise ValueError(f"{self.label} final Rust round-trip failed")
        self._finalized = True
        return rebuilt, {
            "physical_stream": self.label,
            "workflow": "decode_once_write_all_check_then_compress_once",
            "decoder_backend": "rust",
            "compressor_backend": "rust-fit",
            "initial_decode_count": 1,
            "write_stage_count": len(self.write_stages),
            "compression_count": 1,
            "final_readback_decode_count": 1,
            "source_stored_size": len(self.stored),
            "output_stored_size": len(rebuilt),
            "decoded_size": len(self.current),
            "sector_budget": max_output_size,
            "stages": self.write_stages,
            "final_round_trip_exact": True,
        }


def decoded_view(member) -> DecodeResult:
    """Decoded view of a compressed member or of an open stream workspace."""

    if isinstance(member, CompressedStreamWorkspace):
        return member.view()
    return decode_production(member)


def write_decoded(member, decoded: DecodeResult, data: bytes, *, stage: str, label: str):
    """Commit decoded edits: stage them in a workspace, or compress a plain member once."""

    if isinstance(member, CompressedStreamWorkspace):
        member.replace(bytes(data), stage=stage)
        return member
    if bytes(data) == decoded.output:
        return member
    packed = reencode_changed_suffix(member, bytes(data), strategy="rust-fit",
                                     max_output_size=len(member), original_result=decoded)
    if len(packed) > len(member) or decode_production(packed).output != bytes(data):
        raise ValueError(f"{label} compression roundtrip failed")
    return packed + bytes(len(member) - len(packed))


class CompressedArchiveWorkspace:
    """Every chunk of one fixed-allocation archive, decoded at most once.

    Writers read and replace decoded chunks; ``finalize`` compresses each
    changed chunk exactly once into its original allocation. Untouched chunks
    keep their stored bytes, and the archive size and chunk offsets never move.
    """

    def __init__(self, label: str, payload: bytes, offsets, *, decoded=None) -> None:
        offsets = tuple(int(offset) for offset in offsets)
        if (not offsets or offsets[0] != 0 or offsets[-1] != len(payload)
                or any(left > right for left, right in zip(offsets, offsets[1:]))):
            raise ValueError(f"{label} chunk offsets do not cover the archive")
        self.label = label
        self.payload = bytes(payload)
        self.offsets = offsets
        self._chunks: dict[int, CompressedStreamWorkspace] = {}
        # Decodes the caller already holds for these exact source chunks.
        self._known = dict(decoded or {})
        self._lock = threading.Lock()
        self._finalized = False

    @property
    def chunk_count(self) -> int:
        return len(self.offsets) - 1

    def allocation(self, index: int) -> tuple[int, int]:
        if not 0 <= index < self.chunk_count:
            raise IndexError(f"{self.label} has no chunk {index}")
        return self.offsets[index], self.offsets[index + 1]

    def stored(self, index: int) -> bytes:
        """The chunk's current stored allocation (source bytes until finalized)."""

        start, end = self.allocation(index)
        return self.payload[start:end]

    def chunk(self, index: int) -> CompressedStreamWorkspace:
        if self._finalized:
            raise ValueError(f"{self.label} is already finalized")
        with self._lock:
            workspace = self._chunks.get(index)
            if workspace is None:
                start, end = self.allocation(index)
                allocation = self.payload[start:end]
                known = self._known.pop(index, None)
                if known is None:
                    workspace = CompressedStreamWorkspace.open_zero_padded_allocation(
                        f"{self.label} chunk {index}", allocation
                    )
                else:
                    if any(allocation[known.consumed:]):
                        raise ValueError(f"{self.label} chunk {index} has nonzero compressed padding")
                    workspace = CompressedStreamWorkspace(
                        label=f"{self.label} chunk {index}",
                        stored=allocation[: known.consumed],
                        source=known,
                        current=known.output,
                    )
                self._chunks[index] = workspace
            return workspace

    def view(self, index: int) -> DecodeResult:
        return self.chunk(index).view()

    def replace(self, index: int, decoded: bytes, *, stage: str) -> None:
        self.chunk(index).replace(bytes(decoded), stage=stage)

    def changed_chunks(self) -> dict[int, bytes]:
        return {
            index: workspace.current
            for index, workspace in sorted(self._chunks.items())
            if workspace.current != workspace.source.output
        }

    @classmethod
    def from_overlay(cls, base_payload: bytes, overlay: bytes, *, stage: str) -> "CompressedArchiveWorkspace":
        """Rebuild the decoded edits of an overlay over its exact source archive."""

        if overlay[:8] != b"SRWZOVL1":
            raise ValueError("overlay has no SRWZOVL1 header")
        (size,) = struct.unpack_from("<Q", overlay, 8)
        header = json.loads(overlay[16 : 16 + size])
        archive = cls(header.get("label", "archive"), base_payload, header["offsets"])
        archive.import_overlay(overlay, stage=stage)
        return archive

    def export_overlay(self) -> bytes:
        """Serialize the decoded edits so another process can continue them.

        The overlay is bound to the exact source archive; no chunk is
        compressed here, the final owner of the archive compresses once.
        """

        chunks = self.changed_chunks()
        header = {
            "schema_version": 1,
            "kind": "srwz-decoded-archive-overlay",
            "label": self.label,
            "source_size": len(self.payload),
            "source_sha256": hashlib.sha256(self.payload).hexdigest(),
            "offsets": list(self.offsets),
            "chunks": [
                {
                    "index": index,
                    "decoded_size": len(data),
                    "decoded_sha256": hashlib.sha256(data).hexdigest(),
                    "write_stages": [row["stage"] for row in self._chunks[index].write_stages],
                }
                for index, data in chunks.items()
            ],
        }
        encoded = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
        return b"SRWZOVL1" + struct.pack("<Q", len(encoded)) + encoded + b"".join(chunks.values())

    def import_overlay(self, overlay: bytes, *, stage: str) -> dict:
        """Apply another process's decoded edits as one write stage."""

        if overlay[:8] != b"SRWZOVL1":
            raise ValueError(f"{self.label} overlay has no SRWZOVL1 header")
        (size,) = struct.unpack_from("<Q", overlay, 8)
        header = json.loads(overlay[16 : 16 + size])
        if (header.get("schema_version") != 1
                or header.get("kind") != "srwz-decoded-archive-overlay"
                or header.get("source_size") != len(self.payload)
                or header.get("source_sha256") != hashlib.sha256(self.payload).hexdigest()
                or tuple(header.get("offsets", ())) != self.offsets):
            raise ValueError(f"{self.label} overlay is bound to another source archive")
        cursor = 16 + size
        for row in header["chunks"]:
            data = overlay[cursor : cursor + row["decoded_size"]]
            cursor += row["decoded_size"]
            if len(data) != row["decoded_size"] or hashlib.sha256(data).hexdigest() != row["decoded_sha256"]:
                raise ValueError(f"{self.label} overlay chunk {row['index']} is damaged")
            self.replace(row["index"], data, stage=stage)
        if cursor != len(overlay):
            raise ValueError(f"{self.label} overlay has trailing bytes")
        return header

    def finalize(
        self,
        *,
        strategy: str,
        min_match_length: int,
        max_match_chain: int,
        lazy_matching: bool,
        workers: int = 4,
        codec_for=None,
        fallback_strategy: str | None = None,
    ) -> tuple[bytes, dict[int, dict]]:
        """Compress every changed chunk once.

        ``codec_for(index, stage_names)`` may return a different
        ``(min_match_length, max_match_chain)`` for a chunk, e.g. to keep the
        codec of the domain that owns the chunk's last write.
        """
        if self._finalized:
            raise ValueError(f"{self.label} was already compressed")
        self._finalized = True
        changed = {index: self._chunks[index] for index in self.changed_chunks()}

        def compress(item):
            index, workspace = item
            start, end = self.allocation(index)
            match_length, match_chain = min_match_length, max_match_chain
            if codec_for is not None:
                match_length, match_chain = codec_for(
                    index, [row["stage"] for row in workspace.write_stages]
                )
            encoded, report = workspace.finalize(
                strategy=strategy,
                min_match_length=match_length,
                max_match_chain=match_chain,
                lazy_matching=lazy_matching,
                max_output_size=end - start,
                fallback_strategy=fallback_strategy,
            )
            match_settings[index] = (match_length, match_chain)
            return index, encoded, report

        match_settings = {}
        output = bytearray(self.payload)
        reports = {}
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(changed) or 1)),
                                thread_name_prefix="srwz-archive-finalize") as executor:
            for index, encoded, report in executor.map(compress, changed.items()):
                start, end = self.allocation(index)
                output[start:end] = encoded + bytes(end - start - len(encoded))
                reports[index] = {
                    "chunk_index": index,
                    "source_stored_size": end - start,
                    "source_encoded_size": len(changed[index].stored),
                    "output_encoded_size": len(encoded),
                    "output_encoded_sha256": hashlib.sha256(encoded).hexdigest(),
                    "output_padding_size": end - start - len(encoded),
                    "decoded_size": report["decoded_size"],
                    "min_match_length": match_settings[index][0],
                    "max_match_chain": match_settings[index][1],
                    "write_stages": report["stages"],
                    "compression_count": 1,
                    "codec_round_trip_exact": True,
                }
        if len(output) != len(self.payload):
            raise ValueError(f"{self.label} archive size changed")
        self.payload = bytes(output)
        return self.payload, reports


__all__ = ["CompressedArchiveWorkspace", "CompressedStreamWorkspace", "decoded_view", "write_decoded"]
