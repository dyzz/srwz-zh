"""Explicit disc identities and disjoint build contexts for edition targets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


class EditionError(ValueError):
    """An edition, source identity or output boundary is invalid."""


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def load_json(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise EditionError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise EditionError(f"expected JSON object: {path}")
    return value


def project_path(root: Path, raw: str, prefix: str | None = None) -> Path:
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute() or ".." in Path(raw).parts:
        raise EditionError(f"invalid project-relative path: {raw!r}")
    path = (root / raw).resolve()
    boundary = (root / prefix).resolve() if prefix else root.resolve()
    if not boundary.is_relative_to(root.resolve()) or not path.is_relative_to(boundary):
        raise EditionError(f"path escapes {boundary}: {raw}")
    return path


@dataclass(frozen=True)
class FileIdentity:
    path: str
    size: int
    sha256: str

    @classmethod
    def parse(cls, raw: dict, path_key: str = "path") -> "FileIdentity":
        if not isinstance(raw, dict) or set(raw) != {path_key, "size", "sha256"}:
            raise EditionError("invalid file identity fields")
        if type(raw["size"]) is not int or raw["size"] <= 0:
            raise EditionError("invalid file identity size")
        if not isinstance(raw["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", raw["sha256"]):
            raise EditionError("invalid file identity SHA-256")
        if not isinstance(raw[path_key], str) or not raw[path_key]:
            raise EditionError("invalid file identity path")
        return cls(raw[path_key], raw["size"], raw["sha256"])


@dataclass(frozen=True)
class EditionProfile:
    edition_id: str
    profile_id: str
    adapter: str | None
    source_iso: FileIdentity
    executable: FileIdentity
    stage_base: int
    stage_function_table: int
    compdata_base: int
    compdata_corrections: str
    contract_sha256: str

    @classmethod
    def load(cls, root: Path, raw_path: str) -> "EditionProfile":
        path = project_path(root, raw_path, "config/editions")
        d = load_json(path)
        required = {"schema_version", "edition_id", "profile_id", "adapter", "source_iso", "executable", "layout", "compdata_corrections"}
        if set(d) != required or d["schema_version"] != 1:
            raise EditionError("unknown or missing edition contract fields")
        edition = d["edition_id"]
        if edition not in {"original", "best", "sp"} or d["profile_id"] != f"zh-release-{edition}":
            raise EditionError("edition/profile identity mismatch")
        source = FileIdentity.parse(d["source_iso"])
        executable = FileIdentity.parse(d["executable"], "member")
        project_path(root, source.path, "rom")
        layout = d["layout"]
        if not isinstance(layout, dict) or set(layout) != {"stage_base", "stage_function_table", "compdata_base"}:
            raise EditionError("invalid edition layout fields")
        try:
            values = tuple(int(layout[k], 0) for k in ("stage_base", "stage_function_table", "compdata_base"))
        except (TypeError, ValueError) as error:
            raise EditionError("invalid edition addresses") from error
        expected = {
            "original": ("SLPS_258.87", (0x7566F0, 0x2FF0B0, 0x6D6800), "apply_original_four_fields"),
            "best": ("SLPS_732.70", (0x756EF0, 0x2FF830, 0x6D7000), "preserve_best_native_fields"),
            "sp": ("SLPS_259.20", (0x8045F0, 0x358980, 0x764F80), "preserve_sp_native_fields"),
        }[edition]
        if (executable.path, values, d["compdata_corrections"]) != expected:
            raise EditionError("edition member/layout/correction policy mismatch")
        expected_adapter = {"original": "original-production-v1", "best": "best-current-source-v1", "sp": "sp-full-text-v1"}[edition]
        if d["adapter"] not in (None, expected_adapter):
            raise EditionError("edition adapter mismatch; Original adapter cannot build BEST")
        return cls(edition, d["profile_id"], d["adapter"], source, executable,
                   *values, d["compdata_corrections"], hashlib.sha256(json_bytes(d)).hexdigest())

    def require_supported(self) -> None:
        if self.adapter is None:
            raise EditionError(f"{self.edition_id}: native source writer is not implemented; no build started")


@dataclass(frozen=True)
class BuildContext:
    root: Path
    profile: EditionProfile
    input_digest: str

    def __post_init__(self):
        object.__setattr__(self, "root", self.root.resolve())
        if not re.fullmatch(r"[0-9a-f]{64}", self.input_digest):
            raise EditionError("invalid shared input digest")

    def _path(self, raw: str, prefix: str) -> Path:
        path = project_path(self.root, raw, prefix)
        if path != self.root / raw:
            raise EditionError(f"edition namespace must not alias another path: {raw}")
        return path

    @property
    def run_key(self) -> str:
        return hashlib.sha256((self.input_digest + self.profile.contract_sha256).encode()).hexdigest()

    @property
    def run_root(self) -> Path:
        return self._path(f"work/build/{self.profile.profile_id}/{self.run_key}", "work/build")

    @property
    def project_root(self) -> Path:
        return self._path(f"work/build/{self.profile.profile_id}/{self.run_key}/project", "work/build")

    @property
    def cache_root(self) -> Path:
        return self._path(f"work/cache/editions/{self.profile.edition_id}", "work/cache")

    @property
    def output_iso(self) -> Path:
        if self.profile.edition_id == "sp":
            return self._path("build/iso/special-disc/sp-current.iso", "build/iso")
        return self._path(f"build/iso/{self.profile.profile_id}/current-{self.profile.edition_id}.iso", "build/iso")

    @property
    def receipt(self) -> Path:
        return self._path(f"manifests/editions/{self.profile.edition_id}/current.json", "manifests/editions")


def load_release_profiles(root: Path, path: str, requested: tuple[str, ...]) -> tuple[EditionProfile, ...]:
    d = load_json(project_path(root, path, "config/release"))
    if set(d) != {"schema_version", "editions", "policies"} or d["schema_version"] != 1:
        raise EditionError("invalid dual-edition release contract")
    if d["policies"] != {"library_visibility": "all_valid_entries_without_save_writeback", "animation_resources": "native_per_edition"}:
        raise EditionError("shared library/animation policy drift")
    if not requested or len(set(requested)) != len(requested):
        raise EditionError("editions must be nonempty and unique")
    if not isinstance(d["editions"], dict) or set(d["editions"]) not in ({"original", "best"}, {"original", "best", "sp"}):
        raise EditionError("release must register both edition identities")
    if set(requested) - set(d["editions"]):
        raise EditionError("unknown requested edition")
    profiles = tuple(EditionProfile.load(root, d["editions"][name]) for name in requested)
    if tuple(p.edition_id for p in profiles) != requested:
        raise EditionError("release registry resolves to the wrong edition")
    return profiles
