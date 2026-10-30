from __future__ import annotations

import struct
import unittest

from tools.srwz.armsx2_text_probe import (
    decode_line,
    glyph_rows,
    set_text_lines,
    trace_commands,
    unique_rows,
)


CODEBOOK = {0x8FB7: "捷", 0x9798: "利", 0x9141: "“"}


def glyph_hit(frame: int, code: int, x: int, y: int, u: int = 0, v: int = 48) -> dict:
    record = struct.pack("<hhhh", u, v, x, y) + bytes(12)
    return {
        "frame": frame,
        "name": "glyph",
        "mem": {"@70000060:2": struct.pack("<H", code).hex(), "s0:20": record.hex()},
    }


class Armsx2TextProbeTests(unittest.TestCase):
    def test_trace_commands_per_edition(self) -> None:
        self.assertEqual(
            trace_commands("sp"),
            ["trace 13b5f0 name=glyph @70000060:2 s0:20", "trace 2112d0 name=SetText a1:160"],
        )
        self.assertTrue(trace_commands("original")[0].startswith("trace 13ab50 "))
        self.assertTrue(trace_commands("best")[1].startswith("trace 20cd70 "))
        with self.assertRaises(ValueError):
            trace_commands("z2")

    def test_decode_line_handles_breaks_and_unknown_codes(self) -> None:
        data = bytes.fromhex("8fb79798") + b"\n" + bytes.fromhex("9141") + b"A\x01\x00junk"
        self.assertEqual(decode_line(data, CODEBOOK), "捷利\n“A[01]")
        # Codes outside the codebook fall back to CP932, then to a hex marker.
        self.assertEqual(decode_line(bytes.fromhex("82a0"), {}), "あ")

    def test_glyph_rows_group_by_frame_and_y(self) -> None:
        hits = [
            glyph_hit(10, 0x8FB7, -240, 47),
            glyph_hit(10, 0x9798, -219, 47),
            glyph_hit(10, 0x9141, -240, 61),
            {"frame": 10, "name": "SetText", "mem": {"a1:160": "8fb7979800"}},
        ]
        rows = glyph_rows(hits, CODEBOOK)
        self.assertEqual([(r.y, r.text) for r in rows], [(47, "捷利"), (61, "“")])
        self.assertEqual((rows[0].x_start, rows[0].x_end, rows[0].width), (-240, -198, 42))
        self.assertEqual(set_text_lines(hits, CODEBOOK), [(10, "捷利")])

    def test_unique_rows_drop_redraws(self) -> None:
        hits = [glyph_hit(f, 0x8FB7, -240, 47) for f in (10, 11, 12)] + [glyph_hit(13, 0x8FB7, -219, 47)]
        rows = unique_rows(glyph_rows(hits, CODEBOOK))
        self.assertEqual([(r.frame, r.x_start) for r in rows], [(10, -240), (13, -219)])


if __name__ == "__main__":
    unittest.main()
