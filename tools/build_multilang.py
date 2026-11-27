#!/usr/bin/env python3
"""One disc per edition with every language: Simplified, Traditional (Taiwan), Traditional (Hong Kong).

The corpora of all languages live in this checkout (corpus/zh, corpus/zh-hant and corpus/zh-hant-hk).
Original and BEST use per-language candidate discs. SP compiles three language resource sets in parallel
and writes one multilingual disc from Japanese retail data. An SP-only build consumes Original frontend
members directly, without building Original discs.

In a build of every edition the SP regions start with the Original builds: Simplified needs no Original
frontend, a Traditional region does everything that does not read one and goes on when the Original builds
announce their components. The three discs are laid out at the same time once every build has passed;
nothing is published before that.

Usage: build_multilang.py [--editions original,best,sp] [--release-version 0.5.1]
SP language tools need NumPy and Pillow: set SRWZ_LANGUAGE_PYTHON to an interpreter that has them when this one does not.
Each language's text is static. For an editorial report run tools/zh_hant/preflight.py separately.
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
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
ZH_HANT = ROOT / "tools/zh_hant"
LOGS = ROOT / "build/multilang/logs"
ENV_PYTHON = "SRWZ_LANGUAGE_PYTHON"
LANGUAGES = ["zh-hant-tw", "zh-hant-hk"]


def language_python() -> str:
    """SRWZ_LANGUAGE_PYTHON, else the checkout's own .venv (python3 -m venv .venv; pip install numpy pillow), else this interpreter."""
    local = ROOT / ".venv/bin/python3"
    return os.environ.get(ENV_PYTHON) or (str(local) if local.exists() else sys.executable)


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


EARLY_FRONTENDS = ROOT / "work/cache/editions/sp-frontends-early"


def early_frontend(language: str) -> Path:
    return EARLY_FRONTENDS / f"{language or 'zh'}.json"


def build(edition: str, language: str, badge: str, force_rebuild: bool, frontend_only: bool = False,
          early: bool = False) -> float:
    command = [sys.executable, "tools/build_editions.py", "--editions", edition, "--candidate",
               "--frozen-badge", badge]
    if frontend_only:
        command.append("--sp-frontend-only")
    if early:
        command += ["--frontend-receipt", str(early_frontend(language))]
    if force_rebuild:
        command.append("--force-rebuild")
    if language:
        command += ["--language", language]
    return run(f"{edition.replace(',', '+')}-{language or 'zh-hans'}", command)


def image(edition: str, language: str) -> Path:
    suffix = f"-{language}" if language else ""
    receipt = json.loads((ROOT / f"manifests/editions/{edition}/candidate{suffix}.json").read_text(encoding="utf-8"))
    return ROOT / receipt["output"]["path"]


def check_authored(languages: list[str], frontend_only=False) -> None:
    """Traditional pictures are authored ahead of the build and kept in config/zh-hant; a build made from newer
    text or a grown codebook must not ship the old pictures."""
    sys.path.insert(0, str(ZH_HANT))
    from build_dual import stale_stage_titles
    def receipt_for(language):
        if frontend_only:
            path = ROOT / f"work/cache/editions/sp-frontends/{language}.json"
        else:
            path = ROOT / f"manifests/editions/original/candidate-{language}.json"
        return json.loads(path.read_text())

    for language in languages:
        frontend = receipt_for(language)
        components = ROOT / frontend['workspace'] / 'work/build/zh-release-full-story/components'
        stale = stale_stage_titles(components)
        if stale:
            raise SystemExit(f'{language}: stale stage-title pictures: {stale}')
    receipt = receipt_for('zh-hant-tw')
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


GO = EARLY_FRONTENDS / "go"


def build_sp_early(out: Path, badge: str, force_rebuild: bool, languages: list[str], frontends_done) -> bool:
    """Build SP beside the Original and BEST builds; True when its disc was published.

    Simplified needs no Original frontend. A Traditional region starts with everything that does not read one
    and goes on when each Original build has written its frontend receipt (its components are final long before
    its disc is). The compiled regions then wait for the `go` file, which build_discs writes once every Original
    and BEST build and the picture checks have passed, and only then is the disc laid out and published;
    `go.cancel` ends the process without a disc. False: no disc was written here (an Original build reused its
    verified image and wrote no receipt, the build was cancelled, or the compile failed) and the ordinary SP
    build does the work."""
    command = [language_python(), str(ZH_HANT / "build_sp_resources.py"), "--out", str(out), "--badge", badge,
               "--frontend-receipts", str(EARLY_FRONTENDS), "--await-frontends", "--publish-when", str(GO)]
    log = LOGS / "sp-resources-early.log"
    started = time.perf_counter()
    wanted = [early_frontend(language) for language in ("", *languages)]
    with log.open("wb") as output:
        process = subprocess.Popen(command + (["--force-rebuild"] if force_rebuild else []), cwd=ROOT,
                                   stdout=output, stderr=subprocess.STDOUT)
        while process.poll() is None:
            if frontends_done.is_set() and not all(path.is_file() for path in wanted):
                (EARLY_FRONTENDS / "abort").touch()         # ends the regions' wait for receipts
            time.sleep(0.2)
    note = {0: "", 3: " (no rebuilt Original frontend to compile from)", 4: " (cancelled)"}.get(
        process.returncode, f" (failed; the SP build repeats it: {log})")
    print(f"[sp-resources-early] {time.perf_counter() - started:.2f}s{note}", flush=True)
    return process.returncode == 0


def assembly_inputs(edition: str) -> dict:
    proofs = {}
    for language in ["", *LANGUAGES]:
        suffix = f"-{language}" if language else ""
        path = ROOT / f"manifests/editions/{edition}/candidate{suffix}.json"
        receipt = json.loads(path.read_text())
        proofs[language] = [receipt["input_digest"], receipt["output"]]
    # The snapshot includes the assembler, hook and both codebooks. The external
    # binutils suite is installed outside the snapshot.
    import hashlib
    for path in [ROOT / 'tools/build_builtin_cheats.py', *sorted((ROOT / 'tools/builtin_cheats').glob('*'))]:
        if path.is_file():
            proofs[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    proofs.update(binutils_identity())
    return proofs


def binutils_identity():
    from srwz.file_identity import identity_key
    proofs = {}
    for tool in ("as", "ld", "objcopy", "objdump", "nm"):
        binary = shutil.which("mipsel-linux-gnu-" + tool)
        if binary is None:
            raise SystemExit(f"missing MIPS binutils tool: {tool}")
        proofs[tool] = identity_key(Path(binary).stat())
    return proofs


def assemble(edition: str, out: Path, force: bool) -> None:
    from build_editions import atomic_json
    from srwz.file_identity import identity_key
    cache_dir = ROOT / "work/cache/editions/multilang"
    destination = out.resolve().parent.relative_to((ROOT / "build/iso/test").resolve())
    cache = cache_dir / destination / f"{edition}.json"
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
    command.append("--builtin-cheats")
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
    if args.release_version and not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?(?:-rc(?:\.\d+)?)?", args.release_version):
        parser.error("release version must be x.y.z[.hotfix] with an optional -rc[.n] suffix")
    editions = [name for name in args.editions.split(",") if name]
    languages = LANGUAGES
    if not editions or set(editions) - {"original", "best", "sp"}:
        raise SystemExit("editions: original, best, sp")
    args.out_dir = args.out_dir.resolve()
    if not args.out_dir.is_relative_to((ROOT / "build/iso/test").resolve()):
        parser.error("output directory must be under build/iso/test")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    from build_editions import edition_lock
    with edition_lock(ROOT / "work/cache/editions/multilang/build.lock"):
        build_discs(args, editions, languages)


def build_discs(args, editions: list[str], languages: list[str]) -> None:
    started = time.perf_counter()
    run("corpus-coverage", [language_python(), str(ZH_HANT / "fill_corpora.py"), "--check"])
    run("check-intertitles", [language_python(), str(ZH_HANT / "author_intertitles.py"), "--check"])
    # One badge refresh before the parallel builds, so none of them rewrites a file another is capturing.
    sys.path.insert(0, str(ROOT / "tools"))
    from freeze_title_version import refresh_current_badge
    badge = refresh_current_badge(ROOT, text=f"v{args.release_version}" if args.release_version else None)
    print(f"[preflight] {time.perf_counter() - started:.2f}s", flush=True)
    # SP inherits text from the Original build of the same language, in every language.
    main = "original,best" if "best" in editions else "original"      # Original is BEST's and SP's text frontend
    phase_start = time.perf_counter()
    # In a build of every edition SP does not wait for the Original and BEST discs: its resources need the
    # Original components only, which each Original build announces as soon as they are final.
    overlap = "sp" in editions and editions != ["sp"] and os.environ.get("SRWZ_SP_OVERLAP", "1") != "0"
    LOGS.mkdir(parents=True, exist_ok=True)
    EARLY_FRONTENDS.mkdir(parents=True, exist_ok=True)
    for stale in EARLY_FRONTENDS.iterdir():
        stale.unlink()
    frontends_done = threading.Event()
    sp_out = args.out_dir / "multilang-sp.iso"
    early_result: list[bool] = []
    early = None
    if overlap:
        early = threading.Thread(target=lambda: early_result.append(
            build_sp_early(sp_out, badge, args.force_rebuild, languages, frontends_done)))
        early.start()
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(build, main, language, badge, args.force_rebuild, editions == ['sp'],
                                **({"early": True} if overlap else {}))
                    for language in ("", *languages)]
            try:
                for job in jobs:
                    job.result()
            finally:
                frontends_done.set()
        print(f"[Original frontends] {time.perf_counter()-phase_start:.2f}s", flush=True)
        check_authored(languages, frontend_only=editions == ["sp"])
    except BaseException:
        if early is not None:                     # no SP disc from a build whose other editions failed
            GO.with_name(GO.name + ".cancel").touch()
            early.join()
        raise
    GO.touch()                                    # every other build and check has passed: SP may publish

    def finish(edition: str) -> None:
        out = args.out_dir / f"multilang-{edition}.iso"
        if edition == "sp":
            if early is not None:
                early.join()
                if early_result and early_result[0]:
                    return
            cmd = [language_python(), str(ZH_HANT / "build_sp_resources.py"), "--out", str(out), "--badge", badge]
            if editions == ["sp"]:
                cmd.append("--component-frontends")
            run("sp-resources", cmd + (["--force-rebuild"] if args.force_rebuild else []))
        else:
            assemble(edition, out, args.force_rebuild)

    # The three discs are laid out from different inputs into different files: one at a time is only waiting.
    from build_editions import atomic_json  # noqa: F401  (imported once here, not first inside the threads)
    with ThreadPoolExecutor(max_workers=len(editions)) as pool:
        for job in [pool.submit(finish, edition) for edition in editions]:
            job.result()
    if args.release_version and "sp" in editions:
        # The resource compiler uses sparse views. Bind their logical images to independent,
        # single-language SP candidate readbacks before allowing a release freeze.
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(build, "sp", language, badge, args.force_rebuild)
                    for language in ("", *languages)]
            for job in jobs:
                job.result()
    if args.release_version:
        for edition in editions:
            run(f"widescreen-{edition}", [
                language_python(), str(ROOT / "tools/widescreen/build.py"), edition,
                str(args.out_dir / f"multilang-{edition}.iso"),
                str(args.out_dir / f"multilang-{edition}-wide.iso"),
                str(ROOT / f"build/multilang/widescreen-{edition}"), "--replace",
            ])
    print(f"total {time.perf_counter() - started:.2f}s", flush=True)


if __name__ == "__main__":
    main()
