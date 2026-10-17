"""统一入口 scripts/mdf.py：子命令解析、--root、JSON 输出、对旧脚本的原样转交。"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MDF = ROOT / "scripts" / "mdf.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mdf = load_module("_mdf_under_test", MDF)


def run(*argv: str) -> tuple[int, str, str]:
    """进程内调用 mdf.main，捕获 stdout/stderr；argparse 的 SystemExit 转成返回码。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = mdf.main(list(argv))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def run_process(*argv: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MDF), *argv], cwd=ROOT, capture_output=True,
        encoding="utf-8", errors="replace", env={**os.environ, **(env or {})}, timeout=120,
    )


class MdfCliTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def test_stages_json_is_the_config_tree(self):
        code, out, _ = run("stages", "--json")
        self.assertEqual(code, 0)
        config = json.loads((ROOT / "config" / "pipeline_stages.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(out), config)

    def test_init_then_status_under_custom_root(self):
        code, out, _ = run("init", "demo", "--root", self.root)
        self.assertEqual(code, 0)
        for rel in ("sources/demo/raw", "sources/demo/processed", "output/demo"):
            self.assertTrue((Path(self.root) / rel).is_dir(), rel)
        code, out, _ = run("init", "demo", "--root", self.root)
        self.assertIn("目录均已存在", out)

        code, out, _ = run("status", "demo", "--json", "--root", self.root)
        data = json.loads(out)
        self.assertEqual(data["schema"], "pipeline-status-v1")
        self.assertEqual(data["next"]["key"], "sources")

    def test_next_text_names_the_chapter(self):
        code, out, _ = run("next", "demo", "--root", self.root)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("阶段 0 · 意图澄清与初始化 / 目录初始化："), out)

    def test_env_var_sets_data_root(self):
        old = os.environ.get("MDF_DATA_ROOT")
        os.environ["MDF_DATA_ROOT"] = self.root
        try:
            run("init", "demo")
        finally:
            if old is None:
                os.environ.pop("MDF_DATA_ROOT")
            else:
                os.environ["MDF_DATA_ROOT"] = old
        self.assertTrue((Path(self.root) / "output" / "demo").is_dir())

    def test_invalid_slug_is_rejected_not_normalised(self):
        code, _, err = run("status", "Demo Person", "--root", self.root)
        self.assertEqual(code, 2)
        self.assertIn("不合法", err)
        self.assertFalse((Path(self.root) / "sources").exists())

    def test_doctor_json(self):
        code, out, _ = run("doctor", "--json", "--root", self.root)
        data = json.loads(out)
        self.assertEqual(data["schema"], "mdf-doctor-v1")
        self.assertEqual(code, 0 if data["ok"] else 1)
        names = {c["name"] for c in data["checks"]}
        self.assertIn("config/pipeline_stages.json", names)
        self.assertTrue(all(not c["required"] for c in data["checks"] if c["name"].startswith("可选依赖")))

    def test_validate_runs_against_data_root(self):
        code, out, _ = run("validate", "published", "demo", "--root", self.root)
        self.assertEqual(code, 1)
        self.assertIn("demo", out)


class PassthroughTests(unittest.TestCase):
    """转交的子命令要原样传参（含 --help），并把 SystemExit("说明") 的说明打印出来。"""

    def test_dash_arguments_reach_the_delegate(self):
        proc = run_process("index", "--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("local_source_pipeline.py index", proc.stdout)

    def test_delegate_error_message_is_not_swallowed(self):
        code, _, err = run("stats", "zz-no-such-person")
        self.assertEqual(code, 1)
        self.assertIn("Missing manifest", err)

    def test_delegate_restores_argv_and_cwd(self):
        argv, cwd = list(sys.argv), os.getcwd()
        run("manifest", "--help")
        self.assertEqual(sys.argv, argv)
        self.assertEqual(os.getcwd(), cwd)

    def test_top_level_help_lists_passthrough_commands(self):
        code, out, _ = run("--help")
        self.assertEqual(code, 0)
        for name in mdf.PASSTHROUGH:
            self.assertIn(name, out)


if __name__ == "__main__":
    unittest.main()
