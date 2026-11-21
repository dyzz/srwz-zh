"""Build languages: Simplified is the repository's default inputs; every other language is a view of them.

A language's view is made once per build when the inputs are frozen (release_inputs.freeze_inputs): its own
corpus, glossary, codebook, layout word lists and texture configs take the places the pipeline reads, so the
pipeline itself is the same for every language and nothing outside the frozen snapshot is rewritten.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from .edition import EditionError, load_json, project_path

# language -> the tool that rewrites a private copy of the inputs into that language's view
VIEWS = {
    "zh-hant-tw": ("tools/zh_hant/language_view.py", "tw"),
    "zh-hant-hk": ("tools/zh_hant/language_view.py", "hk"),
}
ENV_PYTHON = "SRWZ_LANGUAGE_PYTHON"      # interpreter for the view tools (default: the build's own)


def language_python(root: Path) -> str:
    """SRWZ_LANGUAGE_PYTHON, else the checkout's own .venv (NumPy, Pillow), else this interpreter."""
    local = Path(root) / ".venv/bin/python3"
    return os.environ.get(ENV_PYTHON) or (str(local) if local.exists() else sys.executable)


def require_language(language: str) -> None:
    if language and language not in VIEWS:
        raise EditionError(f"unknown build language: {language} (known: {', '.join(sorted(VIEWS))})")


def _answer_key(root: Path, language: str, candidate: bool) -> Path:
    """The components of the same batch's Original build in ``language`` ("" = Simplified)."""
    name = ("candidate" if candidate else "current") + (f"-{language}" if language else "")
    receipt = root / f"manifests/editions/original/{name}.json"
    if not receipt.is_file():
        raise EditionError(f"SP in {language or 'Simplified'} needs the Original build first: {receipt} is missing")
    workspace = project_path(root, load_json(receipt)["workspace"], "build/editions")
    key = workspace / "work/build/zh-release-full-story/components"
    if not key.is_dir():
        raise EditionError(f"Original components missing: {key}")
    return key


SP_REGIONAL_CONFIGS = ['config/editorial/special-disc/stage-context-reuse.json',
                    'config/editorial/special-disc/stage-native-overrides.json',
                    'config/products/special-disc/flow-layout.json',           # protected terms of the flow texts
                    'config/editorial/special-disc/chart-episode-labels.json',
                    'config/editorial/special-disc/chart-key-help.json',
                    'config/editorial/special-disc/chart-z-ending-titles.json',
                    'config/products/special-disc/shared-name-reference.json',   # Japanese name -> translations
                    'config/products/special-disc/name-unification-20261017.json',
                    'config/products/special-disc/event-gallery.json',             # 名场面集 scene names
                    # styled layouts of the tutorial / Q&A pages: each language's own (records, lines, colour runs
                    # and cells carry that language's text, at that language's lengths)
                    'config/editorial/special-disc/instructions-layout.json',
                    'config/products/special-disc/qa-layout.json',
                    'config/products/special-disc/runtime-text.json',
                    'config/products/special-disc/weapon-detail-labels.json',
                    'config/products/special-disc/event-gallery-talk.json']


def frontend_regions(region: str) -> tuple[str, ...]:
    if os.environ.get("SRWZ_FREEZE_SP_PICTURES") == "1":
        return tuple(dict.fromkeys((region, "tw", "sc")))
    return (region,)


def frontend_options(region, keys):
    options = ["--answer-key", str(keys[region])]
    if os.environ.get("SRWZ_FREEZE_SP_PICTURES") == "1":
        options.extend(["--taiwan-answer-key", str(keys["tw"]), "--simplified-answer-key", str(keys["sc"])])
    return options


def shared_episode_titles(root):
    source = load_json(root / "corpus/zh-hant/special-disc/frame-text.json")
    return [row for row in source["entries"] if row["category"] == "episode-title"]


def view_identity(root: Path, language: str, editions: tuple[str, ...], *, candidate: bool = False) -> str:
    """What a view depends on besides the captured inputs: for SP, the Original builds it reads."""
    if "sp" not in editions:
        return ",".join(editions)
    parts = []
    if language == "zh-hant-hk":
        import hashlib
        data = json.dumps(shared_episode_titles(root), sort_keys=True).encode()
        parts.append(hashlib.sha256(data).hexdigest())
    for region in frontend_regions(VIEWS[language][1]):
        other = "" if region == "sc" else "zh-hant-" + region
        name = ("candidate" if candidate else "current") + (f"-{other}" if other else "")
        receipt = root / f"manifests/editions/original/{name}.json"
        if not receipt.is_file():
            raise EditionError(f"SP in {language} needs the Original build first: {receipt} is missing")
        document = load_json(receipt)
        parts.append(f"{other}:{document['input_digest']}:{document['readback']['sha256']}")
    return ",".join(editions) + " " + " ".join(parts)


def make_view(root: Path, language: str, editions: tuple[str, ...], *, candidate: bool = False):
    """The callable freeze_inputs applies to its private copy of the inputs. It returns the frozen dependencies
    outside the source trees as the view names them (SP's locked baseline inputs)."""
    tool, variant = VIEWS[language]

    def view(project: Path) -> tuple[str, ...]:
        command = [language_python(root), str(root / tool), str(project),
                   "--variant", variant, "--editions", ",".join(editions)]
        if "sp" in editions:
            keys = {r: _answer_key(root, "" if r == "sc" else "zh-hant-" + r, candidate)
                    for r in frontend_regions(variant)}
            command += frontend_options(variant, keys)
        environment = os.environ.copy()
        environment.setdefault("SRWZ_COMPRESSION_CACHE", str(root / "work/cache/compression"))
        if "sp" in editions and os.environ.get("SRWZ_REHASH", "0") in ("", "0"):
            environment["SRWZ_SP_VIEW_CACHE"] = str(root / "work/cache/editions/sp-views" / language)
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
        if result.returncode:
            raise EditionError(f"{language} input view failed:\n{(result.stdout + result.stderr)[-3000:]}")
        lines = result.stdout.rstrip().splitlines()
        if not lines or not lines[-1].startswith("additional: "):
            raise EditionError(f"{language} input view did not report its frozen dependencies")
        for line in lines:
            if line.startswith(("[sp-view]", "[sp-cache]")):
                print(f"[{language}] {line}", flush=True)
        print(f"[{language}] input view: " + "\n".join(line[:240] for line in lines[-12:-1]), flush=True)
        return tuple(json.loads(lines[-1][len("additional: "):]))
    return view
