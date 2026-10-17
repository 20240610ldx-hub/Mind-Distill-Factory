"""语料清洗与质量闸门（scripts/clean_corpus.py）、统一解码（text_decoding.py）及其在 index / P2 中的接线。"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


decoding = load("_text_decoding_ut", ROOT / "scripts" / "text_decoding.py")
cc = load("_clean_corpus_ut", ROOT / "scripts" / "clean_corpus.py")
prov = load("_verify_provenance_cc", ROOT / "scripts" / "verify_provenance.py")
ps = load("_pipeline_status_cc", ROOT / "scripts" / "pipeline_status.py")

PROSE = "子曰：「學而時習之，不亦說乎？有朋自遠方來，不亦樂乎？人不知而不慍，不亦君子乎？」"


def body(n: int = 30) -> list[str]:
    return [f"第{i}段：{PROSE}" for i in range(n)]


def assert_subtractive(test: unittest.TestCase, original: str, cleaned: str) -> None:
    """只删不改：保留下来的每一行都必须逐字出现在原文里。"""
    source_lines = set(original.replace("\r\n", "\n").split("\n"))
    for line in cleaned.split("\n"):
        if line.strip():
            test.assertIn(line, source_lines, f"清洗改写了文本：{line!r}")


class DecodingTests(unittest.TestCase):
    def test_encodings(self):
        self.assertEqual(decoding.decode_bytes(PROSE.encode("utf-8"))[:2], (PROSE, "utf-8"))
        self.assertEqual(decoding.decode_bytes("张居正".encode("gb18030"))[:2], ("张居正", "gb18030"))
        self.assertEqual(decoding.decode_bytes("張居正".encode("utf-16"))[:2], ("張居正", "utf-16"))

    def test_utf8_bom_is_kept_like_before(self):
        # 旧版 P2 按 utf-8 读、保留 BOM 字符；指纹兼容要求这点不变。
        self.assertEqual(decoding.decode_bytes(b"\xef\xbb\xbfabc").text, "\ufeffabc")

    def test_never_silently_falls_back_to_latin1(self):
        decoded = decoding.decode_bytes(b"\xff\xff\xff\xfe\x00\x81")
        self.assertNotEqual(decoded.encoding, "latin-1")


class CleanTextTests(unittest.TestCase):
    def clean(self, lines):
        text = "\n".join(lines)
        cleaned, entry = cc.clean_text(text)
        assert_subtractive(self, text, cleaned)
        return cleaned, entry

    def test_clean_prose_is_accepted_unchanged(self):
        cleaned, entry = self.clean(body())
        self.assertEqual(entry["verdict"], "accepted")
        self.assertEqual(entry["actions"], {})
        self.assertEqual(cleaned.strip(), "\n".join(body()))

    def test_gutenberg_boilerplate(self):
        text = ["The Project Gutenberg eBook of X", "license blah",
                "*** START OF THE PROJECT GUTENBERG EBOOK MEDITATIONS ***", *body(),
                "*** END OF THE PROJECT GUTENBERG EBOOK MEDITATIONS ***", "Section 1. General Terms of Use"]
        cleaned, entry = self.clean(text)
        self.assertNotIn("license blah", cleaned)
        self.assertNotIn("General Terms", cleaned)
        self.assertGreater(entry["actions"]["gutenberg_boilerplate_chars"], 0)

    def test_site_ads_and_page_numbers(self):
        text = ["本电子书由某某txt小说网整理提供下载", "扫码关注公众号获取更多好书", *body(10), "12", *body(10), "- 13 -",
                *body(10), "第14页", "更多精彩电子书请访问本站"]
        cleaned, entry = self.clean(text)
        for noise in ("txt小说网", "公众号", "第14页", "更多精彩"):
            self.assertNotIn(noise, cleaned)
        self.assertEqual(entry["actions"]["page_number_lines"], 3)
        self.assertEqual(entry["samples"]["site_ad_lines"][0], "本电子书由某某txt小说网整理提供下载")

    def test_isolated_numbers_are_kept(self):
        cleaned, entry = self.clean([*body(5), "1", *body(5), "2"])
        self.assertNotIn("page_number_lines", entry["actions"])
        self.assertIn("\n1\n", cleaned)

    def test_publisher_line_without_site_cue_is_kept(self):
        cleaned, _ = self.clean(["本书由人民出版社出版", *body()])
        self.assertIn("本书由人民出版社出版", cleaned)

    def test_running_heads_removed_but_speaker_labels_kept(self):
        lines = []
        for i in range(12):
            lines += [str(i + 1), "张居正集 · 书牍卷", "问：", f"第{i}问的内容是什么？", "答：", PROSE]
        cleaned, entry = self.clean(lines)
        self.assertNotIn("张居正集", cleaned)
        self.assertEqual(cleaned.count("问："), 12)
        self.assertEqual(cleaned.count("答："), 12)
        self.assertIn("heavy_removal", entry["flags"])  # 页眉占了 >10% 的字符
        self.assertEqual(entry["verdict"], "flagged")

    def test_routine_removal_does_not_ask_for_review(self):
        lines = []
        for i in range(20):
            lines += [f"≦ {i} ≧", "论语集注", *body(6)]
        _, entry = self.clean(lines)
        self.assertEqual(entry["actions"]["running_head_lines"], 20)
        self.assertEqual(entry["verdict"], "accepted")

    def test_repeated_headings_without_pagination_are_kept(self):
        # 书信集里反复出现的收信人抬头不是页眉
        lines = []
        for i in range(20):
            lines += ["To Edwin M. Stanton", f"Sir: please see to the matter of regiment {i} at once."]
        cleaned, entry = self.clean(lines)
        self.assertEqual(cleaned.count("To Edwin M. Stanton"), 20)
        self.assertNotIn("running_head_lines", entry["actions"])

    def test_numbered_headings_are_kept(self):
        lines = []
        for i in range(1, 20):
            lines += [str(i * 3), f"FEDERALIST {i}", "To the People of the State of New York:", PROSE]
        cleaned, _ = self.clean(lines)
        self.assertIn("FEDERALIST 7", cleaned)

    def test_transcript_q_a_labels_are_kept(self):
        lines = []
        for i in range(15):
            lines += ["Q  Q", f"What did you do in {i}?", "A  A", "I worked on the bomb project."]
        cleaned, _ = self.clean(lines)
        self.assertEqual(cleaned.count("Q  Q"), 15)

    def test_page_markers_are_location_anchors(self):
        lines = []
        for i in range(12):
            lines += [f"===== PDF_PAGE {3390 + i} =====", PROSE, f"≦ {i} ≧", PROSE, f"--- Page {i} ---", PROSE]
        cleaned, entry = self.clean(lines)
        self.assertIn("===== PDF_PAGE 3395 =====", cleaned)
        self.assertIn("≦ 7 ≧", cleaned)
        self.assertIn("--- Page 3 ---", cleaned)
        self.assertEqual(entry["actions"], {})

    def test_real_world_false_positives_are_kept(self):
        # 来自真实语料校准：单字「网」「站」+「提供/关注」曾把这些正文行当广告删掉。
        keep = [
            "1．给研究像生物体以及神经网络这种复杂的对象提供了一种全新的研究方法。",
            "受了这项工作。而他首先关注的是海外营业网点。",
            "唐太宗建立弘文馆，收集天下图书，网罗天下学",
            "与P1_曾国藩家书.txt内容重复，图像扫描版不可直接使用",
            "https://docs.historyrussia.org/ru/nodes/226958",
            "- Vasilevsky, The Matter of My Whole Life: Google Books record",
        ]
        cleaned, entry = self.clean([*keep, *body(10)])
        for line in keep:
            self.assertIn(line, cleaned)
        self.assertEqual(entry["actions"], {})

    def test_google_scan_disclaimer(self):
        disclaimer = ("This is a digital copy of a book that was preserved for generations on library shelves.\n\n"
                      "+ Make non-commercial use of the files We designed Google Book Search for use by individuals\n\n"
                      "+ Keep it legal Whatever your use, remember that you are responsible")
        cleaned, entry = self.clean([disclaimer, "", *body(10)])
        self.assertNotIn("Google Book Search", cleaned)
        self.assertEqual(entry["actions"]["scan_disclaimer_paragraphs"], 3)

    def test_index_block_removed(self):
        index = [f"Stoicism{i}, {i * 3}, {i * 5}–{i * 5 + 2}" for i in range(1, 20)]
        cleaned, entry = self.clean([*body(10), "Index", *index, *body(5)])
        self.assertNotIn("Stoicism7", cleaned)
        self.assertEqual(entry["actions"]["index_toc_lines"], 19)
        self.assertEqual(cleaned.count("第"), 15)

    def test_toc_block_removed(self):
        toc = [f"第{i}章 论治国……………………{i * 10}" for i in range(1, 15)]
        cleaned, entry = self.clean(["目录", *toc, *body(10)])
        self.assertEqual(entry["actions"]["index_toc_lines"], 14)

    def test_modern_annotation_flag(self):
        cleaned, entry = self.clean([*body(5), "【注释】一", "【译文】二", "【注释】三"])
        self.assertIn("modern_annotation", entry["flags"])
        self.assertEqual(entry["annotation_markers"]["【注释】"], 2)

    def test_rejections(self):
        utf8_as_gbk = PROSE.encode("utf-8").decode("gbk", errors="replace") * 20
        self.assertIn("mojibake_utf8_as_gbk", cc.clean_text(utf8_as_gbk)[1]["reasons"])
        latin = ("Thoughts on the café and naïve résumé — “quoted” " * 40).encode("utf-8").decode("cp1252", errors="replace")
        self.assertIn("mojibake_utf8_as_latin", cc.clean_text(latin)[1]["reasons"])
        self.assertIn("private_use_glyphs", cc.clean_text("正文" * 50 + "\ue001" * 20)[1]["reasons"])
        self.assertIn("replacement_chars", cc.clean_text("正文" * 50 + "\ufffd" * 10)[1]["reasons"])
        self.assertEqual(cc.clean_text("12\n13\n14")[1]["reasons"], ["empty_after_cleaning"])
        for entry in (cc.clean_text(utf8_as_gbk)[1],):
            self.assertEqual(entry["verdict"], "rejected")

    def test_short_text_is_flagged(self):
        self.assertIn("very_short", cc.clean_text(PROSE)[1]["flags"])


class CleanPdfTests(unittest.TestCase):
    def pages(self, n=10):
        return [f"论语集注\n{PROSE}\n{PROSE}第{i}页的内容\n{PROSE}\n{i + 1}" for i in range(n)]

    def test_running_heads_and_folios(self):
        cleaned, entry = cc.clean_pdf_pages(self.pages())
        self.assertEqual(len(cleaned), 10)
        self.assertFalse(any("论语集注" in p for p in cleaned))
        self.assertTrue(all(PROSE in p for p in cleaned))
        self.assertGreaterEqual(entry["actions"]["pdf_running_head_lines"], 10)
        for raw, kept in zip(self.pages(), cleaned):
            assert_subtractive(self, raw, kept)

    def test_ocr_misread_folios_count_as_one_running_head(self):
        # 《熱風》整本 OCR：页码认成「-28一」「13-」「一81一」，逐字比较时每种都凑不够 30% 的页
        folios = ["-28一", "13-", "一81一", "-35-", "4", "46一", "30-", "-57一", "--9-", "12"]
        # 页边比较时阿拉伯数字归一，所以各页正文用天干区分
        pages = [f"三十{num}\n{PROSE}{stem}\n{folio}" for num, stem, folio in zip("一二三四五六七八九十", "甲乙丙丁戊己庚辛壬癸", folios)]
        cleaned, entry = cc.clean_pdf_pages(pages)
        for page, stem, folio in zip(cleaned, "甲乙丙丁戊己庚辛壬癸", folios):
            self.assertFalse(page.endswith(folio), folio)
            self.assertIn(f"{PROSE}{stem}", page)
        self.assertEqual(entry["actions"]["pdf_running_head_lines"], 10)
        # 章节号「三十一」之类的汉字数字不算页码
        self.assertTrue(all(page.startswith("三十") for page in cleaned))

    def test_index_page_dropped(self):
        index_page = "\n".join(f"Virtue{i}, {i}, {i + 40}" for i in range(15))
        cleaned, entry = cc.clean_pdf_pages([*self.pages(3), index_page])
        self.assertEqual(cleaned[3], "")
        self.assertEqual(entry["actions"]["index_toc_pages"], 1)

    def test_ocr_gate(self):
        _, entry = cc.clean_pdf_pages(["", "", ""], {"pages_total": 3, "ocr_required": 3, "ocr_ok": 0})
        self.assertEqual(entry["verdict"], "rejected")
        self.assertIn("ocr_unavailable", entry["reasons"])
        _, entry = cc.clean_pdf_pages(self.pages(4), {"pages_total": 4, "ocr_required": 1, "ocr_ok": 0})
        self.assertIn("ocr_incomplete", entry["flags"])
        _, entry = cc.clean_pdf_pages(self.pages(4), {"pages_total": 4, "ocr_required": 2, "ocr_ok": 2,
                                                       "mean_confidence": 0.41})
        self.assertIn("low_ocr_confidence", entry["flags"])

    def test_ocr_thresholds_follow_calibration(self):
        def gate(ok, conf, total=4):
            return cc.clean_pdf_pages(self.pages(total), {"pages_total": total, "ocr_required": ok, "ocr_ok": ok,
                                                           "mean_confidence": conf})[1]
        # 用过 OCR 就标 ocr_text：P2 只能拿 OCR 文字比对，认错的字它查不出来
        self.assertIn("ocr_text", gate(1, 0.99)["flags"])
        self.assertNotIn("ocr_text", cc.clean_pdf_pages(self.pages(4))[1]["flags"])
        # 0.9 以下：校准实测逐字存活率 ≤26%
        self.assertNotIn("low_ocr_confidence", gate(4, 0.93)["flags"])
        self.assertIn("low_ocr_confidence", gate(4, 0.87)["flags"])
        # 0.6 以下且过半页靠 OCR：乱码，整份退回；OCR 只占少数页时只标不退
        garbled = gate(3, 0.5)
        self.assertEqual(garbled["verdict"], "rejected")
        self.assertIn("ocr_garbled", garbled["reasons"])
        self.assertNotEqual(gate(1, 0.5)["verdict"], "rejected")
        self.assertIn("low_ocr_confidence", gate(1, 0.5)["flags"])

    def test_unread_ocr_lines_are_flagged(self):
        def gate(suspect):
            return cc.clean_pdf_pages(self.pages(4), {"pages_total": 4, "ocr_required": 2, "ocr_ok": 2,
                                                       "mean_confidence": 0.95, "suspect_lines": suspect})[1]
        # 《吶喊》国图本：两整列压在印章上，置信度 0.92 照样「通过」——只有行数对不上才看得出来
        self.assertIn("ocr_lines_dropped", gate(2)["flags"])
        self.assertNotIn("ocr_lines_dropped", gate(0)["flags"])
        self.assertNotEqual(gate(2)["verdict"], "rejected", "漏行只标不退：其余文字仍可用")
        self.assertTrue(cc.PAGE_MARKER_RE.match("--- Page 61 (OCR, 2 unread) ---"), "清洗规则不得删掉带漏行数的页码标记")


class NearDuplicateTests(unittest.TestCase):
    def test_reformatted_copy_is_duplicate_and_priority_decides(self):
        a = "\n".join(body(40))
        b = a.replace("\n", "\n\n").replace("，", ", ")
        result = cc.find_near_duplicates([("p5_copy.txt", 5, b), ("p1_main.txt", 1, a)])
        self.assertEqual(result["p5_copy.txt"]["duplicate_of"], "p1_main.txt")
        self.assertEqual(result["p5_copy.txt"]["relation"], "near_duplicate")

    def test_excerpt_contained_in_book(self):
        book = "\n".join(f"{i}：{PROSE}{i * 7}其為人也孝弟，而好犯上者，鮮矣{i}" for i in range(200))
        excerpt = "\n".join(book.split("\n")[50:70])
        result = cc.find_near_duplicates([("book.txt", 5, book), ("excerpt.txt", 5, excerpt)])
        self.assertEqual(result["excerpt.txt"]["relation"], "contained")
        # 精选摘录优先级更高时两者都保留
        self.assertEqual(cc.find_near_duplicates([("book.txt", 5, book), ("p1_excerpt.txt", 1, excerpt)]), {})

    def test_unrelated_texts(self):
        other = "治天下者，以人為本。考成之法，月有考，歲有稽。" * 50
        self.assertEqual(cc.find_near_duplicates([("a.txt", 5, "\n".join(body(40))), ("b.txt", 5, other)]), {})


class ReportTests(unittest.TestCase):
    def test_report_shape_and_render(self):
        _, ok = cc.clean_text("\n".join(body()))
        _, bad = cc.clean_text("")
        report = cc.build_report({"b.txt": bad, "a.txt": ok, "c.txt": {"verdict": "duplicate", "flags": [], "reasons": [],
                                                                       "duplicate": {"duplicate_of": "a.txt"}}})
        self.assertEqual(report["schema"], "cleaning-report-v1")
        self.assertEqual(report["source_count"], 3)
        self.assertEqual(report["accepted_sources"], ["a.txt"])
        self.assertEqual(report["rejected_sources"][0]["file"], "b.txt")
        self.assertEqual(report["duplicate_sources"][0]["duplicate_of"], "a.txt")
        text = cc.render_report("demo", report)
        self.assertIn("❌ 被拒", text)
        self.assertIn("清洗后没有正文", text)


class IndexIntegrationTests(unittest.TestCase):
    """真实跑一遍 index：清洗报告、重复判定、分片带质量标记、pipeline_status 的清洗步骤。"""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self._old = os.environ.get("MDF_DATA_ROOT")
        os.environ["MDF_DATA_ROOT"] = str(self.root)
        self.raw = self.root / "sources" / "demo" / "raw"
        self.raw.mkdir(parents=True)
        self.pipeline = load("_local_source_pipeline_cc", ROOT / "scripts" / "local_source_pipeline.py")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("MDF_DATA_ROOT", None)
        else:
            os.environ["MDF_DATA_ROOT"] = self._old
        self._td.cleanup()

    def test_index_writes_cleaning_report(self):
        main = "\n".join(body(60))
        (self.raw / "p1_main.txt").write_text(main, encoding="utf-8")
        (self.raw / "copy_gbk.txt").write_bytes(main.encode("gb18030"))          # 同文异码 → 近重复
        (self.raw / "same.txt").write_text(main, encoding="utf-8")                # 字节相同 → 完全重复
        (self.raw / "broken.txt").write_text(main.encode("utf-8").decode("gbk", errors="replace"), encoding="utf-8")
        (self.raw / "annotated.txt").write_text(
            "\n".join(["【注释】甲", "【译文】乙", "【注释】丙"] + [f"治天下者，以人為本{i}。" * 3 for i in range(30)]),
            encoding="utf-8")
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            self.pipeline.write_index("demo")
        processed = self.root / "sources" / "demo" / "processed"
        report = json.loads((processed / "cleaning_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["source_count"], 5)
        self.assertEqual([r["file"] for r in report["rejected_sources"]], ["broken.txt"])
        dups = {d["file"]: d for d in report["duplicate_sources"]}
        self.assertEqual(set(dups), {"copy_gbk.txt", "same.txt"})
        self.assertEqual(dups["copy_gbk.txt"]["duplicate_of"], "p1_main.txt")
        self.assertEqual(report["sources"]["copy_gbk.txt"]["encoding"], "gb18030")

        manifest = json.loads((processed / "local_shards" / "manifest.json").read_text(encoding="utf-8"))
        status = {f["file"]: f["status"] for f in manifest["files"]}
        self.assertEqual(status["broken.txt"], "rejected_by_cleaning")
        self.assertEqual(status["copy_gbk.txt"], "duplicate")
        files_in_shards = {s for shard in manifest["shards"] for s in shard["source_files"]}
        self.assertEqual(files_in_shards, {"p1_main.txt", "annotated.txt"})
        shard = json.loads((processed / "local_shards" / "shard_001.json").read_text(encoding="utf-8"))
        flags = {p["source_file"]: p["quality_flags"] for p in shard["passages"]}
        self.assertIn("modern_annotation", flags["annotated.txt"])

        stages = {s.key: s for s in ps.collect_status("demo", self.root)}
        self.assertEqual(stages["clean"].state, "blocked")
        self.assertIn("1 个被拒", stages["clean"].detail)

    def test_p2_reads_gbk_raw_like_index(self):
        (self.raw / "gbk.txt").write_bytes(("前言\n" + PROSE).encode("gb18030"))
        corpus = prov.load_corpus("demo", self.root)
        self.assertIsNotNone(prov.find_verbatim("學而時習之，不亦說乎", corpus))


if __name__ == "__main__":
    unittest.main()
