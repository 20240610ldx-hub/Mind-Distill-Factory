"""流水线阶段树（config/pipeline_stages.json）与状态检测（scripts/pipeline_status.py）。"""

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ps = load_module("_pipeline_status_under_test", ROOT / "scripts" / "pipeline_status.py")
pkg_fixtures = load_module("_package_v6_fixtures_ps", ROOT / "tests" / "test_package_v6.py")
TREE = ps.load_stage_tree(ROOT)


def by_id(stages):
    return {s.key: s for s in stages}


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class StageTreeTests(unittest.TestCase):
    def test_every_step_has_a_check_and_every_check_a_step(self):
        steps = [s["id"] for p in TREE["phases"] for s in p["steps"]]
        self.assertEqual(len(steps), len(set(steps)), "step id 重复")
        self.assertEqual(set(steps), set(ps.CHECKS))

    def test_phase_orders_are_contiguous_and_ids_unique(self):
        orders = [p["order"] for p in TREE["phases"]]
        self.assertEqual(orders, list(range(len(orders))))
        ids = [p["id"] for p in TREE["phases"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_chapter_titles_follow_policy(self):
        fmt = TREE["chapter_policy"]["title_format"]
        for phase in TREE["phases"]:
            chapter = phase["chapter"]
            self.assertEqual(chapter["title"], fmt.format(order=phase["order"], title=phase["title"]))
            self.assertLessEqual(len(chapter["title"]), 40)
            self.assertTrue(chapter["summary"].strip())

    def test_executor_values_are_known(self):
        for phase in TREE["phases"]:
            for step in phase["steps"]:
                for who in step["executor"].split("|"):
                    self.assertIn(who, ps.EXECUTOR_LABELS, step["id"])
                if "agent" in step["executor"]:
                    self.assertTrue(step.get("agent"), f"{step['id']} 由 agent 执行却没写 agent")

    def test_commands_go_through_the_unified_cli(self):
        for phase in TREE["phases"]:
            for cmd in [s.get("command") for s in phase["steps"]] + [phase.get("checkpoint")]:
                if cmd:
                    self.assertTrue(cmd.startswith("python scripts/mdf.py "), cmd)


class StatusDetectionTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.processed = self.root / "sources" / "demo" / "processed"

    def tearDown(self):
        self._td.cleanup()

    def status(self, check=False):
        return by_id(ps.collect_status("demo", self.root, check=check, tree=TREE))

    def add_raw(self, name="corpus.txt"):
        raw = self.root / "sources" / "demo" / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        (raw / name).write_text("月有考，岁有稽。", encoding="utf-8")

    def test_empty_root_points_to_init(self):
        stages = ps.collect_status("demo", self.root, tree=TREE)
        nxt = ps.next_stage(stages)
        self.assertEqual(nxt.key, "init")
        self.assertIn("mdf.py init demo", nxt.next_action)
        self.assertEqual(nxt.chapter["title"], "阶段 0 · 意图澄清与初始化")

    def test_titles_and_chapters_come_from_the_tree(self):
        stages = ps.collect_status("demo", self.root, tree=TREE)
        expected = [(p["id"], s["title"]) for p in TREE["phases"] for s in p["steps"]]
        self.assertEqual([(s.phase, s.title) for s in stages], expected)

    def test_raw_files_unlock_index(self):
        self.add_raw()
        (self.root / "sources" / "demo" / "raw" / "scan.docx").write_bytes(b"x")
        s = self.status()
        self.assertEqual(s["sources"].state, "done")
        self.assertIn("不支持的格式", s["sources"].detail)
        self.assertEqual(s["index"].state, "pending")
        self.assertIn("mdf.py index demo", s["index"].next_action)

    def test_web_only_run_skips_local_steps(self):
        (self.root / "sources" / "demo").mkdir(parents=True)
        s = self.status()
        for key in ("index", "clean", "extract"):
            self.assertEqual(s[key].state, "skipped", key)
        self.assertNotIn("user_sources.json", s["reduce"].detail)

    def test_cleaning_report_states(self):
        self.add_raw()
        write_json(self.processed / "cleaning_report.json",
                   {"source_count": 3, "flagged_sources": ["a"], "rejected_sources": []})
        s = self.status()
        self.assertEqual(s["clean"].state, "done")
        self.assertIn("1 个需人工复核", s["clean"].detail)
        write_json(self.processed / "cleaning_report.json",
                   {"source_count": 3, "flagged_sources": [], "rejected_sources": ["b"]})
        self.assertEqual(self.status()["clean"].state, "blocked")

    def test_legacy_shards_without_cleaning_report_are_skipped(self):
        self.add_raw()
        write_json(self.processed / "local_shards" / "manifest.json", {"shards": [{"shard_id": "shard_001"}]})
        s = self.status()
        self.assertEqual(s["index"].state, "done")
        self.assertEqual(s["clean"].state, "skipped")

    def test_corrupt_task_status_is_reported_not_raised(self):
        self.add_raw()
        path = self.processed / "local_shards" / "task_status.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.status()["extract"].state, "failed")

    def test_review_verdicts(self):
        out = self.root / "output" / "demo"
        out.mkdir(parents=True)
        self.assertEqual(self.status()["review"].state, "pending")
        (out / "review.md").write_text("# 审查\n\n## 裁决\n\n[PASS]\n", encoding="utf-8")
        self.assertEqual(self.status()["review"].state, "done")
        (out / "review.md").write_text("# 审查\n\n## 裁决\n\n[REVISE: 证据不足]\n", encoding="utf-8")
        review = self.status()["review"]
        self.assertEqual(review.state, "failed")
        self.assertIn("Stage 4", review.next_action)

    def test_outdated_manifest_suggests_backfill(self):
        gallery = self.root / "gallery" / "demo"
        write_json(gallery / "manifest.json", {"files": {}})
        publish = self.status()["publish"]
        self.assertEqual(publish.state, "failed")
        self.assertIn("manifest backfill demo", publish.next_action)

    def test_framework_review_must_pass(self):
        out = self.root / "output" / "demo"
        write_json(out / "framework_core.json", {})
        write_json(out / "frameworks.zh.json", {})
        (out / "framework_alignment_review.md").write_text("[REVISE]", encoding="utf-8")
        self.assertEqual(self.status()["frameworks"].state, "failed")
        (out / "framework_alignment_review.md").write_text("结论：[PASS]", encoding="utf-8")
        self.assertEqual(self.status()["frameworks"].state, "done")


CASE_INDEX = "## 案例索引\n\n| demo-c1-1 | demo-c1-2 | demo-counter-1 |\n"


class CompliantPackageTests(unittest.TestCase):
    """PackageFixture + 案例索引 = 全规则合规的 v6 包：--check 下 P1–P6 必须报完成。"""

    def test_check_runs_package_gates(self):
        with tempfile.TemporaryDirectory() as td:
            fx = pkg_fixtures.PackageFixture(td)
            fx.write_skill(pkg_fixtures.build_skill_md(extra=CASE_INDEX))
            stages = by_id(ps.collect_status("demo", fx.root, tree=TREE))
            self.assertEqual(stages["assemble"].detail, "v6 中文核心")
            self.assertEqual(stages["attachments"].state, "done")
            self.assertEqual(stages["gates"].state, "pending")
            checked = by_id(ps.collect_status("demo", fx.root, check=True, tree=TREE))
            self.assertEqual(checked["gates"].state, "done", checked["gates"].detail)

    def test_check_reports_gate_failures(self):
        with tempfile.TemporaryDirectory() as td:
            fx = pkg_fixtures.PackageFixture(td)
            fx.write_ref("voice.md", pkg_fixtures.build_voice_md(3))
            checked = by_id(ps.collect_status("demo", fx.root, check=True, tree=TREE))
            self.assertEqual(checked["gates"].state, "failed")
            self.assertIn("validate package demo", checked["gates"].next_action)


class RenderingTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "sources" / "demo" / "raw").mkdir(parents=True)
        (self.root / "sources" / "demo" / "raw" / "a.txt").write_text("文本", encoding="utf-8")
        self.stages = ps.collect_status("demo", self.root, tree=TREE)

    def tearDown(self):
        self._td.cleanup()

    def test_phase_states_aggregate_steps(self):
        phases = {p["id"]: p["state"] for p in ps.phase_states(self.stages, TREE)}
        self.assertEqual(phases["init"], "done")
        self.assertEqual(phases["stage1"], "in_progress")
        self.assertEqual(phases["stage6"], "pending")

    def test_json_is_serialisable_and_carries_next_chapter(self):
        data = json.loads(json.dumps(ps.to_json("demo", self.stages, TREE), ensure_ascii=False))
        self.assertEqual(data["schema"], ps.SCHEMA)
        self.assertFalse(data["complete"])
        self.assertEqual(data["next"]["key"], "index")
        self.assertEqual(data["next"]["chapter"]["title"], "阶段 1 · 素材采集")
        self.assertEqual(len(data["phases"]), len(TREE["phases"]))

    def test_markdown_groups_by_phase(self):
        md = ps.to_markdown("demo", self.stages, TREE)
        self.assertIn("| 1 · 素材采集 |", md)
        self.assertEqual(md.count("| 1 · 素材采集 |"), 1, "同一 phase 只在首行标注")
        self.assertRegex(md, r"\*\*下一步（阶段 1 · 素材采集 / .+）：\*\*")

    def test_detail_pipes_are_escaped(self):
        self.stages[0].detail = "a|b"
        self.assertIn("a\\|b", ps.to_markdown("demo", self.stages, TREE))

    def test_tree_render_lists_every_chapter(self):
        text = ps.render_tree(TREE)
        for phase in TREE["phases"]:
            self.assertIn(phase["chapter"]["title"], text)
        self.assertTrue(re.search(r"章节规则：", text))


if __name__ == "__main__":
    unittest.main()
