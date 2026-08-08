"""Strict configuration model for SRWZ texture-bearing archives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping


class AssetInventoryError(ValueError):
    """Asset bytes or configuration do not satisfy the inventory contract."""


@dataclass(frozen=True)
class AssetArchiveSpec:
    name: str
    member: str
    table_start: int
    table_end: int
    storage: str


@dataclass(frozen=True)
class AssetInventoryConfig:
    schema_version: int
    upstream_commit: str
    provenance_source_path: str
    reuse_scope: str
    executable_member: str
    archives: tuple[AssetArchiveSpec, ...]
    direct_members: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "AssetInventoryConfig":
        raw = _require_mapping(raw, "asset inventory config")
        expected_keys = {
            "schema_version",
            "provenance",
            "executable_member",
            "archives",
            "direct_members",
        }
        _require_exact_keys(raw, expected_keys, "asset inventory config")
        if raw["schema_version"] != 1 or isinstance(
            raw["schema_version"],
            bool,
        ):
            raise AssetInventoryError("asset inventory schema_version must be 1")

        provenance = _require_mapping(raw["provenance"], "provenance")
        _require_exact_keys(
            provenance,
            {"upstream_commit", "source_path", "reuse_scope"},
            "provenance",
        )
        upstream_commit = _require_string(
            provenance["upstream_commit"],
            "provenance.upstream_commit",
        )
        if len(upstream_commit) != 40 or any(
            character not in "0123456789abcdef"
            for character in upstream_commit
        ):
            raise AssetInventoryError(
                "provenance.upstream_commit must be 40 lowercase hex digits"
            )
        provenance_source_path = _require_relative_path(
            provenance["source_path"],
            "provenance.source_path",
        )
        reuse_scope = _require_string(
            provenance["reuse_scope"],
            "provenance.reuse_scope",
        )
        executable_member = _require_relative_path(
            raw["executable_member"],
            "executable_member",
        )

        archives_raw = raw["archives"]
        if not isinstance(archives_raw, list) or not archives_raw:
            raise AssetInventoryError("archives must be a non-empty list")
        archives = []
        for index, value in enumerate(archives_raw):
            item = _require_mapping(value, f"archives[{index}]")
            _require_exact_keys(
                item,
                {
                    "name",
                    "member",
                    "table_start",
                    "table_end",
                    "storage",
                },
                f"archives[{index}]",
            )
            name = _require_string(item["name"], f"archives[{index}].name")
            member = _require_relative_path(
                item["member"],
                f"archives[{index}].member",
            )
            table_start = parse_integer(
                item["table_start"],
                f"archives[{index}].table_start",
            )
            table_end = parse_integer(
                item["table_end"],
                f"archives[{index}].table_end",
            )
            if not 0 <= table_start < table_end:
                raise AssetInventoryError(
                    f"archives[{index}] table range must be positive and ordered"
                )
            storage = _require_string(
                item["storage"],
                f"archives[{index}].storage",
            )
            if storage not in ("raw", "srwz_stream"):
                raise AssetInventoryError(
                    f"archives[{index}] has unsupported storage {storage!r}"
                )
            archives.append(
                AssetArchiveSpec(
                    name=name,
                    member=member,
                    table_start=table_start,
                    table_end=table_end,
                    storage=storage,
                )
            )

        archive_names = [item.name for item in archives]
        archive_members = [item.member for item in archives]
        _require_unique(archive_names, "archive names")
        _require_unique(archive_members, "archive members")

        direct_raw = raw["direct_members"]
        if not isinstance(direct_raw, list):
            raise AssetInventoryError("direct_members must be a list")
        direct_members = tuple(
            _require_relative_path(value, f"direct_members[{index}]")
            for index, value in enumerate(direct_raw)
        )
        _require_unique(direct_members, "direct members")
        overlap = sorted(set(archive_members) & set(direct_members))
        if overlap:
            raise AssetInventoryError(
                f"archive and direct members overlap: {overlap}"
            )
        if executable_member in set(archive_members) | set(direct_members):
            raise AssetInventoryError(
                "executable_member must not also be an asset member"
            )

        return cls(
            schema_version=1,
            upstream_commit=upstream_commit,
            provenance_source_path=provenance_source_path,
            reuse_scope=reuse_scope,
            executable_member=executable_member,
            archives=tuple(archives),
            direct_members=direct_members,
        )

    def archive_for_member(self, member: str) -> AssetArchiveSpec | None:
        return next(
            (item for item in self.archives if item.member == member),
            None,
        )

    @property
    def required_members(self) -> frozenset[str]:
        return frozenset(
            {
                self.executable_member,
                *(item.member for item in self.archives),
                *self.direct_members,
            }
        )


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise AssetInventoryError(f"{field} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise AssetInventoryError(f"{field} keys must be strings")
    return value


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise AssetInventoryError(
            f"{field} keys differ: missing={missing}, unknown={unknown}"
        )


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AssetInventoryError(f"{field} must be a non-empty string")
    return value


def _require_relative_path(value: object, field: str) -> str:
    text = _require_string(value, field)
    if "\\" in text:
        raise AssetInventoryError(f"{field} must use forward slashes")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise AssetInventoryError(f"{field} must be a safe relative path")
    return path.as_posix()


def _require_unique(values, field: str) -> None:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise AssetInventoryError(
            f"{field} contain duplicates: {sorted(duplicates)}"
        )


def parse_integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise AssetInventoryError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as error:
            raise AssetInventoryError(
                f"{field} is not an integer: {value!r}"
            ) from error
    raise AssetInventoryError(f"{field} must be an integer")


__all__ = [
    "AssetArchiveSpec",
    "AssetInventoryConfig",
    "AssetInventoryError",
    "parse_integer",
]
