#!/usr/bin/env python3
"""Build and verify a deterministic xdelta release package.

The full source and target ISOs remain local.  The release directory contains
only the patch, checksums, manifest, instructions, and their deterministic ZIP.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/release/v0.1.0.json"
HASH_CHUNK_SIZE = 4 * 1024 * 1024
ZIP_TIMESTAMP = (2020, 1, 1, 0, 0, 0)


class ReleaseBuildError(RuntimeError):
    """Raised when a release input or generated artifact violates its lock."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseBuildError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseBuildError(f"expected JSON object: {path}")
    return value


def project_path(value: str) -> Path:
    candidate = (PROJECT_ROOT / value).resolve()
    try:
        candidate.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ReleaseBuildError(f"path escapes project root: {value}") from exc
    return candidate


def verify_locked_file(path: Path, lock: dict[str, Any], label: str) -> None:
    if not path.is_file():
        raise ReleaseBuildError(f"missing {label}: {path}")
    expected_size = int(lock["size"])
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise ReleaseBuildError(
            f"{label} size mismatch: expected {expected_size}, got {actual_size}"
        )
    expected_hash = str(lock["sha256"]).lower()
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise ReleaseBuildError(
            f"{label} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
        )


def verify_config_bindings(config: dict[str, Any]) -> None:
    if config.get("schema_version") != 1:
        raise ReleaseBuildError("unsupported release config schema")
    version = str(config.get("version", ""))
    tag = str(config.get("tag", ""))
    if tag != f"v{version}" or not version:
        raise ReleaseBuildError("release tag must equal 'v' plus version")

    source = config["source_iso"]
    target = config["target_iso"]
    iso_config_path = project_path("config/iso/zh-release-full-story-build.json")
    iso_config = load_json(iso_config_path)
    original_disc = load_json(
        project_path("manifests/original-disc.json")
    )["disc"]
    iso_source = iso_config["source_iso"]
    iso_output = iso_config["output"]
    for key in ("path", "size", "sha256"):
        if source[key] != iso_source[key]:
            raise ReleaseBuildError(
                f"source_iso.{key} is not bound to ISO build input"
            )
    for release_key, iso_key in (
        ("path", "path"),
        ("size", "expected_size"),
        ("sha256", "expected_sha256"),
    ):
        if target[release_key] != iso_output[iso_key]:
            raise ReleaseBuildError(
                f"target_iso.{release_key} is not bound to ISO build output"
            )

    redump = source.get("redump")
    if not isinstance(redump, dict):
        raise ReleaseBuildError("source_iso.redump metadata is required")
    redump_filename = str(redump.get("filename", ""))
    if (
        not redump_filename
        or Path(redump_filename).name != redump_filename
        or not redump_filename.lower().endswith(".iso")
        or any(character in redump_filename for character in ('"', "\r", "\n"))
    ):
        raise ReleaseBuildError("invalid Redump ISO filename")
    if Path(source["path"]).name != redump_filename:
        raise ReleaseBuildError(
            "source ISO path must use the Redump canonical filename"
        )

    if source["size"] != original_disc["file_size"]:
        raise ReleaseBuildError(
            "source_iso.size is not bound to the original-disc manifest"
        )
    if source["sha256"] != original_disc["sha256"]:
        raise ReleaseBuildError(
            "source_iso.sha256 is not bound to the original-disc manifest"
        )
    if redump_filename != original_disc["local_file_name"]:
        raise ReleaseBuildError(
            "Redump filename is not bound to the original-disc manifest"
        )
    original_redump = original_disc["redump"]
    for release_key, manifest_key in (
        ("disc_id", "disc_id"),
        ("url", "url"),
        ("filename", "canonical_filename"),
        ("edition", "edition"),
        ("version", "version"),
        ("crc32", "crc32"),
        ("md5", "md5"),
        ("sha1", "sha1"),
    ):
        if redump.get(release_key) != original_redump.get(manifest_key):
            raise ReleaseBuildError(
                f"Redump {release_key} is not bound to the original-disc manifest"
            )

    digest_lengths = {"crc32": 8, "md5": 32, "sha1": 40}
    for key, length in digest_lengths.items():
        value = str(redump.get(key, "")).lower()
        if len(value) != length or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ReleaseBuildError(f"invalid Redump {key} lock")
    disc_id = redump.get("disc_id")
    if (
        not isinstance(disc_id, int)
        or isinstance(disc_id, bool)
        or disc_id <= 0
    ):
        raise ReleaseBuildError("invalid Redump disc ID")

    expected_release_dir = f"build/release/{tag}"
    if config["output"]["directory"] != expected_release_dir:
        raise ReleaseBuildError(
            f"release output must be {expected_release_dir}"
        )

    patch_name = config["xdelta"]["patch_filename"]
    archive_name = config["output"]["archive_filename"]
    if patch_name != f"srwz-zh-{tag}.xdelta":
        raise ReleaseBuildError("patch filename does not match release tag")
    if archive_name != f"srwz-zh-{tag}.zip":
        raise ReleaseBuildError("archive filename does not match release tag")


def xdelta_version(executable: str) -> str:
    resolved = shutil.which(executable)
    if resolved is None:
        raise ReleaseBuildError(
            f"missing {executable}; install xdelta3 before building a release"
        )
    completed = subprocess.run(
        [resolved, "-V"],
        check=False,
        capture_output=True,
        text=True,
    )
    output = (completed.stdout + completed.stderr).splitlines()
    if completed.returncode != 0 or not output:
        raise ReleaseBuildError(f"cannot determine {executable} version")
    return output[0].strip()


def run_xdelta(command: list[str], operation: str) -> None:
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise ReleaseBuildError(
            f"xdelta {operation} failed with exit code {completed.returncode}"
        )


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )


def release_readme(config: dict[str, Any]) -> bytes:
    tag = config["tag"]
    source = config["source_iso"]
    redump = source["redump"]
    source_filename = redump["filename"]
    target = config["target_iso"]
    patch_name = config["xdelta"]["patch_filename"]
    text = f"""《超级机器人大战 Z》简体中文补丁 {tag}

这是非官方测试版补丁，不包含游戏 ISO 或其他原版游戏数据。
使用者必须自行合法持有与下列校验值完全一致的 PS2 日文原版镜像。

Redump 记录：Disc {redump['disc_id']}（{redump['url']}）
Redump 规范文件名：{source_filename}
版本：{redump['version']}（{redump['edition']}）
原版镜像大小：{source['size']} 字节
原版镜像 CRC-32：{redump['crc32']}
原版镜像 MD5：{redump['md5']}
原版镜像 SHA-1：{redump['sha1']}
原版镜像 SHA-256：{source['sha256']}

安装 xdelta3 后执行：

xdelta3 -d -s "{source_filename}" "{patch_name}" "srwz-zh-{tag}.iso"

生成镜像大小：{target['size']} 字节
生成镜像 SHA-256：{target['sha256']}

请勿在旧汉化版或其他修改版镜像上重复打补丁。操作前请备份原版镜像和存档。
本补丁仍处于测试阶段，完整状态与已知限制见项目 README 和对应发布页面。
"""
    return text.encode("utf-8")


def write_deterministic_zip(
    archive_path: Path, members: list[Path]
) -> None:
    with zipfile.ZipFile(archive_path, "w") as archive:
        for member in sorted(members, key=lambda path: path.name):
            info = zipfile.ZipInfo(member.name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, member.read_bytes())


def build_release(config_path: Path, *, force: bool = False) -> Path:
    config = load_json(config_path)
    verify_config_bindings(config)

    source_path = project_path(config["source_iso"]["path"])
    target_path = project_path(config["target_iso"]["path"])
    verify_locked_file(source_path, config["source_iso"], "source ISO")
    verify_locked_file(target_path, config["target_iso"], "target ISO")

    xdelta = config["xdelta"]
    version_line = xdelta_version(xdelta["executable"])
    if version_line != xdelta["version_line"]:
        raise ReleaseBuildError(
            "xdelta version mismatch: "
            f"expected {xdelta['version_line']!r}, got {version_line!r}"
        )
    executable = shutil.which(xdelta["executable"])
    assert executable is not None

    output_dir = project_path(config["output"]["directory"])
    release_root = project_path("build/release")
    if output_dir.parent != release_root:
        raise ReleaseBuildError("refusing release output outside build/release")
    release_root.mkdir(parents=True, exist_ok=True)
    if output_dir.exists() and not force:
        raise ReleaseBuildError(
            f"release output already exists: {output_dir}; pass --force to rebuild"
        )

    temp_dir = Path(tempfile.mkdtemp(prefix=f".{config['tag']}-", dir=release_root))
    try:
        patch_path = temp_dir / xdelta["patch_filename"]
        encode_command = [
            executable,
            *[str(arg) for arg in xdelta["encode_args"]],
            "-s",
            str(source_path),
            str(target_path),
            str(patch_path),
        ]
        run_xdelta(encode_command, "encode")

        reconstructed = temp_dir / ".reconstructed.iso"
        decode_command = [
            executable,
            "-d",
            "-s",
            str(source_path),
            str(patch_path),
            str(reconstructed),
        ]
        run_xdelta(decode_command, "decode")
        verify_locked_file(
            reconstructed, config["target_iso"], "reconstructed ISO"
        )
        reconstructed.unlink()

        evidence = []
        for value in config["evidence"]:
            evidence_path = project_path(value)
            if not evidence_path.is_file():
                raise ReleaseBuildError(f"missing release evidence: {value}")
            evidence.append(
                {
                    "path": value,
                    "sha256": sha256_file(evidence_path),
                }
            )

        manifest = {
            "schema_version": 1,
            "version": config["version"],
            "tag": config["tag"],
            "channel": config["channel"],
            "format": "xdelta3-vcdiff",
            "source_iso": config["source_iso"],
            "target_iso": config["target_iso"],
            "patch": {
                "filename": patch_path.name,
                "size": patch_path.stat().st_size,
                "sha256": sha256_file(patch_path),
            },
            "tool": {
                "version_line": version_line,
                "encode_args": xdelta["encode_args"],
            },
            "verification": {
                "reconstructed_size_matches": True,
                "reconstructed_sha256_matches": True,
                "iso_in_release_package": False,
            },
            "evidence": evidence,
        }
        manifest_path = temp_dir / "release-manifest.json"
        manifest_path.write_bytes(json_bytes(manifest))
        readme_path = temp_dir / "README.txt"
        readme_path.write_bytes(release_readme(config))

        checksum_members = [patch_path, manifest_path, readme_path]
        checksum_text = "".join(
            f"{sha256_file(path)}  {path.name}\n"
            for path in sorted(checksum_members, key=lambda path: path.name)
        )
        checksums_path = temp_dir / "SHA256SUMS.txt"
        checksums_path.write_text(checksum_text, encoding="utf-8")

        archive_path = temp_dir / config["output"]["archive_filename"]
        write_deterministic_zip(
            archive_path, [*checksum_members, checksums_path]
        )
        archive_checksum_path = temp_dir / f"{archive_path.name}.sha256"
        archive_checksum_path.write_text(
            f"{sha256_file(archive_path)}  {archive_path.name}\n",
            encoding="utf-8",
        )

        if any(temp_dir.glob("*.iso")):
            raise ReleaseBuildError("release directory unexpectedly contains an ISO")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        temp_dir.rename(output_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="release config (default: config/release/v0.1.0.json)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace only the configured build/release/<tag> directory",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    try:
        output_dir = build_release(config_path.resolve(), force=args.force)
    except ReleaseBuildError as exc:
        print(f"release build failed: {exc}")
        return 1
    print(f"release package: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
