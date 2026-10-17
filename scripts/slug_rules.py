#!/usr/bin/env python3
"""共享 slug 校验：所有把 slug 拼进路径的入口都必须先过这里。

slug 会被直接拼成 output/{slug}/、gallery/{slug}/、sources/{slug}/ 以及
~/.claude/skills/{slug}-wisdom/。在此之前，publish_skill.py 只做了
`strip().lower()`，`..`、`a/b`、全角空格都能原样流进路径。
"""

from __future__ import annotations

import re
from pathlib import Path

SLUG_MAX_LEN = 64
# 白名单而非黑名单：只放行小写 ASCII 字母数字段、段间单个连字符。黑名单总会漏
# 掉没想到的字符——零宽空格 U+200B 不算 str.isspace()，`a:b` 在 NTFS 上是备用
# 数据流——白名单则把这些一并挡掉。
_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Windows 保留设备名：能过上面的正则，但 gallery/con/ 这样的目录在 Windows 上建不出来。
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


class InvalidSlug(ValueError):
    """slug 不合法。消息里写明原因，CLI 直接打印给用户。"""


def validate_slug(raw: str) -> str:
    """校验并原样返回 slug；不合法时抛 InvalidSlug。

    只拒绝、不规范化：`"Seneca "` 不会被悄悄改成 `seneca`——strip()/lower()
    会把脚本拼接带进来的换行、大小写笔误一并吞掉，让错误输入看起来像成功。
    命名约定见 CLAUDE.md：小写、连字符分隔（`charlie-munger`、`sun-tzu`）。
    """
    if not isinstance(raw, str) or not raw:
        raise InvalidSlug("slug 为空")
    if len(raw) > SLUG_MAX_LEN:
        raise InvalidSlug(f"slug 长度 {len(raw)} 超过上限 {SLUG_MAX_LEN}")
    # fullmatch 而非 match(r"^...$")：`$` 会在末尾换行前匹配成功，"sun-tzu\n" 能混过去。
    if not _SLUG_RE.fullmatch(raw):
        raise InvalidSlug(
            f"slug {raw!r} 不合法：只允许小写 ASCII 字母、数字，以单个连字符分隔（如 charlie-munger）"
        )
    if raw in _WINDOWS_RESERVED:
        raise InvalidSlug(f"slug {raw!r} 是 Windows 保留设备名，无法建目录")
    return raw


def slug_arg(raw: str) -> str:
    """argparse 的 type=。

    argparse 会吞掉 type 函数抛的 ValueError 的原因文字，只打印
    "invalid validate_slug value"；转成 ArgumentTypeError 才能把原因带给用户。
    """
    import argparse
    try:
        return validate_slug(raw)
    except InvalidSlug as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def slug_dir(base: Path, raw: str) -> Path:
    """validate_slug 之后再确认 base/slug 解析后仍在 base 之内（纵深防御）。"""
    slug = validate_slug(raw)
    base_resolved = base.resolve()
    target = (base / slug).resolve()
    if target.parent != base_resolved:
        raise InvalidSlug(f"slug {raw!r} 解析后逃出了 {base}")
    return base / slug
