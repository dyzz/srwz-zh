"""Order-preserving map over spawned worker processes for CPU-bound pure jobs.

The layout and caption passes are pure Python (fraction arithmetic, pixel
loops) and the interpreter lock keeps threads from helping. Workers are
forked while the calling process is single-threaded (the loaded modules,
layout tables and caches come for free; the Rust codec worker re-opens per
pid), and spawned otherwise. ``function`` must be importable by module name
and every argument and result must pickle, so both modes behave the same.
``SRWZ_WORKERS`` caps the worker count; ``1`` runs the jobs in the calling
process, which is also what short job lists do.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
import sys
import threading

ENV_WORKERS = "SRWZ_WORKERS"
MIN_PARALLEL_ITEMS = 4


def worker_count(limit: int | None = None) -> int:
    configured = os.environ.get(ENV_WORKERS)
    count = int(configured) if configured and configured.strip().isdigit() else (os.cpu_count() or 1)
    count = max(1, min(count, 8 if configured is None else count))
    return max(1, min(count, limit)) if limit else count


def map_processes(function, items, *, workers: int | None = None, chunksize: int = 1,
                  initializer=None, initargs=()):
    """Return ``[function(item) for item in items]`` computed in worker processes."""
    items = list(items)
    count = worker_count(min(workers or len(items), len(items)))
    if len(items) < MIN_PARALLEL_ITEMS or count == 1:
        if initializer is not None:
            initializer(*initargs)
        return [function(item) for item in items]
    method = "fork" if sys.platform != "win32" and threading.active_count() == 1 else "spawn"
    global _FORK_JOB
    if method == "fork":
        # Forked workers inherit the parent's memory, so a closure (a per-stage
        # builder over large decoded inputs) runs there without pickling it.
        _FORK_JOB = function
        function = _call_fork_job
    elif not _importable(function):
        if initializer is not None:
            initializer(*initargs)
        return [function(item) for item in items]
    context = multiprocessing.get_context(method)
    try:
        with ProcessPoolExecutor(max_workers=count, mp_context=context,
                                 initializer=initializer, initargs=initargs) as pool:
            return list(pool.map(function, items, chunksize=chunksize))
    finally:
        _FORK_JOB = None


_FORK_JOB = None


def _call_fork_job(item):
    return _FORK_JOB(item)


def _importable(function) -> bool:
    module = sys.modules.get(getattr(function, "__module__", None) or "")
    name = getattr(function, "__qualname__", "")
    return module is not None and "<" not in name and getattr(module, name.split(".")[0], None) is not None


def split_shards(items, count: int | None = None) -> list[list]:
    """Contiguous, order-preserving shards; one per worker by default."""
    items = list(items)
    if not items:
        return []
    count = max(1, min(worker_count(count or len(items)), len(items)))
    size = -(-len(items) // count)
    return [items[start:start + size] for start in range(0, len(items), size)]


def merge_shard_values(name: str, initial, values: list, *, first_wins: bool = False):
    """Fold per-shard tallies that each started from ``initial`` into one value.

    Counts add their deltas (``maximum_*`` take the maximum), lists append in
    shard order, sets union, dictionaries and counters merge (a key may not
    change meaning between shards unless ``first_wins`` says the serial loop
    kept the first occurrence), and a scalar may be set by one shard only.
    """
    from collections import Counter
    if isinstance(initial, bool) or initial is None or isinstance(initial, str):
        changed = [value for value in values if value != initial]
        if not changed:
            return initial
        if any(value != changed[0] for value in changed):
            raise ValueError(f"shards disagree on {name}")
        return changed[0]
    if isinstance(initial, int):
        if name.startswith("maximum_"):
            return max([initial, *values])
        return initial + sum(value - initial for value in values)
    if isinstance(initial, list):
        merged = list(initial)
        for value in values:
            if value[:len(initial)] != initial:
                raise ValueError(f"shard rewrote the initial list {name}")
            merged.extend(value[len(initial):])
        return merged
    if isinstance(initial, set):
        merged = set(initial)
        for value in values:
            merged |= value
        return merged
    if isinstance(initial, Counter):
        merged = Counter(initial)
        for value in values:
            for key, count in value.items():
                merged[key] += count - initial.get(key, 0)
        return merged
    if isinstance(initial, dict):
        merged = dict(initial)
        for value in values:
            for key, item in value.items():
                if key in merged:
                    if first_wins:
                        continue
                    if merged[key] != item:
                        raise ValueError(f"shards disagree on {name}[{key!r}]")
                merged[key] = item
        return merged
    raise TypeError(f"cannot merge shard values for {name}: {type(initial).__name__}")
