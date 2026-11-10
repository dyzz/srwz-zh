"""User-approved SRVC target repairs, with fixed chunk/table allocations.

Predicates are shared. Repack their sequences and retarget candidate pointers;
never mutate a shared target predicate in place. Only six candidate semantics
may change. Native Best already fixes the Mazinger candidates. SP has different
native tables/labels and is intentionally outside this main-disc patch.
"""
from __future__ import annotations

import hashlib
import struct

CATEGORY_BYTES = 79 * 4
CANDIDATE_START = 8 + CATEGORY_BYTES
SOURCE_LOCKS = {
    59: '072517f0ca55e1b341bf15da6973f00fcea23cddd289ecaeb75319efeae493ed',
    60: '262fff7b688eaf190c19f21f18bf8b6fa035c1cb8bd1fe216beab560e2cf4b0d',
    335: 'c9b7f421acb5d9d01dd4483f00c37699928d6d666853595206a8accdad81d79b',
}
BEST_MAZINGER_LOCK = '4f7fc3a0f5158683f4265540682caaeebbf032c5f0332174ae70393730ba34e4'
# (old complete condition sequence, replacement complete condition sequence).
# Sara is Z Gundam voice group 104 (0x68), NOT the namesakes at 102/103.
# The Katz stage threshold remains 0x30. Its two pure AND checks are reordered
# to share the stage predicate while fitting the unchanged 29-record table.
FIXES = {
    (59, 130): ('0100020000004500', '0100020000002e00'),
    (59, 131): ('0100020000002e00', '0100020000004500'),
    (60, 162): ('0100010000008100 0201010000003000', '0201010000003000 0100010000006800'),
    (60, 180): ('0100010000008100 0201010000003000', '0201010000003000 0100010000006800'),
    (335, 30): ('0000010106000100 0101000100001001', '0000010106000000 0101000100001001'),
    (335, 59): ('0000010106000100 0101000100001001', '0000010106000000 0101000100001001'),
}


def _sequence(text):
    return tuple(bytes.fromhex(word) for word in text.split())


def _find(haystack, needle):
    for i in range(len(haystack) - len(needle) + 1):
        if haystack[i:i + len(needle)] == needle:
            return i
    return None


def _pack(sequences):
    parts = sorted(set(sequences))
    parts = [p for p in parts if not any(p != q and _find(q, p) is not None for q in parts)]
    while len(parts) > 1:
        best = (-1, 0, 1)
        for i, left in enumerate(parts):
            for j, right in enumerate(parts):
                if i == j:
                    continue
                overlap = max([0] + [n for n in range(1, min(len(left), len(right)) + 1)
                                     if left[-n:] == right[:n]])
                if overlap > best[0]:
                    best = overlap, i, j
        overlap, i, j = best
        merged = parts[i] + parts[j][overlap:]
        parts = [p for k, p in enumerate(parts) if k not in (i, j)] + [merged]
    return parts[0]


def _layout(chunk):
    magic, counts, candidate_count, _ = struct.unpack_from('<4H', chunk)
    if magic != 0x4F00:
        raise ValueError('SRVC target repairs require Original/Best native headers')
    predicate_count, quick_count = counts & 255, counts >> 8
    predicate_start = CANDIDATE_START + candidate_count * 8
    index_start = predicate_start + predicate_count * 8 + quick_count * 4
    if index_start > len(chunk):
        raise ValueError('SRVC selector allocation outside chunk')
    return candidate_count, predicate_count, predicate_start, index_start


def candidate_sequences(chunk):
    count, size, start, _ = _layout(chunk)
    predicates = tuple(chunk[start+i*8:start+(i+1)*8] for i in range(size))
    sequences = {}
    for i in range(count):
        offset, length, _, mode, _, _, _ = struct.unpack_from('<BBBBHBB', chunk, CANDIDATE_START+i*8)
        if mode == 0 and length:
            if offset + length > size:
                raise ValueError('SRVC candidate condition range outside table')
            sequences[i] = predicates[offset:offset+length]
    return sequences


def repair_srvc_selectors(data: bytes, offsets: tuple[int, ...]):
    """Return repaired archive and proof; fail closed on any native table drift.

    Call after text rebuild. Only selector-prefix bytes change; all metadata,
    text indices/pools/tails, category counts, SEG boundaries and size survive.
    Native inputs must be unpatched (calling this twice deliberately fails).
    """
    if len(offsets) <= 336 or offsets[0] != 0 or offsets[-1] != len(data):
        raise ValueError('SRVC archive offsets drift')
    output = bytearray(data)
    proof = []
    for ci in SOURCE_LOCKS:
        lo, hi = offsets[ci:ci+2]
        original = data[lo:hi]
        count, capacity, start, index_start = _layout(original)
        lock = hashlib.sha256(original[2:index_start]).hexdigest()
        if ci == 335 and lock == BEST_MAZINGER_LOCK:
            seqs = candidate_sequences(original)
            for candidate in (30, 59):
                if seqs[candidate] != _sequence(FIXES[(335, candidate)][1]):
                    raise ValueError('Best official Mazinger condition drift')
            proof.append({'chunk': ci, 'status': 'native_best_already_correct', 'changed_candidates': []})
            continue
        if lock != SOURCE_LOCKS[ci]:
            raise ValueError(f'SRVC selector source lock drift: chunk {ci}')
        before = candidate_sequences(original)
        wanted = dict(before)
        changed = []
        for (chunk_id, candidate), (old, new) in FIXES.items():
            if chunk_id != ci:
                continue
            if before.get(candidate) != _sequence(old):
                raise ValueError(f'SRVC target condition drift: {ci}/{candidate}')
            wanted[candidate] = _sequence(new)
            changed.append(candidate)
        packed = _pack(tuple(wanted.values()))
        if len(packed) > capacity:
            raise ValueError(f'SRVC repaired predicates exceed allocation: {ci}')
        result = bytearray(original)
        result[start:start+capacity*8] = b''.join(packed) + bytes((capacity-len(packed))*8)
        for candidate, seq in wanted.items():
            new_start = _find(packed, seq)
            if new_start is None or new_start > 255:
                raise ValueError('SRVC repacked predicate sequence missing')
            result[CANDIDATE_START+candidate*8] = new_start
        after = candidate_sequences(bytes(result))
        if after != wanted:
            raise ValueError('SRVC per-candidate semantic readback mismatch')
        if result[:CANDIDATE_START] != original[:CANDIDATE_START] or result[start+capacity*8:] != original[start+capacity*8:]:
            raise ValueError('SRVC non-selector bytes changed')
        for candidate in range(count):
            pos = CANDIDATE_START+candidate*8
            if result[pos+1:pos+8] != original[pos+1:pos+8]:
                raise ValueError('SRVC weight/mode/text binding changed')
            if candidate not in before and result[pos] != original[pos]:
                raise ValueError('SRVC quick/unconditional selector changed')
        output[lo:hi] = result
        proof.append({'chunk': ci, 'status': 'repaired', 'changed_candidates': changed,
                      'all_other_condition_sequences_preserved': True,
                      'predicate_capacity': capacity, 'used_predicates': len(packed),
                      'prefix_before_sha256': lock,
                      'prefix_after_sha256': hashlib.sha256(result[2:index_start]).hexdigest()})
    return bytes(output), {'repairs': proof, 'archive_size_preserved': len(output) == len(data),
                           'text_and_metadata_preserved': True}
