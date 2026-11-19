#!/usr/bin/env python3
"""One disc per edition with every language: Simplified, Traditional (Taiwan), Traditional (Hong Kong).

The corpora of all languages live in this checkout (corpus/zh, corpus/zh-hant and corpus/zh-hant-hk).
Each language is an ordinary build_editions.py build of the same pipeline (--language), run from this directory:
no project copies, shared caches. tools/zh_hant/assemble_dual.py then puts the languages of an edition on one disc.

  phase 1 (parallel)  Original and BEST in every language (BEST is built from the same language's Original
                      frontend, in one build), SP in Simplified
  phase 2 (parallel)  SP in each Traditional language (its inherited text comes from that language's Original)
  assemble            build/iso/test/multilang-original.iso, multilang-best.iso, multilang-sp.iso

The three-language disc is the only product: there is no two-language or single-language variant of this build
(the single-language images under build/iso/test/integrated-* are its intermediates).

Usage: build_multilang.py [--editions original,best,sp] [--release-version 0.5.1]
A Traditional view needs opencc: set SRWZ_LANGUAGE_PYTHON to an interpreter that has it when this one does not.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ZH_HANT = ROOT / "tools/zh_hant"
LOGS = ROOT / "build/multilang/logs"
ENV_PYTHON = "SRWZ_LANGUAGE_PYTHON"
LANGUAGES = ["zh-hant-tw", "zh-hant-hk"]


def language_python() -> str:
    return os.environ.get(ENV_PYTHON) or sys.executable


def run(name: str, command: list[str]) -> float:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"{name}.log"
    started = time.perf_counter()
    with log.open("wb") as output:
        result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - started
    if result.returncode:
        raise SystemExit(f"{name} failed after {elapsed:.2f}s; {log}\n{log.read_text(errors='replace')[-3000:]}")
    print(f"[{name}] {elapsed:.2f}s", flush=True)
    return elapsed


def build(edition: str, language: str, badge: str, force_rebuild: bool) -> float:
    command = [sys.executable, "tools/build_editions.py", "--editions", edition, "--candidate",
               "--frozen-badge", badge]
    if force_rebuild:
        command.append("--force-rebuild")
    if language:
        command += ["--language", language]
    return run(f"{edition.replace(',', '+')}-{language or 'zh-hans'}", command)


def image(edition: str, language: str) -> Path:
    suffix = f"-{language}" if language else ""
    receipt = json.loads((ROOT / f"manifests/editions/{edition}/candidate{suffix}.json").read_text(encoding="utf-8"))
    return ROOT / receipt["output"]["path"]


def check_authored(languages: list[str]) -> None:
    """Traditional pictures are authored ahead of the build and kept in config/zh-hant; a build made from newer
    text or a grown codebook must not ship the old pictures."""
    sys.path.insert(0, str(ZH_HANT))
    from build_dual import stale_stage_titles
    stale = stale_stage_titles(image("original", "zh-hant-tw"))
    if stale:
        raise SystemExit(f"Traditional stage-title pictures are stale ({', '.join(stale)}): run "
                         f"tools/zh_hant/author_stage_titles.py --iso {image('original', 'zh-hant-tw')} and build again")
    if stale_stage_titles(image("original", "zh-hant-hk")):
        raise SystemExit("the Hong Kong build does not carry the Taiwan font / stage titles")
    # author_textures.stale reads the Taiwan view the build just froze (it drafts with opencc: language python)
    receipt = json.loads((ROOT / "manifests/editions/original/candidate-zh-hant-tw.json").read_text(encoding="utf-8"))
    view = ROOT / "work/build/shared" / receipt["input_digest"] / "project"
    probe = subprocess.run([language_python(), "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                            "from author_textures import stale; from pathlib import Path; "
                            "raise SystemExit(3 if stale(Path(sys.argv[2])) else 0)", str(ZH_HANT), str(view)],
                           cwd=ROOT, capture_output=True, text=True)
    if probe.returncode == 3:
        raise SystemExit("Traditional pictures are stale (their texts or sources changed): run "
                         "tools/zh_hant/build_dual.py --author-textures and build again")
    if probe.returncode:
        raise SystemExit("Traditional picture check failed:\n" + (probe.stdout + probe.stderr)[-2000:])


def assembly_inputs(edition: str) -> dict:
    from srwz.file_identity import identity_key
    proofs = {}
    for language in ["", *LANGUAGES]:
        suffix = f"-{language}" if language else ""
        path = ROOT / f"manifests/editions/{edition}/candidate{suffix}.json"
        receipt = json.loads(path.read_text())
        proofs[language] = [receipt["input_digest"], receipt["output"]]
    # The snapshot includes the assembler, hook and both codebooks. The external
    # binutils suite is installed outside the snapshot.
    for tool in ("as", "ld", "objcopy", "objdump", "nm"):
        binary = shutil.which("mipsel-linux-gnu-" + tool)
        if binary is None:
            raise SystemExit(f"missing MIPS binutils tool: {tool}")
        proofs[tool] = identity_key(Path(binary).stat())
    return proofs


def assemble(edition: str, out: Path, force: bool) -> None:
    from build_editions import atomic_json
    from srwz.file_identity import identity_key
    cache = ROOT / f"work/cache/editions/multilang/{edition}.json"
    receipt = out.with_suffix(".receipt.json")
    inputs = assembly_inputs(edition)
    def proof():
        return {"inputs": inputs, "iso": identity_key(out.stat()), "receipt": identity_key(receipt.stat())}
    if not force and cache.exists() and out.exists() and receipt.exists():
        try:
            previous = json.loads(cache.read_text())
        except ValueError:
            previous = None
        if previous == proof():
            print(f"[assemble-{edition}] reused verified ISO", flush=True)
            return
    command = [sys.executable, str(ZH_HANT / "assemble_dual.py"), "--edition", edition,
               "--sc", str(image(edition, "")), "--tc", str(image(edition, "zh-hant-tw")),
               "--tc-codebook", str(ROOT / "config/zh-hant/encoding/zh-release-font-assignments.json"),
               "--hk", str(image(edition, "zh-hant-hk")),
               "--out", str(out), "--work", str(ROOT / f"build/multilang/assemble-{edition}")]
    run(f"assemble-{edition}", command)
    if assembly_inputs(edition) != inputs:
        raise SystemExit(f"{edition} candidate changed during assembly")
    atomic_json(cache, proof())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--editions", default="original,best,sp")
    parser.add_argument("--release-version")
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "build/iso/test")
    args = parser.parse_args()
    if args.release_version and not re.fullmatch(r"\d+\.\d+\.\d+(?:-rc(?:\.\d+)?)?", args.release_version):
        parser.error("release version must be x.y.z or x.y.z-rc[.n]")
    editions = [name for name in args.editions.split(",") if name]
    languages = LANGUAGES
    if not editions or set(editions) - {"original", "best", "sp"}:
        raise SystemExit("editions: original, best, sp")
    if args.out_dir.resolve() != (ROOT / "build/iso/test").resolve():
        parser.error("the assembler writes to build/iso/test")
    from build_editions import edition_lock
    with edition_lock(ROOT / "work/cache/editions/multilang/build.lock"):
        build_discs(args, editions, languages)


def build_discs(args, editions: list[str], languages: list[str]) -> None:
    started = time.perf_counter()
    if "sp" in editions:
        dependencies = subprocess.run([language_python(), "-c", "import opencc, numpy, PIL"], capture_output=True, text=True)
        if dependencies.returncode:
            raise SystemExit(f"SP language tools require OpenCC, NumPy and Pillow in {language_python()}:\n"
                             + dependencies.stderr)
    run("corpus-coverage", [language_python(), str(ZH_HANT / "fill_corpora.py")])
    # Traditional render locks that live in the parallel corpus follow its text (deterministic, a few seconds).
    run("author-intertitles", [language_python(), str(ZH_HANT / "author_intertitles.py")])
    # One badge refresh before the parallel builds, so none of them rewrites a file another is capturing.
    sys.path.insert(0, str(ROOT / "tools"))
    from freeze_title_version import refresh_current_badge
    badge = refresh_current_badge(ROOT, text=f"v{args.release_version}" if args.release_version else None)
    print(f"[preflight] {time.perf_counter() - started:.2f}s", flush=True)
    # SP inherits text from the Original build of the same language, in every language.
    main = "original,best" if "best" in editions else "original"      # Original is BEST's and SP's text frontend
    first = [(main, language) for language in ("", *languages)] + ([("sp", "")] if "sp" in editions else [])
    second = [("sp", language) for language in languages] if "sp" in editions else []
    for batch in (first, second):
        if not batch:
            continue
        phase_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = [pool.submit(build, edition, language, badge, args.force_rebuild) for edition, language in batch]
            for future in futures:
                future.result()
        print(f"[phase {1 if batch is first else 2}] {time.perf_counter() - phase_start:.2f}s", flush=True)
        if batch is first:
            check_start = time.perf_counter()
            check_authored(languages)
            print(f"[artwork verification] {time.perf_counter() - check_start:.2f}s", flush=True)
    for edition in editions:
        assemble(edition, args.out_dir / f"multilang-{edition}.iso", args.force_rebuild)
    print(f"total {time.perf_counter() - started:.2f}s", flush=True)


if __name__ == "__main__":
    main()
