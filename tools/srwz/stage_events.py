"""Read-only recovery of map-event triggers from a decoded STAGE overlay.

Every playable STAGE overlay installs a dispatcher function pointer at
``0x595278``.  The executable calls it with an event kind (2 = phase start,
3 = third-party phase start, 4 = battle start, 5 = battle end, 6 = unit
action finished, 7 = unit destroyed, 8 = map start).  The dispatcher's small
handler functions test globals (turn number, scenario part byte, stage flags,
destroyed-unit queries) and run 16-byte-record map scripts through
``FUN_0017a960``.  Scripts invoke battle dialogue sections by event id with
opcode ``0x0f``; pre-battle conversations come from the table passed to
``FUN_001744a0`` on event 4, and scripted duels from the ``0x595290`` table.

This module symbolically walks the handler code (MIPS subset) and the map
scripts to recover, for every battle dialogue section, the event that shows
it and the conditions guarding it.  Nothing here writes game data; the
findings are recorded in ``work/analysis/stage-map-events-20260914``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

BASE = 0x7566F0
GP = 0x4537F0
# Address-profile fields; the default remains the Original executable.
GLOBAL_STORE_START = 0x590000
GLOBAL_STORE_END = 0x5A0000
DISPATCHER_SLOT = 0x595278
BATTLE_PAIR_SLOT = 0x595290
DEPLOYMENT_GROUP_SLOT = 0x595268
DEPLOYMENT_RECORD_SLOT = 0x595258
DEPLOYMENT_COUNT_SLOT = 0x595250

# SLPS helpers reachable from overlay handler code.
FN_RUN_SCRIPT = 0x17A960
FN_FLAG_TEST = 0x14B4C0
FN_FLAG_SET = 0x14B410
FN_FLAG_CLEAR = 0x14B460
FN_GFLAG_TEST = 0x14B3C0
FN_UNIT_DESTROYED = 0x1B66F0
FN_DESTROYED_QUERY = 0x1741C0
FN_COUNT_UNITS = 0x175AC0
FN_IN_BATTLE = 0x1B9500
FN_VAR_READ = 0x1BB060
FN_BATTLE_TALK = 0x1744A0
FN_SPAWN_LIST = 0x1B0F50

GLOBAL_NAMES = {
    0x5585D0: "turn",
    0x5585D2: "turn_counter",
    0x55856A: "turn_total",
    0x558815: "part",
    0x5586E1: "phase",
    0x55856E: "route",
    0x44BDB4: "gp_7a3c",
}


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


# ---------------------------------------------------------------------------
# tiny MIPS decoder
# ---------------------------------------------------------------------------


@dataclass
class Insn:
    op: str
    rs: int = 0
    rt: int = 0
    rd: int = 0
    imm: int = 0
    target: int = 0
    raw: int = 0


def decode(word: int) -> Insn:
    op = word >> 26
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    rd = (word >> 11) & 0x1F
    sa = (word >> 6) & 0x1F
    imm = word & 0xFFFF
    simm = imm - 0x10000 if imm >= 0x8000 else imm
    if word == 0:
        return Insn("nop", raw=word)
    if op == 0:
        fn = word & 0x3F
        names = {
            0x21: "addu", 0x2D: "daddu", 0x25: "or", 0x23: "subu", 0x2F: "dsubu",
            0x24: "and", 0x26: "xor", 0x2A: "slt", 0x2B: "sltu",
        }
        if fn == 0x08:
            return Insn("jr", rs=rs, raw=word)
        if fn == 0x09:
            return Insn("jalr", rs=rs, rd=rd, raw=word)
        if fn == 0x00:
            return Insn("sll", rt=rt, rd=rd, imm=sa, raw=word)
        if fn == 0x02:
            return Insn("srl", rt=rt, rd=rd, imm=sa, raw=word)
        if fn == 0x03:
            return Insn("sra", rt=rt, rd=rd, imm=sa, raw=word)
        if fn in names:
            return Insn(names[fn], rs=rs, rt=rt, rd=rd, raw=word)
        if fn in (0x38, 0x3A, 0x3B, 0x3C, 0x3E, 0x3F):
            # dsll/dsrl/dsra and their 32 variants: used as sign/zero
            # extension idioms on already-narrow values
            return Insn("dshift", rt=rt, rd=rd, imm=sa, raw=word)
        return Insn("r_other", rs=rs, rt=rt, rd=rd, raw=word)
    if op == 1:
        if rt == 0:
            return Insn("bltz", rs=rs, imm=simm, raw=word)
        if rt == 1:
            return Insn("bgez", rs=rs, imm=simm, raw=word)
        return Insn("regimm", rs=rs, rt=rt, imm=simm, raw=word)
    if op == 2:
        return Insn("j", target=(word & 0x3FFFFFF) << 2, raw=word)
    if op == 3:
        return Insn("jal", target=(word & 0x3FFFFFF) << 2, raw=word)
    if op == 4:
        return Insn("beq", rs=rs, rt=rt, imm=simm, raw=word)
    if op == 5:
        return Insn("bne", rs=rs, rt=rt, imm=simm, raw=word)
    if op == 6:
        return Insn("blez", rs=rs, imm=simm, raw=word)
    if op == 7:
        return Insn("bgtz", rs=rs, imm=simm, raw=word)
    if op == 0x08 or op == 0x09 or op == 0x18 or op == 0x19:
        return Insn("addiu", rs=rs, rt=rt, imm=simm, raw=word)
    if op == 0x0A:
        return Insn("slti", rs=rs, rt=rt, imm=simm, raw=word)
    if op == 0x0B:
        return Insn("sltiu", rs=rs, rt=rt, imm=simm, raw=word)
    if op == 0x0C:
        return Insn("andi", rs=rs, rt=rt, imm=imm, raw=word)
    if op == 0x0D:
        return Insn("ori", rs=rs, rt=rt, imm=imm, raw=word)
    if op == 0x0E:
        return Insn("xori", rs=rs, rt=rt, imm=imm, raw=word)
    if op == 0x0F:
        return Insn("lui", rt=rt, imm=imm, raw=word)
    loads = {0x20: "lb", 0x21: "lh", 0x23: "lw", 0x24: "lbu", 0x25: "lhu", 0x27: "lwu", 0x37: "ld"}
    stores = {0x28: "sb", 0x29: "sh", 0x2B: "sw", 0x3F: "sd"}
    if op in loads:
        return Insn(loads[op], rs=rs, rt=rt, imm=simm, raw=word)
    if op in stores:
        return Insn(stores[op], rs=rs, rt=rt, imm=simm, raw=word)
    return Insn("other", rs=rs, rt=rt, imm=simm, raw=word)


# ---------------------------------------------------------------------------
# symbolic values
# ---------------------------------------------------------------------------

# Values are tuples:
#   ("const", n)
#   ("global", addr, size)      memory load of a fixed address
#   ("call", fn, args)          return value of an SLPS helper
#   ("sp", delta)               stack pointer
#   ("stack", off)              value loaded from stack slot (unknown)
#   ("add", value, n)
#   ("shl", value, n)
#   ("lt", value, n, signed)    result of slti/sltiu
#   ("jt", table, index)        jump table pointer
#   ("unknown", tag)


def is_const(v: Any) -> bool:
    return isinstance(v, tuple) and v[0] == "const"


def const_of(v: Any) -> int | None:
    return v[1] if is_const(v) else None


def add_value(v: Any, n: int) -> Any:
    if is_const(v):
        return ("const", (v[1] + n) & 0xFFFFFFFF)
    if v[0] == "sp":
        return ("sp", v[1] + n)
    if v[0] == "add":
        return ("add", v[1], v[2] + n)
    return ("add", v, n)


def symbol_key(v: Any):
    """Canonical identity of a tested value, or None when not comparable."""
    if v[0] == "global":
        return ("global", v[1])
    if v[0] == "event":
        return ("event",)
    if v[0] == "call":
        fn, args = v[1], v[2]
        nargs = {FN_FLAG_TEST: 1, FN_GFLAG_TEST: 1, FN_UNIT_DESTROYED: 2, FN_IN_BATTLE: 2,
                 FN_COUNT_UNITS: 2, FN_DESTROYED_QUERY: 2, FN_VAR_READ: 2}.get(fn)
        if nargs is None:
            return None
        key = []
        for a in args[:nargs]:
            if not is_const(a):
                return None
            key.append(a[1])
        return ("call", fn, tuple(key))
    return None


def _cond_key(cond):
    opn, a, b = cond
    if is_const(a) and not is_const(b):
        a, b = b, a
        opn = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}.get(opn, opn)
    if not is_const(b):
        return None
    key = symbol_key(a)
    if key is None:
        return None
    return (key, opn, b[1])


def cond_signature(conds):
    """Hashable summary of the keyed conditions on a path."""
    return frozenset(k for k in (_cond_key(c) for c in conds) if k is not None)


def action_signature(actions):
    # Flag writes are deliberately left out: long handlers set one flag per
    # destroyed unit and the combinations would multiply the explored states
    # without changing which scripts can run afterwards.
    return tuple(str(a) for a in actions if a[0] in ("run_script", "battle_talk_table"))


def consistent(conds, new) -> bool:
    opn, a, b = new
    if is_const(a) and not is_const(b):
        a, b = b, a
        opn = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}.get(opn, opn)
    if not is_const(b):
        return True
    key = symbol_key(a)
    if key is None:
        return True
    value = b[1]
    for c in conds:
        copn, ca, cb = c
        if is_const(ca) and not is_const(cb):
            ca, cb = cb, ca
            copn = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}.get(copn, copn)
        if not is_const(cb) or symbol_key(ca) != key:
            continue
        cvalue = cb[1]
        if copn == "==" and opn == "==" and cvalue != value:
            return False
        if copn == "==" and opn == "!=" and cvalue == value:
            return False
        if copn == "!=" and opn == "==" and cvalue == value:
            return False
        if copn == "==" and opn in ("<", "<=", ">", ">="):
            x = cvalue - 0x100000000 if cvalue >= 0x80000000 else cvalue
            y = value - 0x100000000 if value >= 0x80000000 else value
            if not {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[opn]:
                return False
        if opn == "==" and copn in ("<", "<=", ">", ">="):
            x = value - 0x100000000 if value >= 0x80000000 else value
            y = cvalue - 0x100000000 if cvalue >= 0x80000000 else cvalue
            if not {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[copn]:
                return False
        if cvalue == value and {copn, opn} in ({"<=", ">"}, {"<", ">="}):
            return False
    return True


REG_SP = 29
REG_RA = 31
REG_GP = 28


@dataclass
class Path:
    conds: list[tuple[str, Any, Any]] = field(default_factory=list)
    actions: list[tuple] = field(default_factory=list)


class HandlerAnalyzer:
    """Enumerate condition/action paths through overlay handler code."""

    def __init__(self, data: bytes, code_end: int):
        self.data = data
        self.code_end = code_end
        self.paths: list[Path] = []
        self.warnings: list[str] = []
        self.budget = 3_000_000
        self.visited: set = set()

    def insn_at(self, off: int) -> Insn:
        return decode(u32(self.data, off))

    def run(self, entry_off: int, preset_regs: dict[int, Any] | None = None, event: Any = None):
        regs: dict[int, Any] = {0: ("const", 0), REG_SP: ("sp", 0), REG_GP: ("const", GP)}
        if preset_regs:
            regs.update(preset_regs)
        self.paths = []
        self.visited = set()
        self.meet = {}
        self.triggers = []
        self._walk(entry_off, regs, {}, [], Path(), 0)
        return self.paths

    # -- execution ---------------------------------------------------------
    def _read_reg(self, regs, r):
        return regs.get(r, ("unknown", f"r{r}"))

    def _load(self, regs, stack, insn: Insn):
        base = self._read_reg(regs, insn.rs)
        size = {"lb": 1, "lbu": 1, "lh": 2, "lhu": 2, "lw": 4, "lwu": 4, "ld": 8}[insn.op]
        if base[0] == "sp":
            return stack.get(base[1] + insn.imm, ("stack", base[1] + insn.imm))
        if is_const(base):
            addr = (base[1] + insn.imm) & 0xFFFFFFFF
            if BASE <= addr < BASE + len(self.data):
                off = addr - BASE
                fmt = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}[size]
                if insn.op in ("lb", "lh"):
                    fmt = fmt.lower()
                return ("const", struct.unpack_from(fmt, self.data, off)[0] & 0xFFFFFFFF)
            return ("global", addr, size)
        if base[0] == "add" and is_const(base[1]):
            # table lookup: base const + index
            return ("load", add_value(base[1], base[2] + insn.imm), base)
        if base[0] == "add":
            inner = base[1]
            if inner[0] == "add" and is_const(inner[1]):
                pass
        # jump table: ("add", ("shl", idx, 2), n) with n const table?
        if base[0] == "addr":
            pass
        return ("load", base, insn.imm)

    def _walk(self, pc, regs, stack, ret_stack, path: Path, depth, loops=None):
        steps = 0
        loops = dict(loops) if loops else {}
        while True:
            steps += 1
            self.budget -= 1
            if steps > 20000 or depth > 160 or self.budget < 0:
                if self.budget == -1 or steps > 20000 or depth > 160:
                    self.warnings.append(f"path limit at {pc:#x}")
                return
            if pc < 0x80 or pc >= self.code_end:
                self.warnings.append(f"pc outside code: {pc:#x}")
                return
            insn = self.insn_at(pc)
            op = insn.op
            if op in ("beq", "bne", "blez", "bgtz", "bltz", "bgez"):
                # execute delay slot first
                self._exec_simple(self.insn_at(pc + 4), regs, stack, path)
                target = pc + 4 + insn.imm * 4
                a = self._read_reg(regs, insn.rs)
                if op in ("beq", "bne"):
                    b = self._read_reg(regs, insn.rt)
                    if op == "beq":
                        cond_t, cond_f = ("==", a, b), ("!=", a, b)
                    else:
                        cond_t, cond_f = ("!=", a, b), ("==", a, b)
                else:
                    zero = ("const", 0)
                    mapping = {
                        "blez": (("<=", a, zero), (">", a, zero)),
                        "bgtz": ((">", a, zero), ("<=", a, zero)),
                        "bltz": (("<", a, zero), (">=", a, zero)),
                        "bgez": ((">=", a, zero), ("<", a, zero)),
                    }
                    cond_t, cond_f = mapping[op]
                decided = self._evaluate(cond_t)
                if target <= pc and decided is not False:
                    # loop back-edge (for example iterating the unit table):
                    # a couple of iterations are enough to observe its effects
                    loops[pc] = loops.get(pc, 0) + 1
                    if loops[pc] > 2:
                        decided = False
                if decided is True:
                    pc = target
                    continue
                if decided is False:
                    pc = pc + 8
                    continue
                # fork, pruning paths whose new condition contradicts an
                # earlier test of the same symbol, and skipping states already
                # explored with the same keyed conditions and pending actions
                if consistent(path.conds, cond_t):
                    path_t = Path(list(path.conds) + [cond_t], list(path.actions))
                    if self._enter_state(target, regs, ret_stack, path_t):
                        self._walk(target, dict(regs), dict(stack), list(ret_stack), path_t, depth + 1, loops)
                if not consistent(path.conds, cond_f):
                    return
                path.conds.append(cond_f)
                if not self._enter_state(pc + 8, regs, ret_stack, path):
                    return
                pc = pc + 8
                continue
            if op == "j":
                self._exec_simple(self.insn_at(pc + 4), regs, stack, path)
                pc = ((pc + 4 + BASE) & 0xF0000000 | insn.target) - BASE
                continue
            if op == "jal":
                self._exec_simple(self.insn_at(pc + 4), regs, stack, path)
                target = ((pc + 4 + BASE) & 0xF0000000) | insn.target
                if BASE <= target < BASE + len(self.data):
                    ret_stack = list(ret_stack) + [pc + 8]
                    pc = target - BASE
                    continue
                self._call(target, regs, path, pc)
                pc = pc + 8
                continue
            if op == "jalr":
                self._exec_simple(self.insn_at(pc + 4), regs, stack, path)
                target = self._read_reg(regs, insn.rs)
                if is_const(target) and BASE <= target[1] < BASE + len(self.data):
                    ret_stack = list(ret_stack) + [pc + 8]
                    pc = target[1] - BASE
                    continue
                if is_const(target):
                    self._call(target[1], regs, path, pc)
                else:
                    path.actions.append(("call_indirect", target))
                    regs[2] = ("unknown", "jalr")
                pc = pc + 8
                continue
            if op == "jr":
                self._exec_simple(self.insn_at(pc + 4), regs, stack, path)
                if insn.rs == REG_RA:
                    if ret_stack:
                        pc = ret_stack[-1]
                        ret_stack = ret_stack[:-1]
                        continue
                    self.paths.append(path)
                    return
                target = self._read_reg(regs, insn.rs)
                if target[0] == "jt":
                    table_off = target[1] - BASE
                    index = target[2]
                    # the switch guard (sltiu index, N) bounds the table
                    bound = 64
                    for copn, ca, cb in path.conds:
                        if (
                            copn == "!="
                            and isinstance(ca, tuple)
                            and ca[0] == "lt"
                            and ca[1] == index
                            and is_const(cb)
                            and cb[1] == 0
                        ):
                            bound = min(bound, ca[2])
                    for i in range(bound):
                        entry = u32(self.data, table_off + i * 4)
                        if not (BASE + 0x80 <= entry < BASE + self.code_end):
                            break
                        sub = Path(list(path.conds) + [("==", index, ("const", i))], list(path.actions))
                        self._walk(entry - BASE, dict(regs), dict(stack), list(ret_stack), sub, depth + 1, loops)
                    return
                if is_const(target) and BASE <= target[1] < BASE + len(self.data):
                    pc = target[1] - BASE
                    continue
                self.warnings.append(f"unresolved jr at {pc:#x}: {target}")
                self.paths.append(path)
                return
            self._exec_simple(insn, regs, stack, path)
            pc += 4

    def _enter_state(self, pc, regs, ret_stack, path: Path) -> bool:
        """Meet-over-paths pruning.

        A program point is re-explored only when the set of conditions known
        on the new path removes something from the intersection recorded so
        far; the path then continues with that intersection.  Callee-saved
        registers are part of the state because handlers accumulate loop
        results in them.
        """

        saved = tuple(str(regs.get(r)) for r in range(16, 24))
        key = (pc, tuple(ret_stack), action_signature(path.actions), saved)
        conds = cond_signature(path.conds)
        previous = self.meet.get(key)
        if previous is None:
            self.meet[key] = conds
            return True
        joined = previous & conds
        if joined == previous:
            return False
        self.meet[key] = joined
        path.conds = [c for c in path.conds if _cond_key(c) in joined]
        return True

    def _evaluate(self, cond):
        opn, a, b = cond
        if is_const(a) and is_const(b):
            x, y = a[1], b[1]
            xs = x - 0x100000000 if x >= 0x80000000 else x
            ys = y - 0x100000000 if y >= 0x80000000 else y
            return {
                "==": x == y, "!=": x != y, "<": xs < ys, "<=": xs <= ys,
                ">": xs > ys, ">=": xs >= ys,
            }[opn]
        return None

    def _exec_simple(self, insn: Insn, regs, stack, path: Path):
        op = insn.op
        if op == "nop" or op in ("beq", "bne", "blez", "bgtz", "bltz", "bgez", "j", "jal", "jalr", "jr"):
            return
        if op == "lui":
            regs[insn.rt] = ("const", (insn.imm << 16) & 0xFFFFFFFF)
        elif op == "addiu":
            regs[insn.rt] = add_value(self._read_reg(regs, insn.rs), insn.imm)
        elif op == "ori":
            v = self._read_reg(regs, insn.rs)
            regs[insn.rt] = ("const", v[1] | insn.imm) if is_const(v) else ("or", v, insn.imm)
        elif op == "andi":
            v = self._read_reg(regs, insn.rs)
            if is_const(v):
                regs[insn.rt] = ("const", v[1] & insn.imm)
            elif v[0] == "global" and insn.imm in (0xFF, 0xFFFF) and v[2] * 8 <= insn.imm.bit_length():
                regs[insn.rt] = v
            elif v[0] == "event" and insn.imm == 0xFF:
                regs[insn.rt] = v
            else:
                regs[insn.rt] = ("and", v, insn.imm)
        elif op == "xori":
            v = self._read_reg(regs, insn.rs)
            regs[insn.rt] = ("const", v[1] ^ insn.imm) if is_const(v) else ("xor", v, insn.imm)
        elif op in ("slti", "sltiu"):
            v = self._read_reg(regs, insn.rs)
            if is_const(v):
                x = v[1]
                if op == "slti":
                    x = x - 0x100000000 if x >= 0x80000000 else x
                    regs[insn.rt] = ("const", int(x < insn.imm))
                else:
                    regs[insn.rt] = ("const", int(x < (insn.imm & 0xFFFFFFFF)))
            else:
                regs[insn.rt] = ("lt", v, insn.imm, op == "slti")
        elif op in ("addu", "daddu", "or"):
            a = self._read_reg(regs, insn.rs)
            b = self._read_reg(regs, insn.rt)
            if insn.rt == 0:
                regs[insn.rd] = a
            elif insn.rs == 0:
                regs[insn.rd] = b
            elif is_const(a) and is_const(b):
                regs[insn.rd] = ("const", (a[1] + b[1]) & 0xFFFFFFFF)
            elif is_const(b):
                regs[insn.rd] = add_value(a, b[1])
            elif is_const(a):
                regs[insn.rd] = add_value(b, a[1])
            else:
                regs[insn.rd] = ("addr", a, b)
        elif op in ("subu", "dsubu"):
            a = self._read_reg(regs, insn.rs)
            b = self._read_reg(regs, insn.rt)
            if is_const(a) and is_const(b):
                regs[insn.rd] = ("const", (a[1] - b[1]) & 0xFFFFFFFF)
            elif insn.rs == 0:
                regs[insn.rd] = ("neg", b)
            else:
                regs[insn.rd] = ("sub", a, b)
        elif op == "sll":
            v = self._read_reg(regs, insn.rt)
            if is_const(v):
                regs[insn.rd] = ("const", (v[1] << insn.imm) & 0xFFFFFFFF)
            else:
                regs[insn.rd] = ("shl", v, insn.imm)
        elif op in ("srl", "sra"):
            v = self._read_reg(regs, insn.rt)
            if is_const(v):
                regs[insn.rd] = ("const", v[1] >> insn.imm)
            else:
                regs[insn.rd] = ("shr", v, insn.imm)
        elif op == "dshift":
            regs[insn.rd] = self._read_reg(regs, insn.rt)
        elif op in ("slt", "sltu"):
            regs[insn.rd] = ("cmp", self._read_reg(regs, insn.rs), self._read_reg(regs, insn.rt))
        elif op in ("and", "xor"):
            regs[insn.rd] = ("bin", op, self._read_reg(regs, insn.rs), self._read_reg(regs, insn.rt))
        elif op in ("lb", "lbu", "lh", "lhu", "lw", "lwu", "ld"):
            base = self._read_reg(regs, insn.rs)
            if base[0] == "addr":
                # jump table pattern: addr(shl(idx,2), const table)
                x, y = base[1], base[2]
                if x[0] == "shl" and x[2] == 2 and is_const(y):
                    regs[insn.rt] = ("jt", y[1] + insn.imm, x[1])
                    return
                if y[0] == "shl" and y[2] == 2 and is_const(x):
                    regs[insn.rt] = ("jt", x[1] + insn.imm, y[1])
                    return
            if base[0] == "add" and base[1][0] == "shl" and base[1][2] == 2:
                regs[insn.rt] = ("jt", base[2] + insn.imm, base[1][1])
                return
            regs[insn.rt] = self._load(regs, stack, insn)
        elif op in ("sb", "sh", "sw", "sd"):
            base = self._read_reg(regs, insn.rs)
            if base[0] == "sp":
                stack[base[1] + insn.imm] = self._read_reg(regs, insn.rt)
            elif is_const(base):
                addr = (base[1] + insn.imm) & 0xFFFFFFFF
                path.actions.append(("store", addr, self._read_reg(regs, insn.rt)))
        elif op in ("r_other", "other", "regimm"):
            if insn.rd and op == "r_other":
                regs[insn.rd] = ("unknown", f"r_other@{insn.raw:08x}")
            elif op == "other" and insn.rt:
                regs[insn.rt] = ("unknown", f"other@{insn.raw:08x}")

    def _call(self, target, regs, path: Path, site: int = 0):
        args = tuple(self._read_reg(regs, r) for r in (4, 5, 6, 7))
        if target == FN_RUN_SCRIPT:
            path.actions.append(("run_script", args[0]))
            self.triggers.append((site, list(path.conds), list(path.actions)))
        elif target == FN_FLAG_SET:
            path.actions.append(("set_flag", args[0]))
            self.triggers.append((site, list(path.conds), list(path.actions)))
        elif target == FN_FLAG_CLEAR:
            path.actions.append(("clear_flag", args[0]))
            self.triggers.append((site, list(path.conds), list(path.actions)))
        elif target == FN_BATTLE_TALK:
            path.actions.append(("battle_talk_table", args[0]))
            self.triggers.append((site, list(path.conds), list(path.actions)))
        elif target == FN_SPAWN_LIST:
            path.actions.append(("spawn_list", args[0], args[1], args[2]))
        else:
            path.actions.append(("call", target, args))
        regs[2] = ("call", target, args)
        # caller-saved registers become unknown
        for r in (1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25):
            regs[r] = ("unknown", f"clobber{r}")


# ---------------------------------------------------------------------------
# entry function: installed globals
# ---------------------------------------------------------------------------


def installed_globals(data: bytes, function_offset: int) -> dict[int, int]:
    regs: dict[int, int] = {}
    stores: dict[int, int] = {}
    for off in range(function_offset, min(function_offset + 0x800, len(data) - 4), 4):
        w = u32(data, off)
        insn = decode(w)
        if insn.op == "lui":
            regs[insn.rt] = (insn.imm << 16) & 0xFFFFFFFF
        elif insn.op == "addiu":
            if insn.rs == 0:
                regs[insn.rt] = insn.imm & 0xFFFFFFFF
            elif insn.rs in regs:
                regs[insn.rt] = (regs[insn.rs] + insn.imm) & 0xFFFFFFFF
            else:
                regs.pop(insn.rt, None)
        elif insn.op == "sw":
            if insn.rs in regs and GLOBAL_STORE_START <= regs[insn.rs] + insn.imm < GLOBAL_STORE_END:
                stores[regs[insn.rs] + insn.imm] = regs.get(insn.rt, 0)
        elif insn.op == "jal":
            target = ((off + 4 + BASE) & 0xF0000000) | insn.target
            if BASE <= target < BASE + len(data):
                # tiny getter functions: lui/jr/addiu
                t = target - BASE
                a = decode(u32(data, t))
                b = decode(u32(data, t + 8))
                if a.op == "lui" and b.op == "addiu":
                    regs[2] = ((a.imm << 16) + b.imm) & 0xFFFFFFFF
                else:
                    regs.pop(2, None)
            else:
                regs.pop(2, None)
            for r in (4, 5, 6, 7):
                regs.pop(r, None)
        elif insn.op == "jr" and insn.rs == REG_RA:
            break
    return stores


# ---------------------------------------------------------------------------
# script walker
# ---------------------------------------------------------------------------

OP_END = 0x0B
OP_END_DISPATCH = 0x4F
OP_RET = 0x54
OP_CALL = 0x52
OP_CALL_TABLE = 0x53
OP_BATTLE_DLG = 0x0F
OP_DLG_BY_DIFFICULTY = 0x10
OP_DLG_POINTER = 0x11
OP_FLAG = 0x12
OP_NATIVE = 0x14
OP_JMP_IF = 0x20
OP_JMP = 0x21
OP_JMP_IF_UNIT_GONE = 0x3C
OP_JMP_IF_FLAG = 0x3E
OP_JMP_IF_GFLAG = 0x3F
OP_JMP_IF_ROUTE1 = 0x49
OP_SET_PART = 0x58
OP_SPAWN = 0x05
OP_SELECT_GROUP = 0x04
OP_SPAWN_LIST = 0x0D
OP_IF = 0x1389
OP_IF2 = 0x138A
OP_ELSE = 0x138B
OP_ENDIF = 0x138C
OP_LOOP = 0x138D
OP_LOOP_END = 0x138E
OP_LOOP2 = 0x138F
OP_ASSIGN = 0x1388

COMPARE_OPS = {0x800: "==", 0x801: "!=", 0x802: ">", 0x803: "<", 0x804: ">=", 0x805: "<=", 0x806: "&"}


def script_operand(value: int) -> dict[str, Any]:
    lo = value & 0xFFFF
    hi = (value >> 16) & 0xFFFF
    if hi == 0:
        return {"kind": "var", "var": lo}
    if hi == 0x9000:
        return {"kind": "imm", "value": lo - 0x10000 if lo >= 0x8000 else lo}
    if hi == 0x9003:
        return {"kind": "flag", "flag": lo}
    if hi == 0x9002:
        return {"kind": "gflag", "flag": lo}
    return {"kind": "var2", "var": hi, "arg": lo}


@dataclass
class ScriptDialogue:
    event_id: int | None
    conds: list[dict[str, Any]]
    offset: int
    kind: str = "battle"  # battle | pointer | difficulty
    pointer: int | None = None
    variants: list[tuple[int, int]] | None = None


class ScriptWalker:
    """Walk a 16-byte-record map script and collect dialogue invocations."""

    def __init__(self, data: bytes):
        self.data = data
        self.dialogues: list[ScriptDialogue] = []
        self.effects: list[tuple] = []  # ("set_part", n) / ("set_flag", n) / ("clear_flag", n)
        self.warnings: list[str] = []
        self.notes: list[str] = []
        self.visited: set[int] = set()
        self.unknown_ops: set[int] = set()
        self.native_calls: list[int] = []
        self.calls: list[int] = []

    def record(self, off: int):
        w = struct.unpack_from("<4I", self.data, off)
        return w[0] & 0xFFFF, w[1], w[2], w[3]

    def walk(self, start: int, conds: list[dict[str, Any]] | None = None):
        self._walk(start, len(self.data) - 16, list(conds or []), 0)

    def _walk(self, pc: int, limit: int, conds: list[dict[str, Any]], depth: int) -> None:
        """Walk records in [pc, limit) until END/RET.  Returns nothing."""
        steps = 0
        while pc < limit:
            steps += 1
            if steps > 4000 or depth > 24:
                self.warnings.append(f"script limit at {pc:#x}")
                return
            if pc < 0 or pc + 16 > len(self.data):
                self.warnings.append(f"script pc outside overlay: {pc:#x}")
                return
            if pc in self.visited:
                return
            self.visited.add(pc)
            op, a, b, c = self.record(pc)
            if op in (OP_END, OP_END_DISPATCH, OP_RET):
                return
            if op == OP_CALL:
                if BASE <= a < BASE + len(self.data):
                    self.calls.append(a - BASE)
                    self._walk(a - BASE, len(self.data) - 16, conds, depth + 1)
                pc += 16
                continue
            if op == OP_CALL_TABLE:
                if BASE <= a < BASE + len(self.data):
                    for i in range(3):
                        ptr = u32(self.data, a - BASE + i * 4)
                        if BASE <= ptr < BASE + len(self.data):
                            self._walk(ptr - BASE, len(self.data) - 16, conds + [{"type": "route", "value": i}], depth + 1)
                pc += 16
                continue
            if op == OP_JMP:
                target = self._jump_target(pc, a)
                if target is None or target < pc:
                    return
                pc = target
                continue
            if op in (OP_JMP_IF, OP_JMP_IF_UNIT_GONE, OP_JMP_IF_FLAG, OP_JMP_IF_GFLAG, OP_JMP_IF_ROUTE1):
                if op == OP_JMP_IF:
                    target = self._absolute_target(a)
                    if b == 1:
                        cond = {"type": "flag", "flag": c, "value": 1}
                    elif b == 2:
                        cond = {"type": "gflag", "flag": c, "value": 1}
                    else:
                        cond = None
                elif op == OP_JMP_IF_UNIT_GONE:
                    target = self._jump_target(pc, c)
                    cond = {"type": "unit_gone", "unit_kind": a, "unit": b}
                elif op == OP_JMP_IF_FLAG:
                    target = self._jump_target(pc, c)
                    cond = {"type": "flag", "flag": a, "value": b}
                elif op == OP_JMP_IF_GFLAG:
                    target = self._jump_target(pc, c)
                    cond = {"type": "gflag", "flag": a, "value": b}
                else:
                    target = self._jump_target(pc, a)
                    cond = {"type": "route", "value": 1}
                if target is None:
                    if cond is None:
                        return
                    # conditional jump out of the overlay: the remaining
                    # records run only when the condition is false
                    conds = conds + [negate(cond)]
                    pc += 16
                    continue
                if cond is None:
                    pc = target
                    continue
                if pc < target < limit:
                    # records between the jump and its target run when the
                    # condition is false; execution continues at the target
                    # unconditionally when that block falls through, and only
                    # under the condition when the block ends the script.
                    self._walk(pc + 16, target, conds + [negate(cond)], depth + 1)
                    if self._block_terminates(pc + 16, target):
                        conds = conds + [cond]
                    pc = target
                    continue
                # jump elsewhere (another script, or backwards): explore the
                # target as a branch and keep walking sequentially
                self._walk(target, len(self.data) - 16, conds + [cond], depth + 1)
                conds = conds + [negate(cond)]
                pc += 16
                continue
            if op in (OP_IF, OP_IF2, OP_LOOP, OP_LOOP2):
                cond = self._compare_cond(a, b, c) if op != OP_LOOP2 else None
                end, else_off = self._find_block_end(pc, op)
                body_conds = conds + ([cond] if cond else [])
                if else_off is not None and else_off != end:
                    self._walk(pc + 16, else_off, body_conds, depth + 1)
                    self.visited.add(else_off)
                    self._walk(else_off + 16, end, conds + ([negate(cond)] if cond else []), depth + 1)
                elif else_off is not None:
                    self._walk(pc + 16, else_off, body_conds, depth + 1)
                    self.visited.add(else_off)
                    conds = conds + ([negate(cond)] if cond else [])
                else:
                    self._walk(pc + 16, end, body_conds, depth + 1)
                self.visited.add(end)
                pc = end + 16
                continue
            self._simple_record(pc, op, a, b, c, conds)
            pc += 16
            if op in TWO_RECORD_OPS:
                pc += 16
            elif op in PARAM_RECORD_OPS and pc + 16 <= len(self.data):
                following = u32(self.data, pc) & 0xFFFF
                if following not in KNOWN_OPS and following not in KNOWN_EXT_OPS:
                    pc += 16

    def _simple_record(self, pc, op, a, b, c, conds):
        if op == OP_BATTLE_DLG:
            self.dialogues.append(ScriptDialogue(a & 0xFFFF, list(conds), pc))
        elif op == OP_DLG_BY_DIFFICULTY:
            variants = [(i, (a >> (8 * i)) & 0xFF) for i in range(3)]
            self.dialogues.append(ScriptDialogue(None, list(conds), pc, kind="difficulty", variants=variants))
        elif op == OP_DLG_POINTER:
            self.dialogues.append(ScriptDialogue(None, list(conds), pc, kind="pointer", pointer=a))
        elif op == OP_FLAG:
            self.effects.append(("set_flag" if b == 0 else "clear_flag", a))
        elif op == OP_SET_PART:
            self.effects.append(("set_part", a))
        elif op == OP_SPAWN:
            if a == 0xFFFFFFFF:
                self.effects.append(("spawn_group_selected", 0))
            else:
                self.effects.append(("spawn_group", a))
        elif op == OP_SELECT_GROUP:
            self.effects.append(("select_group", [a, b, c]))
        elif op == OP_SPAWN_LIST:
            if BASE <= a < BASE + len(self.data):
                self.effects.append(("spawn_list", a - BASE))
        elif op == OP_NATIVE:
            if BASE <= a < BASE + len(self.data):
                self.native_calls.append(a)
        elif op in (OP_ELSE, OP_ENDIF, OP_LOOP_END):
            pass
        elif (op >= 0x1388 and op not in KNOWN_EXT_OPS) or (op < 0x1388 and op not in KNOWN_OPS):
            self.unknown_ops.add(op)
            self.warnings.append(f"unknown opcode {op:#x} at {pc:#x}")

    def _absolute_target(self, address: int) -> int | None:
        if BASE <= address < BASE + len(self.data):
            return address - BASE
        # jump into an SLPS-resident script (for example the shared game-over
        # sequence): no further overlay dialogue follows
        return None

    def _block_terminates(self, start: int, end: int) -> bool:
        """Whether a skipped block ends the script instead of falling through."""

        p = start
        while p + 16 <= end:
            op = u32(self.data, p) & 0xFFFF
            if op in (OP_END, OP_END_DISPATCH, OP_RET):
                return True
            if op == OP_JMP:
                return True
            p += 16
        return False

    def _jump_target(self, pc: int, arg: int) -> int | None:
        if arg >= 0x80000000:
            arg -= 0x100000000
        if -10000 < arg < 10000:
            return pc + arg * 16
        p = pc + 16
        while p + 16 <= len(self.data):
            if u32(self.data, p) == arg:
                return p
            p += 16
        self.warnings.append(f"label {arg} not found from {pc:#x}")
        return None

    def _compare_cond(self, a, b, c):
        return {
            "type": "compare",
            "lhs": script_operand(a),
            "op": COMPARE_OPS.get(b, f"op{b:#x}"),
            "rhs": script_operand(c),
        }

    def _find_block_end(self, pc: int, op: int):
        depth = 1
        else_off = None
        p = pc + 16
        if op in (OP_IF, OP_IF2):
            while p + 16 <= len(self.data):
                o = u32(self.data, p) & 0xFFFF
                if o in (OP_IF, OP_IF2):
                    depth += 1
                elif o == OP_ELSE:
                    if depth == 1 and else_off is None:
                        else_off = p
                elif o == OP_ENDIF:
                    depth -= 1
                    if depth == 0:
                        return p, else_off
                p += 16
        else:
            while p + 16 <= len(self.data):
                o = u32(self.data, p) & 0xFFFF
                if o in (OP_LOOP, OP_LOOP2):
                    depth += 1
                elif o == OP_LOOP_END:
                    depth -= 1
                    if depth == 0:
                        return p, None
                p += 16
        # Some scripts close an IF/ELSE/IF chain with a single ENDIF.  The
        # game tolerates it; treat the ELSE (or the script end) as the block
        # end so the conditions still attach to the right dialogue.
        self.notes.append(f"unterminated block at {pc:#x}")
        if else_off is not None:
            return else_off, else_off
        p = pc + 16
        while p + 16 <= len(self.data):
            if (u32(self.data, p) & 0xFFFF) in (OP_END, OP_END_DISPATCH, OP_RET):
                return p, None
            p += 16
        return len(self.data) - 16, else_off


def negate(cond: dict[str, Any]) -> dict[str, Any]:
    out = dict(cond)
    out["negated"] = not cond.get("negated", False)
    return out


TWO_RECORD_OPS = {0x2A, 0x2B, 0x2C, 0x3B, 0x44, 0x56}
PARAM_RECORD_OPS = {0x17, 0x2D}
KNOWN_OPS = set(range(0x00, 0x65)) | {10000} | set(range(0x2711, 0x2720))
KNOWN_EXT_OPS = set(range(0x1388, 0x13D0))


# ---------------------------------------------------------------------------
# battle talk table
# ---------------------------------------------------------------------------


def parse_battle_talk_table(data: bytes, off: int) -> list[dict[str, Any]]:
    entries = []
    while off + 16 <= len(data):
        vals = struct.unpack_from("<8h", data, off)
        if vals[0] == -1:
            break
        callback = struct.unpack_from("<I", data, off + 8)[0]
        entries.append(
            {
                "offset": off,
                "flag": vals[0],
                "pilotA": vals[1],
                "pilotB": vals[2],
                "callback": callback if BASE <= callback < BASE + len(data) else None,
                "eventId": vals[6],
            }
        )
        off += 16
    return entries


# ---------------------------------------------------------------------------
# top-level analysis
# ---------------------------------------------------------------------------


def describe_value(v: Any) -> str:
    if v is None:
        return "?"
    if is_const(v):
        n = v[1]
        return f"{n:#x}" if n > 9 else str(n)
    if v[0] == "global":
        return GLOBAL_NAMES.get(v[1], f"[{v[1]:#x}]")
    if v[0] == "call":
        return f"{v[1]:#x}(" + ", ".join(describe_value(a) for a in v[2][:3]) + ")"
    if v[0] == "event":
        return "event"
    return repr(v)


def structure_condition(cond) -> dict[str, Any] | None:
    """Translate a symbolic branch condition into a structured record."""

    opn, a, b = cond
    # normalise: constant on the right
    if is_const(a) and not is_const(b):
        a, b = b, a
        opn = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}.get(opn, opn)
    if not is_const(b):
        return {"type": "raw", "text": f"{describe_value(a)} {opn} {describe_value(b)}"}
    value = b[1]
    if value >= 0x80000000:
        value -= 0x100000000
    if a[0] == "lt" and a[1][0] != "event":
        # (x < n) compared with 0: rewrite as a comparison on x itself
        truth = (opn == "!=") == (value == 0)
        limit = a[2]
        inner = structure_condition(("<" if truth else ">=", a[1], ("const", limit & 0xFFFFFFFF)))
        return inner
    if a[0] == "event":
        return {"type": "event", "op": opn, "value": value}
    if a[0] == "lt" and a[1][0] == "event":
        return None  # jump-table bound check
    if a[0] == "global":
        name = GLOBAL_NAMES.get(a[1])
        if name:
            return {"type": name, "op": opn, "value": value}
        return {"type": "global", "address": a[1], "op": opn, "value": value}
    if a[0] == "call":
        fn, args = a[1], a[2]
        arg0 = const_of(args[0])
        arg1 = const_of(args[1])
        if fn == FN_FLAG_TEST:
            truth = (opn == "!=") == (value == 0)
            return {"type": "flag", "flag": arg0, "value": 1 if truth else 0}
        if fn == FN_GFLAG_TEST:
            truth = (opn == "!=") == (value == 0)
            return {"type": "gflag", "flag": arg0, "value": 1 if truth else 0}
        if fn == FN_UNIT_DESTROYED:
            truth = (opn == "==" and value == 1) or (opn == "!=" and value == 0)
            return {"type": "unit_destroyed", "unit_kind": arg0, "unit": arg1, "value": 1 if truth else 0}
        if fn == FN_IN_BATTLE:
            truth = (opn == "==" and value == 1) or (opn == "!=" and value == 0)
            return {"type": "in_battle", "unit_kind": arg0, "unit": arg1, "value": 1 if truth else 0}
        if fn == FN_COUNT_UNITS:
            return {"type": "unit_count", "kind": arg0, "arg": arg1, "op": opn, "value": value}
        if fn == FN_DESTROYED_QUERY:
            truth = (opn == "==" and value == 1) or (opn == "!=" and value == 0)
            return {"type": "destroyed_query", "kind": arg0, "arg": arg1, "value": 1 if truth else 0}
        if fn == FN_VAR_READ:
            return {"type": "var", "var": arg0, "arg": arg1, "op": opn, "value": value}
        return {"type": "call", "function": fn, "args": [const_of(x) for x in args[:3]], "op": opn, "value": value}
    return {"type": "raw", "text": f"{describe_value(a)} {opn} {value}"}


def structure_action(action) -> dict[str, Any] | None:
    kind = action[0]
    if kind == "run_script":
        ptr = const_of(action[1])
        return {"type": "run_script", "offset": ptr - BASE if ptr and BASE <= ptr < BASE + 0x100000 else None, "address": ptr}
    if kind in ("set_flag", "clear_flag"):
        return {"type": kind, "flag": const_of(action[1])}
    if kind == "battle_talk_table":
        ptr = const_of(action[1])
        return {"type": "battle_talk_table", "offset": ptr - BASE if ptr else None}
    if kind == "spawn_list":
        ptr = const_of(action[1])
        return {"type": "spawn_list", "offset": ptr - BASE if ptr else None}
    if kind == "call":
        return {"type": "call", "function": action[1], "args": [const_of(x) for x in action[2][:3]]}
    if kind == "store":
        return {"type": "store", "address": action[1], "value": const_of(action[2])}
    return None


INTERESTING_ACTIONS = {"run_script", "battle_talk_table", "spawn_list", "set_flag", "clear_flag"}


def analyze_stage(data: bytes, function_address: int) -> dict[str, Any]:
    fn = function_address - BASE
    globals_installed = installed_globals(data, fn)
    dispatcher = globals_installed.get(DISPATCHER_SLOT)
    result: dict[str, Any] = {
        "installed": {f"{k:#x}": f"{v:#x}" for k, v in sorted(globals_installed.items())},
        "triggers": [],
        "scripts": {},
        "battleTalks": [],
        "warnings": [],
    }
    if not dispatcher:
        return result
    code_end = min([v - BASE for v in globals_installed.values() if v > dispatcher] + [len(data)])
    analyzer = HandlerAnalyzer(data, code_end)
    analyzer.run(dispatcher - BASE, {4: ("event",)})
    result["warnings"].extend(analyzer.warnings)
    scripts: dict[int, dict[str, Any]] = {}
    merged: dict[tuple, dict[str, Any]] = {}
    for site, raw_conds, raw_actions in analyzer.triggers:
        actions = [structure_action(a) for a in raw_actions]
        actions = [a for a in actions if a and a["type"] in INTERESTING_ACTIONS]
        conds = [structure_condition(c) for c in raw_conds]
        conds = [c for c in conds if c]
        event = next((c["value"] for c in conds if c["type"] == "event" and c["op"] == "=="), None)
        conds = [c for c in conds if c["type"] != "event"]
        if not actions:
            continue
        key = (event, site, str(actions[-1]))
        entry = merged.get(key)
        if entry is None:
            merged[key] = {"event": event, "site": site, "conds": conds, "actions": actions, "paths": 1}
        else:
            keep = {str(c) for c in conds}
            entry["conds"] = [c for c in entry["conds"] if str(c) in keep]
            entry["paths"] += 1
            if len(actions) < len(entry["actions"]):
                entry["actions"] = actions
    # A flag-only trigger that is merely the prefix of a script-running path
    # (set flag, then run script) is not a separate event.
    script_triggers = [t for t in merged.values() if any(a["type"] in ("run_script", "battle_talk_table") for a in t["actions"])]
    def redundant(trigger):
        flags = {a["flag"] for a in trigger["actions"] if a["type"] in ("set_flag", "clear_flag")}
        conds = {str(c) for c in trigger["conds"]}
        for other in script_triggers:
            other_flags = {a["flag"] for a in other["actions"] if a["type"] in ("set_flag", "clear_flag")}
            if other["event"] == trigger["event"] and flags <= other_flags and conds <= {str(c) for c in other["conds"]}:
                return True
        return False
    for trigger in merged.values():
        if trigger not in script_triggers and redundant(trigger):
            continue
        result["triggers"].append(trigger)
        actions = trigger["actions"]
        for a in actions:
            if a["type"] == "run_script" and a["offset"] is not None and a["offset"] not in scripts:
                scripts[a["offset"]] = walk_script(data, a["offset"])
            if a["type"] == "battle_talk_table" and a["offset"] is not None:
                for entry in parse_battle_talk_table(data, a["offset"]):
                    if entry in result["battleTalks"]:
                        continue
                    entry["callbackScripts"] = []
                    entry["callbackConds"] = []
                    if entry["callback"] is not None:
                        sub = HandlerAnalyzer(data, code_end)
                        sub.run(entry["callback"] - BASE)
                        for _site, raw_conds, raw_actions in sub.triggers:
                            for act in raw_actions:
                                if act[0] == "run_script" and is_const(act[1]):
                                    off = act[1][1] - BASE
                                    if off not in entry["callbackScripts"]:
                                        entry["callbackScripts"].append(off)
                                        entry["callbackConds"].append([c for c in (structure_condition(x) for x in raw_conds) if c])
                                    if off not in scripts:
                                        scripts[off] = walk_script(data, off)
                    result["battleTalks"].append(entry)
    # scripts may call overlay-native functions that run further scripts
    pending = [off for s in scripts.values() for off in s["nativeCalls"]]
    while pending:
        native = pending.pop()
        sub = HandlerAnalyzer(data, code_end)
        for path in sub.run(native - BASE):
            for a in path.actions:
                if a[0] == "run_script" and is_const(a[1]):
                    off = a[1][1] - BASE
                    if off not in scripts:
                        scripts[off] = walk_script(data, off)
                        pending.extend(scripts[off]["nativeCalls"])
    result["deploymentGroups"] = deployment_groups(data, globals_installed)
    for script in scripts.values():
        spawned: list[int] = []
        for kind, value in script["effects"]:
            if kind == "spawn_group" and 0 <= value < len(result["deploymentGroups"]):
                spawned.extend(result["deploymentGroups"][value])
            elif kind == "select_group":
                for index in value:
                    if 0 <= index < len(result["deploymentGroups"]):
                        spawned.extend(result["deploymentGroups"][index])
            elif kind == "spawn_list":
                spawned.extend(spawn_list_pilots(data, value))
        script["spawnedPilots"] = sorted(set(spawned))
    result["tablePilots"] = sorted({p for group in result["deploymentGroups"] for p in group})
    pair_table = globals_installed.get(BATTLE_PAIR_SLOT)
    result["battlePairs"] = []
    if pair_table and BASE < pair_table < BASE + len(data):
        for entry in parse_battle_pair_table(data, pair_table - BASE):
            entry["actionScripts"] = []
            entry["actionConds"] = []
            for fn_key in ("callback", "action"):
                fn = entry.get(fn_key)
                if fn is None:
                    continue
                sub = HandlerAnalyzer(data, code_end)
                sub.run(fn - BASE)
                for _site, raw_conds, raw_actions in sub.triggers:
                    for act in raw_actions:
                        if act[0] == "run_script" and is_const(act[1]):
                            off = act[1][1] - BASE
                            if off not in entry["actionScripts"]:
                                entry["actionScripts"].append(off)
                                entry["actionConds"].append([c for c in (structure_condition(x) for x in raw_conds) if c])
                            if off not in scripts:
                                scripts[off] = walk_script(data, off)
            result["battlePairs"].append(entry)
    result["scripts"] = {f"{k:#x}": v for k, v in sorted(scripts.items())}
    return result


def deployment_groups(data: bytes, installed: dict[int, int]) -> list[list[int]]:
    """Pilot ids of every spawn group (script opcode 0x05 argument).

    ``0x595268`` holds (first record, count) pairs and ``0x595258`` holds
    22-byte placement records whose fifth half-word is the pilot id.
    """

    groups_address = installed.get(DEPLOYMENT_GROUP_SLOT)
    records_address = installed.get(DEPLOYMENT_RECORD_SLOT)
    count_address = installed.get(DEPLOYMENT_COUNT_SLOT)
    if not groups_address or not records_address or not count_address:
        return []
    records_off = records_address - BASE
    count_off = count_address - BASE
    if not (0 <= count_off + 4 <= len(data)):
        return []
    record_count = u32(data, count_off)
    groups: list[list[int]] = []
    off = groups_address - BASE
    while 0 <= off + 8 <= len(data) and len(groups) < 64:
        start, _pad, count, _pad2 = struct.unpack_from("<4H", data, off)
        if count == 0 or start + count > record_count or count > 256:
            break
        pilots = []
        for index in range(start, start + count):
            record_off = records_off + index * 22
            if record_off + 22 > len(data):
                break
            pilot = struct.unpack_from("<H", data, record_off + 8)[0]
            if pilot not in (0xFFFF, 0):
                pilots.append(pilot)
        groups.append(pilots)
        off += 8
    return groups


def spawn_list_pilots(data: bytes, off: int) -> list[int]:
    """Pilot ids in a spawn list consumed by ``FUN_001b0f50`` (opcode 0x0d)."""

    pilots = []
    for _ in range(64):
        if off + 32 > len(data):
            break
        if data[off + 3] == 0xFF:
            break
        pilot = struct.unpack_from("<H", data, off + 0x12)[0]
        if pilot not in (0xFFFF, 0):
            pilots.append(pilot)
        off += 32
    return pilots


def parse_battle_pair_table(data: bytes, off: int) -> list[dict[str, Any]]:
    """Parse the 0x595290 table consumed by FUN_0017bc40.

    Records are 16 bytes: flag, pilot A, pilot B (shorts), a condition
    callback and an action function pointer.  The table ends with flag -1.
    """

    entries = []
    while off + 16 <= len(data):
        flag, pilot_a, pilot_b, _pad = struct.unpack_from("<4h", data, off)
        if flag == -1:
            break
        callback, action = struct.unpack_from("<II", data, off + 8)
        entries.append(
            {
                "offset": off,
                "flag": flag,
                "pilotA": pilot_a,
                "pilotB": pilot_b,
                "callback": callback if BASE <= callback < BASE + len(data) else None,
                "action": action if BASE <= action < BASE + len(data) else None,
            }
        )
        off += 16
    return entries


def walk_script(data: bytes, offset: int) -> dict[str, Any]:
    walker = ScriptWalker(data)
    walker.walk(offset)
    return {
        "dialogues": [
            {
                "eventId": d.event_id,
                "kind": d.kind,
                "pointer": d.pointer,
                "variants": d.variants,
                "conds": d.conds,
                "offset": d.offset,
            }
            for d in walker.dialogues
        ],
        "effects": walker.effects,
        "nativeCalls": walker.native_calls,
        "warnings": walker.warnings,
        "notes": walker.notes,
        "unknownOps": sorted(walker.unknown_ops),
    }


def format_cond(c: dict[str, Any]) -> str:
    t = c["type"]
    neg = "!" if c.get("negated") else ""
    if t == "flag":
        return f"{neg}flag{c['flag']:#x}={c['value']}"
    if t == "gflag":
        return f"{neg}gflag{c['flag']:#x}={c['value']}"
    if t in ("turn", "part", "phase", "route", "turn_counter", "turn_total"):
        return f"{neg}{t}{c['op']}{c['value']}"
    if t == "unit_destroyed":
        return f"{neg}destroyed(k{c['unit_kind']},{c['unit']:#x})={c['value']}"
    if t == "in_battle":
        return f"{neg}in_battle(k{c['unit_kind']},{c['unit']:#x})={c['value']}"
    if t == "unit_count":
        return f"{neg}count(k{c['kind']},{c['arg']}){c['op']}{c['value']}"
    if t == "destroyed_query":
        return f"{neg}destroyed_query(k{c['kind']},{c['arg']})={c['value']}"
    if t == "var":
        return f"{neg}var{c['var']:#x}{c['op']}{c['value']}"
    if t == "compare":
        def opnd(o):
            if o["kind"] == "imm":
                return str(o["value"])
            if o["kind"] == "var":
                return f"var{o['var']:#x}"
            if o["kind"] == "flag":
                return f"flag{o['flag']:#x}"
            if o["kind"] == "gflag":
                return f"gflag{o['flag']:#x}"
            return f"prop{o['var']:#x}({o['arg']:#x})"
        return f"{neg}({opnd(c['lhs'])}{c['op']}{opnd(c['rhs'])})"
    if t == "unit_gone":
        return f"{neg}unit_gone(k{c['unit_kind']},{c['unit']:#x})"
    if t == "call":
        return f"{neg}{c['function']:#x}{tuple(c['args'])}{c['op']}{c['value']}"
    return f"{neg}{c.get('text', t)}"


def report(result: dict[str, Any]) -> str:
    lines = []
    for t in result["triggers"]:
        lines.append(f"event {t['event']}: " + " && ".join(format_cond(c) for c in t["conds"]))
        for a in t["actions"]:
            if a["type"] == "run_script":
                lines.append(f"    run_script @{a['offset']:#x}" if a['offset'] is not None else f"    run_script slps {a['address']:#x}")
            elif a["type"] == "battle_talk_table":
                lines.append(f"    battle_talk_table @{a['offset']:#x}")
            else:
                lines.append(f"    {a}")
    for off, s in result["scripts"].items():
        lines.append(f"script {off}: effects={s['effects']} warn={s['warnings']} unknown={[hex(x) for x in s['unknownOps']]} native={[hex(x) for x in s['nativeCalls']]}")
        for d in s["dialogues"]:
            tag = d["eventId"] if d["kind"] == "battle" else f"{d['kind']}:{d['pointer'] or d['variants']}"
            lines.append(f"    dlg {tag} " + " && ".join(format_cond(c) for c in d["conds"]))
    for e in result["battleTalks"]:
        lines.append(f"battle_talk flag{e['flag']:#x} {e['pilotA']:#x} vs {e['pilotB']:#x} -> event {e['eventId']} cb={e['callback']} cbscripts={[hex(x) for x in e.get('callbackScripts', [])]}")
    for e in result.get("battlePairs", []):
        lines.append(f"battle_pair flag{e['flag']:#x} {e['pilotA']:#x} vs {e['pilotB']:#x} cb={e['callback']} action={e['action']} scripts={[hex(x) for x in e['actionScripts']]}")
    if result["warnings"]:
        lines.append("warnings: " + "; ".join(result["warnings"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# playthrough ordering
# ---------------------------------------------------------------------------

EVENT_KIND_NAMES = {
    2: "phase-start",
    3: "third-phase-start",
    4: "battle-start",
    5: "battle-end",
    6: "unit-action",
    7: "unit-destroyed",
    8: "map-start",
    9: "event-9",
}


def _cond_value(conds, cond_type, op="=="):
    for c in conds:
        if c.get("type") == cond_type and c.get("op") == op and not c.get("negated"):
            return c.get("value")
    return None


def invocation_groups(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten an analysis into dialogue invocation groups.

    Each group is one way the game can start a run of battle dialogue: a
    handler trigger running a script, one pre-battle conversation entry, or
    one scripted duel.  Groups carry the structured conditions and the
    ordered dialogue invocations of the script they run.
    """

    scripts = analysis.get("scripts", {})
    groups: list[dict[str, Any]] = []

    def script_part(offset):
        return scripts.get(f"{offset:#x}") or {"dialogues": [], "effects": [], "spawnedPilots": []}

    for trigger in analysis.get("triggers", []):
        handler_flags = [a["flag"] for a in trigger["actions"] if a["type"] == "set_flag"]
        handler_clears = [a["flag"] for a in trigger["actions"] if a["type"] == "clear_flag"]
        if not any(a["type"] in ("run_script", "battle_talk_table") for a in trigger["actions"]):
            groups.append(
                {
                    "source": "event",
                    "event": trigger["event"],
                    "conds": trigger["conds"],
                    "scriptOffset": None,
                    "externalScript": None,
                    "dialogues": [],
                    "setsFlags": handler_flags,
                    "clearsFlags": handler_clears,
                    "setsPart": None,
                    "spawnedPilots": [],
                }
            )
            continue
        for action in trigger["actions"]:
            if action["type"] == "run_script":
                if action["offset"] is None:
                    groups.append(
                        {
                            "source": "event",
                            "event": trigger["event"],
                            "conds": trigger["conds"],
                            "scriptOffset": None,
                            "externalScript": action["address"],
                            "dialogues": [],
                            "setsFlags": handler_flags,
                            "clearsFlags": handler_clears,
                            "setsPart": None,
                            "spawnedPilots": [],
                        }
                    )
                    continue
                script = script_part(action["offset"])
                effects = script["effects"]
                groups.append(
                    {
                        "source": "event",
                        "event": trigger["event"],
                        "conds": trigger["conds"],
                        "scriptOffset": action["offset"],
                        "externalScript": None,
                        "dialogues": script["dialogues"],
                        "setsFlags": handler_flags + [f for kind, f in effects if kind == "set_flag"],
                        "clearsFlags": handler_clears + [f for kind, f in effects if kind == "clear_flag"],
                        "setsPart": next((n for kind, n in effects if kind == "set_part"), None),
                        "spawnedPilots": list(script.get("spawnedPilots", [])),
                    }
                )
    for entry in analysis.get("battleTalks", []):
        dialogues = []
        if entry["eventId"] is not None and entry["eventId"] >= 0:
            dialogues.append({"eventId": entry["eventId"], "kind": "battle", "pointer": None, "variants": None, "conds": [], "offset": entry["offset"]})
        sets_flags = [entry["flag"]] if entry["flag"] is not None and entry["flag"] >= 0 else []
        sets_part = None
        spawned: list[int] = []
        for off in entry.get("callbackScripts", []):
            script = script_part(off)
            dialogues.extend(script["dialogues"])
            sets_flags.extend(f for kind, f in script["effects"] if kind == "set_flag")
            sets_part = next((n for kind, n in script["effects"] if kind == "set_part"), sets_part)
            spawned.extend(script.get("spawnedPilots", []))
        groups.append(
            {
                "source": "battle-talk",
                "spawnedPilots": spawned,
                "event": 4,
                "conds": [],
                "pilotA": entry["pilotA"],
                "pilotB": entry["pilotB"],
                "flag": entry["flag"],
                "scriptOffset": entry.get("callbackScripts", [None])[0] if entry.get("callbackScripts") else None,
                "externalScript": None,
                "dialogues": dialogues,
                "setsFlags": sets_flags,
                "clearsFlags": [],
                "setsPart": sets_part,
            }
        )
    for entry in analysis.get("battlePairs", []):
        dialogues = []
        sets_flags = [entry["flag"]] if entry["flag"] is not None and entry["flag"] >= 0 else []
        sets_part = None
        conds: list[dict[str, Any]] = []
        spawned = []
        for off, off_conds in zip(entry.get("actionScripts", []), entry.get("actionConds", [])):
            script = script_part(off)
            dialogues.extend(script["dialogues"])
            sets_flags.extend(f for kind, f in script["effects"] if kind == "set_flag")
            sets_part = next((n for kind, n in script["effects"] if kind == "set_part"), sets_part)
            spawned.extend(script.get("spawnedPilots", []))
            if not conds:
                conds = off_conds
        groups.append(
            {
                "source": "battle-pair",
                "spawnedPilots": spawned,
                "event": 4,
                "conds": conds,
                "pilotA": entry["pilotA"],
                "pilotB": entry["pilotB"],
                "flag": entry["flag"],
                "scriptOffset": entry.get("actionScripts", [None])[0] if entry.get("actionScripts") else None,
                "externalScript": None,
                "dialogues": dialogues,
                "setsFlags": sets_flags,
                "clearsFlags": [],
                "setsPart": sets_part,
            }
        )
    return merge_groups(groups)


def merge_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge groups that run the same script from different triggers.

    A script such as "Rand is defeated or turn 4 begins" is reachable from
    several handler paths; the merged group keeps every alternative condition
    list under ``alternatives`` and the first one as ``conds``.
    """

    merged: list[dict[str, Any]] = []
    by_script: dict[int, dict[str, Any]] = {}
    for group in groups:
        group.setdefault("alternatives", [{"event": group["event"], "conds": group["conds"]}])
        offset = group.get("scriptOffset")
        if group["source"] != "event" or offset is None:
            merged.append(group)
            continue
        existing = by_script.get(offset)
        if existing is None:
            by_script[offset] = group
            merged.append(group)
            continue
        existing["alternatives"].append({"event": group["event"], "conds": group["conds"]})
        for flag in group["setsFlags"]:
            if flag not in existing["setsFlags"]:
                existing["setsFlags"].append(flag)
    return merged


def _requires_pilots(group: dict[str, Any], conds) -> list[int]:
    pilots = []
    if group["source"] in ("battle-talk", "battle-pair"):
        pilots.extend(p for p in (group.get("pilotA"), group.get("pilotB")) if p is not None and p >= 0)
    for c in conds:
        if c.get("negated"):
            continue
        if c["type"] in ("unit_destroyed", "in_battle") and c.get("unit_kind") == 2 and c.get("value") == 1:
            pilots.append(c["unit"])
    return pilots


def _group_rank(group: dict[str, Any]) -> tuple:
    return min(_alternative_rank(group, alt["event"], alt["conds"]) for alt in group["alternatives"])


def _alternative_rank(group: dict[str, Any], event, conds) -> tuple:
    turn = _cond_value(conds, "turn")
    source = group["source"]
    if source in ("battle-talk", "battle-pair"):
        rank = 1
    elif event == 8:
        rank = 0
    elif event == 2 and turn == 1:
        rank = 0
    elif event in (2, 3):
        rank = 2
    elif event in (4, 5, 6):
        rank = 4
    elif event == 7:
        rank = 5
        if any(c.get("type") == "unit_count" and c.get("kind") == 5 and c.get("op") in ("==", "<=") and not c.get("negated") for c in conds):
            rank = 6
    else:
        rank = 5
    return (rank, turn if turn is not None else 0, group.get("scriptOffset") or 0)


def ordered_groups(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Order invocation groups along a plausible playthrough.

    The scenario part byte and the stage flags form a dependency graph: a
    trigger that requires ``part == 2`` cannot fire before a script sets part
    2, and a trigger that requires flag N cannot fire before the trigger that
    sets it.  Within what is currently possible, turn-driven events come
    before conversations, which come before destruction and clear events.
    Groups whose prerequisites are never satisfied are appended by rank.
    """

    remaining = invocation_groups(analysis)
    for index, group in enumerate(remaining):
        group["groupIndex"] = index
    ordered: list[dict[str, Any]] = []
    part: int | None = None
    flags: set[int] = set()
    table_pilots = set(analysis.get("tablePilots", []))
    present: set[int] = set()

    def pilot_present(pilot):
        # pilots that never appear in the deployment tables (player units,
        # transformed units) are assumed to be on the map from the start
        return pilot not in table_pilots or pilot in present

    def conds_enabled(conds):
        for c in conds:
            if c.get("negated"):
                continue
            if c["type"] == "part" and c.get("op") == "==":
                if part != c["value"]:
                    return False
            if c["type"] == "flag":
                if c["value"] == 1 and c["flag"] not in flags:
                    return False
                if c["value"] == 0 and c["flag"] in flags:
                    return False
        return True

    def enabled(group):
        return any(
            conds_enabled(alt["conds"])
            and all(pilot_present(p) for p in _requires_pilots(group, alt["conds"]))
            for alt in group["alternatives"]
        )

    while remaining:
        candidates = [g for g in remaining if enabled(g)]
        relaxed = False
        if not candidates:
            candidates = remaining
            relaxed = True
        group = min(candidates, key=_group_rank)
        remaining.remove(group)
        group["order"] = len(ordered)
        group["prerequisitesMet"] = not relaxed
        ordered.append(group)
        for flag in group["setsFlags"]:
            flags.add(flag)
        for flag in group["clearsFlags"]:
            flags.discard(flag)
        if group["setsPart"] is not None:
            part = group["setsPart"]
        present.update(group.get("spawnedPilots", []))
    return ordered


def section_event_order(analysis: dict[str, Any]) -> list[int]:
    """Battle dialogue event ids in first-invocation order."""

    seen: list[int] = []
    for group in ordered_groups(analysis):
        for dialogue in group["dialogues"]:
            ids: list[int] = []
            if dialogue["kind"] == "battle" and dialogue["eventId"] is not None:
                ids.append(dialogue["eventId"])
            elif dialogue["kind"] == "difficulty" and dialogue["variants"]:
                ids.extend(v for _i, v in dialogue["variants"] if v != 0xFF)
            for event_id in ids:
                if event_id not in seen:
                    seen.append(event_id)
    return seen
