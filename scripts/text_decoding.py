#!/usr/bin/env python3
"""raw 文本的唯一解码入口。

index（抽取）、清洗闸门与 P2 溯源必须读到同一份文本：过去 index 会回退 GB18030，
P2 却只按 UTF-8 读，GBK 编码的中文电子书能被抽取，引文却永远溯源失败。

顺序：带 BOM 的 UTF-16 → 严格 UTF-8（保留 BOM 字符，与旧行为一致）→ GB18030 → Big5
→ UTF-8 替换模式（计数 U+FFFD，交给清洗闸门判定）。刻意不用 latin-1 兜底：它永不报错，
只会把中文悄悄变成乱码。
"""

from typing import NamedTuple

FALLBACK_ENCODINGS = ("gb18030", "big5")


class Decoded(NamedTuple):
    text: str
    encoding: str
    replacements: int


def decode_bytes(data: bytes) -> Decoded:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return Decoded(data.decode("utf-16"), "utf-16", 0)
        except UnicodeDecodeError:
            pass
    try:
        return Decoded(data.decode("utf-8"), "utf-8", 0)
    except UnicodeDecodeError:
        pass
    for encoding in FALLBACK_ENCODINGS:
        try:
            return Decoded(data.decode(encoding), encoding, 0)
        except UnicodeDecodeError:
            continue
    text = data.decode("utf-8", errors="replace")
    return Decoded(text, "utf-8-replace", text.count("�"))
