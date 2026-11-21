"""Bind SP native records before encoding; never select a hash's first answer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BindingError(ValueError):
    pass


class StageBindings:
    def __init__(self, root: Path, *, allow_draft: bool):
        self.allow_draft = allow_draft
        self.direct = {}
        self.bound = {}
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
        references = root / "config/products/special-disc/stage-record-bindings.json"
        raw = references.read_bytes()
        self.inputs[str(references.relative_to(root))] = hashlib.sha256(raw).hexdigest()
        by_file = {}
        for target, (reference, entry_id) in json.loads(raw).items():
            if reference not in by_file:
                by_file[reference] = {r["id"]: r for r in self._load(root, root / reference)}
            self.bound[target] = by_file[reference][entry_id]

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
            row = self.bound.get(target)
            if row is None or row["source_text_sha256"] != source_hash:
                raise BindingError(f"missing binding or source drift: {target}")
            route = "explicit_corpus_id"
        if not row.get("translation"):
            raise BindingError(f"empty translation: {target}")
        if row.get("editorial_status") != "reviewed" and not self.allow_draft:
            raise BindingError(f"draft requires --allow-draft: {target}")
        return dict(target=target, source_text_sha256=source_hash, translation=row["translation"],
                    route=route, corpus=row["corpus"], corpus_id=row["id"],
                    kind=row.get("kind", kind), editorial_status=row.get("editorial_status"))
