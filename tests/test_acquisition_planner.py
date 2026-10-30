"""采集计划（scripts/acquisition_planner.py）：模型列候选，目录核对，用户批准后才交给 mdf acquire。

以前「该采哪些书」靠子代理在 collection_notes 里写一段话，书名怎么落成维基文库篇名、IA 条目号要人去查，
模型凭记忆给的篇名、版本没人核对（墨子 3 篇篇名就标错过）。现在分三段：
1. acquisition-scout 凭记忆写结构化候选 `sources/{slug}/acquisition_candidates.json`（不联网）；
2. 脚本只查白名单站点的目录：维基文库只读 robots 放行的 /wiki/ 页（作者页、作品页；它的搜索接口对爬虫是 Disallow），
   IA 用 advancedsearch（排除借阅馆藏），古腾堡用离线目录 CSV（网站禁止自动访问）。目录里查不到的不进计划；
3. 草稿（processed/acquisition_plan.draft.json + .md）给用户看，批准了才写进 acquire 读的 acquisition_plan.json。
法域未设定时，公有领域一律标「待复核」。全部离线：假 fetcher 模拟各站点。
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sibling import load_module  # noqa: E402  按路径加载模块的唯一入口（先登记 sys.modules）

planner = load_module(ROOT / "scripts" / "acquisition_planner.py", "_planner_under_test")
acq = planner.acquire
POLICY = acq.load_policy(ROOT / "config" / "acquisition_policy.json")
NOW = "2026-10-24T00:00:00+00:00"

WIKISOURCE_ROBOTS = """
User-agent: *
Allow: /w/api.php?action=mobileview&
Disallow: /w/
Disallow: /api/
Disallow: /wiki/Special:
"""


def ws(title: str) -> str:
    return acq.wikisource_url("zh", title)


def href(title: str) -> str:
    return ws(title).split("wikisource.org", 1)[1]


HTML = "text/html; charset=UTF-8"
AUTHOR_PAGE = f"""<html><body><div class="mw-parser-output">
<table class="ws-header"><tr><td><a href="/wiki/Portal:%E6%96%87%E5%AD%B8">門戶</a></td></tr></table>
<ul>
<li><a href="{href('吶喊')}" title="吶喊">吶喊</a>（1923）</li>
<li><a href="{href('墳')}" title="墳">墳</a>（1927）</li>
<li><a href="/wiki/Category:%E9%AD%AF%E8%BF%85">分類</a></li>
<li><a href="/w/index.php?title=x&amp;action=edit&amp;redlink=1" class="new">紅鏈</a></li>
</ul></div></body></html>"""
NAHAN_PAGE = f"""<html><body><div class="mw-parser-output">
<p>作者：<a href="{href('作者:魯迅')}">魯迅</a></p><p>自序……</p></div></body></html>"""
FEN_PAGE = f"""<html><body><div class="mw-parser-output"><p>魯迅 著</p><ul>
<li><a href="{href('墳/題記')}">題記</a></li>
<li><a href="{href('墳/人之歷史')}">人之歷史</a></li>
<li><a href="{href('墳/題記')}">題記</a></li>
<li><a href="{href('熱風')}">熱風</a></li>
</ul></div></body></html>"""
YECAO_PAGE = f"""<html><body><div class="mw-parser-output"><div id="disambig">消歧義頁</div>
<ul><li><a href="{href('野草 (魯迅)')}">野草 (魯迅)</a></li><li><a href="{href('野草 (詩)')}">野草 (詩)</a></li></ul>
</div></body></html>"""
KUANGREN_PAGE = """<html><body><div class="mw-parser-output"><p>某人 撰</p><p>正文</p></div></body></html>"""

IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_DOCS = {"response": {"docs": [
    {"identifier": "briefhistoryofch00luxu", "title": "A brief history of Chinese fiction",
     "creator": "Lu, Xun, 1881-1936", "date": "1959-01-01T00:00:00Z", "possible-copyright-status": "NOT_IN_COPYRIGHT"},
    {"identifier": "someoneelse", "title": "A Brief History of Chinese Fiction", "creator": ["Someone Else"]},
]}}
IA_PARTIAL = {"response": {"docs": [{"identifier": "wildgrass01", "title": "Wild grass", "creator": "Anon"}]}}


def routes(ia_body=IA_DOCS):
    return {
        "https://zh.wikisource.org/robots.txt": ("text/plain", WIKISOURCE_ROBOTS),
        ws("作者:魯迅"): (HTML, AUTHOR_PAGE),
        ws("吶喊"): (HTML, NAHAN_PAGE),
        ws("墳"): (HTML, FEN_PAGE),
        ws("野草"): (HTML, YECAO_PAGE),
        ws("狂人日記"): (HTML, KUANGREN_PAGE),
        IA_SEARCH: ia_body if callable(ia_body) else ("application/json", json.dumps(ia_body)),
    }


class FakeFetcher:
    """按 URL 返回预置响应；没有精确匹配时按前缀匹配（advancedsearch 带查询串）；其余 404。"""

    def __init__(self, table):
        self.table = table
        self.calls: list[str] = []

    def fetch(self, url, headers, max_bytes, timeout):
        self.calls.append(url)
        route = self.table.get(url) or next((v for k, v in self.table.items() if url.startswith(k + "?")), None)
        if callable(route):  # 按查询串给不同结果（IA 先按作者查，再退回只按篇名）
            route = route(url)
        if route is None:
            return acq.Response(404, {}, b"", url)
        content_type, body = route
        return acq.Response(200, {"content-type": content_type}, body.encode("utf-8"), url)


def session_for(table=None, *, policy=None, contact="https://example.invalid/project"):
    fetcher = FakeFetcher(routes() if table is None else table)
    session = acq.Session(policy or copy.deepcopy(POLICY), fetcher, contact=contact, clock=lambda: 0.0,
                          sleep=lambda s: None, now=lambda: NOW)
    return session, fetcher


LU_XUN = {
    "schema": "acquisition-candidates-v1",
    "person": {"name": "魯迅", "aliases": ["鲁迅", "魯迅", "周樹人", "Lu Xun"], "death_year": 1936,
               "wikisource_author": {"zh": "魯迅"}},
    "candidates": [
        {"id": "c01", "work": "吶喊", "titles": ["吶喊", "呐喊"], "kind": "primary", "language": "zh", "year": 1923,
         "why": "小说集，早期思想的主干", "catalogs": ["wikisource"]},
        {"id": "c02", "work": "墳", "titles": ["墳", "坟"], "kind": "primary", "language": "zh", "year": 1927,
         "why": "早期论文集", "catalogs": ["wikisource"]},
        {"id": "c03", "work": "不存在的書", "titles": ["不存在的書"], "kind": "primary", "language": "zh",
         "why": "测试：目录里没有", "catalogs": ["wikisource"]},
        {"id": "c04", "work": "中國小說史略（英譯）", "titles": ["A Brief History of Chinese Fiction"],
         "kind": "primary", "language": "en", "why": "英译本对照", "catalogs": ["internet_archive"]},
        {"id": "c05", "work": "野草", "titles": ["野草"], "kind": "primary", "language": "zh",
         "why": "散文诗集", "catalogs": ["wikisource"]},
        {"id": "c06", "work": "狂人日記", "titles": ["狂人日記"], "kind": "primary", "language": "zh",
         "why": "第一篇白话小说", "catalogs": ["wikisource"]},
    ],
}


def by_id(resolutions):
    return {r.candidate_id: r for r in resolutions}


def write_candidates(root: Path, data=LU_XUN, slug="lu-xun") -> Path:
    path = root / "sources" / slug / "acquisition_candidates.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


class CandidateSchemaTests(unittest.TestCase):
    def test_valid_file_loads_into_value_objects(self):
        self.assertEqual(planner.check_candidates(LU_XUN), [])
        with tempfile.TemporaryDirectory() as td:
            person, candidates = planner.load_candidates(write_candidates(Path(td)))
        self.assertEqual((person.name, person.death_year, person.wikisource_author), ("魯迅", 1936, {"zh": "魯迅"}))
        self.assertEqual([c.id for c in candidates], ["c01", "c02", "c03", "c04", "c05", "c06"])
        self.assertIsInstance(candidates[0], planner.Candidate)
        self.assertEqual(candidates[0].titles, ("吶喊", "呐喊"))

    def test_editors_must_be_a_list_of_names(self):
        data = copy.deepcopy(LU_XUN)
        data["candidates"][0]["editors"] = "C. R. Haines"
        self.assertTrue(any("editors" in e for e in planner.check_candidates(data)))

    def test_every_problem_is_reported(self):
        bad = copy.deepcopy(LU_XUN)
        bad["candidates"] += [
            {"id": "c01", "work": "重复", "titles": ["x"], "kind": "primary", "language": "zh", "why": "x"},
            {"id": "C 9", "work": "坏 id", "titles": ["x"], "kind": "primary", "language": "zh", "why": "x"},
            {"id": "c10", "work": "没理由", "titles": ["x"], "kind": "primary", "language": "zh"},
            {"id": "c11", "work": "没篇名", "titles": [], "kind": "primary", "language": "zh", "why": "x"},
            {"id": "c12", "work": "怪类型", "titles": ["x"], "kind": "fanfic", "language": "zh", "why": "x"},
            {"id": "c13", "work": "怪目录", "titles": ["x"], "kind": "primary", "language": "zh", "why": "x",
             "catalogs": ["google_books"]},
            {"id": "c14", "work": "怪语言", "titles": ["x"], "kind": "primary", "language": "中文", "why": "x"},
        ]
        errors = "\n".join(planner.check_candidates(bad))
        for needle in ("c01", "C 9", "c10", "c11", "c12", "google_books", "中文"):
            self.assertIn(needle, errors)
        self.assertTrue(planner.check_candidates({"schema": "other"}))
        self.assertTrue(planner.check_candidates([]))


class WikisourceTests(unittest.TestCase):
    def resolve(self, ids):
        person, candidates = planner.parse_candidates(LU_XUN)
        session, fetcher = session_for()
        result = planner.resolve(person, [c for c in candidates if c.id in ids], session=session)
        return by_id(result), fetcher

    def test_author_page_link_resolves_to_one_page(self):
        result, fetcher = self.resolve({"c01"})
        res = result["c01"]
        self.assertEqual(res.status, "resolved")
        self.assertEqual(res.hits[0].catalog, "wikisource")
        self.assertEqual(res.hits[0].targets, ({"connector": "wikisource", "lang": "zh", "title": "吶喊"},))
        self.assertEqual(res.hits[0].confidence, "exact")
        paths = [unquote(u.split("wikisource.org", 1)[1]) for u in fetcher.calls if "wikisource.org" in u]
        self.assertFalse([p for p in paths if p.startswith(("/w/", "/api/", "/wiki/Special:"))],
                         "维基文库的搜索与 API 对爬虫是 Disallow，只能读 /wiki/ 页")

    def test_contents_page_expands_to_its_subpages(self):
        res = self.resolve({"c02"})[0]["c02"]
        self.assertEqual(res.status, "resolved")
        self.assertEqual([t["title"] for t in res.hits[0].targets], ["墳/題記", "墳/人之歷史"])
        self.assertIn("墳", res.hits[0].note)

    def test_disambiguation_page_is_ambiguous_with_options(self):
        res = self.resolve({"c05"})[0]["c05"]
        self.assertEqual(res.status, "ambiguous")
        self.assertTrue(any("野草 (魯迅)" in n for n in res.notes), res.notes)

    def test_page_that_does_not_name_the_author_is_only_partial(self):
        res = self.resolve({"c06"})[0]["c06"]
        self.assertEqual(res.status, "ambiguous")
        self.assertEqual(res.hits[0].confidence, "partial")

    def test_absent_everywhere_is_unresolved_after_trying_every_title(self):
        res, fetcher = self.resolve({"c03"})
        self.assertEqual(res["c03"].status, "unresolved")
        self.assertIn(ws("不存在的書"), fetcher.calls)

    def test_author_page_is_fetched_once_per_run(self):
        _, fetcher = self.resolve({"c01", "c02", "c03"})
        self.assertEqual(fetcher.calls.count(ws("作者:魯迅")), 1)


class RealSiteMarkupTests(unittest.TestCase):
    """2026-10-30 对真实站点实跑发现的：英文维基文库的站内链接是绝对地址，多译本页要当「待选定」。"""

    def test_absolute_links_on_the_same_wiki_count_and_other_hosts_do_not(self):
        page = """<html><body><div class="mw-parser-output"><p>魯迅 著</p><ul>
<li><a href="https://zh.wikisource.org/wiki/%E5%A2%B3/%E9%A1%8C%E8%A8%98">題記</a></li>
<li><a href="//zh.wikisource.org/wiki/%E5%A2%B3/%E4%BA%BA%E4%B9%8B%E6%AD%B7%E5%8F%B2">人之歷史</a></li>
<li><a href="https://zh.wikipedia.org/wiki/%E5%A2%B3/%E5%88%A5%E7%9A%84">維基百科</a></li>
<li><a href="https://en.wikisource.org/wiki/%E5%A2%B3/Other">英文站</a></li>
</ul></div></body></html>"""
        table = {**routes(), ws("墳"): (HTML, page)}
        person, candidates = planner.parse_candidates(LU_XUN)
        session, _ = session_for(table)
        res = by_id(planner.resolve(person, [c for c in candidates if c.id == "c02"], session=session))["c02"]
        self.assertEqual([t["title"] for t in res.hits[0].targets], ["墳/題記", "墳/人之歷史"])

    def test_translations_page_is_ambiguous_with_the_translations_as_options(self):
        page = """<html><body><div class="mw-parser-output"><p>Marcus Aurelius</p><ul>
<li><a href="https://en.wikisource.org/wiki/Meditations_(Long)">George Long</a></li>
<li><a href="https://en.wikisource.org/wiki/The_Thoughts_of_the_Emperor_Marcus_Aurelius_Antoninus">Long, 1862</a></li>
</ul></div><div id="catlinks"><a href="/wiki/Category:Translations_pages">Translations pages</a></div></body></html>"""
        data = copy.deepcopy(MARCUS)
        data["candidates"][0]["catalogs"] = ["wikisource"]
        person, candidates = planner.parse_candidates(data)
        session, _ = session_for({acq.wikisource_url("en", "Meditations"): (HTML, page)})
        res = planner.resolve(person, candidates, session=session)[0]
        self.assertEqual(res.status, "ambiguous", "译本列表页不是正文，下载它只会得到一张链接表")
        self.assertTrue(any("Meditations (Long)" in n for n in res.notes), res.notes)


class InternetArchiveTests(unittest.TestCase):
    def resolve(self, body=IA_DOCS, titles=None):
        data = copy.deepcopy(LU_XUN)
        if titles:
            data["candidates"][3]["titles"] = titles
        person, candidates = planner.parse_candidates(data)
        session, fetcher = session_for(routes(body))
        return by_id(planner.resolve(person, [candidates[3]], session=session))["c04"], fetcher

    def test_query_uses_advancedsearch_and_excludes_lending_items(self):
        _, fetcher = self.resolve()
        query = unquote(next(u for u in fetcher.calls if u.startswith(IA_SEARCH)).replace("+", " "))
        for needle in ('title:("A Brief History of Chinese Fiction")', "mediatype:(texts)", "inlibrary",
                       "printdisabled", "output=json"):
            self.assertIn(needle, query)

    def test_title_and_creator_match_resolves_with_ia_rights(self):
        res, _ = self.resolve()
        self.assertEqual(res.status, "resolved")
        hit = res.hits[0]
        self.assertEqual(hit.targets, ({"connector": "internet_archive", "identifier": "briefhistoryofch00luxu"},))
        self.assertEqual(hit.rights_status, "public_domain_us")
        self.assertEqual([h.confidence for h in res.hits], ["exact", "partial"], "同名别人的书留作备选")

    def test_title_only_match_is_ambiguous(self):
        res, _ = self.resolve(IA_PARTIAL, titles=["Wild Grass"])
        self.assertEqual(res.status, "ambiguous")

    def test_the_first_query_asks_for_the_author(self):
        # 只按篇名查，「Meditations」这类通用篇名会把本人的书挤出前几条（2026-10-30 实跑）
        _, fetcher = self.resolve()
        first = unquote(next(u for u in fetcher.calls if u.startswith(IA_SEARCH)).replace("+", " "))
        for needle in ("creator:(", "(Lu AND Xun)", '"魯迅"'):
            self.assertIn(needle, first)
        self.assertEqual(sum(u.startswith(IA_SEARCH) for u in fetcher.calls), 1, "按作者查到了就不再查")

    def test_falls_back_to_title_only_when_the_author_query_finds_nothing(self):
        def answer(url):
            docs = [] if "creator%3A" in url else IA_DOCS["response"]["docs"][1:]
            return "application/json", json.dumps({"response": {"docs": docs}})
        res, fetcher = self.resolve(answer)
        self.assertEqual(sum(u.startswith(IA_SEARCH) for u in fetcher.calls), 2)
        self.assertEqual((res.status, res.hits[0].confidence), ("ambiguous", "partial"))

    def test_public_domain_copies_come_first(self):
        docs = [{"identifier": "modernreprint01", "title": "A Brief History of Chinese Fiction", "creator": "Lu Xun"},
                *IA_DOCS["response"]["docs"][:1]]
        res, _ = self.resolve({"response": {"docs": docs}})
        self.assertEqual(res.hits[0].targets[0]["identifier"], "briefhistoryofch00luxu",
                         "权利能放行的副本排第一，批准时默认下它")

    def test_translator_in_editors_counts_as_the_responsible_person(self):
        # 译本、校注本在 IA 上常只登记译者（Fronto 书信登记为 C. R. Haines，2026-10-30 实跑）
        data = copy.deepcopy(LU_XUN)
        data["candidates"][3].update({"creator": "Fronto", "editors": ["C. R. Haines"],
                                      "titles": ["The Correspondence of Marcus Cornelius Fronto"]})
        person, candidates = planner.parse_candidates(data)
        docs = [{"identifier": "correspondenceof01fron", "title": "The Correspondence of Marcus Cornelius Fronto",
                 "creator": "C.R. Haines"}]
        session, _ = session_for(routes({"response": {"docs": docs}}))
        res = by_id(planner.resolve(person, [candidates[3]], session=session))["c04"]
        self.assertEqual((res.status, res.hits[0].confidence), ("resolved", "exact"))


GUTENBERG_CSV = (
    'Text#,Type,Issued,Title,Language,Authors,Subjects,LoCC,Bookshelves\n'
    '2680,Text,2001-07-01,Meditations,en,"Marcus Aurelius, Emperor of Rome, 121-180",Stoics,B,Philosophy\n'
    '55317,Text,2017-08-10,"Meditations\nWith an introduction",en,"Someone, 1900-1980",,,\n'
    '9999,Sound,2005-01-01,Meditations,en,"Marcus Aurelius, Emperor of Rome, 121-180",,,\n'
)
MARCUS = {
    "schema": "acquisition-candidates-v1",
    "person": {"name": "Marcus Aurelius", "aliases": ["Marcus Aurelius", "马可·奥勒留"], "death_year": 180},
    "candidates": [{"id": "m01", "work": "沉思录", "titles": ["Meditations"], "kind": "primary", "language": "en",
                    "why": "唯一传世著作", "catalogs": ["gutenberg"]}],
}


class GutenbergTests(unittest.TestCase):
    def test_without_an_offline_catalog_nothing_is_fetched(self):
        person, candidates = planner.parse_candidates(MARCUS)
        session, fetcher = session_for({})
        res = planner.resolve(person, candidates, session=session)[0]
        self.assertEqual(res.status, "unresolved")
        self.assertTrue(any("CATALOG_NOT_CONFIGURED" in n for n in res.notes), res.notes)
        self.assertEqual(fetcher.calls, [], "古腾堡网站禁止自动访问：只读离线目录")

    def test_catalog_row_resolves_to_an_ebook_number(self):
        person, candidates = planner.parse_candidates(MARCUS)
        session, fetcher = session_for({})
        with tempfile.TemporaryDirectory() as td:
            catalog = Path(td) / "pg_catalog.csv"
            catalog.write_text(GUTENBERG_CSV, encoding="utf-8")
            res = planner.resolve(person, candidates, session=session, gutenberg_catalog=catalog)[0]
        self.assertEqual(res.status, "resolved")
        self.assertEqual([h.targets for h in res.hits if h.confidence == "exact"],
                         [({"connector": "gutenberg", "ebook": 2680},)])
        self.assertEqual(fetcher.calls, [])


class DraftAndApprovalTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        write_candidates(self.root)
        self.session, _ = session_for()
        self.draft = planner.run_plan(self.root, "lu-xun", session=self.session, now=NOW)

    def tearDown(self):
        self._td.cleanup()

    def entry(self, cid):
        return next(e for e in self.draft["entries"] if e["candidate_id"] == cid)

    def test_draft_lists_every_candidate_and_is_not_read_by_acquire(self):
        processed = self.root / "sources" / "lu-xun" / "processed"
        on_disk = json.loads((processed / "acquisition_plan.draft.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, self.draft)
        self.assertEqual([e["status"] for e in self.draft["entries"]],
                         ["resolved", "resolved", "unresolved", "resolved", "ambiguous", "ambiguous"])
        self.assertFalse((self.root / "sources" / "lu-xun" / "acquisition_plan.json").exists(),
                         "没批准前 mdf acquire 读不到任何目标")
        report = (processed / "acquisition_plan.md").read_text(encoding="utf-8")
        for cid in ("c01", "c02", "c03", "c04", "c05", "c06"):
            self.assertIn(cid, report)
        self.assertNotIn(b"\r\n", (processed / "acquisition_plan.draft.json").read_bytes())

    def test_public_domain_is_pending_review_while_jurisdiction_is_unset(self):
        rights = self.entry("c04")["rights"]
        self.assertTrue(rights["review_required"])
        self.assertIn("1936", rights["note"])
        self.assertIn("待复核", rights["note"])
        self.assertFalse(self.entry("c01")["rights"]["review_required"], "维基文库按站点许可 CC BY-SA，不涉及公有领域判定")

    def test_approving_writes_targets_acquire_can_read(self):
        summary = planner.approve(self.root, "lu-xun", "c01,c02", now=NOW)
        self.assertEqual(summary["approved"], ["c01", "c02"])
        args = Namespace(plan=None, slug="lu-xun", wikisource=None, ia=None, gutenberg=None, url=None, local=None,
                         rights=None, rights_evidence=None)
        targets = [acq.normalize_target(t) for t in acq.targets_from_args(args, self.root)]
        self.assertEqual([t["title"] for t in targets], ["吶喊", "墳/題記", "墳/人之歷史"])
        plan = json.loads((self.root / "sources" / "lu-xun" / "acquisition_plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["approvals"][0]["candidates"], ["c01", "c02"])

    def test_all_means_every_resolved_downloadable_entry_and_reapproval_dedupes(self):
        planner.approve(self.root, "lu-xun", "c01", now=NOW)
        summary = planner.approve(self.root, "lu-xun", "all", now=NOW)
        self.assertEqual(summary["approved"], ["c01", "c02", "c04"])
        plan = json.loads((self.root / "sources" / "lu-xun" / "acquisition_plan.json").read_text(encoding="utf-8"))
        self.assertEqual(len(plan["targets"]), 4, "吶喊 + 墳 两篇 + IA 一条；c01 不重复")

    def test_unresolved_or_ambiguous_ids_cannot_be_approved(self):
        for cid in ("c03", "c05", "c99"):
            with self.subTest(cid=cid), self.assertRaises(ValueError):
                planner.approve(self.root, "lu-xun", cid, now=NOW)

    def test_editing_candidates_after_resolution_invalidates_the_draft(self):
        data = copy.deepcopy(LU_XUN)
        data["candidates"][0]["why"] = "改过"
        write_candidates(self.root, data)
        with self.assertRaises(ValueError) as caught:
            planner.approve(self.root, "lu-xun", "c01", now=NOW)
        self.assertIn("acquire-plan", str(caught.exception))

    def test_a_disabled_connector_is_not_even_queried(self):
        policy = copy.deepcopy(POLICY)
        policy["connectors"]["internet_archive"]["enabled"] = False
        session, fetcher = session_for(policy=policy)
        draft = planner.run_plan(self.root, "lu-xun", session=session, now=NOW)
        entry = next(e for e in draft["entries"] if e["candidate_id"] == "c04")
        self.assertEqual(entry["status"], "unresolved")
        self.assertTrue(any("CONNECTOR_DISABLED" in n for n in entry["notes"]), entry["notes"])
        self.assertFalse([u for u in fetcher.calls if "archive.org" in u])

    def test_resolved_but_blocked_offline_is_not_downloadable(self):
        write_candidates(self.root, MARCUS, slug="marcus-aurelius")
        catalog = self.root / "pg_catalog.csv"
        catalog.write_text(GUTENBERG_CSV, encoding="utf-8")
        draft = planner.run_plan(self.root, "marcus-aurelius", session=self.session, gutenberg_catalog=catalog, now=NOW)
        entry = draft["entries"][0]
        self.assertEqual((entry["status"], entry["downloadable"]), ("resolved", False))
        self.assertIn("CONNECTOR_NOT_CONFIGURED", entry["blockers"], "古腾堡下载要先配私有镜像")
        with self.assertRaises(ValueError):
            planner.approve(self.root, "marcus-aurelius", "m01", now=NOW)


class CliTests(unittest.TestCase):
    def setUp(self):
        # 进程内直接调 main：控制台可能是 GBK（mdf.py 入口才把输出改成 UTF-8），输出收进缓冲区
        self.out = io.StringIO()
        stack = contextlib.ExitStack()
        stack.enter_context(contextlib.redirect_stdout(self.out))
        stack.enter_context(contextlib.redirect_stderr(self.out))
        self.addCleanup(stack.close)

    def test_check_validates_offline(self):
        with tempfile.TemporaryDirectory() as td:
            write_candidates(Path(td))
            fetcher = FakeFetcher({})
            self.assertEqual(planner.main(["lu-xun", "--check", "--root", td], fetcher=fetcher), 0)
            bad = copy.deepcopy(LU_XUN)
            bad["candidates"][0].pop("why")
            write_candidates(Path(td), bad)
            self.assertEqual(planner.main(["lu-xun", "--check", "--root", td], fetcher=fetcher), 1)
            self.assertEqual(fetcher.calls, [])

    def test_dry_run_touches_no_network_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            write_candidates(Path(td))
            fetcher = FakeFetcher(routes())
            self.assertEqual(planner.main(["lu-xun", "--dry-run", "--root", td], fetcher=fetcher), 0)
            self.assertEqual(fetcher.calls, [])
            self.assertFalse((Path(td) / "sources" / "lu-xun" / "processed").exists())

    def test_missing_contact_stops_before_any_request(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ):
            os.environ.pop("MDF_CONTACT", None)
            write_candidates(Path(td))
            fetcher = FakeFetcher(routes())
            self.assertEqual(planner.main(["lu-xun", "--root", td], fetcher=fetcher), 2)
            self.assertEqual(fetcher.calls, [])

    def test_resolve_then_approve_through_the_cli(self):
        with tempfile.TemporaryDirectory() as td:
            write_candidates(Path(td))
            settings = load_module(ROOT / "scripts" / "acquisition_settings.py", "_settings_for_planner_cli")
            settings.save(Path(td), contact="https://example.invalid/project", now=NOW)
            fetcher = FakeFetcher(routes())
            self.assertEqual(planner.main(["lu-xun", "--root", td], fetcher=fetcher, sleep=lambda s: None), 0)
            self.assertTrue(fetcher.calls)
            self.assertEqual(planner.main(["lu-xun", "--approve", "c01", "--root", td], fetcher=fetcher), 0)
            self.assertTrue((Path(td) / "sources" / "lu-xun" / "acquisition_plan.json").exists())

    def test_mdf_passes_through(self):
        import subprocess
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "mdf.py"), "acquire-plan", "../x", "--check"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
