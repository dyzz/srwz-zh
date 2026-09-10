"""Edition-bound LIBRARY name formatter; normalize defaults without save writes.

The only caller supplies CHFN and two output buffers. Retail recognizes the two
protagonists, then replaces both names from the live pilot table. Keep that
custom-name behavior, but normalize exact Japanese defaults per field and use
the character's Chinese full-name order. The replacement fits the original
function allocation, uses only caller-saved registers, and writes only the
caller's buffers/lengths and its own stack frame.
"""
from __future__ import annotations

import hashlib
import struct


class LibraryNameError(ValueError):
    pass


FILE_TO_VIRTUAL = 0xFE580
FUNCTION_SIZE = 0x230
EDITIONS = {
    "original": {
        "offset": 0x125F40, "identity_table": 0x41FC50,
        "pilot_table": 0x6D8960, "default_names": 0x4399C0,
        "sha256": "1ec9c979bb450d1bfe7dc4700be845c0dabbef3c211f3f3881ee5de9f57c9b7d",
    },
    "best": {
        "offset": 0x126300, "identity_table": 0x420480,
        "pilot_table": 0x6D9160, "default_names": 0x43A1B0,
        "sha256": "86b68e07cea60aa6100ce1068a1d98bcc013c6bc1a092cd63558d2a779ed3689",
    },
}


class _Code:
    """Small fixed MIPS instruction emitter with checked label relocations."""
    def __init__(self, address):
        self.address, self.words, self.labels, self.fixups = address, [], {}, []

    def mark(self, label):
        if label in self.labels:
            raise LibraryNameError(f"duplicate label: {label}")
        self.labels[label] = self.address + len(self.words) * 4

    def i(self, opcode, rt, rs, immediate):
        self.words.append(opcode << 26 | rs << 21 | rt << 16 | (immediate & 0xFFFF))

    def r(self, function, rd, rs=0, rt=0, shift=0):
        self.words.append(rs << 21 | rt << 16 | rd << 11 | shift << 6 | function)

    def move(self, target, source):
        self.r(0x21, target, source)  # addu

    def nop(self):
        self.words.append(0)

    def branch(self, label, rs=0, rt=0, opcode=4):
        self.fixups.append((len(self.words), "branch", label))
        self.i(opcode, rt, rs, 0)

    def call(self, label):
        self.fixups.append((len(self.words), "call", label))
        self.words.append(3 << 26)

    def address_to(self, reg, address):
        if isinstance(address, str):
            self.fixups.append((len(self.words), "address", address))
            address = 0
        self.i(15, reg, 0, address >> 16)
        self.i(13, reg, reg, address)

    def pointer(self, address):
        if isinstance(address, str):
            self.fixups.append((len(self.words), "pointer", address))
            address = 0
        self.words.append(address)

    def string(self, label, text):
        self.mark(label)
        raw = text.encode("cp932") + b"\0"
        raw += bytes(-len(raw) % 4)
        self.words.extend(struct.unpack("<" + "I" * (len(raw) // 4), raw))

    def finish(self):
        for index, kind, label in self.fixups:
            target = self.labels[label]
            if kind == "branch":
                delta = (target - (self.address + index * 4 + 4)) // 4
                if not -32768 <= delta < 32768:
                    raise LibraryNameError("branch out of range")
                self.words[index] |= delta & 0xFFFF
            elif kind == "call":
                if target >> 28 != (self.address + index * 4 + 4) >> 28:
                    raise LibraryNameError("call out of range")
                self.words[index] |= (target >> 2) & 0x3FFFFFF
            elif kind == "address":
                self.words[index] |= target >> 16
                self.words[index + 1] |= target & 0xFFFF
            else:
                self.words[index] = target
        raw = struct.pack("<" + "I" * len(self.words), *self.words)
        if len(raw) > FUNCTION_SIZE:
            raise LibraryNameError(f"formatter exceeds retail allocation: {len(raw)}")
        return raw.ljust(FUNCTION_SIZE, b"\0")


def formatter_bytes(edition: str) -> bytes:
    try:
        spec = EDITIONS[edition]
    except KeyError as error:
        raise LibraryNameError(f"unknown edition: {edition}") from error
    # Registers: v0=2, v1=3, a0..a3=4..7, t0..t7=8..15, sp=29, ra=31.
    # Stack: title/length/nickname/length at 0/4/8/12, ra at 16,
    # pilot pointer/default pair table/route at 24/28/32.
    c = _Code(spec["offset"] + FILE_TO_VIRTUAL)
    c.i(9, 29, 29, -48)
    for reg, offset in [(6, 0), (7, 4), (8, 8), (9, 12)]:
        c.i(43, reg, 29, offset)
    c.i(63, 31, 29, 16)  # sd ra
    c.move(14, 4)
    c.address_to(12, spec["identity_table"])
    c.move(15, 0)
    c.mark("identity")
    c.i(35, 5, 12, 0)
    c.move(4, 14)
    c.mark("identity_byte")
    # CHFN is length-delimited ZKAN data, not a C string. Retail compares
    # strlen(default) bytes; only the ELF identity string supplies a terminator.
    c.i(36, 11, 5, 0)
    c.branch("matched", 11)
    c.nop()
    c.i(36, 10, 4, 0)
    c.branch("next_identity", 10, 11, 5)
    c.i(9, 4, 4, 1)
    c.branch("identity_byte")
    c.i(9, 5, 5, 1)
    c.mark("next_identity")
    c.i(9, 15, 15, 1)
    c.i(11, 10, 15, 2)
    c.branch("identity", 10, 0, 5)
    c.i(9, 12, 12, 4)
    c.branch("return")
    c.move(2, 0)

    c.mark("matched")
    c.i(43, 15, 29, 32)
    c.i(9, 3, 0, 713)
    c.branch("pilot_index", 15)
    c.nop()
    c.i(9, 3, 0, 702)
    c.mark("pilot_index")
    c.r(0, 10, rt=3, shift=2)
    c.r(0x21, 10, 10, 3)
    c.r(0, 10, rt=10, shift=1)
    c.r(0x21, 10, 10, 3)
    c.r(0, 10, rt=10, shift=4)
    c.address_to(3, spec["pilot_table"])
    c.r(0x21, 3, 3, 10)
    c.i(43, 3, 29, 24)
    c.address_to(12, "defaults")
    c.r(0, 10, rt=15, shift=4)
    c.r(0x21, 12, 12, 10)
    c.i(43, 12, 29, 28)
    c.i(9, 10, 0, 46)
    c.branch("first", 15)
    c.nop()
    c.i(9, 10, 0, 23)
    c.i(9, 12, 12, 8)
    c.mark("first")
    c.r(0x21, 5, 3, 10)
    c.i(35, 4, 29, 0)
    c.i(35, 6, 12, 0)
    c.call("normalized_copy")
    c.i(35, 7, 12, 4)

    c.i(35, 15, 29, 32)
    c.i(35, 12, 29, 28)
    c.i(35, 5, 29, 24)
    c.branch("male_second", 15)
    c.move(4, 2)
    c.i(9, 5, 5, 46)
    c.branch("second")
    c.nop()
    c.mark("male_second")
    # Fetch the existing translated separator; do not embed a font assignment.
    c.address_to(10, spec["identity_table"])
    c.i(35, 10, 10, 0)  # male default full name
    c.i(37, 10, 10, 4)  # two Chinese glyphs (兰德), followed by the middle dot
    c.i(41, 10, 4, 0)
    c.i(9, 4, 4, 2)
    c.i(9, 5, 5, 23)
    c.i(9, 12, 12, 8)
    c.mark("second")
    c.i(35, 6, 12, 0)
    c.call("normalized_copy")
    c.i(35, 7, 12, 4)
    c.i(35, 10, 29, 0)
    c.r(0x23, 2, 2, 10)
    c.i(35, 11, 29, 4)
    c.i(43, 2, 11, 0)

    c.i(35, 4, 29, 8)
    c.i(35, 5, 29, 24)
    c.i(9, 5, 5, 2)
    c.i(35, 12, 29, 28)
    c.i(35, 6, 12, 0)
    c.call("normalized_copy")
    c.i(35, 7, 12, 4)
    c.i(35, 10, 29, 8)
    c.r(0x23, 2, 2, 10)
    c.i(35, 11, 29, 12)
    c.i(43, 2, 11, 0)
    c.r(0x2B, 2, 0, 2)  # retail falls back when either output is empty
    c.i(35, 10, 29, 4)
    c.i(35, 10, 10, 0)
    c.r(0x2B, 10, 0, 10)
    c.r(0x24, 2, 2, 10)
    c.mark("return")
    c.i(55, 31, 29, 16)  # ld ra
    c.r(8, 0, 31)
    c.i(9, 29, 29, 48)

    c.mark("normalized_copy")
    c.move(10, 5)
    c.mark("compare_default")
    c.i(36, 11, 10, 0)
    c.i(36, 12, 6, 0)
    c.branch("copy", 11, 12, 5)
    c.nop()
    c.branch("use_chinese", 11)
    c.i(9, 10, 10, 1)
    c.branch("compare_default")
    c.i(9, 6, 6, 1)
    c.mark("use_chinese")
    c.move(5, 7)
    c.mark("copy")
    c.i(36, 11, 5, 0)
    c.i(40, 11, 4, 0)
    c.branch("copied", 11)
    c.i(9, 5, 5, 1)
    c.branch("copy")
    c.i(9, 4, 4, 1)
    c.mark("copied")
    c.r(8, 0, 31)
    c.move(2, 4)

    c.mark("defaults")
    names = spec["default_names"]
    for japanese, target in [("rand", names), ("travis", names + 8),
                             ("setsuko", names + 24), ("ohara", names + 32)]:
        c.pointer(japanese)
        c.pointer(target)
    for label, value in [("rand", "ランド"), ("travis", "トラビス"),
                         ("setsuko", "セツコ"), ("ohara", "オハラ")]:
        c.string(label, value)
    return c.finish()


def apply_library_protagonist_names(executable: bytes, edition="original"):
    replacement = formatter_bytes(edition)
    spec = EDITIONS[edition]
    start, end = spec["offset"], spec["offset"] + FUNCTION_SIZE
    observed = executable[start:end]
    observed_hash = hashlib.sha256(observed).hexdigest()
    if observed != replacement and observed_hash != spec["sha256"]:
        raise LibraryNameError(f"{edition}: LIBRARY name formatter preimage drift")
    output = executable[:start] + replacement + executable[end:]
    return output, {
        "policy": "preserve_custom_names_normalize_exact_japanese_defaults_and_chinese_order",
        "edition": edition, "file_offset": f"0x{start:X}",
        "virtual_address": f"0x{start + FILE_TO_VIRTUAL:X}",
        "allocation_size": FUNCTION_SIZE,
        "original_sha256": spec["sha256"],
        "output_sha256": hashlib.sha256(replacement).hexdigest(),
        "changed_byte_count": sum(a != b for a, b in zip(observed, replacement)),
        "already_patched": observed == replacement,
        "executable_size_preserved": len(output) == len(executable),
        "save_writeback": False,
    }
