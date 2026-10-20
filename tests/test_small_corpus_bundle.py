"""小语料一次跑完（墨子试跑第 14 条，用户 2026-10-20 决定）。

每个新进程都要重读几十万 token 的上下文，墨子试跑 9 次调用 $6.04，大头是缓存读。语料只有 1 个分片时，
分片抽取、合并与本地补充、原则提取合成一个 `mdf run` 单位：一份简报、三个角色依次执行、三个检查点都跑。
多分片时照旧分开。
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harness  # noqa: E402
import pipeline_status as ps  # noqa: E402
import run_unit  # noqa: E402

TREE = ps.load_stage_tree()
ALL = [s["id"] for p in TREE["phases"] for s in p["steps"]]
BUNDLE = ["extract", "reduce", "principles"]


class Plan(unittest.TestCase):
    def plan(self, step_id, shards, pending=ALL):
        return run_unit.plan(TREE, step_id, pending=pending, shard_count=shards)

    def test_single_shard_bundles_the_three_steps(self):
        unit = self.plan("extract", 1)
        self.assertEqual(unit.id, "small-corpus")
        self.assertEqual(unit.step_ids, BUNDLE)
        self.assertTrue(unit.is_bundle)

    def test_several_shards_keep_steps_apart(self):
        for shards in (2, 5):
            with self.subTest(shards=shards):
                unit = self.plan("extract", shards)
                self.assertEqual((unit.id, unit.step_ids, unit.is_bundle), ("extract", ["extract"], False))

    def test_no_shard_manifest_keeps_steps_apart(self):
        self.assertFalse(self.plan("extract", None).is_bundle)

    def test_resume_bundles_only_what_is_left(self):
        left = [s for s in ALL if s != "extract"]
        self.assertEqual(self.plan("reduce", 1, pending=left).step_ids, ["reduce", "principles"])
        self.assertFalse(self.plan("principles", 1, pending=["principles"]).is_bundle, "只剩一步就不用合并")

    def test_rerunning_a_finished_step_is_just_that_step(self):
        left = [s for s in ALL if s != "extract"]
        self.assertEqual(self.plan("extract", 1, pending=left).step_ids, ["extract"])

    def test_bundle_id_can_be_asked_for_directly(self):
        self.assertEqual(self.plan("small-corpus", 1).step_ids, BUNDLE)
        with self.assertRaises(ValueError):
            self.plan("small-corpus", 3)

    def test_bundle_runs_every_checkpoint(self):
        commands = self.plan("extract", 1).checkpoints(phase_finished=lambda _: False)
        self.assertEqual(commands, [
            "python scripts/task_status.py summary sources/{slug}/processed/local_shards/task_status.json --strict",
            "python scripts/mdf.py validate sources {slug}",
            "python scripts/mdf.py validate principles {slug}",
        ], "三个检查点都跑，不看阶段有没有收尾")

    def test_single_step_keeps_phase_checkpoint_for_the_end_of_the_phase(self):
        unit = self.plan("extract", 3)
        self.assertEqual(len(unit.checkpoints(phase_finished=lambda _: False)), 1)
        self.assertEqual(unit.checkpoints(phase_finished=lambda _: True)[-1],
                         "python scripts/mdf.py validate sources {slug}")

    def test_network_ban_and_classification_carry_over(self):
        unit = self.plan("extract", 1)
        self.assertTrue(unit.forbids_network, "reduce 禁网，合并单位整体禁网")
        self.assertIn("classification", unit.requires, "principles 要用户确认的类目")


class TreeDeclaration(unittest.TestCase):
    def test_bundles_name_consecutive_agent_steps(self):
        bundles = TREE.get("bundles") or []
        self.assertTrue(bundles)
        for bundle in bundles:
            with self.subTest(bundle=bundle["id"]):
                self.assertNotIn(bundle["id"], ALL, "单位 id 不能和步骤 id 撞名")
                start = ALL.index(bundle["steps"][0])
                self.assertEqual(ALL[start:start + len(bundle["steps"])], bundle["steps"], "必须是阶段树里相邻的步骤")
                for step_id in bundle["steps"]:
                    _, step = harness.find_step(TREE, step_id)
                    self.assertIn("agent", step["executor"].split("|"))
                self.assertGreaterEqual(bundle["max_shards"], 1)


class Corpus(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        src = self.root / "sources" / "demo"
        (src / "raw").mkdir(parents=True)
        (src / "raw" / "墨子.txt").write_text("兼相爱，交相利。", encoding="utf-8")
        (src / "processed" / "local_shards").mkdir(parents=True)
        (self.root / "output" / "demo").mkdir(parents=True)
        (src / "classification.json").write_text(
            json.dumps({"primary": "governance", "secondary": ["philosophy"]}), encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def shards(self, n: int):
        manifest = {"shard_count": n, "sampling_mode": "exhaustive",
                    "shards": [{"shard_id": f"shard_{i:03d}", "token_estimate": 9000} for i in range(1, n + 1)]}
        (self.root / "sources" / "demo" / "processed" / "local_shards" / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")

    def brief(self, step="extract"):
        with redirect_stderr(io.StringIO()):
            return harness.build_brief("demo", step, self.root)


class BundleBrief(Corpus):
    def test_shard_count_is_read_from_the_manifest(self):
        self.assertIsNone(run_unit.shard_count(self.root, "demo"))
        self.shards(1)
        self.assertEqual(run_unit.shard_count(self.root, "demo"), 1)

    def test_one_brief_three_roles_three_checkpoints(self):
        self.shards(1)
        unit_id, text = self.brief()
        self.assertEqual(unit_id, "small-corpus")
        for role in ("local-source-worker", "source-researcher", "principle-extractor"):
            self.assertIn(f"## 角色定义：{role}", text)
        self.assertLess(text.index("## 角色定义：local-source-worker"), text.index("## 角色定义：principle-extractor"))
        for command in ("task_status.py summary sources/demo/processed/local_shards/task_status.json --strict",
                        "python scripts/mdf.py validate sources demo",
                        "python scripts/mdf.py validate principles demo"):
            self.assertIn(command, text)
        self.assertIn("python scripts/mdf.py reduce demo", text, "合并脚本由同一个进程在两个角色之间跑")
        self.assertIn("**禁止网络检索**", text)
        self.assertIn("不得再派子代理", text)
        self.assertIn("主类 governance", text)
        self.assertIn("## 阶段 1 · 素材采集", text)
        self.assertIn("## 阶段 2 · 原则提取", text)
        self.assertNotIn("\r", text)

    def test_separate_data_root_gets_runnable_script_and_checkpoints(self):
        self.shards(1)
        _, text = self.brief()  # 临时目录不是仓库：数据根与代码根分离
        data = self.root.resolve().as_posix()
        self.assertIn(f"MDF_DATA_ROOT='{data}' python", text)
        reduce_line = next(line for line in text.splitlines() if "先运行" in line)
        self.assertIn("mdf.py reduce demo", reduce_line)
        self.assertIn("MDF_DATA_ROOT=", reduce_line, "mdf reduce 不认当前目录，也不收 --root")
        self.assertIn("`scripts/mdf.py` 的命令", text, "路径约定要说清 mdf 怎么找数据根")

    def test_auto_pick_lands_on_the_bundle(self):
        self.shards(1)
        self.assertEqual(self.brief(None)[0], "small-corpus")

    def test_several_shards_get_the_old_brief(self):
        self.shards(2)
        unit_id, text = self.brief()
        self.assertEqual(unit_id, "extract")
        self.assertNotIn("principle-extractor", text)

    def test_bundle_needs_the_confirmed_categories(self):
        self.shards(1)
        (self.root / "sources" / "demo" / "classification.json").unlink()
        with self.assertRaises(SystemExit):
            self.brief()

    def test_cli_prints_launch_commands_without_web_tools(self):
        self.shards(1)
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            harness.main(["brief", "demo", "--root", str(self.root), "--harness", "claude-code"])
        self.assertIn("small-corpus.md", out.getvalue())
        self.assertIn("--disallowedTools WebSearch,WebFetch", out.getvalue())


class StageCard(Corpus):
    def test_card_points_at_the_bundle_when_there_is_one_shard(self):
        self.shards(1)
        stages = ps.collect_status("demo", self.root)
        card = ps.render_card("demo", stages, step_key="extract", shard_count=1)
        self.assertIn("mdf.py run demo small-corpus", card)
        self.assertIn("3 个检查点都跑", card)
        self.assertIn("validate principles demo", card, "闸门一行列出全部检查点")

    def test_mdf_next_card_reads_the_shard_count(self):
        self.shards(1)
        spec = importlib.util.spec_from_file_location("_mdf_for_bundle_test", ROOT / "scripts" / "mdf.py")
        mdf = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mdf
        spec.loader.exec_module(mdf)
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            mdf.main(["next", "demo", "--card", "--root", str(self.root)])
        self.assertIn("small-corpus", out.getvalue())

    def test_card_keeps_the_step_command_with_several_shards(self):
        self.shards(3)
        stages = ps.collect_status("demo", self.root)
        card = ps.render_card("demo", stages, step_key="extract", shard_count=3)
        self.assertIn("mdf.py run demo extract", card)
        self.assertNotIn("small-corpus", card)


if __name__ == "__main__":
    unittest.main()
