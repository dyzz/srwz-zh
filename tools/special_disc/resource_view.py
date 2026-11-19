"""Seekable resource overlay on a retail disc. Only writes are stored, as separate blobs."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

ENV = "SRWZ_SP_RESOURCE_BUILD"


def enabled():
    return os.environ.get(ENV) == "1"


def open_view(path):
    if isinstance(path, ResourceView):
        return path
    path = Path(path)
    return ResourceView.load(path) if path.suffix == ".spview" else path


class ResourceView:
    def __init__(self, path, base, size, spans=()):
        self.path = Path(path).resolve()
        self.base = base
        self.size = size
        self.spans = list(spans)

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        doc = json.loads(path.read_text())
        return cls(
            path,
            open_view(path.parent / doc["base"]),
            doc["size"],
            [
                (offset, length, path.parent / blob, start)
                for offset, length, blob, start in doc["spans"]
            ],
        )

    @classmethod
    def create(cls, path, base):
        return cls(path, base, base.stat().st_size)

    def save(self):
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        base = self.base.path if isinstance(self.base, ResourceView) else self.base
        doc = {
            "base": os.path.relpath(base, parent),
            "size": self.size,
            "spans": [
                (o, n, os.path.relpath(p, parent), s) for o, n, p, s in self.spans
            ],
        }
        self.path.write_text(json.dumps(doc))

    def add(self, offset, length, blob, start=0):
        if (
            offset < 0
            or length < 0
            or start < 0
            or start + length > blob.stat().st_size
        ):
            raise ValueError("resource range out of bounds")
        self.spans.append((offset, length, blob, start))
        self.size = max(self.size, offset + length)

    def digest(self):
        h = hashlib.sha256()
        with self.open("rb") as f:
            while block := f.read(8 << 20):
                h.update(block)
        return h.hexdigest()

    @property
    def parent(self):
        return self.path.parent

    @property
    def name(self):
        return self.path.name

    def resolve(self):
        return self

    def __str__(self):
        return str(self.path)

    def relative_to(self, parent):
        return self.path.relative_to(parent)

    def with_suffix(self, suffix):
        return self.path.with_suffix(suffix)

    def stat(self):
        return SimpleNamespace(st_size=self.size)

    def open(self, mode):
        if mode not in ("rb", "r+b"):
            raise ValueError(mode)
        return ResourceStream(self, mode == "r+b")

    def materialize(self, target):
        from srwz.release_inputs import copy_file

        if isinstance(self.base, ResourceView):
            self.base.materialize(target)
        else:
            copy_file(self.base, target)
        with target.open("r+b") as out:
            out.truncate(self.size)
            for offset, length, path, start in self.spans:
                with path.open("rb") as src:
                    src.seek(start)
                    out.seek(offset)
                    while length:
                        block = src.read(min(length, 8 << 20))
                        if not block:
                            raise ValueError("truncated resource")
                        out.write(block)
                        length -= len(block)


class ResourceStream(io.RawIOBase):
    def __init__(self, view, writable):
        self.view = view
        self.position = 0
        self.can_write = writable
        self.source = view.base.open("rb")

    def close(self):
        self.source.close()
        super().close()

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = (0, self.position, self.view.size)[whence] + offset
        if self.position < 0:
            raise ValueError("negative offset")
        return self.position

    def read(self, size=-1):
        start = self.position
        size = (
            max(0, self.view.size - start)
            if size < 0
            else max(0, min(size, self.view.size - start))
        )
        self.source.seek(start)
        data = bytearray(self.source.read(size))
        data.extend(bytes(size - len(data)))
        for at, length, blob, source_at in self.view.spans:
            lo, hi = max(at, start), min(at + length, start + size)
            if lo < hi:
                with blob.open("rb") as f:
                    f.seek(source_at + lo - at)
                    block = f.read(hi - lo)
                if len(block) != hi - lo:
                    raise ValueError(f"truncated resource: {blob}")
                data[lo - start : hi - start] = block
        self.position += size
        return bytes(data)

    def write(self, data):
        if not self.can_write:
            raise io.UnsupportedOperation("read only")
        if data:
            directory = self.view.path.with_suffix(".resources")
            directory.mkdir(parents=True, exist_ok=True)
            blob = directory / str(len(self.view.spans))
            blob.write_bytes(data)
            self.view.add(self.position, len(data), blob)
            self.position += len(data)
        return len(data)

    def truncate(self, size):
        if not self.can_write or size < self.view.size:
            raise ValueError("resource views may only be extended")
        self.view.size = size
        return size
