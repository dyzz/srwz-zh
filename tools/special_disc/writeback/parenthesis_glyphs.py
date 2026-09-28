"""Native SP parenthesis pixels, applied after the locked shared font."""

from srwz.codec import decode_production, reencode_changed_suffix
from srwz.font import sha256_bytes
from srwz.native_parentheses import replace_parenthesis_slots
from install_font import sp_offsets, VT1_TABLE, FONT_CHUNK, JAPANESE_FONT_SHA256


def decoded_font(vt1, exe):
    offsets = sp_offsets(exe, VT1_TABLE, len(vt1))
    start, end = offsets[FONT_CHUNK:FONT_CHUNK + 2]
    return start, end, decode_production(vt1[start:end])


def native_font(vt1, exe):
    original = decoded_font(vt1, exe)[2].output
    if sha256_bytes(original) != JAPANESE_FONT_SHA256:
        raise ValueError("native SP parenthesis source font identity drift")
    return original


def apply_parentheses(vt1, exe, original_vt1, original_exe, assignments, codec):
    start, end, before = decoded_font(vt1, exe)
    after, report = replace_parenthesis_slots(
        before.output, native_font(original_vt1, original_exe), assignments)
    if report["changed_glyphs"]:
        packed = reencode_changed_suffix(vt1[start:end], after, **codec,
                                        max_output_size=end-start, original_result=before)
        if len(packed) > end-start or decode_production(packed).output != after:
            raise ValueError("SP parenthesis font slot budget or roundtrip failed")
        vt1 = vt1[:start] + packed + bytes(end-start-len(packed)) + vt1[end:]
    report.update(source_decoded_font_sha256=JAPANESE_FONT_SHA256,
                  decoded_font_sha256=sha256_bytes(after),
                  codes_unchanged=True, renderer_widths_unchanged=True)
    return vt1, report


def verify_parentheses(vt1, exe, original_vt1, original_exe, assignments, report):
    actual = decoded_font(vt1, exe)[2].output
    expected, copies = replace_parenthesis_slots(
        actual, native_font(original_vt1, original_exe), assignments)
    if actual != expected or copies["copies"] != report["copies"]:
        raise ValueError("SP native parenthesis pixels differ in final ISO")
    if (sha256_bytes(actual) != report["decoded_font_sha256"] or
            report["source_decoded_font_sha256"] != JAPANESE_FONT_SHA256):
        raise ValueError("SP native parenthesis font receipt drift")
    return {"all_native_parentheses_byte_exact": True, "copies": copies["copies"]}
