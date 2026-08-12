"""One-decode/one-compress workspace for a physical SRWZ stream."""

from __future__ import annotations

from dataclasses import dataclass, field

from .codec import decode_production, reencode_changed_suffix
from .codec_contract import DecodeResult


@dataclass
class CompressedStreamWorkspace:
    """Keep one physical stream decoded across all ordered write stages."""

    label: str
    stored: bytes
    source: DecodeResult
    current: bytes
    write_stages: list[dict] = field(default_factory=list)

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
        return DecodeResult(
            output=self.current,
            consumed=len(self.stored),
            declared_size=len(self.current),
            flags=self.source.flags,
            header_size=self.source.header_size,
            metadata=self.source.metadata,
        )

    def replace(self, decoded: bytes, *, stage: str) -> None:
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
    ) -> tuple[bytes, dict]:
        if strategy != "rust-fit":
            raise ValueError(f"{self.label} must use rust-fit")
        rebuilt = reencode_changed_suffix(
            self.stored,
            self.current,
            strategy=strategy,
            min_match_length=min_match_length,
            max_match_chain=max_match_chain,
            lazy_matching=lazy_matching,
            max_output_size=max_output_size,
            original_result=self.source,
        )
        reread = decode_production(rebuilt)
        if (
            reread.consumed != len(rebuilt)
            or reread.output != self.current
            or reread.flags != self.source.flags
        ):
            raise ValueError(f"{self.label} final Rust round-trip failed")
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


__all__ = ["CompressedStreamWorkspace"]
