#!/usr/bin/env python3
"""Export the release code table for third-party tool authors.

The game stores some characters under more than one code.  A table that
lists only the primary codes decodes the others as the Japanese character
that originally lived at that code (``907D`` is ``∀`` here, ``図`` in the
stock font).  This export therefore always carries all three groups:

* ``primary_assignments`` – one code per character;
* ``surface_alias_assignments`` – a second code for the same character,
  and the one the builder actually writes for names and dialogue;
* ``source_compatibility_assignments`` – codes that keep the stock
  Japanese glyph.

Outputs, in ``work/codebook`` unless ``--out`` is given:

* ``zh-release-font-assignments-DATE.json`` – the three groups;
* ``zh-release-codebook-DATE.tbl`` – ``CODE=character`` for reading;
* ``zh-release-encode-DATE.tbl`` – ``character=CODE`` for writing names;
* ``码表-DATE.zip`` – the three files plus ``使用说明.txt``.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from srwz.text import TextTable, load_text_table  # noqa: E402

SNAPSHOT = PROJECT_ROOT / "config/encoding/zh-release-font-assignments.json"
STOCK_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
GROUPS = (
    "primary_assignments",
    "surface_alias_assignments",
    "source_compatibility_assignments",
)
ROW_FIELDS = ("character", "code", "glyph_index", "mapping")
TWO_BYTE_SPACE = "8140"

README = """\
超级机器人大战Z 汉化版码表（{date}）

文件
  zh-release-codebook-{date}.tbl          读取用：码=字，共 {decode_count} 个码
  zh-release-encode-{date}.tbl            写入名称用：字=码，共 {encode_count} 个字
  zh-release-font-assignments-{date}.json 完整数据（三组）

为什么有三组
  primary_assignments              主码，一字一码，{primary} 条
  surface_alias_assignments        别名码，同一个字的第二个码位，{alias} 条
  source_compatibility_assignments 兼容码，保留日版原字形的码位，{compat} 条
  游戏文本里实际写入的常常是别名码。例如 ∀ 的主码是 81CD，
  但机体名里存的是 907D（日版这个码位是“図”）。只读主码的话，
  这些位置会显示成日版原字。

读取
  三组都要并入同一张“码→字”表，多个码可以对应同一个字。
  直接用 .tbl 即可，它已经合并好。表里没有的两字节码按 Shift-JIS 显示。

排版控制码（0.5.0 起文本里会出现）
  31 XX  颜色      32 XX  字宽      33 XX  字高      34 XX  字距
  都是两个字节：一个控制码加一个参数字节，不是文字。
  读取时遇到 31–34 要连同后面一个字节一起跳过，不能当成数字 1–4，
  也不能在参数字节处截断。例如机体名 D.O.M.E.G-Bit 存的是
  34 0E … 34 16，图鉴正文很多以 32 15 34 15 开头。
  写回时这些字节原样保留。

写入
  1. 没改动的文字保持原字节，不要解码后再整体重新编码。
  2. 新写的字按 encode .tbl 取码：有别名码的字用别名码，其余用主码。
  3. 英文字母和数字不要写单字节 ASCII，写全角码（L=826B，0=824F），
     encode .tbl 里已经按半角字符列出。
  4. 空格写 8140，不要写单字节 20。
  5. 表里没有的字不能写入，字库里没有这个字形。

JSON 每条的字段
  character         游戏里显示的字
  code              存储码（十六进制，高字节在前）
  glyph_index       字库槽位
  source_character  这个码位在日版原字库里的字（日版空位则没有这一项）
  primary_code      仅别名码有：同一个字的主码
"""


def stock_character(stock: TextTable, code: int) -> str | None:
    """Return what the Japanese disc shows at a code, if anything."""

    character = stock.characters.get(code)
    if character is None:
        try:
            character = code.to_bytes(2, "big").decode("cp932")
        except UnicodeDecodeError:
            return None
    return character


def export_rows(
    rows: list[dict], stock: TextTable, *, alias: bool
) -> list[dict]:
    exported = []
    for row in rows:
        item = {field: row[field] for field in ROW_FIELDS}
        source = row.get("source_character") or stock_character(
            stock, int(row["code"], 16)
        )
        if source is not None:
            item["source_character"] = source
        if alias:
            item["primary_code"] = row["primary_code"]
        exported.append(item)
    return exported


def build(snapshot: dict, stock: TextTable) -> tuple[dict, dict[str, str], dict[str, str]]:
    document: dict = {
        "schema_version": snapshot["schema_version"],
        "snapshot_id": snapshot["snapshot_id"],
        "note": (
            "解码时三组都要并入（多码对一字）。surface_alias_assignments "
            "是同一字符的第二个码位，游戏文本里实际会写入。"
        ),
    }
    decode: dict[str, str] = {}
    for group in GROUPS:
        rows = snapshot.get(group)
        if not isinstance(rows, list) or not rows:
            raise SystemExit(f"code table snapshot has no {group}")
        exported = export_rows(
            rows, stock, alias=group == "surface_alias_assignments"
        )
        document[group.replace("assignments", "assignment_count")] = len(exported)
        document[group] = exported
        for row in exported:
            code = row["code"].upper()
            if code in decode:
                raise SystemExit(f"code {code} appears twice in the snapshot")
            decode[code] = row["character"]

    # Writing follows the builder's order for stored names: primary code,
    # then the alias, then stock fullwidth codes for ASCII letters/digits.
    encode = {row["character"]: row["code"] for row in document[GROUPS[0]]}
    encode.update(
        {row["character"]: row["code"] for row in document[GROUPS[1]]}
    )
    for character in (
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    ):
        code = chr(ord(character) + 0xFEE0).encode("cp932").hex().upper()
        encode[character] = code
    encode[" "] = TWO_BYTE_SPACE
    return document, dict(sorted(decode.items())), encode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", default=datetime.date.today().strftime("%Y%m%d"))
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "work/codebook")
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    args = parser.parse_args()

    document, decode, encode = build(
        json.loads(args.snapshot.read_text("utf-8")),
        load_text_table(STOCK_TABLE),
    )
    args.out.mkdir(parents=True, exist_ok=True)
    date = args.date
    files = {
        f"zh-release-font-assignments-{date}.json": json.dumps(
            document, ensure_ascii=False, indent=2
        )
        + "\n",
        f"zh-release-codebook-{date}.tbl": "".join(
            f"{code}={character}\n" for code, character in decode.items()
        ),
        f"zh-release-encode-{date}.tbl": "".join(
            f"{character}={code}\n"
            for character, code in sorted(encode.items(), key=lambda item: item[1])
        ),
        "使用说明.txt": README.format(
            date=date,
            decode_count=len(decode),
            encode_count=len(encode),
            primary=document["primary_assignment_count"],
            alias=document["surface_alias_assignment_count"],
            compat=document["source_compatibility_assignment_count"],
        ),
    }
    archive = args.out / f"码表-{date}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, text in files.items():
            (args.out / name).write_text(text, "utf-8")
            bundle.writestr(name, text)
    print(
        f"{archive}: {len(decode)} codes "
        f"({document['primary_assignment_count']} primary, "
        f"{document['surface_alias_assignment_count']} alias, "
        f"{document['source_compatibility_assignment_count']} compatibility), "
        f"{len(encode)} characters to write"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
