"""Execute emitted MIPS bytes against name records and guarded output buffers."""
import struct
import unittest

from tools.srwz.library_protagonist_names import (
    EDITIONS, FILE_TO_VIRTUAL, FUNCTION_SIZE, LibraryNameError,
    apply_library_protagonist_names, formatter_bytes,
)


def run_mips(memory, registers, pc, stop):
    """Independent interpreter for the integer MIPS subset used by the shim.

    Branches and JAL/JR execute their delay slot. Unknown instructions and
    unterminated loops fail, rather than interpreting the intended algorithm.
    """
    pending = None
    for _ in range(10000):
        if pc == stop:
            return
        word = int.from_bytes(memory[pc:pc + 4], 'little')
        op, rs, rt, rd = word >> 26, (word >> 21) & 31, (word >> 16) & 31, (word >> 11) & 31
        imm = word & 65535
        signed = imm - 65536 if imm & 32768 else imm
        branch = None
        if op == 0:
            fn = word & 63
            if fn == 0:
                registers[rd] = registers[rt] << ((word >> 6) & 31) & 0xFFFFFFFF
            elif fn == 0x21:
                registers[rd] = (registers[rs] + registers[rt]) & 0xFFFFFFFF
            elif fn == 0x23:
                registers[rd] = (registers[rs] - registers[rt]) & 0xFFFFFFFF
            elif fn == 0x24:
                registers[rd] = registers[rs] & registers[rt]
            elif fn == 0x2B:
                registers[rd] = int(registers[rs] < registers[rt])
            elif fn == 8:
                branch = registers[rs]
            else:
                raise AssertionError(f'unsupported R instruction: {word:08x}')
        elif op == 9:
            registers[rt] = (registers[rs] + signed) & 0xFFFFFFFF
        elif op == 11:
            registers[rt] = int(registers[rs] < (signed & 0xFFFFFFFF))
        elif op == 15:
            registers[rt] = imm << 16
        elif op == 13:
            registers[rt] = registers[rs] | imm
        elif op in (4, 5):
            equal = registers[rs] == registers[rt]
            if equal == (op == 4):
                branch = pc + 4 + signed * 4
        elif op == 3:
            registers[31] = pc + 8
            branch = ((pc + 4) & 0xF0000000) | ((word & 0x3FFFFFF) << 2)
        elif op in (35, 36, 37, 55, 40, 41, 43, 63):
            size = {35: 4, 36: 1, 37: 2, 55: 8, 40: 1, 41: 2, 43: 4, 63: 8}[op]
            address = registers[rs] + signed
            if not 0 <= address <= len(memory) - size:
                raise AssertionError('MIPS memory access out of range')
            if op in (35, 36, 37, 55):
                registers[rt] = int.from_bytes(memory[address:address + size], 'little')
            else:
                memory[address:address + size] = (registers[rt] & ((1 << (8 * size)) - 1)).to_bytes(size, 'little')
        else:
            raise AssertionError(f'unsupported instruction: {word:08x}')
        registers[0] = 0
        pc, pending = (pending if pending is not None else pc + 4), branch
    raise AssertionError('MIPS instruction limit exceeded')


CN = {
    'rand': bytes.fromhex('909e9270'),
    'travis': bytes.fromhex('93c19d6695cf8e7a'),
    'setsuko': bytes.fromhex('94cd8e71'),
    'ohara': bytes.fromhex('8fac8cb4'),
    'dot': bytes.fromhex('904b'),
}
JP = {key: value.encode('cp932') for key, value in
      [('rand', 'ランド'), ('travis', 'トラビス'), ('setsuko', 'セツコ'), ('ohara', 'オハラ')]}


class LibraryProtagonistNamesTests(unittest.TestCase):
    def execute(self, edition, route, fields, *, recognized=True):
        spec = EDITIONS[edition]
        memory = bytearray(0x2000000)
        start = spec['offset'] + FILE_TO_VIRTUAL
        memory[start:start + FUNCTION_SIZE] = formatter_bytes(edition)
        full_names = [CN['rand'] + CN['dot'] + CN['travis'], CN['ohara'] + CN['setsuko']]
        for index, value in enumerate(full_names):
            pointer = 0x450000 + index * 64
            struct.pack_into('<I', memory, spec['identity_table'] + index * 4, pointer)
            memory[pointer:pointer + len(value) + 1] = value + b'\0'
        # Actual ZKAN CHFN is followed immediately by the next tagged field.
        # It must match the ELF C-string identity without requiring CHFN NUL.
        source_name = 0x450200
        raw_name = full_names[route] + b'CHNN\x07\0\0\0'
        memory[source_name:source_name + len(raw_name)] = raw_name
        for offset, name in [(0, 'rand'), (8, 'travis'), (24, 'setsuko'), (32, 'ohara')]:
            pointer = spec['default_names'] + offset
            memory[pointer:pointer + len(CN[name]) + 1] = CN[name] + b'\0'
        pilot = spec['pilot_table'] + [713, 702][route] * 176
        for offset, capacity, value in zip([2, 23, 46], [21, 23, 23], fields):
            self.assertLess(len(value), capacity)
            memory[pilot + offset:pilot + offset + capacity] = (value + b'\0').ljust(capacity, b'\xBA')
        # Arbitrary legacy order flags must not change either protagonist's order.
        memory[0x58B000:0x58C000] = b'\xFF' * 0x1000
        title, nickname, lengths, stack, stop = 0x1200020, 0x12000A0, 0x12000D0, 0x1000000, 0x1400000
        memory[title - 16:lengths + 16] = b'\xCD' * (lengths + 32 - title)
        memory[0x450100:0x450107] = b'NPC\0xxx'
        registers = [i * 0x10001 for i in range(32)]
        registers[0] = 0
        registers[4] = source_name if recognized else 0x450100
        registers[6:10] = [title, lengths, nickname, lengths + 4]
        registers[29], registers[31] = stack, stop
        saved_registers = registers[16:24] + [registers[28], registers[30]]
        source_record = bytes(memory[pilot:pilot + 176])
        before = bytes(memory)
        run_mips(memory, registers, start, stop)
        self.assertEqual(registers[29], stack)
        self.assertEqual(registers[16:24] + [registers[28], registers[30]], saved_registers)
        self.assertEqual(memory[pilot:pilot + 176], source_record)
        valid = bool(fields[0] and (not route or fields[1] or fields[2]))
        self.assertEqual(registers[2], int(recognized and valid))
        if not recognized:
            self.assertEqual(memory[title - 16:lengths + 16], before[title - 16:lengths + 16])
        else:
            for address, limit in [(title, 72), (nickname, 24)]:
                size = memory[address:address + limit].index(0)
                self.assertEqual(memory[address + size + 1:address + limit], before[address + size + 1:address + limit])
            self.assertEqual(memory[title - 16:title], b'\xCD' * 16)
            self.assertEqual(memory[title + 72:nickname], before[title + 72:nickname])
            self.assertEqual(memory[nickname + 24:lengths], before[nickname + 24:lengths])
            self.assertEqual(memory[lengths + 8:lengths + 16], before[lengths + 8:lengths + 16])
        result = None
        if recognized:
            title_size, nickname_size = struct.unpack_from('<II', memory, lengths)
            self.assertLess(title_size, 72)
            self.assertLess(nickname_size, 24)
            self.assertEqual(memory[title + title_size], 0)
            self.assertEqual(memory[nickname + nickname_size], 0)
            result = bytes(memory[title:title + title_size]), bytes(memory[nickname:nickname + nickname_size])
        # Restore only authorized destinations; every other byte must be exact.
        for lo, hi in [(stack - 48, stack), (title, title + 72),
                       (nickname, nickname + 24), (lengths, lengths + 8)]:
            memory[lo:hi] = before[lo:hi]
        self.assertEqual(memory, before)
        return result

    def test_exact_japanese_and_chinese_defaults_in_both_editions(self):
        for edition in EDITIONS:
            for route, given, family in [(0, 'rand', 'travis'), (1, 'setsuko', 'ohara')]:
                expected = CN[family] + CN[given] if route else CN[given] + CN['dot'] + CN[family]
                for language in [JP, CN]:
                    with self.subTest(edition=edition, route=route, language=language is JP):
                        self.assertEqual(self.execute(edition, route, [language[given], language[family], language[given]]),
                                         (expected, CN[given]))

    def test_custom_names_and_default_prefixes_are_preserved(self):
        for edition in EDITIONS:
            for route in [0, 1]:
                fields = [JP['setsuko'] + '改'.encode('cp932'), b'CUSTOM-FAMILY', b'CUSTOM-GIVEN']
                expected = fields[1] + fields[2] if route else fields[2] + CN['dot'] + fields[1]
                self.assertEqual(self.execute(edition, route, fields), (expected, fields[0]))

    def test_mixed_custom_and_japanese_defaults_normalize_independently(self):
        for edition in EDITIONS:
            self.assertEqual(self.execute(edition, 1, [b'NICK', JP['ohara'], b'GIVEN']),
                             (CN['ohara'] + b'GIVEN', b'NICK'))
            self.assertEqual(self.execute(edition, 0, [JP['rand'], b'FAMILY', JP['rand']]),
                             (CN['rand'] + CN['dot'] + b'FAMILY', CN['rand']))

    def test_non_protagonist_falls_back_without_output_writes(self):
        for edition in EDITIONS:
            self.execute(edition, 0, [b'N', b'F', b'G'], recognized=False)

    def test_maximum_length_custom_fields_and_empty_fallback(self):
        fields = [b'\x82\x60' * 10, b'\x82\x61' * 11, b'\x82\x62' * 11]
        for edition in EDITIONS:
            self.assertEqual(self.execute(edition, 0, fields),
                             (fields[2] + CN['dot'] + fields[1], fields[0]))
            self.assertEqual(self.execute(edition, 1, fields),
                             (fields[1] + fields[2], fields[0]))
            self.assertEqual(self.execute(edition, 1, [b'N', b'', b'']), (b'', b'N'))
            self.assertEqual(self.execute(edition, 0, [b'', b'F', b'G']),
                             (b'G' + CN['dot'] + b'F', b''))

    def test_patch_is_idempotent_and_unknown_bytes_fail_closed(self):
        for edition, spec in EDITIONS.items():
            source = bytearray(spec['offset'] + FUNCTION_SIZE + 16)
            patch = formatter_bytes(edition)
            source[spec['offset']:spec['offset'] + FUNCTION_SIZE] = patch
            output, report = apply_library_protagonist_names(bytes(source), edition)
            self.assertEqual(output, source)
            self.assertTrue(report['already_patched'])
            self.assertEqual(report['changed_byte_count'], 0)
            source[spec['offset'] + 4] ^= 1
            with self.assertRaisesRegex(LibraryNameError, 'preimage drift'):
                apply_library_protagonist_names(bytes(source), edition)
        with self.assertRaisesRegex(LibraryNameError, 'unknown edition'):
            formatter_bytes('other')


if __name__ == '__main__':
    unittest.main()
