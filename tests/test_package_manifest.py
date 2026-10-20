from __future__ import annotations

import json
import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sibling import load_module  # noqa: E402  按路径加载模块的唯一入口（先登记 sys.modules）


pm = load_module(ROOT / "scripts" / "package_manifest.py", "package_manifest")
prov = load_module(ROOT / "scripts" / "verify_provenance.py", "verify_provenance")

CORPUS_TEXT = "天下之事，不难于立法，而难于法之必行。\n其余正文若干。\n"
EVIDENCE_OK = "# 证据\n\n### 法之必行\n\n> 不难于立法，而难于法之必行\n\n- 出处：示例奏疏\n"
EVIDENCE_BAD = "# 证据\n\n### 伪引\n\n> 这句话语料里根本没有出现过\n\n- 出处：示例\n"


def write_corpus(root: Path, slug: str, text: str = CORPUS_TEXT) -> None:
    raw = root / "sources" / slug / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "memorial.txt").write_text(text, encoding="utf-8")


def stage_v6_package(root: Path, evidence: str = EVIDENCE_OK) -> Path:
    staged = root / "staging" / "demo"
    refs = staged / "references"
    refs.mkdir(parents=True)
    (staged / "SKILL.md").write_text("---\nname: demo-wisdom\nformat_version: 6\n---\n", encoding="utf-8")
    (refs / "cases.md").write_text("# cases\n", encoding="utf-8")
    (refs / "evidence.md").write_text(evidence, encoding="utf-8")
    (refs / "voice.md").write_text("# voice\n", encoding="utf-8")
    (staged / "人物档案.md").write_text("# 档案\n", encoding="utf-8")
    return staged


def build_ok_manifest(root: Path) -> tuple[Path, dict]:
    write_corpus(root, "demo")
    staged = stage_v6_package(root)
    p2 = pm.attest_p2(staged / "references" / "evidence.md", "demo", root, prov)
    manifest = pm.build_manifest(
        staged, "demo", format_version=6, clusters=["cluster_law"], p2_attestation=p2,
        review={"verdict": "PASS", "detail": "", "review_sha256": None},
    )
    return staged, manifest


class SafeRelativePathTests(unittest.TestCase):
    def test_accepts_nested_posix_path(self) -> None:
        self.assertTrue(pm.is_safe_relative("references/evidence.md"))
        self.assertTrue(pm.is_safe_relative("人物档案.md"))

    def test_rejects_escapes_and_platform_paths(self) -> None:
        for rel in ("", "../x.md", "a/../../x", "/etc/passwd", "C:/x.md", "references\\x.md", "./SKILL.md", "a//b"):
            with self.subTest(rel=rel):
                self.assertFalse(pm.is_safe_relative(rel))


class CorpusFingerprintTests(unittest.TestCase):
    def test_is_order_independent(self) -> None:
        a = [("a.txt", "甲"), ("b.txt", "乙")]
        self.assertEqual(pm.corpus_fingerprint(a), pm.corpus_fingerprint(list(reversed(a))))

    def test_changes_when_text_changes(self) -> None:
        self.assertNotEqual(
            pm.corpus_fingerprint([("a.txt", "甲")]), pm.corpus_fingerprint([("a.txt", "乙")])
        )

    def test_name_boundary_is_unambiguous(self) -> None:
        # ("ab", x) 与 ("a", "b"+x) 这类拼接歧义不能撞出同一指纹。
        self.assertNotEqual(
            pm.corpus_fingerprint([("ab", "c")]), pm.corpus_fingerprint([("a", "bc")])
        )


class AttestP2Tests(unittest.TestCase):
    def test_passing_evidence_records_pass_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_corpus(root, "demo")
            staged = stage_v6_package(root)
            p2 = pm.attest_p2(staged / "references" / "evidence.md", "demo", root, prov)
            self.assertEqual(p2["status"], "pass")
            self.assertEqual(p2["hard_errors"], 0)
            self.assertEqual(p2["corpus_files"], 1)
            self.assertEqual(p2["evidence_sha256"], pm.sha256_file(staged / "references" / "evidence.md"))
            self.assertTrue(p2["corpus_fingerprint"])

    def test_fabricated_quote_records_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_corpus(root, "demo")
            staged = stage_v6_package(root, evidence=EVIDENCE_BAD)
            p2 = pm.attest_p2(staged / "references" / "evidence.md", "demo", root, prov)
            self.assertEqual(p2["status"], "fail")
            self.assertEqual(p2["hard_errors"], 1)

    def test_empty_corpus_records_fail_without_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staged = stage_v6_package(root)
            p2 = pm.attest_p2(staged / "references" / "evidence.md", "demo", root, prov)
            self.assertEqual(p2["status"], "fail")
            self.assertIsNone(p2["corpus_fingerprint"])


class ReviewVerdictTests(unittest.TestCase):
    def _verdict(self, text: str | None) -> dict:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "review.md"
            if text is not None:
                path.write_text(text, encoding="utf-8")
            return pm.read_review_verdict(path)

    def test_missing_file(self) -> None:
        self.assertEqual(self._verdict(None)["verdict"], "MISSING")

    def test_pass(self) -> None:
        text = "# 质量审查报告\n\n## 裁决\n\n**[PASS]**\n\n综合 4.6/5\n\n## 各维度评分\n\n[FAIL] 不应被读到\n"
        self.assertEqual(self._verdict(text)["verdict"], "PASS")

    def test_revise_keeps_detail(self) -> None:
        result = self._verdict("## 裁决\n\n**[REVISE: 表达 DNA 第 7 维为空]**\n")
        self.assertEqual(result["verdict"], "REVISE")
        self.assertEqual(result["detail"], "表达 DNA 第 7 维为空")

    def test_unfilled_template_placeholder_is_unparseable(self) -> None:
        self.assertEqual(self._verdict("## 裁决\n\n**[PASS / REVISE / FAIL]**\n")["verdict"], "UNPARSEABLE")

    def test_conflicting_verdicts_are_unparseable(self) -> None:
        self.assertEqual(self._verdict("## 裁决\n\n[PASS]\n\n曾经是 [FAIL: x]\n")["verdict"], "UNPARSEABLE")

    def test_no_verdict_section_is_unparseable(self) -> None:
        self.assertEqual(self._verdict("# 报告\n\n[PASS]\n")["verdict"], "UNPARSEABLE")


class BuildAndRoundTripTests(unittest.TestCase):
    def test_lists_every_staged_file_but_not_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            staged, manifest = build_ok_manifest(Path(td))
            self.assertEqual(
                sorted(manifest["files"]),
                ["SKILL.md", "references/cases.md", "references/evidence.md", "references/voice.md", "人物档案.md"],
            )

    def test_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            staged, first = build_ok_manifest(root)
            p2 = pm.attest_p2(staged / "references" / "evidence.md", "demo", root, prov)
            second = pm.build_manifest(
                staged, "demo", format_version=6, clusters=["cluster_law"], p2_attestation=p2,
                review=first["review"],
            )
            self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_write_then_load_round_trips_and_verifies_clean(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            staged, manifest = build_ok_manifest(Path(td))
            path = staged / pm.MANIFEST_NAME
            pm.write_manifest(path, manifest)
            self.assertFalse(path.with_name(path.name + ".tmp").exists())
            loaded, errors = pm.load_manifest(path)
            self.assertEqual(errors, [])
            self.assertEqual(pm.verify_manifest(staged, loaded, "demo"), [])

    def test_legacy_manifest_needs_no_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            staged = Path(td) / "legacy"
            staged.mkdir()
            (staged / "SKILL.md").write_text("---\nname: legacy-wisdom\n---\n", encoding="utf-8")
            manifest = pm.build_manifest(staged, "legacy", format_version=1)
            self.assertNotIn("attestation", manifest)
            self.assertEqual(pm.verify_manifest(staged, manifest, "legacy"), [])


class LoadManifestTests(unittest.TestCase):
    def test_v1_manifest_is_reported_outdated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "manifest.json"
            path.write_text(json.dumps({"format_version": 6, "files": {"SKILL.md": "x"}}), encoding="utf-8")
            manifest, errors = pm.load_manifest(path)
            self.assertIsNone(manifest)
            self.assertTrue(errors[0].startswith("MANIFEST_OUTDATED"))

    def test_missing_and_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "manifest.json"
            self.assertTrue(pm.load_manifest(path)[1][0].startswith("MANIFEST_MISSING"))
            path.write_text("{not json", encoding="utf-8")
            self.assertTrue(pm.load_manifest(path)[1][0].startswith("MANIFEST_PARSE_ERROR"))


class VerifyManifestRejectsTests(unittest.TestCase):
    """发布侧校验必须对每一种该拒的输入报错，而不是报 clean。"""

    def _codes(self, staged: Path, manifest: dict, slug: str = "demo") -> list[str]:
        return [e.split(":", 1)[0] for e in pm.verify_manifest(staged, manifest, slug)]

    def test_tampered_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            staged, manifest = build_ok_manifest(Path(td))
            (staged / "references" / "voice.md").write_text("# 被改过\n", encoding="utf-8")
            self.assertIn("MANIFEST_HASH_MISMATCH", self._codes(staged, manifest))

    def test_stale_leftover_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            staged, manifest = build_ok_manifest(Path(td))
            (staged / "references" / "old_cases.md").write_text("# 旧附件\n", encoding="utf-8")
            self.assertIn("MANIFEST_UNLISTED_FILE", self._codes(staged, manifest))

    def test_listed_file_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            staged, manifest = build_ok_manifest(Path(td))
            (staged / "references" / "cases.md").unlink()
            self.assertIn("MANIFEST_MISSING_FILE", self._codes(staged, manifest))

    def test_path_traversal_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            staged, manifest = build_ok_manifest(Path(td))
            manifest["files"]["../outside.md"] = "0" * 64
            self.assertIn("MANIFEST_UNSAFE_PATH", self._codes(staged, manifest))

    def test_slug_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            staged, manifest = build_ok_manifest(Path(td))
            self.assertIn("MANIFEST_SLUG_MISMATCH", self._codes(staged, manifest, slug="other"))

    def test_evidence_edited_after_p2(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            staged, manifest = build_ok_manifest(Path(td))
            evidence = staged / "references" / "evidence.md"
            evidence.write_text(EVIDENCE_BAD, encoding="utf-8")
            manifest["files"]["references/evidence.md"] = pm.sha256_file(evidence)  # 清单也同步改了
            self.assertIn("MANIFEST_P2_STALE", self._codes(staged, manifest))

    def test_failed_p2_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_corpus(root, "demo")
            staged = stage_v6_package(root, evidence=EVIDENCE_BAD)
            p2 = pm.attest_p2(staged / "references" / "evidence.md", "demo", root, prov)
            manifest = pm.build_manifest(staged, "demo", format_version=6, clusters=["c"], p2_attestation=p2)
            self.assertIn("MANIFEST_P2_NOT_PASSED", self._codes(staged, manifest))

    def test_v6_without_attestation_or_clusters(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            staged, manifest = build_ok_manifest(Path(td))
            manifest["clusters"] = []
            del manifest["attestation"]
            codes = self._codes(staged, manifest)
            self.assertIn("MANIFEST_NO_CLUSTERS", codes)
            self.assertIn("MANIFEST_NO_P2_ATTESTATION", codes)

    def test_bad_review_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            staged, manifest = build_ok_manifest(Path(td))
            manifest["review"] = {"verdict": "LGTM"}
            self.assertIn("MANIFEST_BAD_REVIEW", self._codes(staged, manifest))


if __name__ == "__main__":
    unittest.main()
