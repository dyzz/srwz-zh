"""Strict clean-room decoder for the SRWZ LZSS byte stream.

The format names in this module deliberately distinguish observed structure
from unknown header semantics.  In particular, the coded integer following
the flags is retained as ``header_unknown_1`` rather than assigned a guessed
meaning.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import tempfile
from array import array
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path
from typing import Callable, Deque, Dict, Mapping, Optional, Union

from .codec_contract import (
    CodedInteger,
    DecodeResult,
    SrwzCodecError,
    SrwzEncodeError,
)


DEFAULT_MAX_OUTPUT_SIZE = 256 * 1024 * 1024
DEFAULT_MAX_CODED_INTEGER_BYTES = 10
DEFAULT_MAX_TOKENS = 10_000_000
DEFAULT_MAX_MATCH_CHAIN = 64
DEFAULT_MIN_MATCH_LENGTH = 3
MAXIMUM_MATCH_CHAIN = 0xFFFF
MAXIMUM_MATCH_LENGTH = 0xFFFFFF
MAXIMUM_LAZY_BIASES = tuple(range(9))
MAXIMUM_LEGACY_PORTFOLIO_LIMIT = 64 * 1024
MAX_WINDOW_EXPONENT = 23
MIN_WINDOW_EXPONENT = 8

BytesLike = Union[bytes, bytearray, memoryview]
TraceEvent = Mapping[str, object]
TraceSink = Callable[[TraceEvent], None]


class ByteReader:
    """A byte reader that turns every out-of-range access into a codec error."""

    def __init__(self, data: BytesLike):
        self._data = memoryview(data).cast("B")
        self._offset = 0

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def remaining(self) -> int:
        return len(self._data) - self._offset

    def read_byte(self, context: str) -> int:
        if self._offset >= len(self._data):
            raise SrwzCodecError(f"truncated {context}", offset=self._offset)
        value = self._data[self._offset]
        self._offset += 1
        return int(value)

    def read_bytes(self, count: int, context: str) -> bytes:
        if count < 0:
            raise ValueError("byte count must be non-negative")
        end = self._offset + count
        if end > len(self._data):
            raise SrwzCodecError(f"truncated {context}", offset=self._offset)
        value = self._data[self._offset:end].tobytes()
        self._offset = end
        return value


def read_coded_integer(
    reader: ByteReader,
    *,
    initial_value: int = 0,
    max_bytes: int = DEFAULT_MAX_CODED_INTEGER_BYTES,
    context: str = "coded integer",
) -> CodedInteger:
    """Read one SRWZ coded integer, optionally continuing from a seed value."""

    if initial_value < 0:
        raise ValueError("coded integer initial value must be non-negative")
    if max_bytes <= 0:
        raise ValueError("coded integer max_bytes must be positive")

    start = reader.offset
    value = initial_value
    for _ in range(max_bytes):
        current = reader.read_byte(context)
        value = (value << 7) | (current >> 1)
        if current & 1:
            return CodedInteger(value=value, start=start, end=reader.offset)

    raise SrwzCodecError(
        f"{context} exceeds {max_bytes}-byte limit",
        offset=reader.offset,
    )


def encode_coded_integer(value: int) -> bytes:
    """Encode one non-negative SRWZ big-endian seven-bit integer."""

    if value < 0:
        raise ValueError("coded integer value must be non-negative")

    groups = [value & 0x7F]
    value >>= 7
    while value:
        groups.append(value & 0x7F)
        value >>= 7
    groups.reverse()
    return bytes(
        (group << 1) | (1 if index == len(groups) - 1 else 0)
        for index, group in enumerate(groups)
    )


def _emit(trace_sink: Optional[TraceSink], event: TraceEvent) -> None:
    if trace_sink is not None:
        trace_sink(event)


def _uses_conditional_header_value(flags: int, window_size: int, size: int) -> bool:
    """Mirror the statically observed header branch without naming its field."""

    if not flags & 0x40:
        return False
    return window_size <= size or (flags & 0x21) != 1


def flags_for_size(size: int) -> int:
    """Choose the smallest observed odd flags value whose window fits size."""

    if size < 0:
        raise ValueError("size must be non-negative")
    exponent = max(
        MIN_WINDOW_EXPONENT,
        max(size - 1, 0).bit_length(),
    )
    exponent = min(exponent, MAX_WINDOW_EXPONENT)
    return ((exponent - MIN_WINDOW_EXPONENT) << 1) | 1


def _window_size_from_flags(flags: int) -> int:
    if flags < 0:
        raise ValueError("flags must be non-negative")
    return 1 << (((flags >> 1) & 0x0F) + MIN_WINDOW_EXPONENT)


def _encode_header(
    size: int,
    flags: int,
    *,
    header_unknown_0: Optional[int],
    header_unknown_1: int,
) -> bytes:
    window_size = _window_size_from_flags(flags)
    uses_conditional = _uses_conditional_header_value(
        flags,
        window_size,
        size,
    )
    if uses_conditional and header_unknown_0 is None:
        raise ValueError(
            "flags require header_unknown_0 for this output size"
        )
    if not uses_conditional and header_unknown_0 is not None:
        raise ValueError(
            "header_unknown_0 was supplied but flags do not encode it"
        )
    if header_unknown_1 < 0:
        raise ValueError("header_unknown_1 must be non-negative")

    output = bytearray()
    output.extend(encode_coded_integer(size))
    output.extend(encode_coded_integer(flags))
    if uses_conditional:
        output.extend(encode_coded_integer(header_unknown_0))
    output.extend(encode_coded_integer(header_unknown_1))
    return bytes(output)


def _distance_encoding(
    distance: int,
    *,
    compact_seed: bool,
) -> tuple[int, bytes]:
    """Return the token distance bits and exact coded-integer extension."""

    if distance <= 0:
        raise ValueError("match distance must be positive")
    distance_value = distance - 1
    if distance_value <= 7:
        return (distance_value << 1) | 1, b""

    encoded = encode_coded_integer(distance_value)
    if (
        compact_seed
        and len(encoded) > 1
        and encoded[0] >> 1 < 8
    ):
        # The decoder continues the coded integer from the token's three-bit
        # seed. The DLL CIL and every eligible original COMPDATA token use
        # this shorter representation.
        return (encoded[0] >> 1) << 1, encoded[1:]
    return 0, encoded


def _encoded_block_size(
    literals: bytes,
    matches,
    *,
    compact_distance_seed: bool,
) -> int:
    """Calculate the real serialized cost of one block in bytes."""

    literal_count = len(literals)
    match_count = len(matches)
    size = 1 + literal_count
    if literal_count > 0x0F:
        size += len(encode_coded_integer(literal_count))
    if match_count == 0 or match_count > 0x0F:
        size += len(encode_coded_integer(match_count))
    for distance, length in matches:
        _, distance_extension = _distance_encoding(
            distance,
            compact_seed=compact_distance_seed,
        )
        length_value = length - 1
        size += 1 + len(distance_extension)
        if not 1 <= length_value <= 0x0F:
            size += len(encode_coded_integer(length_value))
    return size


def _encode_block(
    literals: bytes,
    matches,
    *,
    compact_distance_seed: bool = False,
) -> bytes:
    literal_count = len(literals)
    match_count = len(matches)
    if literal_count == 0:
        raise ValueError(
            "SRWZ game-compatible blocks require at least one literal byte"
        )
    literal_nibble = literal_count if 0 < literal_count <= 0x0F else 0
    match_nibble = match_count if 0 < match_count <= 0x0F else 0
    output = bytearray([(match_nibble << 4) | literal_nibble])
    if literal_nibble == 0:
        output.extend(encode_coded_integer(literal_count))
    if match_nibble == 0:
        output.extend(encode_coded_integer(match_count))
    output.extend(literals)

    for distance, length in matches:
        if length <= 0:
            raise ValueError("match length must be positive")

        distance_bits, distance_extension = _distance_encoding(
            distance,
            compact_seed=compact_distance_seed,
        )

        length_value = length - 1
        if 1 <= length_value <= 0x0F:
            length_bits = length_value << 4
            length_extension = b""
        else:
            length_bits = 0
            length_extension = encode_coded_integer(length_value)

        output.append(length_bits | distance_bits)
        output.extend(distance_extension)
        output.extend(length_extension)

    expected_size = _encoded_block_size(
        literals,
        matches,
        compact_distance_seed=compact_distance_seed,
    )
    if len(output) != expected_size:
        raise AssertionError("encoded block cost calculation drift")
    return bytes(output)


def _literal_payload(data: bytes) -> bytes:
    if not data:
        return b""
    return _encode_block(data, ())


def _greedy_payload(
    data: bytes,
    *,
    window_size: int,
    min_match_length: int,
    max_match_chain: int,
    prefix_size: int = 0,
    lazy_matching: bool = False,
    compact_distance_seed: bool = False,
) -> bytes:
    if not data or prefix_size == len(data):
        return b""
    if min_match_length < 2:
        raise ValueError("min_match_length must be at least 2")
    if max_match_chain <= 0:
        raise ValueError("max_match_chain must be positive")
    if not 0 <= prefix_size <= len(data):
        raise ValueError("prefix_size is outside the decoded output")

    positions: Dict[bytes, Deque[int]] = defaultdict(
        lambda: deque(maxlen=max_match_chain)
    )
    output = bytearray()
    literal_start = prefix_size
    match_sequence_start = None
    pending_matches = []
    position = prefix_size
    size = len(data)

    def add_position(index: int) -> None:
        if index + min_match_length > size:
            return
        key = data[index:index + min_match_length]
        positions[key].append(index)

    def find_match(index: int):
        if index + min_match_length > size:
            return None
        key = data[index:index + min_match_length]
        candidates = positions.get(key)
        if not candidates:
            return None

        best_distance = 0
        best_length = 0
        maximum = size - index
        for candidate in reversed(candidates):
            distance = index - candidate
            if distance <= 0:
                continue
            if distance > window_size:
                break
            length = min_match_length
            while (
                length < maximum
                and data[index + length]
                == data[index + length - distance]
            ):
                length += 1
            if length > best_length:
                best_distance = distance
                best_length = length
                if length == maximum:
                    break
        if best_length < min_match_length:
            return None
        return best_distance, best_length

    for seed_position in range(
        max(0, prefix_size - window_size),
        prefix_size,
    ):
        add_position(seed_position)

    while position < size:
        match = find_match(position)
        if match is not None and lazy_matching and position + 1 < size:
            following = find_match(position + 1)
            if following is not None and following[1] > match[1] + 1:
                match = None
        if (
            match is not None
            and not pending_matches
            and position == literal_start
        ):
            # A seeded suffix can have a match at byte zero, but every block
            # accepted by the game must start with at least one literal.
            match = None
        if match is None:
            if pending_matches:
                output.extend(
                    _encode_block(
                        data[literal_start:match_sequence_start],
                        pending_matches,
                        compact_distance_seed=compact_distance_seed,
                    )
                )
                literal_start = position
                match_sequence_start = None
                pending_matches = []
            add_position(position)
            position += 1
            continue

        distance, length = match
        if not pending_matches:
            match_sequence_start = position
            if match_sequence_start == literal_start:
                raise ValueError(
                    "greedy parser produced a block without a leading literal"
                )
        pending_matches.append((distance, length))
        match_end = position + length
        while position < match_end:
            add_position(position)
            position += 1

    if pending_matches:
        output.extend(
            _encode_block(
                data[literal_start:match_sequence_start],
                pending_matches,
                compact_distance_seed=compact_distance_seed,
            )
        )
    elif literal_start < size:
        output.extend(_encode_block(data[literal_start:], ()))
    return bytes(output)


def _size_constrained_payload(
    data: bytes,
    *,
    window_size: int,
    min_match_length: int,
    max_match_chain: int,
    prefix_size: int = 0,
    lazy_matching: bool = False,
) -> bytes:
    """Choose the shortest exact-byte candidate under a bounded search cap."""

    candidate_chains = sorted({min(64, max_match_chain), max_match_chain})
    candidates = [
        _greedy_payload(
            data,
            window_size=window_size,
            min_match_length=min_match_length,
            max_match_chain=chain,
            prefix_size=prefix_size,
            lazy_matching=lazy_matching,
            compact_distance_seed=True,
        )
        for chain in candidate_chains
    ]
    # The serialized payload already contains control bytes, coded integers,
    # literals, distance extensions and length extensions. Length is therefore
    # the real byte cost, not a token-count proxy. Bytes provide a stable final
    # tie-break if two bounded parses cost the same.
    return min(candidates, key=lambda candidate: (len(candidate), candidate))


def _coded_integer_size(value: int) -> int:
    """Return the encoded size without allocating the coded integer."""

    if value < 0:
        raise ValueError("coded integer value must be non-negative")
    return max(1, (value.bit_length() + 6) // 7)


def _compact_match_size(distance: int, length: int) -> int:
    """Return the exact compact token, distance and length byte cost."""

    if distance <= 0:
        raise ValueError("match distance must be positive")
    if length < 2:
        raise ValueError("match length must be at least two")

    distance_value = distance - 1
    if distance_value <= 7:
        distance_extension_size = 0
    else:
        groups = _coded_integer_size(distance_value)
        top_group = distance_value >> (7 * (groups - 1))
        distance_extension_size = (
            groups - 1 if groups > 1 and top_group < 8 else groups
        )

    length_value = length - 1
    length_extension_size = (
        0
        if length_value <= 0x0F
        else _coded_integer_size(length_value)
    )
    return 1 + distance_extension_size + length_extension_size


def _maximum_gain_upper_bound(maximum_length: int) -> int:
    """Best possible local byte gain for any match up to this length."""

    if maximum_length < 2:
        return 0
    short_gain = min(maximum_length, 16) - 1
    if maximum_length <= 16:
        return short_gain
    long_gain = (
        maximum_length
        - 1
        - _coded_integer_size(maximum_length - 1)
    )
    return max(short_gain, long_gain)


@lru_cache(maxsize=1)
def _maximum_match_library():
    if sys.platform == "darwin":
        filename = "libsrwz_maximum_match.dylib"
    elif sys.platform.startswith("linux"):
        filename = "libsrwz_maximum_match.so"
    else:
        return None
    project_root = Path(__file__).resolve().parents[2]
    path = (
        project_root
        / "work/toolchain/srwz-maximum-match"
        / filename
    )
    if not path.is_file():
        return None
    try:
        library = ctypes.CDLL(str(path))
    except OSError:
        return None
    function = library.srwz_maximum_match_table
    function.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_int32),
    ]
    function.restype = ctypes.c_int
    return library


def _accelerate_maximum_match_table(
    data: bytes,
    *,
    window_size: int,
    min_match_length: int,
    max_match_chain: int,
    prefix_size: int,
    distances: array,
    lengths: array,
    gains: array,
) -> bool:
    """Fill tables with the optional independently authored C helper."""

    library = _maximum_match_library()
    if library is None:
        return False
    if (
        distances.itemsize != ctypes.sizeof(ctypes.c_uint32)
        or lengths.itemsize != ctypes.sizeof(ctypes.c_uint32)
        or gains.itemsize != ctypes.sizeof(ctypes.c_int32)
    ):
        return False
    data_buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
    distance_buffer = (
        ctypes.c_uint32 * len(distances)
    ).from_buffer(distances)
    length_buffer = (
        ctypes.c_uint32 * len(lengths)
    ).from_buffer(lengths)
    gain_buffer = (ctypes.c_int32 * len(gains)).from_buffer(gains)
    status = library.srwz_maximum_match_table(
        data_buffer,
        len(data),
        window_size,
        min_match_length,
        max_match_chain,
        prefix_size,
        distance_buffer,
        length_buffer,
        gain_buffer,
    )
    if status != 0:
        raise RuntimeError(
            f"maximum match accelerator failed with status {status}"
        )
    return True


def _maximum_match_table(
    data: bytes,
    *,
    window_size: int,
    min_match_length: int,
    max_match_chain: int,
    prefix_size: int,
) -> tuple[array, array, array]:
    """Find the best local serialized-byte gain at every suffix position.

    The two-byte rolling index and 65,535-candidate cap are statically
    recovered from the bundled upstream ``CompressTool.exe`` level-9 path.
    Unlike that tool's longest-match parser, this table ranks candidates by
    the exact compact token cost.  Computing every suffix position once lets
    the maximum strategy compare several lazy parses without repeating the
    expensive chain search.
    """

    if not 0 <= prefix_size <= len(data):
        raise ValueError("prefix_size is outside the decoded output")
    if min_match_length < 2:
        raise ValueError("min_match_length must be at least 2")
    if max_match_chain <= 0:
        raise ValueError("max_match_chain must be positive")

    size = len(data)
    distances = array("I", [0]) * size
    lengths = array("I", [0]) * size
    gains = array("i", [0]) * size
    if size < 2 or prefix_size == size:
        return distances, lengths, gains
    if _accelerate_maximum_match_table(
        data,
        window_size=window_size,
        min_match_length=min_match_length,
        max_match_chain=max_match_chain,
        prefix_size=prefix_size,
        distances=distances,
        lengths=lengths,
        gains=gains,
    ):
        return distances, lengths, gains

    padded = data + b"\0"
    heads = array("i", [-1]) * 65536
    previous = array("i", [-1]) * size
    history_start = max(0, prefix_size - window_size)

    for position in range(history_start, size):
        key = (padded[position] << 8) | padded[position + 1]
        candidate = heads[key]
        previous[position] = candidate
        heads[key] = position

        maximum_length = min(
            size - position,
            MAXIMUM_MATCH_LENGTH,
        )
        if (
            position < prefix_size
            or maximum_length < min_match_length
            or candidate < history_start
        ):
            continue

        lower_bound = max(history_start, position - window_size)
        best_distance = 0
        best_length = 0
        best_gain = 0
        maximum_gain = _maximum_gain_upper_bound(maximum_length)
        chain_remaining = min(max_match_chain, position - lower_bound)

        while (
            candidate >= lower_bound
            and chain_remaining > 0
        ):
            distance = position - candidate
            length = 2
            while (
                length < maximum_length
                and data[position + length]
                == data[candidate + length]
            ):
                length += 1

            if length >= min_match_length:
                gain = length - _compact_match_size(distance, length)
                if (
                    gain > best_gain
                    or (
                        gain == best_gain
                        and (
                            length > best_length
                            or (
                                length == best_length
                                and (
                                    best_distance == 0
                                    or distance < best_distance
                                )
                            )
                        )
                    )
                ):
                    best_distance = distance
                    best_length = length
                    best_gain = gain
                    if (
                        best_gain == maximum_gain
                        and best_length == maximum_length
                    ):
                        break

            candidate = previous[candidate]
            chain_remaining -= 1

        if best_gain > 0:
            distances[position] = best_distance
            lengths[position] = best_length
            gains[position] = best_gain

    return distances, lengths, gains


def _payload_from_match_table(
    data: bytes,
    *,
    distances: array,
    lengths: array,
    gains: array,
    prefix_size: int,
    lazy_bias: int,
) -> bytes:
    """Serialize one deterministic one-byte-lookahead parse."""

    output = bytearray()
    literal_start = prefix_size
    match_sequence_start = None
    pending_matches = []
    position = prefix_size
    size = len(data)

    while position < size:
        distance = int(distances[position])
        length = int(lengths[position])
        gain = int(gains[position])
        use_match = length >= 2 and gain > 0

        if use_match and position + 1 < size:
            next_gain = int(gains[position + 1])
            if next_gain > gain + lazy_bias:
                use_match = False

        if (
            use_match
            and not pending_matches
            and position == literal_start
        ):
            # A preserved prefix ends at a complete block boundary. The game
            # decoder's post-tested literal loop still requires the new block
            # to begin with at least one literal.
            use_match = False

        if not use_match:
            if pending_matches:
                output.extend(
                    _encode_block(
                        data[literal_start:match_sequence_start],
                        pending_matches,
                        compact_distance_seed=True,
                    )
                )
                literal_start = position
                match_sequence_start = None
                pending_matches = []
            position += 1
            continue

        if not pending_matches:
            match_sequence_start = position
        pending_matches.append((distance, length))
        position += length

    if pending_matches:
        output.extend(
            _encode_block(
                data[literal_start:match_sequence_start],
                pending_matches,
                compact_distance_seed=True,
            )
        )
    elif literal_start < size:
        output.extend(_encode_block(data[literal_start:], ()))
    return bytes(output)


def _maximum_payload(
    data: bytes,
    *,
    window_size: int,
    min_match_length: int,
    max_match_chain: int,
    prefix_size: int = 0,
) -> bytes:
    """Choose the shortest member of a deliberately expensive parse portfolio.

    ``maximum`` is an engineering name, not a proof of global optimality. It
    runs one full level-9-style match search ranked by serialized gain, then
    compares nine one-byte-lookahead biases by their final byte strings.
    Small payloads also retain the older bounded-greedy portfolio as a
    regression candidate. Large production payloads omit that redundant
    pure-Python pass so the independently verified native match-table helper
    controls the build cost.
    """

    if not data or prefix_size == len(data):
        return b""
    search_chain = max(max_match_chain, MAXIMUM_MATCH_CHAIN)
    distances, lengths, gains = _maximum_match_table(
        data,
        window_size=window_size,
        min_match_length=min_match_length,
        max_match_chain=search_chain,
        prefix_size=prefix_size,
    )
    candidates = list(
        _payload_from_match_table(
            data,
            distances=distances,
            lengths=lengths,
            gains=gains,
            prefix_size=prefix_size,
            lazy_bias=lazy_bias,
        )
        for lazy_bias in MAXIMUM_LAZY_BIASES
    )
    if len(data) - prefix_size <= MAXIMUM_LEGACY_PORTFOLIO_LIMIT:
        candidates.append(
            _size_constrained_payload(
                data,
                window_size=window_size,
                min_match_length=min_match_length,
                max_match_chain=max_match_chain,
                prefix_size=prefix_size,
                lazy_matching=True,
            )
        )
    return min(candidates, key=lambda candidate: (len(candidate), candidate))


def _rust_compressor_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    return (
        project_root
        / "work/toolchain/srwz-compressor-rs/target/release/srwz-compress"
    )


def _rust_maximum_payload(
    data: bytes,
    *,
    window_size: int,
    min_match_length: int,
    max_match_chain: int,
    prefix_size: int = 0,
) -> bytes:
    """Run the repository-owned Rust payload encoder.

    The process boundary keeps the Rust implementation independent from the
    Python decoder used as the round-trip oracle. Generated inputs and outputs
    stay inside the ignored work tree.
    """

    binary = _rust_compressor_path()
    if not binary.is_file():
        raise RuntimeError(
            "Rust compressor is not built; run "
            "`python3 tools/build_rust_compressor.py --force`"
        )
    project_root = Path(__file__).resolve().parents[2]
    work_root = project_root / "work"
    work_root.mkdir(parents=True, exist_ok=True)
    search_chain = max(max_match_chain, MAXIMUM_MATCH_CHAIN)
    with tempfile.TemporaryDirectory(
        prefix="srwz-rust-compressor-",
        dir=work_root,
    ) as temporary:
        temporary_root = Path(temporary)
        input_path = temporary_root / "decoded.bin"
        output_path = temporary_root / "payload.bin"
        input_path.write_bytes(data)
        completed = subprocess.run(
            [
                str(binary),
                "payload",
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--window-size",
                str(window_size),
                "--prefix-size",
                str(prefix_size),
                "--min-match-length",
                str(min_match_length),
                "--max-match-chain",
                str(search_chain),
            ],
            check=False,
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                f"Rust compressor failed with status "
                f"{completed.returncode}: {detail}"
            )
        if not output_path.is_file():
            raise RuntimeError("Rust compressor did not produce a payload")
        return output_path.read_bytes()


def reencode_changed_suffix(
    original_stream: BytesLike,
    modified_output: BytesLike,
    *,
    strategy: str = "greedy",
    min_match_length: int = DEFAULT_MIN_MATCH_LENGTH,
    max_match_chain: int = DEFAULT_MAX_MATCH_CHAIN,
    lazy_matching: bool = False,
    max_output_size: Optional[int] = None,
) -> bytes:
    """Preserve complete original blocks before a changed decoded suffix."""

    if strategy not in {
        "greedy",
        "literal",
        "maximum",
        "rust-maximum",
        "size-constrained",
    }:
        raise ValueError(
            "suffix strategy must be 'greedy', 'literal', 'maximum', "
            "'rust-maximum' or 'size-constrained'"
        )
    if max_output_size is not None and max_output_size < 0:
        raise ValueError("max_output_size must be non-negative")
    source = memoryview(original_stream).cast("B").tobytes()
    replacement = memoryview(modified_output).cast("B").tobytes()
    blocks = []

    def collect_blocks(event: TraceEvent) -> None:
        if event["kind"] == "block":
            blocks.append(event)

    original = decode(source, trace_sink=collect_blocks)
    if not replacement:
        raise ValueError("suffix re-encode requires non-empty output")
    first_changed = next(
        (
            index
            for index, (before, after) in enumerate(
                zip(original.output, replacement)
            )
            if before != after
        ),
        None,
    )
    if first_changed is None:
        if len(replacement) == len(original.output):
            encoded = source[:original.consumed]
            if (
                max_output_size is not None
                and len(encoded) > max_output_size
            ):
                raise SrwzEncodeError(
                    f"encoded output size {len(encoded)} exceeds "
                    f"limit {max_output_size}"
                )
            return encoded
        first_changed = min(len(original.output), len(replacement))

    header_reader = ByteReader(source)
    old_declared = read_coded_integer(
        header_reader,
        context="declared output size",
    )
    new_declared = encode_coded_integer(len(replacement))
    old_conditional = _uses_conditional_header_value(
        original.flags,
        int(original.metadata["window_size"]),
        len(original.output),
    )
    new_conditional = _uses_conditional_header_value(
        original.flags,
        int(original.metadata["window_size"]),
        len(replacement),
    )
    if old_conditional != new_conditional:
        raise ValueError(
            "suffix size change would alter the original header shape"
        )

    block = max(
        (
            event
            for event in blocks
            if int(event["output_offset"]) <= first_changed
        ),
        key=lambda event: int(event["output_offset"]),
    )
    output_prefix_size = int(block["output_offset"])
    input_prefix_size = int(block["input_offset"])
    if (
        original.output[:output_prefix_size]
        != replacement[:output_prefix_size]
    ):
        raise ValueError("suffix splice would preserve changed prefix bytes")

    if strategy == "literal":
        payload = _literal_payload(replacement[output_prefix_size:])
    elif strategy == "maximum":
        payload = _maximum_payload(
            replacement,
            window_size=int(original.metadata["window_size"]),
            min_match_length=min_match_length,
            max_match_chain=max_match_chain,
            prefix_size=output_prefix_size,
        )
    elif strategy == "rust-maximum":
        payload = _rust_maximum_payload(
            replacement,
            window_size=int(original.metadata["window_size"]),
            min_match_length=min_match_length,
            max_match_chain=max_match_chain,
            prefix_size=output_prefix_size,
        )
    elif strategy == "size-constrained":
        payload = _size_constrained_payload(
            replacement,
            window_size=int(original.metadata["window_size"]),
            min_match_length=min_match_length,
            max_match_chain=max_match_chain,
            prefix_size=output_prefix_size,
            lazy_matching=lazy_matching,
        )
    else:
        payload = _greedy_payload(
            replacement,
            window_size=int(original.metadata["window_size"]),
            min_match_length=min_match_length,
            max_match_chain=max_match_chain,
            prefix_size=output_prefix_size,
            lazy_matching=lazy_matching,
        )
    encoded = (
        new_declared
        + source[old_declared.end:input_prefix_size]
        + payload
    )
    reread = decode(encoded)
    if reread.output != replacement or reread.consumed != len(encoded):
        raise ValueError("suffix re-encode failed its decoded round-trip")
    if max_output_size is not None and len(encoded) > max_output_size:
        raise SrwzEncodeError(
            f"encoded output size {len(encoded)} exceeds "
            f"limit {max_output_size}"
        )
    return encoded


def encode(
    data: BytesLike,
    *,
    strategy: str = "greedy",
    flags: Optional[int] = None,
    header_unknown_0: Optional[int] = None,
    header_unknown_1: int = 0,
    min_match_length: int = DEFAULT_MIN_MATCH_LENGTH,
    max_match_chain: int = DEFAULT_MAX_MATCH_CHAIN,
    max_output_size: Optional[int] = None,
) -> bytes:
    """Encode one deterministic SRWZ stream without archive padding.

    ``literal`` emits a single literal-only block and is the smallest
    evidence-dependent baseline. ``greedy`` preserves the original clean-room
    encoder behavior as a byte-level regression baseline. ``size-constrained``
    compares bounded greedy parses by their exact serialized size and uses the
    compact extended-distance seed observed in both the DLL CIL and original
    game streams. ``maximum`` adds the statically recovered level-9 two-byte
    hash-chain bound, exact token-gain ranking and a nine-bias lazy portfolio;
    small payloads also compare the legacy bounded-greedy portfolio. It is not
    a mathematical optimality claim. Large production payloads deliberately
    skip the redundant legacy pass to keep offline build time bounded.
    ``rust-maximum`` uses the repository-owned Rust implementation and keeps
    this decoder as an independent round-trip oracle. ``max_output_size`` is a
    hard failure gate, never truncation.
    """

    source = memoryview(data).cast("B").tobytes()
    selected_flags = flags_for_size(len(source)) if flags is None else flags
    window_size = _window_size_from_flags(selected_flags)
    header = _encode_header(
        len(source),
        selected_flags,
        header_unknown_0=header_unknown_0,
        header_unknown_1=header_unknown_1,
    )
    if max_output_size is not None and max_output_size < 0:
        raise ValueError("max_output_size must be non-negative")
    if strategy == "literal":
        payload = _literal_payload(source)
    elif strategy == "greedy":
        payload = _greedy_payload(
            source,
            window_size=window_size,
            min_match_length=min_match_length,
            max_match_chain=max_match_chain,
        )
    elif strategy == "size-constrained":
        payload = _size_constrained_payload(
            source,
            window_size=window_size,
            min_match_length=min_match_length,
            max_match_chain=max_match_chain,
        )
    elif strategy == "maximum":
        payload = _maximum_payload(
            source,
            window_size=window_size,
            min_match_length=min_match_length,
            max_match_chain=max_match_chain,
        )
    elif strategy == "rust-maximum":
        payload = _rust_maximum_payload(
            source,
            window_size=window_size,
            min_match_length=min_match_length,
            max_match_chain=max_match_chain,
        )
    else:
        raise ValueError(f"unknown encoding strategy: {strategy!r}")
    encoded = header + payload
    if max_output_size is not None and len(encoded) > max_output_size:
        raise SrwzEncodeError(
            f"encoded output size {len(encoded)} exceeds "
            f"limit {max_output_size}"
        )
    return encoded


def decode(
    data: BytesLike,
    *,
    max_output_size: int = DEFAULT_MAX_OUTPUT_SIZE,
    max_coded_integer_bytes: int = DEFAULT_MAX_CODED_INTEGER_BYTES,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    trace_sink: Optional[TraceSink] = None,
) -> DecodeResult:
    """Decode one SRWZ stream and stop at its exact compressed-stream boundary."""

    if max_output_size < 0:
        raise ValueError("max_output_size must be non-negative")
    if max_coded_integer_bytes <= 0:
        raise ValueError("max_coded_integer_bytes must be positive")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    reader = ByteReader(data)
    declared = read_coded_integer(
        reader,
        max_bytes=max_coded_integer_bytes,
        context="declared output size",
    )
    if declared.value > max_output_size:
        raise SrwzCodecError(
            f"declared output size {declared.value} exceeds "
            f"limit {max_output_size}",
            offset=declared.start,
        )

    flags_value = read_coded_integer(
        reader,
        max_bytes=max_coded_integer_bytes,
        context="flags",
    )
    flags = flags_value.value
    window_size = 1 << (((flags >> 1) & 0x0F) + 8)
    metadata = {"window_size": window_size}

    if _uses_conditional_header_value(flags, window_size, declared.value):
        conditional = read_coded_integer(
            reader,
            max_bytes=max_coded_integer_bytes,
            context="conditional unknown header value",
        )
        metadata["header_unknown_0"] = conditional.value

    trailing_header = read_coded_integer(
        reader,
        max_bytes=max_coded_integer_bytes,
        context="unknown header value",
    )
    metadata["header_unknown_1"] = trailing_header.value
    header_size = reader.offset

    _emit(
        trace_sink,
        {
            "kind": "header",
            "input_offset": 0,
            "input_end": header_size,
            "declared_size": declared.value,
            "flags": flags,
            "window_size": window_size,
            **metadata,
        },
    )

    output = bytearray()
    structural_tokens = 0
    block_index = 0
    match_index = 0

    def count_token(offset: int) -> None:
        nonlocal structural_tokens
        structural_tokens += 1
        if structural_tokens > max_tokens:
            raise SrwzCodecError(
                f"structural token count exceeds limit {max_tokens}",
                offset=offset,
            )

    while len(output) < declared.value:
        if reader.remaining == 0:
            raise SrwzCodecError(
                f"declared output size mismatch: produced {len(output)} "
                f"of {declared.value} bytes",
                offset=reader.offset,
            )

        control_offset = reader.offset
        count_token(control_offset)
        control = reader.read_byte("block control")
        literal_count = control & 0x0F
        match_count = control >> 4

        if literal_count == 0:
            literal_value = read_coded_integer(
                reader,
                max_bytes=max_coded_integer_bytes,
                context="literal count",
            )
            literal_count = literal_value.value
            if literal_count == 0:
                raise SrwzCodecError(
                    "zero literal count is unsupported by the game "
                    "decompressor",
                    offset=control_offset,
                )

        if match_count == 0:
            match_value = read_coded_integer(
                reader,
                max_bytes=max_coded_integer_bytes,
                context="match count",
            )
            match_count = match_value.value

        _emit(
            trace_sink,
            {
                "kind": "block",
                "block_index": block_index,
                "input_offset": control_offset,
                "output_offset": len(output),
                "control": control,
                "literal_count": literal_count,
                "match_count": match_count,
            },
        )
        block_index += 1

        remaining_output = declared.value - len(output)
        if literal_count > remaining_output:
            raise SrwzCodecError(
                f"literal run of {literal_count} bytes exceeds "
                f"remaining output size {remaining_output}",
                offset=control_offset,
            )
        output.extend(reader.read_bytes(literal_count, "literal run"))

        if len(output) == declared.value:
            break

        if match_count == 0:
            raise SrwzCodecError(
                "zero match count before end of output is unsupported by "
                "the game decompressor",
                offset=control_offset,
            )

        for block_match_index in range(match_count):
            if len(output) == declared.value:
                raise SrwzCodecError(
                    "match count continues after declared output size",
                    offset=reader.offset,
                )

            token_offset = reader.offset
            count_token(token_offset)
            token = reader.read_byte("back-reference token")
            distance_value = (token & 0x0F) >> 1
            distance_extended = token & 1 == 0
            if distance_extended:
                distance_coded = read_coded_integer(
                    reader,
                    initial_value=distance_value,
                    max_bytes=max_coded_integer_bytes,
                    context="back-reference distance",
                )
                distance_value = distance_coded.value

            distance = distance_value + 1
            if distance > window_size:
                raise SrwzCodecError(
                    f"back-reference distance {distance} exceeds "
                    f"window size {window_size}",
                    offset=token_offset,
                )
            if distance > len(output):
                raise SrwzCodecError(
                    f"back-reference distance {distance} exceeds "
                    f"produced output size {len(output)}",
                    offset=token_offset,
                )

            length_value = token >> 4
            length_extended = length_value == 0
            if length_extended:
                length_coded = read_coded_integer(
                    reader,
                    max_bytes=max_coded_integer_bytes,
                    context="back-reference length",
                )
                length_value = length_coded.value
            length = length_value + 1

            remaining_output = declared.value - len(output)
            if length > remaining_output:
                raise SrwzCodecError(
                    f"back-reference length {length} exceeds "
                    f"remaining output size {remaining_output}",
                    offset=token_offset,
                )

            output_offset = len(output)
            for _ in range(length):
                output.append(output[-distance])

            _emit(
                trace_sink,
                {
                    "kind": "match",
                    "match_index": match_index,
                    "block_match_index": block_match_index,
                    "input_offset": token_offset,
                    "output_offset": output_offset,
                    "distance": distance,
                    "length": length,
                    "distance_extended": distance_extended,
                    "length_extended": length_extended,
                },
            )
            match_index += 1

    return DecodeResult(
        output=bytes(output),
        consumed=reader.offset,
        declared_size=declared.value,
        flags=flags,
        header_size=header_size,
        metadata=metadata,
    )


__all__ = [
    "ByteReader",
    "DEFAULT_MAX_CODED_INTEGER_BYTES",
    "DEFAULT_MAX_MATCH_CHAIN",
    "DEFAULT_MAX_OUTPUT_SIZE",
    "DEFAULT_MAX_TOKENS",
    "decode",
    "encode",
    "encode_coded_integer",
    "flags_for_size",
    "read_coded_integer",
    "reencode_changed_suffix",
]
