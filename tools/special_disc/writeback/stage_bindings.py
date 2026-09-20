"""Bind SP native records before encoding; never select a hash's first answer."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BindingError(ValueError):
    pass


class StageBindings:
    def __init__(self, root: Path, *, allow_draft: bool):
        self.allow_draft = allow_draft
        self.direct = {}
        self.sp_fallback = defaultdict(list)
        self.fallback = defaultdict(list)
        self.inputs = {}
        from squad_names import load_names, INVENTORY_PATH, CORPUS_PATH
        _, self.squad_names = load_names(root)
        for reference in (INVENTORY_PATH, CORPUS_PATH):
            self.inputs[reference] = hashlib.sha256((root / reference).read_bytes()).hexdigest()
        sp_paths = [root / "corpus/zh/special-disc" / f"{name}.json"
                    for name in ("story-dialogue", "challenge-dialogue", "frame-text")]
        sp_paths.append(root / "config/editorial/special-disc/stage-native-overrides.json")
        sp_paths.append(root / "config/editorial/special-disc/stage-context-reuse.json")
        for path in sp_paths:
            for row in self._load(root, path):
                if digest(row["source_text"]) != row["source_text_sha256"]:
                    raise BindingError(f"source hash mismatch: {row['id']}")
                for target in row.get("locations", [row["id"]]):
                    if target in self.direct:
                        raise BindingError(f"duplicate native target: {target}")
                    self.direct[target] = row
                if row['corpus'].startswith('corpus/zh/special-disc/'):
                    kind = row.get('kind', 'dialogue')
                    if kind in {'scene_label', 'location_caption'}:
                        kind = 'dialogue'
                    self.sp_fallback[kind, row['source_text_sha256']].append(row)
        paths = [("dialogue", p) for p in sorted((root / "corpus/zh/story-dialogue").glob("stage-*.json"))]
        paths += [(kind, root / f"corpus/zh/story-{name}.json")
                  for kind, name in (("speaker", "speakers"), ("condition", "conditions"))]
        for kind, path in paths:
            for row in self._load(root, path):
                if row.get("translation"):
                    self.fallback[kind, row["source_text_sha256"]].append(row)

    def _load(self, root, path):
        raw = path.read_bytes()
        reference = str(path.relative_to(root))
        self.inputs[reference] = hashlib.sha256(raw).hexdigest()
        return [dict(row, corpus=reference) for row in json.loads(raw)["entries"]]

    def resolve(self, target: str, kind: str, source: str) -> dict:
        source_hash = digest(source)
        row = self.direct.get(target)
        if row is not None:
            if row["source_text_sha256"] != source_hash:
                raise BindingError(f"native source drift: {target}")
            route = "sp_native_id"
        elif not source.strip("　 \n") or all(c in "？?！!…―ー・。　 \n" for c in source):
            return dict(target=target, source_text_sha256=source_hash, translation=source,
                        route="preserved_placeholder", editorial_status="preserved")
        else:
            candidates = self.sp_fallback[kind, source_hash]
            if len({r.get('translation') for r in candidates}) == 1:
                route = 'sp_unique_source'
            else:
                candidates = self.fallback[kind, source_hash]
                route = 'main_unique_source'
            accepted = [r for r in candidates if self.allow_draft or r.get("editorial_status") == "reviewed"]
            answers = {r["translation"] for r in accepted}
            if len(answers) != 1:
                raise BindingError(f"{target}: {len(answers)} fallback answers for {source!r}")
            # The answer is unique; select only its provenance deterministically.
            row = min(accepted, key=lambda r: (r.get("editorial_status") != "reviewed", r["corpus"], r["id"]))
        if not row.get("translation"):
            raise BindingError(f"empty translation: {target}")
        if row.get("editorial_status") != "reviewed" and not self.allow_draft:
            raise BindingError(f"draft requires --allow-draft: {target}")
        return dict(target=target, source_text_sha256=source_hash, translation=row["translation"],
                    route=route, corpus=row["corpus"], corpus_id=row["id"],
                    kind=row.get("kind", kind), editorial_status=row.get("editorial_status"))
