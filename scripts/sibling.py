#!/usr/bin/env python3
"""按路径加载模块的唯一入口：scripts/ 不是包，脚本与测试都靠它取同目录的兄弟模块。

先登记 `sys.modules` 再执行。被加载的模块若在 `from __future__ import annotations` 下定义
dataclass，dataclasses 要到 `sys.modules[cls.__module__]` 里查注解；没登记就崩
（`AttributeError: 'NoneType' object has no attribute '__dict__'`）。这个坑踩过三次——
pipeline_status._sibling、verify_provenance.EvidenceCoverage、publish_skill._load_sibling——
所以 scripts/ 下除本文件外不得再直接调用 `spec_from_file_location`（tests/test_sibling.py 守着）。

本模块自己也得被找到：调用方在 import 前把 scripts/ 目录放进 sys.path，与 `from workspace import ...`
同一个写法。

不缓存：每次调用都重新执行模块。需要缓存的调用方（如 verify_provenance 构造 OpenCC 开销不小）
自己套 `functools.lru_cache`。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPTS_DIR = Path(__file__).resolve().parent
_MISSING = object()


def load_module(path: Path | str, name: str | None = None) -> ModuleType:
    """加载 `path` 处的 .py 文件，以 `name` 登记进 sys.modules 后执行并返回。

    `name` 缺省为 `_mdf_{文件名}`：带下划线前缀，不会盖掉 sys.path 上真正的顶层模块
    （mdf.py 里 `from workspace import ...` 拿到的那份）。同名再次加载会替换登记项；
    执行失败则撤销登记（有旧项则还原），不留半成品模块。
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到要加载的模块：{path}")
    name = name or f"_mdf_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法按路径加载 {path}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(name, _MISSING)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous  # type: ignore[assignment]
        raise
    return module


def load_sibling(name: str, as_name: str | None = None) -> ModuleType:
    """加载 scripts/{name}.py。`as_name` 为登记名，缺省 `_mdf_{name}`。"""
    return load_module(SCRIPTS_DIR / f"{name}.py", as_name)
