"""Make the SP chart's valid nodes visible without changing progress queries.

Both chart tables use flow.bin's initializer. Negative IDs already bypass the
progress lookup (the bundled Z chart); nonnegative IDs use the read-only query
at 0x155040. Override only its boolean result inside this chart initializer.
The 0x46 table terminator, negative-ID path, and shared save query stay intact.
"""
from __future__ import annotations
import hashlib
from srwz.codec import decode_production, reencode_changed_suffix

SITE = 0xD88
BEFORE = bytes.fromhex('2b500200')  # sltu t2, zero, v0
AFTER = bytes.fromhex('01000a24')   # addiu t2, zero, 1
INITIALIZER_SHA256 = '711089a44560f1a01c4f259da6010b0ce84e85ac2401505e776bee70e4e482da'
CONTEXT_START = 0xD6C
CONTEXT = bytes.fromhex('500023860700600401000a64ffff62243c2402001054050c3f2404002b5002000000000068002792')


def patch_flow(flow: bytes) -> bytes:
    if hashlib.sha256(flow[0xB70:0xF50]).hexdigest() != INITIALIZER_SHA256:
        raise ValueError('SP chart initializer function drift')
    if flow[CONTEXT_START:CONTEXT_START+len(CONTEXT)] != CONTEXT:
        raise ValueError('SP chart visibility initializer preimage drift')
    out = bytearray(flow)
    out[SITE:SITE+4] = AFTER
    return bytes(out)


def apply_chart_visibility(stage: bytes, slot: int) -> tuple[bytes, dict]:
    original = decode_production(stage[:slot])
    decoded = patch_flow(original.output)
    encoded = reencode_changed_suffix(stage[:slot], decoded, strategy='rust-fit',
                                      max_output_size=slot, original_result=original)
    if len(encoded) > slot or decode_production(encoded).output != decoded:
        raise ValueError('SP chart repack/readback failed')
    result = encoded + bytes(slot-len(encoded)) + stage[slot:]
    return result, dict(policy='show_all_valid_chart_nodes_without_save_writeback',
        member='DATA/STAGE.BIN', chunk=0, decoded_offset=hex(SITE),
        virtual_address=hex(0x8045F0+SITE), before_hex=BEFORE.hex(), after_hex=AFTER.hex(),
        sp_nodes=21, z_nodes=110, slot_bytes=slot, encoded_bytes=len(encoded),
        decoded_sha256=hashlib.sha256(decoded).hexdigest(),
        outside_chunk_zero_unchanged=result[slot:]==stage[slot:])
