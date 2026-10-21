"""数据根可以整体复制或挪动：任务状态里存的路径不能把进度钉死在某个绝对位置。

2026-10-20 实测：把鲁迅的数据根复制到别处、删掉副本里的抽取结果并重置 task_status.json，`mdf status` 仍显示
「分片抽取 ✅ 1/1」——因为状态里存的是原位置的绝对路径，原位置的产物还在。反过来，数据根被挪走（HANDOFF
「发现 0」给的补救）后，状态会一直停在 pending。
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import task_status as ts  # noqa: E402
from workspace import ENV, Workspace  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclass 按模块名查注解
    spec.loader.exec_module(module)
    return module


ps = load_module("_pipeline_status_portable", ROOT / "scripts" / "pipeline_status.py")
TREE = ps.load_stage_tree(ROOT)
FINGERPRINT = "fp-demo"
SHARD_DIR = "sources/demo/processed/local_shards"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def make_corpus(root: Path, *, extracted: bool) -> Path:
    """一份只有一个分片的语料，已 index；返回任务状态文件。"""
    shards = root / SHARD_DIR
    (root / "sources" / "demo" / "raw").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "demo" / "raw" / "corpus.txt").write_text("月有考，岁有稽。", encoding="utf-8")
    write_json(shards / "manifest.json", {
        "input_fingerprint": FINGERPRINT,
        "shards": [{"shard_id": "shard_001", "path": "local_shards/shard_001.json", "token_estimate": 10}],
    })
    write_json(shards / "shard_001.json", {"shard_id": "shard_001"})
    if extracted:
        add_extracts(root)
    return ts.init_stage1a("demo", root=root)


def add_extracts(root: Path) -> None:
    manifest = json.loads((root / SHARD_DIR / "manifest.json").read_text(encoding="utf-8"))
    write_json(root / SHARD_DIR / "shard_001_extracts.json",
               {"shard_id": "shard_001", "input_fingerprint": manifest["input_fingerprint"], "extracts": []})


def extract_row(root: Path):
    return {s.key: s for s in ps.collect_status("demo", root, tree=TREE)}["extract"]


def reset_progress(status_path: Path) -> None:
    """重置 task_status.json：只清进度，不动登记的单元（鲁迅实测的做法）。"""
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update(completed_units=[], output_paths={}, status="pending")
    write_json(status_path, status)


class TempRoots(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.a = Path(self._td.name, "a")
        self.b = Path(self._td.name, "b")
        self.a.mkdir()


class CopiedDataRoot(TempRoots):
    def test_deleting_the_copys_extracts_is_not_hidden_by_the_original(self):
        make_corpus(self.a, extracted=True)
        self.assertEqual(extract_row(self.a).state, "done")
        shutil.copytree(self.a, self.b)
        (self.b / SHARD_DIR / "shard_001_extracts.json").unlink()
        reset_progress(self.b / SHARD_DIR / "task_status.json")
        row = extract_row(self.b)
        self.assertNotEqual(row.state, "done", row.detail)
        self.assertIn("0/1", row.detail)

    def test_extracts_that_exist_only_in_the_copy_count(self):
        make_corpus(self.a, extracted=False)
        shutil.copytree(self.a, self.b)
        add_extracts(self.b)
        self.assertEqual(extract_row(self.a).state, "pending")
        row = extract_row(self.b)
        self.assertEqual(row.state, "done", row.detail)
        self.assertIn("1/1", row.detail)


class MovedDataRoot(TempRoots):
    def test_progress_follows_a_data_root_that_was_moved_away(self):
        make_corpus(self.a, extracted=True)
        shutil.move(str(self.a), str(self.b))
        self.assertFalse(self.a.exists())
        row = extract_row(self.b)
        self.assertEqual(row.state, "done", row.detail)

    def test_stage3_units_follow_a_moved_data_root(self):
        out = self.a / "output" / "demo"
        write_json(out / "framework_core.json", {"person_slug": "demo"})
        status_path = ts.init_stage3("demo", root=self.a)
        shutil.move(str(self.a), str(self.b))
        status = ts.load_status(self.b / "output" / "demo" / "stage3_status.json")
        self.assertEqual(status["completed_units"], ["framework_core"])
        self.assertEqual(status_path.name, "stage3_status.json")


class NewStatusFilesAreRelative(TempRoots):
    def test_stage1a_status_stores_no_absolute_path(self):
        path = make_corpus(self.a, extracted=True)
        status = json.loads(path.read_text(encoding="utf-8"))
        unit = status["input_units"][0]
        self.assertEqual(unit["input_path"], f"{SHARD_DIR}/shard_001.json")
        self.assertEqual(unit["expected_output"], f"{SHARD_DIR}/shard_001_extracts.json")
        self.assertEqual(status["manifest_path"], f"{SHARD_DIR}/manifest.json")
        self.assertEqual(status["output_paths"], {"shard_001": f"{SHARD_DIR}/shard_001_extracts.json"})
        self.assertNotIn(str(self.a), path.read_text(encoding="utf-8"))

    def test_stage3_status_stores_no_absolute_path(self):
        path = ts.init_stage3("demo", root=self.a)
        units = {u["unit_id"]: u for u in json.loads(path.read_text(encoding="utf-8"))["input_units"]}
        self.assertEqual(units["framework_core"]["input_path"], "output/demo")
        self.assertEqual(units["framework_core"]["expected_output"], "output/demo/framework_core.json")
        self.assertEqual(units["framework_zh"]["input_path"], "output/demo/framework_core.json")
        self.assertNotIn(str(self.a), path.read_text(encoding="utf-8"))

    def test_mark_completed_records_the_output_relative_to_the_data_root(self):
        path = make_corpus(self.a, extracted=False)
        add_extracts(self.a)
        ts.mark_completed(path, "shard_001", str(self.a / SHARD_DIR / "shard_001_extracts.json"))
        status = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(status["output_paths"]["shard_001"], f"{SHARD_DIR}/shard_001_extracts.json")

    def test_next_prints_paths_that_exist_for_the_current_root(self):
        path = make_corpus(self.a, extracted=False)
        shutil.copytree(self.a, self.b)
        unit = ts.runnable_units(ts.load_status(self.b / SHARD_DIR / "task_status.json"))[0]
        located = ts.display_unit(unit, ts.workspace_of(self.b / SHARD_DIR / "task_status.json"))
        self.assertEqual(Path(located["input_path"]), (self.b / SHARD_DIR / "shard_001.json").resolve())
        self.assertTrue(Path(located["input_path"]).is_file())
        self.assertTrue(path.is_file())


def strings_in(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)


class IndexedCorpusIsPortable(TempRoots):
    """真实跑一遍 index：processed/ 下没有任何 JSON 把数据根的绝对路径当事实存下来。"""

    def index(self, root: Path) -> None:
        pipeline = load_module("_local_source_pipeline_portable", ROOT / "scripts" / "local_source_pipeline.py")
        raw = root / "sources" / "demo" / "raw"
        raw.mkdir(parents=True)
        book = [f"治天下者，以人為本{i}。" * 3 for i in range(40)]
        (raw / "book.txt").write_text(chr(10).join(book), encoding="utf-8")
        with mock.patch.dict(os.environ, {ENV: str(root)}), contextlib.redirect_stdout(io.StringIO()):
            pipeline.write_index("demo")

    def test_no_processed_json_embeds_the_data_root(self):
        self.index(self.a)
        needles = {str(self.a), self.a.as_posix(), str(self.a.resolve()), self.a.resolve().as_posix()}
        files = sorted((self.a / "sources" / "demo" / "processed").rglob("*.json"))
        self.assertTrue(files)
        for path in files:
            for text in strings_in(json.loads(path.read_text(encoding="utf-8"))):
                with self.subTest(file=path.name, value=text[:60]):
                    self.assertFalse(any(n in text for n in needles), f"{path.name} 存了绝对路径：{text}")

    def test_copied_index_reports_the_copys_own_progress(self):
        self.index(self.a)
        shutil.copytree(self.a, self.b)
        add_extracts(self.a)
        self.assertEqual(extract_row(self.a).state, "done")
        self.assertEqual(extract_row(self.b).state, "pending")


class LegacyAbsolutePaths(TempRoots):
    """旧版状态文件里存的是写入时的绝对路径（Windows 反斜杠或 posix），要重新挂到当前数据根下。"""

    def legacy_status(self, prefix: str, sep: str) -> dict:
        def p(*parts):
            return prefix + sep + sep.join(parts)
        return {
            "schema_version": "task-status-v2", "task_id": "demo:stage1a", "stage": "stage1a",
            "agent_role": "local-source-worker", "status": "pending",
            "input_units": [{
                "unit_id": "shard_001", "unit_type": "local_source_shard",
                "input_path": p("sources", "demo", "processed", "local_shards", "shard_001.json"),
                "expected_output": p("sources", "demo", "processed", "local_shards", "shard_001_extracts.json"),
                "input_fingerprint": FINGERPRINT,
            }],
            "completed_units": [], "pending_units": ["shard_001"], "failed_units": [], "blocked_units": [],
            "failure_counts": {}, "output_paths": {}, "last_error": "",
            "manifest_path": p("sources", "demo", "processed", "local_shards", "manifest.json"),
        }

    def check(self, prefix: str, sep: str):
        make_corpus(self.a, extracted=True)
        path = self.a / SHARD_DIR / "task_status.json"
        write_json(path, self.legacy_status(prefix, sep))
        status = ts.load_status(path)
        self.assertEqual(status["completed_units"], ["shard_001"])
        self.assertEqual(extract_row(self.a).state, "done")
        return status

    def test_windows_path_of_a_root_that_is_gone(self):
        status = self.check("D:\\gone\\worktrees\\lu-xun-acceptance", "\\")
        self.assertEqual(status["output_paths"]["shard_001"], f"{SHARD_DIR}/shard_001_extracts.json")

    def test_posix_path_of_another_machine(self):
        self.check("/home/someone/mdf", "/")

    def test_legacy_path_pointing_at_a_live_old_root_does_not_leak_its_progress(self):
        make_corpus(self.a, extracted=True)  # 原位置：抽取结果还在
        shutil.copytree(self.a, self.b)
        (self.b / SHARD_DIR / "shard_001_extracts.json").unlink()
        write_json(self.b / SHARD_DIR / "task_status.json", self.legacy_status(str(self.a), "/"))
        self.assertNotEqual(extract_row(self.b).state, "done")

    def test_legacy_stage3_path_still_checks_the_person_slug(self):
        out = self.a / "output" / "demo"
        write_json(out / "framework_core.json", {"person_slug": "someone-else"})
        status_path = ts.init_stage3("demo", root=self.a)
        status = json.loads(status_path.read_text(encoding="utf-8"))
        for unit in status["input_units"]:  # 改回旧版的绝对路径（反斜杠）
            for key in ("input_path", "expected_output"):
                unit[key] = "D:\\gone\\" + unit[key].replace("/", "\\")
        status.update(completed_units=[], output_paths={})
        write_json(status_path, status)
        self.assertNotIn("framework_core", ts.load_status(status_path)["completed_units"])


class WorkspacePathRules(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name).resolve()
        self.ws = Workspace(self.root)

    def test_locate_resolves_relative_paths_against_the_data_root(self):
        self.assertEqual(self.ws.locate("sources/demo/x.json"), self.root / "sources" / "demo" / "x.json")

    def test_locate_remounts_foreign_absolute_paths_under_the_data_root(self):
        want = self.root / "output" / "demo" / "frameworks.zh.json"
        self.assertEqual(self.ws.locate("D:\\old\\wt\\output\\demo\\frameworks.zh.json"), want)
        self.assertEqual(self.ws.locate("/srv/mdf/output/demo/frameworks.zh.json"), want)

    def test_locate_uses_the_last_anchor_so_an_output_folder_in_the_old_root_is_harmless(self):
        want = self.root / "sources" / "demo" / "processed" / "m.json"
        self.assertEqual(self.ws.locate("C:\\output\\mdf\\sources\\demo\\processed\\m.json"), want)

    def test_locate_leaves_unrecognised_absolute_paths_alone(self):
        outside = (self.root / ".." / "elsewhere" / "x.txt").resolve()
        self.assertEqual(self.ws.locate(str(outside)), outside)

    def test_portable_gives_posix_paths_relative_to_the_data_root(self):
        self.assertEqual(self.ws.portable(self.root / "sources" / "demo" / "a.json"), "sources/demo/a.json")
        self.assertEqual(self.ws.portable("sources\\demo\\a.json"), "sources/demo/a.json")
        self.assertEqual(self.ws.portable("D:\\old\\output\\demo\\a.json"), "output/demo/a.json")

    def test_containing_finds_the_data_root_from_an_artifact_path(self):
        status = self.root / "sources" / "demo" / "processed" / "local_shards" / "task_status.json"
        self.assertEqual(Workspace.containing(status).data_root, self.root)
        stage3 = self.root / "output" / "demo" / "stage3_status.json"
        self.assertEqual(Workspace.containing(stage3).data_root, self.root)
        self.assertIsNone(Workspace.containing(self.root / "task_status.json"))


if __name__ == "__main__":
    unittest.main()
