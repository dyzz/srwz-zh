"""Clean-room support code for Super Robot Wars Z data formats."""

from .archive import ArchiveLayoutError, OffsetLayout, slice_archive
from .codec import (
    ByteReader,
    decode_production as decode,
    encode,
    encode_coded_integer,
    flags_for_size,
    read_coded_integer,
)
from .codec_contract import CodedInteger, DecodeResult, SrwzCodecError
from .diagnostics import TraceCollector
from .text import (
    DecodedText,
    SrwzTextEncodeError,
    SrwzTextError,
    TextTable,
    decode_text,
    encode_text,
    load_text_table,
)
from .stage import (
    StageParseError,
    StageParseResult,
    StageTextEntry,
    parse_stage,
    read_stage_function_addresses,
)
from .menu import MenuParseError, MenuParseResult, MenuTextEntry, parse_menu_file
from .summary import (
    SummaryParseError,
    SummaryParseResult,
    SummaryTextEntry,
    parse_summary,
)
from .iso_layout import (
    CORE_ARCHIVE_SPECS,
    ExecutableOffsetSpec,
    IsoLayoutError,
    read_executable_archive_offsets,
)
__all__ = [
    "ArchiveLayoutError",
    "ByteReader",
    "CodedInteger",
    "DecodeResult",
    "DecodedText",
    "OffsetLayout",
    "MenuParseError",
    "MenuParseResult",
    "MenuTextEntry",
    "CORE_ARCHIVE_SPECS",
    "ExecutableOffsetSpec",
    "IsoLayoutError",
    "SrwzCodecError",
    "SrwzTextError",
    "SrwzTextEncodeError",
    "SummaryParseError",
    "SummaryParseResult",
    "SummaryTextEntry",
    "StageParseError",
    "StageParseResult",
    "StageTextEntry",
    "TextTable",
    "TraceCollector",
    "decode",
    "encode",
    "encode_coded_integer",
    "decode_text",
    "encode_text",
    "flags_for_size",
    "load_text_table",
    "parse_stage",
    "parse_menu_file",
    "parse_summary",
    "read_stage_function_addresses",
    "read_executable_archive_offsets",
    "read_coded_integer",
    "slice_archive",
]
