"""Loaded by every Python process of a traced build step (PYTHONPATH; srwz.step_memo).

While SRWZ_STEP_TRACE names a log file, each file opened for reading, each directory listed and each file cloned
is appended to it as "KIND<TAB>real path". A tool that answers from one large file entry by entry (srwz.build_language) reports
the entries asked for instead ("K" lines: path, selector, answer digest). Nothing else changes. The hook must never raise.
"""
import os
import sys

_LOG = os.environ.get("SRWZ_STEP_TRACE")
if _LOG:
    _FD = os.open(_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    _WRITE_ONLY = os.O_WRONLY | os.O_TRUNC
    _SEEN = set()
    _KEYED = set()       # files whose next read is answered entry by entry ("K" lines), not as a whole
    _DERIVING = {}       # thread -> depth: its reads are summed up by a value it reports ("V" lines)
    import threading

    def _note(kind, path):
        if path is None:
            path = "."
        if isinstance(path, int):
            return
        path = os.path.realpath(os.fsdecode(path))
        key = (kind, path)
        if key in _SEEN:
            return
        _SEEN.add(key)
        os.write(_FD, f"{kind}\t{path}\n".encode("utf-8", "surrogateescape"))

    def _hook(event, args):
        try:
            if event == "srwz.derive-begin":
                thread = threading.get_ident()
                _DERIVING[thread] = _DERIVING.get(thread, 0) + 1
                return
            if event in ("srwz.derive-end", "srwz.derive-abort"):
                thread = threading.get_ident()
                _DERIVING[thread] = _DERIVING.get(thread, 1) - 1
                if event == "srwz.derive-end":
                    key = ("V", args[0], args[1], args[2])
                    if key not in _SEEN:
                        _SEEN.add(key)
                        os.write(_FD, f"V\t{os.path.realpath(args[1])}\t{args[0]}\t{args[2]}\n".encode(
                            "utf-8", "surrogateescape"))
                else:
                    os.write(_FD, b"X\tderivation failed\n")
                return
            if _DERIVING and _DERIVING.get(threading.get_ident()):
                return
            if event == "open":
                target, mode, flags = args[0], args[1], args[2]
                if isinstance(mode, str):
                    reads = mode.startswith("r") or mode.startswith("U")
                else:
                    reads = flags is None or not (flags & _WRITE_ONLY)
                if reads:
                    real = None if isinstance(target, int) else os.path.realpath(os.fsdecode(target))
                    if real in _KEYED:
                        _KEYED.discard(real)
                    else:
                        _note("R", target)
            elif event in ("os.listdir", "os.scandir"):
                _note("D", args[0] if args else None)
            elif event in ("glob.glob", "glob.glob/2"):
                _note("D", os.path.dirname(args[0]) or ".")
            elif event == "srwz.clonefile":
                _note("R", args[0])
            elif event == "srwz.keyed":
                _KEYED.add(os.path.realpath(os.fsdecode(args[0])))
            elif event == "srwz.lookup":
                path = os.path.realpath(os.fsdecode(args[0]))
                key = ("K", path, args[1])
                if key not in _SEEN:
                    _SEEN.add(key)
                    os.write(_FD, f"K\t{path}\t{args[1]}\t{args[2]}\n".encode("utf-8", "surrogateescape"))
        except Exception:  # noqa: BLE001  (a trace line lost is recorded below as a broken trace)
            try:
                os.write(_FD, b"X\tbroken\n")
            except OSError:
                pass

    sys.addaudithook(_hook)
