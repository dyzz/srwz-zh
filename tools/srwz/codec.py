"""Strict clean-room decoder for the SRWZ LZSS byte stream.

The format names in this module deliberately distinguish observed structure
from unknown header semantics.  In particular, the coded integer following
the flags is retained as ``header_unknown_1`` rather than assigned a guessed
meaning.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Callable, Deque, Dict, Mapping, Optional, Union

from .codec_contract import CodedInteger, DecodeResult, SrwzCodecError


DEFAULT_MAX_OUTPUT_SIZE = 256 * 1024 * 1024
DEFAULT_MAX_CODED_INTEGER_BYTES = 10
DEFAULT_MAX_TOKENS = 10_000_000
DEFAULT_MAX_MATCH_CHAIN = 64
DEFAULT_MIN_MATCH_LENGTH = 3
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


def _encode_block(literals: bytes, matches) -> bytes:
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
        if distance <= 0:
            raise ValueError("match distance must be positive")
        if length <= 0:
            raise ValueError("match length must be positive")

        distance_value = distance - 1
        if distance_value <= 7:
            distance_bits = (distance_value << 1) | 1
            distance_extension = b""
        else:
            distance_bits = 0
            distance_extension = encode_coded_integer(distance_value)

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
            )
        )
    elif literal_start < size:
        output.extend(_encode_block(data[literal_start:], ()))
    return bytes(output)


def reencode_changed_suffix(
    original_stream: BytesLike,
    modified_output: BytesLike,
    *,
    min_match_length: int = DEFAULT_MIN_MATCH_LENGTH,
    max_match_chain: int = DEFAULT_MAX_MATCH_CHAIN,
) -> bytes:
    """Preserve complete original blocks before a changed decoded suffix."""

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
            return source[:original.consumed]
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

    payload = _greedy_payload(
        replacement,
        window_size=int(original.metadata["window_size"]),
        min_match_length=min_match_length,
        max_match_chain=max_match_chain,
        prefix_size=output_prefix_size,
    )
    encoded = (
        new_declared
        + source[old_declared.end:input_prefix_size]
        + payload
    )
    reread = decode(encoded)
    if reread.output != replacement or reread.consumed != len(encoded):
        raise ValueError("suffix re-encode failed its decoded round-trip")
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
) -> bytes:
    """Encode one deterministic SRWZ stream without archive padding.

    ``literal`` emits a single literal-only block and is the smallest
    evidence-dependent baseline. ``greedy`` adds deterministic back-references
    while using the exact token grammar exercised by the decoder fixtures and
    original game streams.
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
    if strategy == "literal":
        payload = _literal_payload(source)
    elif strategy == "greedy":
        payload = _greedy_payload(
            source,
            window_size=window_size,
            min_match_length=min_match_length,
            max_match_chain=max_match_chain,
        )
    else:
        raise ValueError(f"unknown encoding strategy: {strategy!r}")
    return header + payload


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
