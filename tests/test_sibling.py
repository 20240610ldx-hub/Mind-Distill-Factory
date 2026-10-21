"""按路径加载模块的共享 helper（scripts/sibling.py）。

scripts/ 不是包，脚本与测试都得按路径加载同目录模块。裸写 spec_from_file_location 而不登记
sys.modules，被加载的模块里只要有 `from __future__ import annotations` + dataclass 就崩
（dataclasses 要到 sys.modules[cls.__module__] 里查注解）——这个坑踩过三次：
pipeline_status._sibling、verify_provenance.EvidenceCoverage、publish_skill._load_sibling。
"""

from __future__ import annotations

import ast
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sibling  # noqa: E402

FUTURE_DATACLASS = textwrap.dedent(
    '''
    from __future__ import annotations

    from dataclasses import dataclass, field


    @dataclass(frozen=True)
    class Box:
        label: str
        items: list[str] = field(default_factory=list)
    '''
)


class LoadModuleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _write(self, name: str, body: str) -> Path:
        path = self.dir / f"{name}.py"
        path.write_text(body, encoding="utf-8")
        return path

    def test_dataclass_under_future_annotations_loads(self):
        path = self._write("future_box", FUTURE_DATACLASS)
        module = sibling.load_module(path, "_t_future_box")
        self.addCleanup(sys.modules.pop, "_t_future_box", None)
        box = module.Box("a", ["x"])
        self.assertEqual((box.label, box.items), ("a", ["x"]))

    def test_module_is_registered_in_sys_modules(self):
        path = self._write("registered", "VALUE = 1\n")
        module = sibling.load_module(path, "_t_registered")
        self.addCleanup(sys.modules.pop, "_t_registered", None)
        self.assertIs(sys.modules["_t_registered"], module)
        self.assertEqual(module.__name__, "_t_registered")

    def test_default_name_is_private_and_stable(self):
        path = self._write("defaulted", "VALUE = 1\n")
        module = sibling.load_module(path)
        self.addCleanup(sys.modules.pop, module.__name__, None)
        self.assertTrue(module.__name__.startswith("_"), "默认名要带下划线前缀，免得盖掉真正的顶层模块")
        self.assertIn("defaulted", module.__name__)

    def test_failed_exec_leaves_nothing_behind(self):
        path = self._write("broken", "raise RuntimeError('boom')\n")
        with self.assertRaises(RuntimeError):
            sibling.load_module(path, "_t_broken")
        self.assertNotIn("_t_broken", sys.modules)

    def test_failed_exec_restores_previous_registration(self):
        previous = object()
        sys.modules["_t_prev"] = previous  # type: ignore[assignment]
        self.addCleanup(sys.modules.pop, "_t_prev", None)
        path = self._write("broken_again", "raise RuntimeError('boom')\n")
        with self.assertRaises(RuntimeError):
            sibling.load_module(path, "_t_prev")
        self.assertIs(sys.modules["_t_prev"], previous)

    def test_missing_file_raises_clear_error(self):
        with self.assertRaises(FileNotFoundError):
            sibling.load_module(self.dir / "nope.py", "_t_nope")
        self.assertNotIn("_t_nope", sys.modules)


class LoadSiblingTests(unittest.TestCase):
    def test_loads_a_script_next_to_the_helper(self):
        module = sibling.load_sibling("slug_rules")
        self.addCleanup(sys.modules.pop, module.__name__, None)
        self.assertEqual(module.validate_slug("charlie-munger"), "charlie-munger")

    def test_loads_a_module_that_defines_a_future_annotations_dataclass(self):
        module = sibling.load_sibling("workspace")  # Workspace 就是 frozen dataclass
        self.addCleanup(sys.modules.pop, module.__name__, None)
        self.assertTrue(hasattr(module, "Workspace"))

    def test_unknown_sibling_is_a_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            sibling.load_sibling("no_such_script")


class SingleLoaderArchitectureTests(unittest.TestCase):
    """scripts/ 与 evaluation/ 的脚本里，只有 sibling.py 能直接碰 spec_from_file_location。"""

    SCANNED = ("scripts", "evaluation/scripts", "evaluation/runtime")
    ALLOWED = {Path("scripts/sibling.py")}

    def _offenders(self) -> list[str]:
        offenders = []
        for base in self.SCANNED:
            for path in sorted((ROOT / base).rglob("*.py")):
                rel = path.relative_to(ROOT)
                if rel in self.ALLOWED:
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    named = (
                        (isinstance(node, ast.Attribute) and node.attr == "spec_from_file_location")
                        or (isinstance(node, ast.Name) and node.id == "spec_from_file_location")
                        or (isinstance(node, ast.alias) and node.name == "spec_from_file_location")
                    )
                    if named:
                        offenders.append(f"{rel.as_posix()}:{getattr(node, 'lineno', '?')}")
        return offenders

    def test_only_the_helper_calls_spec_from_file_location(self):
        self.assertEqual(self._offenders(), [], "改调 sibling.load_module / sibling.load_sibling")


class DocumentedTests(unittest.TestCase):
    def test_architecture_names_the_shared_loader(self):
        text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        self.assertIn("sibling.load_module", text)
        self.assertIn("sibling.load_sibling", text)


if __name__ == "__main__":
    unittest.main()
