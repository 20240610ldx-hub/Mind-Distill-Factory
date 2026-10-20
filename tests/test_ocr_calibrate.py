"""OCR 校准：指标、引擎缓存、合成扫描件走 index 同一条 PDF→OCR 路径（用假引擎，离线）。"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ocr_calibrate as oc  # noqa: E402
from sibling import load_module  # noqa: E402

HAVE_RENDER = all(importlib.util.find_spec(m) is not None for m in ("fitz", "PIL"))
TRUTH = ["子曰：學而時習之，不亦說乎？有朋自遠方來，不亦樂乎？", "月有考，岁有稽，事情办没办成，到期一查便知。"]


def fake_engine(pages: list[str], corrupt=None, confidence: float = 0.97):
    """按调用顺序把第 i 次调用当作第 i 页，返回真值（可选损坏）；模拟 OCR 会在行尾断行。"""
    calls = {"n": 0}

    def run(_image: bytes) -> tuple[str, float]:
        text = pages[calls["n"] % len(pages)]
        calls["n"] += 1
        text = corrupt(text) if corrupt else text
        return text[: len(text) // 2] + "\n" + text[len(text) // 2:], confidence

    return run


def every_nth_wrong(n: int):
    return lambda text: "".join("口" if i % n == n - 1 and not ch.isspace() else ch for i, ch in enumerate(text))


class MetricTests(unittest.TestCase):
    def test_levenshtein(self):
        self.assertEqual(oc.levenshtein("", "abc"), 3)
        self.assertEqual(oc.levenshtein("考成之法", "考成之法"), 0)
        self.assertEqual(oc.levenshtein("考成之法", "考城之法"), 1)
        self.assertEqual(oc.levenshtein("abc", "ac"), 1)

    def test_line_breaks_do_not_count_as_errors(self):
        row = oc.page_metrics(TRUTH[1], "月有考，岁有稽，事情办没\n办成，到期一查便知。")
        self.assertEqual(row["cer"], 0.0)
        self.assertEqual(row["sentences_verbatim"], row["sentences"])

    def test_one_wrong_character_loses_the_sentence(self):
        row = oc.page_metrics(TRUTH[1], "月有考，岁有稽，事情办没办戍，到期一查便知。")
        self.assertGreater(row["cer"], 0)
        self.assertLess(row["sentences_verbatim"], row["sentences"])
        self.assertTrue(row["lost_sentences"])

    def test_sample_pages_avoid_covers(self):
        self.assertEqual(oc.sample_pages(100, 3), [25, 50, 75])
        self.assertEqual(oc.sample_pages(2, 3), [1, 2])
        self.assertEqual(oc.sample_pages(5, 1), [2])

    def test_truth_file_splits_pages(self):
        pages = oc.load_truth()
        self.assertEqual(len(pages), 8)
        self.assertTrue(all(pages))
        sentences = sum(oc.page_metrics(p, p)["sentences"] for p in pages)
        self.assertGreaterEqual(sentences, 50, "样张太小，阈值就是在三五句话上调出来的")

    def test_double_line_notes_lay_out_right_then_left(self):
        # 刻本双行小注：大字读到小注处，先读右小列再读左小列，一列放不下接到下一列，仍是先右后左
        self.assertEqual(oc.layout_vertical("甲乙〔一二三四五〕丙", rows=4), [
            (0, 0, 0, "甲"), (0, 1, 0, "乙"),
            (0, 2.0, 1, "一"), (0, 2.5, 1, "二"), (0, 3.0, 1, "三"), (0, 2.0, 2, "四"), (0, 2.5, 2, "五"),
            (1, 0, 0, "丙")])
        self.assertEqual(oc.layout_vertical("甲〔一二三四五六七〕", rows=2), [
            (0, 0, 0, "甲"), (0, 1.0, 1, "一"), (0, 1.5, 1, "二"), (0, 1.0, 2, "三"), (0, 1.5, 2, "四"),
            (1, 0.0, 1, "五"), (1, 0.5, 1, "六"), (1, 0.0, 2, "七")])
        plain = "學而時習之不亦說乎\n有朋自遠方來"
        self.assertEqual([(c, r, ch) for c, r, _sub, ch in oc.layout_vertical(plain, rows=4)],
                         [(c, r, ch) for c, col in enumerate(oc._wrap(plain, 4)) for r, ch in enumerate(col)],
                         "没有小注的页与原来一字一格的排法完全相同")

    def test_note_markers_are_not_truth(self):
        self.assertEqual(oc.strip_notes("學而時習之〔習，鳥數飛也。〕不亦說乎"), "學而時習之習，鳥數飛也。不亦說乎")
        row = oc.page_metrics("學而時習之，不亦說乎〔說，音悅。學之為言效也。〕", "學而時習之，不亦說乎說，音悅。學之為言效也。")
        self.assertEqual((row["cer"], row["sentences"], row["sentences_verbatim"]), (0.0, 2, 2))

    def test_notes_truth_file(self):
        pages = oc.load_truth(oc.DEFAULT_TRUTH.with_name("sample_notes_zh.txt"))
        self.assertEqual(len(pages), 3)
        self.assertTrue(all(oc.NOTE_RE.search(p) for p in pages), "每页都要有双行小注")

    def test_english_sentences_split_on_full_stop_not_decimals(self):
        row = oc.page_metrics("Version 2.0 lists 3.32M tokens. We are met on a great field.", "")
        self.assertEqual(row["sentences"], 2)


class EngineCacheTests(unittest.TestCase):
    def tearDown(self):
        oc.pdf_quality._RUNNERS.pop("counting", None)
        oc.pdf_quality.RUNNER_FACTORIES.pop("counting", None)

    def test_engine_is_built_once_per_process(self):
        built = []

        def factory():
            built.append(1)
            return lambda image: ("文", 0.9)

        oc.pdf_quality.RUNNER_FACTORIES["counting"] = factory
        for _ in range(5):
            self.assertIs(oc.pdf_quality.get_runner("counting"), oc.pdf_quality.get_runner("counting"))
        self.assertEqual(len(built), 1, "模型加载很慢，不能每页新建一次引擎")

    def test_missing_dependency_is_not_cached(self):
        def factory():
            raise ImportError("not installed")

        oc.pdf_quality.RUNNER_FACTORIES["counting"] = factory
        with self.assertRaises(ImportError):
            oc.pdf_quality.get_runner("counting")
        self.assertNotIn("counting", oc.pdf_quality._RUNNERS)


@unittest.skipUnless(HAVE_RENDER, "需要 PyMuPDF 与 Pillow（pip install -e .[pdf,ocr]）")
class SyntheticScanTests(unittest.TestCase):
    def tearDown(self):
        oc.pdf_quality.clear_injected_runners()

    def test_perfect_engine_round_trips_through_the_index_path(self):
        oc.pdf_quality.register_runner("fake", fake_engine(TRUTH))
        report = oc.calibrate(TRUTH, font=None, degrades=["none"])
        [level] = report["levels"]
        self.assertEqual(level["document_type"], "pure_image_pdf", "合成页必须没有文字层，才会走 OCR")
        self.assertEqual((level["ocr_ok_pages"], level["pages"]), (2, 2))
        self.assertEqual(level["cer"], 0.0)
        self.assertEqual(level["verbatim_survival"], 1.0)
        self.assertNotIn("low_ocr_confidence", level["gate_flags"])

    def test_noisy_low_confidence_engine_is_flagged(self):
        oc.pdf_quality.register_runner("fake", fake_engine(TRUTH, corrupt=every_nth_wrong(9), confidence=0.8))
        [level] = oc.calibrate(TRUTH, font=None, degrades=["heavy"])["levels"]
        self.assertGreater(level["cer"], 0.05)
        self.assertLess(level["verbatim_survival"], 1.0)
        self.assertIn("low_ocr_confidence", level["gate_flags"])
        self.assertIn("逐字丢失的句子", oc.render_calibration({"font": None, "dpi": 200,
                                                          "low_confidence_threshold": 0.6, "levels": [level]}))

    def test_scan_reports_each_page(self):
        oc.pdf_quality.register_runner("fake", fake_engine(TRUTH))
        with tempfile.TemporaryDirectory() as td:
            pdf = oc.build_pdf([oc.render_page(t, None) for t in TRUTH], Path(td) / "scan.pdf")
            report = oc.scan(pdf)
        self.assertEqual(report["ocr_ok"], 2)
        self.assertEqual([r["ocr_status"] for r in report["pages"]], ["ok", "ok"])
        self.assertEqual({r["backend"] for r in report["pages"]}, {"fake"})

    def test_scan_reads_selected_pages_from_the_original_file(self):
        # 拷进临时 PDF 再渲染，分层压缩的扫描件会变图：抽页必须在原文件上读，导出的图就是 OCR 读的那张
        seen: list[bytes] = []
        oc.pdf_quality.register_runner("fake", lambda image: (seen.append(image), ("文字", 0.97))[1])
        calls = []
        real = oc.lsp.extract_pdf_pages

        def spy(path, **kwargs):
            calls.append((Path(path), kwargs.get("page_numbers")))
            return real(path, **kwargs)

        with tempfile.TemporaryDirectory() as td, mock.patch.object(oc.lsp, "extract_pdf_pages", spy):
            pdf = oc.build_pdf([oc.render_page(t, None) for t in TRUTH + TRUTH[:1]], Path(td) / "scan.pdf")
            report = oc.scan(pdf, "fake", "2", Path(td) / "out")
            exported = (Path(td) / "out" / "p0002.png").read_bytes()
        self.assertEqual(calls, [(pdf, [2])])
        self.assertEqual([r["page"] for r in report["pages"]], [2])
        self.assertEqual(report["pages_in_file"], 3)
        self.assertEqual(seen, [exported])

    def test_extract_pdf_pages_subset_keeps_page_numbers(self):
        oc.pdf_quality.register_runner("fake", lambda image: ("文字", 0.97))
        with tempfile.TemporaryDirectory() as td:
            pdf = oc.build_pdf([oc.render_page(t, None) for t in TRUTH + TRUTH[:1]], Path(td) / "scan.pdf")
            pages, meta = oc.lsp.extract_pdf_pages(pdf, ocr_backend="fake", page_numbers=[3, 1, 9])
        self.assertEqual([p["page_number"] for p in pages], [3, 1])
        self.assertEqual((meta["page_count"], meta["ocr_page_count"]), (3, 2))

    def test_degrade_levels_render(self):
        for level in oc.DEGRADE:
            with self.subTest(level=level):
                self.assertTrue(oc.render_page(TRUTH[0], None, degrade=level).startswith(b"\x89PNG"))


FAKE_PADDLEOCR_JSON = r'''
import base64, json, sys
print("PaddleOCR-json v1.4", flush=True)
print("OCR init completed.", flush=True)
for line in sys.stdin:
    image = base64.b64decode(json.loads(line)["image_base64"])
    if image == b"blank":
        reply = {"code": 101, "data": "No text found in image."}
    elif image == b"broken":
        reply = {"code": 203, "data": "image decode failed"}
    else:
        reply = {"code": 100, "data": [{"box": [[0, 0], [90, 0], [90, 30], [0, 30]], "score": 0.9, "text": "月有考"},
                                       {"box": [[0, 40], [90, 40], [90, 70], [0, 70]], "score": 0.7, "text": "岁有稽"}]}
    print(json.dumps(reply), flush=True)
'''


def box(x: float, y: float, w: float, h: float) -> list[list[float]]:
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


class EngineAdapterTests(unittest.TestCase):
    def test_rapidocr_v3_output_object(self):
        out = mock.Mock(boxes=[box(0, 0, 90, 30), box(0, 40, 90, 30), box(0, 80, 400, 30)],
                        txts=("月有考", "岁有稽", "管用"), scores=(0.9, 0.7, 0.36))
        fake = mock.Mock(RapidOCR=mock.Mock(return_value=mock.Mock(return_value=out)))
        with mock.patch.dict(sys.modules, {"rapidocr": fake}):
            text, conf, details = oc.pdf_quality._rapidocr_runner()(b"png")
        self.assertEqual(text, "月有考\n岁有稽", "低于 0.5 的行不进文本")
        self.assertAlmostEqual(conf, 0.8)
        self.assertEqual(details["dropped_lines"], 1, "但要数出来：一整行没认出来")
        params = fake.RapidOCR.call_args.kwargs["params"]
        self.assertEqual(params["Global.text_score"], 0.0, "要引擎交回所有行，丢弃由我们计数")

    def test_rapidocr_v3_empty_page(self):
        fake = mock.Mock(RapidOCR=mock.Mock(return_value=mock.Mock(
            return_value=mock.Mock(boxes=None, txts=None, scores=None))))
        with mock.patch.dict(sys.modules, {"rapidocr": fake}):
            self.assertEqual(oc.pdf_quality._rapidocr_runner()(b"png")[:2], ("", 0.0))

    def test_rapidocr_falls_back_to_legacy_package(self):
        legacy = mock.Mock(RapidOCR=mock.Mock(return_value=mock.Mock(
            return_value=([[box(0, 0, 90, 30), "月有考", 0.9], [[0, 9], "岁有稽", "0.7"]], 0.1))))
        with mock.patch.dict(sys.modules, {"rapidocr": None, "rapidocr_onnxruntime": legacy}):
            text, conf, _details = oc.pdf_quality._rapidocr_runner()(b"png")
        self.assertEqual(text, "月有考\n岁有稽", "坏框（[0, 9]）不影响出字")
        self.assertAlmostEqual(conf, 0.8)

    def test_paddleocr_json_pipe_protocol(self):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "fake_paddleocr_json.py"
            script.write_text(FAKE_PADDLEOCR_JSON, encoding="utf-8")
            pipe = oc.pdf_quality.PaddleOcrJsonPipe([sys.executable, "-I", str(script)], cwd=Path(td))
            try:
                text, conf, details = pipe(b"page")
                self.assertEqual(text, "月有考\n岁有稽")
                self.assertAlmostEqual(conf, 0.8)
                self.assertEqual(details["layout"], "horizontal")
                self.assertEqual(pipe(b"blank")[:2], ("", 0.0), "code 101 是图里没字，不是错误")
                with self.assertRaises(RuntimeError):
                    pipe(b"broken")
                self.assertEqual(pipe(b"page")[0], "月有考\n岁有稽", "一次失败之后进程仍可用")
            finally:
                pipe.close()

    def test_paddleocr_json_pipe_that_never_inits(self):
        with self.assertRaises(RuntimeError):
            oc.pdf_quality.PaddleOcrJsonPipe([sys.executable, "-I", "-c", "print('loading')"], init_timeout=10)

    def test_paddleocr_json_needs_explicit_location(self):
        with mock.patch.dict("os.environ", {"MDF_PADDLEOCR_JSON": ""}):
            self.assertIsNone(oc.pdf_quality.paddleocr_json_exe())
            with self.assertRaises(ImportError):
                oc.pdf_quality._paddleocr_json_runner()
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "PaddleOCR-json.exe").write_bytes(b"")
            with mock.patch.dict("os.environ", {"MDF_PADDLEOCR_JSON": td}):
                self.assertEqual(oc.pdf_quality.paddleocr_json_exe(), Path(td) / "PaddleOCR-json.exe")

    def test_backend_pin_keeps_injected_runner_first(self):
        oc.pdf_quality.register_runner("fake", lambda image: ("文", 0.9))
        try:
            with mock.patch.dict("os.environ", {"MDF_OCR_BACKEND": "paddleocr_json"}):
                self.assertEqual(oc.pdf_quality.ocr_candidates(), ["fake", "paddleocr_json"])
                self.assertEqual(oc.pdf_quality.ocr_candidates("rapidocr"), ["rapidocr"])
            with mock.patch.dict("os.environ", {"MDF_OCR_BACKEND": ""}):
                self.assertEqual(oc.pdf_quality.ocr_candidates(), ["fake", *oc.pdf_quality.RUNNER_FACTORIES])
        finally:
            oc.pdf_quality.clear_injected_runners()


def column(x: float, y: float, text: str, score: float = 0.95, w: float = 40, h: float | None = None):
    """竖排一列：宽 w，高按字数（每字 w 高）。"""
    return (box(x, y, w, h if h is not None else w * len(text)), text, score)


class LineLayoutTests(unittest.TestCase):
    """真实扫描抽查（《吶喊》国图本 p61、明刻《四書経筵直解》p12）发现的两类问题。"""

    def texts(self, lines):
        return [t for _b, t, _s in lines]

    def test_vertical_page_reads_right_to_left(self):
        # 引擎按框的上边缘排序：起得高的列排前面，与阅读顺序无关
        engine_order = [column(100, 0, "夜收了旗關門"), column(300, 20, "星期日的早晨"),
                        column(200, 10, "我的一位前輩"), column(400, 60, "頭髮的故事")]
        ordered, layout = oc.pdf_quality.order_lines(engine_order)
        self.assertEqual(layout, "vertical")
        self.assertEqual(self.texts(ordered), ["頭髮的故事", "星期日的早晨", "我的一位前輩", "夜收了旗關門"])

    def test_column_segments_read_top_to_bottom(self):
        lines = [column(200, 300, "便很不高興"), column(300, 0, "我說"), column(200, 0, "正走到我的寓裏")]
        ordered, _ = oc.pdf_quality.order_lines(lines)
        self.assertEqual(self.texts(ordered), ["我說", "正走到我的寓裏", "便很不高興"])

    def test_two_page_spread_starts_with_right_page(self):
        lines = [column(350, 0, "學問之精密而"), column(400, 0, "止於信文王之"),
                 column(850, 0, "件都有始終盡"), column(900, 0, "繼續熙是光明")]
        ordered, _ = oc.pdf_quality.order_lines(lines)
        self.assertEqual(self.texts(ordered), ["繼續熙是光明", "件都有始終盡", "止於信文王之", "學問之精密而"])

    def test_running_heads_stay_at_page_edges(self):
        # 《鲁迅入门读本》p100：横排页眉「第三編 閱讀魯迅(中) 98」曾被并进竖列、插在正文中间
        lines = [column(300, 100, "全是黑沈沈的"), (box(40, 10, 120, 40), "第三編", 0.99),
                 column(200, 100, "妹子是被大哥喫了"), (box(200, 10, 200, 40), "閱讀魯迅(中)", 0.99),
                 (box(330, 10, 60, 40), "98", 0.99), column(100, 100, "在還教人傷心"),
                 (box(40, 900, 60, 40), "77", 0.9)]
        ordered, layout = oc.pdf_quality.order_lines(lines)
        self.assertEqual(layout, "vertical")
        self.assertEqual(self.texts(ordered),
                         ["第三編", "閱讀魯迅(中)", "98", "全是黑沈沈的", "妹子是被大哥喫了", "在還教人傷心", "77"])

    def test_spaced_running_head_split_into_single_chars_stays_at_page_top(self):
        # 《熱風》1947 年版 p41：页眉「熱　風」字距拉开，拆成两个单字框，按 x 插进了正文列之间
        lines = [column(300, 100, "的奴才的脚底下學得"), (box(215, 20, 40, 40), "熱", 0.99),
                 column(240, 100, "自然完全不在話下了"), column(190, 100, "但最奇怪的是七年"),
                 (box(60, 20, 40, 40), "風", 0.99), column(100, 140, "說了這話"),
                 (box(100, 100, 40, 40), "我", 0.99),  # 列首单字框：没有整个高过列顶，留在列里
                 column(50, 100, "也未曾經驗開口不得"), (box(100, 900, 80, 30), "-35-", 0.9)]
        ordered, layout = oc.pdf_quality.order_lines(lines)
        self.assertEqual(layout, "vertical")
        self.assertEqual(self.texts(ordered),
                         ["風", "熱", "的奴才的脚底下學得", "自然完全不在話下了", "但最奇怪的是七年",
                          "我", "說了這話", "也未曾經驗開口不得", "-35-"])

    def test_running_head_glued_to_a_column_does_not_lift_the_column_top(self):
        # 《熱風》p37：「風」和最左一列粘成一个框，从页眉高度起；「熱」仍要归到页首
        lines = [column(300, 100, "這藥原來也已發明"), column(240, 100, "就是科學一味"),
                 (box(200, 20, 40, 40), "熱", 0.99), column(150, 100, "祇希望那班精神上"),
                 column(50, 20, "風們成了祖先的時候")]
        ordered, _ = oc.pdf_quality.order_lines(lines)
        self.assertEqual(self.texts(ordered)[0], "熱")

    def test_horizontal_page_keeps_engine_order(self):
        lines = [(box(0, 0, 600, 30), "Photons: Particles of Light", 0.99),
                 (box(0, 40, 600, 30), "the second line of the page", 0.99),
                 (box(500, 900, 30, 20), "50", 0.9)]
        ordered, layout = oc.pdf_quality.order_lines(lines)
        self.assertEqual(layout, "horizontal")
        self.assertEqual(ordered, lines)

    def test_dropped_and_short_lines_are_counted_specks_are_not(self):
        lines = [column(300, 0, "星期日的早晨我揭去一張隔夜的日曆"),
                 column(250, 0, "一", score=0.495, h=880),       # 整列压在印章上：框在，字没认出来
                 column(200, 0, "管", score=0.6, h=880),         # 认出了，但只有该有字数的零头
                 (box(150, 500, 20, 20), "C", 0.3)]              # 斑点：不算一行字
        text, conf, details = oc.pdf_quality.summarize_lines(lines)
        self.assertEqual(text, "星期日的早晨我揭去一張隔夜的日曆\n管")
        self.assertAlmostEqual(conf, (0.95 + 0.6) / 2)
        self.assertEqual(details, {"layout": "vertical", "lines": 2, "dropped_lines": 1, "short_lines": 1,
                                   "doubtful_lines": 0, "undetected_lines": 0})

    def test_low_score_long_lines_are_doubtful(self):
        # 刻本双行小注被并成一行、草书手稿：字数够，分数在 0.5–0.7，内容多半不对
        lines = [column(300, 0, "大學之道在明明德在親民在止於至善"),
                 column(250, 0, "而育當作帝學有者大之也明者明之", score=0.57),   # 计
                 column(200, 0, "此之謂空靈不怎樣瘦損量不痛哉", score=0.75),     # 0.7–0.8 对错参半，不计
                 column(150, 0, "工有", score=0.53, h=880),                     # 只认出两个字：算 short，不重复计
                 (box(100, 500, 20, 20), "C", 0.6)]                             # 斑点：不算一行字
        _text, _conf, details = oc.pdf_quality.summarize_lines(lines)
        self.assertEqual((details["doubtful_lines"], details["short_lines"]), (1, 1))
        self.assertEqual(oc.pdf_quality.suspect_count(details), 2)

    def test_dropped_box_widened_by_glosses_counts_by_page_glyph_size(self):
        # 《四書経筵直解》p12：経文夹小字音注，框被撑到 1.4 倍宽，按自身短边只有 3.9 字，按本页字号是 5.5 字
        body = [column(1000 - 50 * k, 0, "繼續熙是光明敬止是無不敬而安所") for k in range(4)]
        widened = (box(760, 0, 56, 220), "洪結竹猗猗", 0.475)
        title = column(640, 0, "大學", w=120)                     # 大字号章题：2 字占 2 格，不算只认出一半
        seal = (box(560, 300, 72, 210), "高表", 0.34)               # 《吶喊》p141 的「圖書」馆藏印：1.8 字宽，不是正文
        stamp = (box(520, 900, 49, 165), "CDI", 0.35)               # 《吶喊》p61 的「國家」印：只 1.2 字宽，但读不出汉字
        _text, _conf, details = oc.pdf_quality.summarize_lines(body + [widened, title, seal, stamp])
        self.assertEqual((details["dropped_lines"], details["short_lines"]), (1, 0))

    def test_undetected_columns_are_inferred_from_column_gaps(self):
        # 《大學中庸》国图本 p20：透墨的列根本没被框出来，只能从列距推
        pitch = 50
        detected = [column(1000 - pitch * k, 0, "君子之道費而隱夫婦之愚") for k in (0, 1, 2, 9, 10)]
        self.assertEqual(oc.pdf_quality.undetected_columns(detected), 6, "第 2 与第 9 列之间缺 6 列")
        regular = [column(1000 - pitch * k, 0, "君子之道費而隱夫婦之愚") for k in range(6)]
        self.assertEqual(oc.pdf_quality.undetected_columns(regular), 0)
        blank = [column(1000 - pitch * k, 0, "君子之道費而隱夫婦之愚") for k in (0, 1, 3, 4)]
        self.assertEqual(oc.pdf_quality.undetected_columns(blank), 0, "单个空列是分段或章题，不算漏检")
        self.assertEqual(oc.pdf_quality.undetected_columns(detected[:2]), 0, "少于 3 列不推算")
        # 《鲁迅入门读本》p100：章题「十一」前后各空一列，短框也占位，不算漏检
        heading = [column(1000 - pitch * k, 0, "君子之道費而隱夫婦之愚") for k in (0, 1, 2, 6, 7, 8)]
        heading.append(column(1000 - pitch * 4, 0, "十一"))
        self.assertEqual(oc.pdf_quality.undetected_columns(heading), 0)
        heading.append((box(700, -60, 200, 30), "第三編 閱讀魯迅", 0.99))  # 横排页眉不占列位
        self.assertEqual(oc.pdf_quality.undetected_columns(heading), 0)
        page = oc.pdf_quality.summarize_lines(detected)[2]
        self.assertEqual((page["undetected_lines"], oc.pdf_quality.suspect_count(page)), (6, 6))

    def test_latin_lines_are_not_mistaken_for_short(self):
        # 拉丁字母比字高窄，一行的字数总多于框的长宽比，不会误报
        _, _, details = oc.pdf_quality.summarize_lines([(box(0, 0, 600, 30), "Photons: Particles of Light", 0.99)])
        self.assertEqual(details["short_lines"], 0)

    def test_run_ocr_merges_engine_diagnostics(self):
        oc.pdf_quality.register_runner("diag", lambda image: ("文字", 0.9, {"layout": "vertical", "dropped_lines": 2}))
        try:
            with mock.patch.object(oc.pdf_quality, "_to_image_bytes", return_value=b"png"):
                result = oc.pdf_quality.run_ocr(object(), "diag")
        finally:
            oc.pdf_quality.clear_injected_runners()
        self.assertEqual((result["status"], result["layout"], result["dropped_lines"]), ("ok", "vertical", 2))

    def test_run_ocr_still_accepts_two_tuples(self):
        oc.pdf_quality.register_runner("plain", lambda image: ("文字", 0.9))
        try:
            with mock.patch.object(oc.pdf_quality, "_to_image_bytes", return_value=b"png"):
                result = oc.pdf_quality.run_ocr(object(), "plain")
        finally:
            oc.pdf_quality.clear_injected_runners()
        self.assertEqual((result["status"], result["text"], result["confidence"]), ("ok", "文字", 0.9))

    def test_summarize_ocr(self):
        pages = [
            {"quality": {"ocr_required": True}, "ocr": {"status": "ok", "confidence": 0.9, "layout": "vertical",
                                                        "dropped_lines": 2, "short_lines": 1}},
            {"quality": {"ocr_required": True}, "ocr": {"status": "ok", "confidence": 0.7, "layout": "horizontal"}},
            {"quality": {"ocr_required": True}, "ocr": {"status": "unavailable"}},
            {"quality": {"ocr_required": False}, "ocr": None},
        ]
        self.assertEqual(oc.pdf_quality.summarize_ocr(pages), {
            "pages_total": 4, "ocr_required": 3, "ocr_ok": 2, "mean_confidence": 0.8,
            "vertical_pages": 1, "suspect_lines": 3,
        })


@unittest.skipUnless(HAVE_RENDER, "需要 PyMuPDF 与 Pillow（pip install -e .[pdf,ocr]）")
class OcrIntoIndexTests(unittest.TestCase):
    def tearDown(self):
        oc.pdf_quality.clear_injected_runners()

    def test_each_backend_is_reported_separately(self):
        oc.pdf_quality.register_runner("good", fake_engine(TRUTH))
        oc.pdf_quality.register_runner("bad", fake_engine(TRUTH, corrupt=every_nth_wrong(5), confidence=0.5))
        report = oc.calibrate(TRUTH, font=None, degrades=["none"], backends=["good", "bad"])
        by_engine = {lv["engine"]: lv for lv in report["levels"]}
        self.assertEqual(by_engine["good"]["backend_used"], ["good"])
        self.assertEqual(by_engine["good"]["verbatim_survival"], 1.0)
        self.assertLess(by_engine["bad"]["verbatim_survival"], 1.0)
        self.assertIn("ocr_garbled", by_engine["bad"]["gate_reasons"])
        self.assertIn("| bad | builtin | 横排 | none |", oc.render_calibration(report))

    def test_ocr_pages_are_marked_in_shards(self):
        oc.pdf_quality.register_runner("fake", fake_engine(TRUTH))
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "sources" / "ocr-demo" / "raw"
            raw.mkdir(parents=True)
            oc.build_pdf([oc.render_page(t, None) for t in TRUTH], raw / "scan.pdf")
            with mock.patch.dict("os.environ", {"MDF_DATA_ROOT": td}):
                segments, _files = oc.lsp.collect_segments("ocr-demo")
        text = "\n".join(s.text for s in segments)
        self.assertIn("--- Page 1 (OCR) ---", text)
        self.assertTrue(all("ocr_text" in s.quality_flags for s in segments))
        self.assertTrue(oc.clean_corpus.PAGE_MARKER_RE.match("--- Page 1 (OCR) ---"), "清洗规则不得删掉 OCR 页码标记")

    def test_vertical_layout_only_renders_cjk_pages(self):
        oc.pdf_quality.register_runner("fake", lambda image: ("文", 0.97))
        truth = [TRUTH[1], "Version 2.0 of the index lists 13 files and 86 shards."]
        report = oc.calibrate(truth, font=None, degrades=["none"], fonts={"builtin": None},
                              layouts=("horizontal", "vertical"))
        pages = {lv["layout"]: lv["pages"] for lv in report["levels"]}
        self.assertEqual(pages, {"horizontal": 2, "vertical": 1}, "英文页不竖排")
        self.assertEqual({g["layout"] for g in oc.summarize_levels(report["levels"], "layout")},
                         {"horizontal", "vertical"})

    def test_vertical_render_and_overflow(self):
        self.assertTrue(oc.render_page(TRUTH[0], None, layout="vertical").startswith(b"\x89PNG"))
        with self.assertRaises(ValueError, msg="放不下就报错，不能悄悄截断真值"):
            oc.render_page("字" * 5000, None, layout="vertical")
        with self.assertRaises(ValueError):
            oc.render_page("字" * 5000, None)
        with self.assertRaises(ValueError, msg="小注占的列也要算进去"):
            oc.render_page("字〔" + "注" * 5000 + "〕", None, layout="vertical")
        self.assertTrue(oc.render_page("學而時習之〔習，鳥數飛也。〕", None, layout="vertical").startswith(b"\x89PNG"))

    def test_survey_samples_each_pdf_and_reports_problems(self):
        oc.pdf_quality.register_runner("fake", fake_engine(TRUTH, confidence=0.8))
        with tempfile.TemporaryDirectory() as td:
            oc.build_pdf([oc.render_page(t, None) for t in TRUTH * 3], Path(td) / "book.pdf")
            (Path(td) / "broken.pdf").write_bytes(b"not a pdf")
            report = oc.survey(Path(td), per_file=2)
        by_file = {f["file"]: f for f in report["files"]}
        self.assertIn("error", by_file["broken.pdf"])
        book = by_file["book.pdf"]
        self.assertEqual((book["pages_in_file"], book["sampled"], book["ocr_share"]), (6, [2, 4], 1.0))
        self.assertIn("low_ocr_confidence", book["gate_flags"])
        text = oc.render_survey(report)
        self.assertIn("需要人看一眼的 2 份", text)
        self.assertIn("打不开", text)

    def test_unread_lines_reach_the_shard_and_the_gate(self):
        def leaky(image):
            return "子曰學而時習之", 0.95, {"layout": "vertical", "lines": 1, "dropped_lines": 2, "short_lines": 0}

        oc.pdf_quality.register_runner("leaky", leaky)
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "sources" / "ocr-demo" / "raw"
            raw.mkdir(parents=True)
            pdf = oc.build_pdf([oc.render_page(TRUTH[0], None)], raw / "scan.pdf")
            report = oc.scan(pdf)
            with mock.patch.dict("os.environ", {"MDF_DATA_ROOT": td}):
                segments, _files = oc.lsp.collect_segments("ocr-demo")
        self.assertIn("--- Page 1 (OCR, 2 unread) ---", segments[0].text)
        self.assertIn("ocr_lines_dropped", segments[0].quality_flags)
        self.assertEqual((report["suspect_lines"], report["vertical_pages"]), (2, 1))
        self.assertIn("| 竖排 |", oc.render_scan(report))


class CliTests(unittest.TestCase):
    def test_no_engine_exits_with_install_hint(self):
        err = io.StringIO()
        with mock.patch.object(oc, "engine_available", return_value=[]), contextlib.redirect_stderr(err):
            self.assertEqual(oc.main(["calibrate"]), 2)
        self.assertIn("pip install", err.getvalue())

    def test_mdf_lists_ocr_subcommand(self):
        mdf = load_module(ROOT / "scripts" / "mdf.py", "_mdf_for_ocr")
        self.assertEqual(mdf.PASSTHROUGH["ocr"][0], "ocr_calibrate")


if __name__ == "__main__":
    unittest.main()
