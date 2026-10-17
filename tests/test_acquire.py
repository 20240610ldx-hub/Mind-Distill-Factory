"""合规采集（scripts/acquire.py）：全部离线，用假 fetcher 模拟各站点。"""

import copy
import importlib.util
import json
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


acq = load_module("_acquire_under_test", ROOT / "scripts" / "acquire.py")
registry = load_module("_source_registry_acq", ROOT / "scripts" / "source_registry.py")
POLICY = acq.load_policy(ROOT / "config" / "acquisition_policy.json")

WIKISOURCE_ROBOTS = """
User-agent: *
Allow: /w/api.php?action=mobileview&
Allow: /w/load.php?
Disallow: /w/
Disallow: /api/
Disallow: /wiki/Special:
Disallow: /wiki/Wikipedia:Löschkandidaten/
"""

WIKISOURCE_PAGE = """<html><head><title>x</title><script>var a=1;</script></head><body>
<nav>导航</nav>
<div id="mw-content-text"><div class="mw-parser-output">
<div class="ws-noexport">版本信息</div>
<table class="ws-header"><tr><td><a href="/wiki/x">序說</a> <span> ◄ </span></td><td>學而第一</td></tr></table>
<h2>學而第一<span class="mw-editsection">[编辑]</span></h2>
<p>雖曰未學，吾必謂之學<span class="variant-text" tabindex="0">已<span class="variant-tooltip">一無「已」字</span></span>矣。</p>
<p>子曰：「學而時習之，不亦說乎？」<sup class="reference">[1]</sup></p>
<p>有朋自遠方來，不亦樂乎？&nbsp;</p>
<div class="navbox">上一篇</div>
</div></div>
<div class="printfooter">取自</div>
</body></html>"""


def response(status=200, body=b"", headers=None, url=None):
    return {"status": status, "body": body, "headers": headers or {}, "url": url}


class FakeFetcher:
    """按 URL 返回预置响应；值为列表时依次弹出（模拟重试）。记录每次请求的 URL 与请求头。"""

    def __init__(self, routes):
        self.routes = {k: (list(v) if isinstance(v, list) else v) for k, v in routes.items()}
        self.calls = []

    def fetch(self, url, headers, max_bytes, timeout):
        self.calls.append((url, dict(headers)))
        route = self.routes.get(url)
        if route is None:
            return acq.Response(404, {}, b"", url)
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, Exception):
            raise route
        return acq.Response(route["status"], route["headers"], route["body"][: max_bytes + 1], route["url"] or url)


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 3))
        self.t += seconds


def make_session(routes, policy=None, contact="tests@example.invalid", **kw):
    clock = Clock()
    fetcher = FakeFetcher(routes)
    session = acq.Session(policy or copy.deepcopy(POLICY), fetcher, contact=contact, clock=clock,
                          sleep=clock.sleep, now=lambda: "2026-10-17T00:00:00+00:00", **kw)
    return session, fetcher, clock


WS_URL = "https://zh.wikisource.org/wiki/%E8%AB%96%E8%AA%9E"
WS_ROUTES = {
    "https://zh.wikisource.org/robots.txt": response(body=WIKISOURCE_ROBOTS.encode("utf-8")),
    WS_URL: response(body=WIKISOURCE_PAGE.encode("utf-8"), headers={"content-type": "text/html; charset=UTF-8"}),
}
WS_TARGET = {"connector": "wikisource", "lang": "zh", "title": "論語"}


class RobotsTests(unittest.TestCase):
    def setUp(self):
        self.rules = acq.RobotsRules.parse(WIKISOURCE_ROBOTS)

    def test_wiki_pages_allowed_api_disallowed(self):
        self.assertTrue(self.rules.allowed("/wiki/%E8%AB%96%E8%AA%9E"))
        self.assertFalse(self.rules.allowed("/w/index.php?title=x&action=raw"))
        self.assertFalse(self.rules.allowed("/api/rest_v1/page/html/x"))
        self.assertFalse(self.rules.allowed("/wiki/Special:Random"))

    def test_longest_match_wins(self):
        self.assertTrue(self.rules.allowed("/w/api.php?action=mobileview&page=x"))
        self.assertFalse(self.rules.allowed("/w/api.php?action=parse"))

    def test_non_ascii_patterns_are_percent_encoded(self):
        self.assertFalse(self.rules.allowed("/wiki/Wikipedia:L%C3%B6schkandidaten/2026"))

    def test_specific_group_overrides_star(self):
        rules = acq.RobotsRules.parse("User-agent: *\nDisallow: /\n\nUser-agent: MindDistillFactory\nAllow: /\n")
        self.assertTrue(rules.allowed("/anything"))
        self.assertFalse(rules.allowed("/anything", token="OtherBot"))

    def test_wildcards_and_end_anchor(self):
        rules = acq.RobotsRules.parse("User-agent: *\nDisallow: /*.pdf$\nDisallow: /private*/\n")
        self.assertFalse(rules.allowed("/books/a.pdf"))
        self.assertTrue(rules.allowed("/books/a.pdf?download=1"))
        self.assertFalse(rules.allowed("/private-x/y"))

    def test_empty_disallow_and_consecutive_agents(self):
        rules = acq.RobotsRules.parse("User-agent: a\nUser-agent: *\nDisallow:\n")
        self.assertTrue(rules.allowed("/x"))

    def test_status_handling(self):
        for status, expected in ((404, True), (401, True), (429, False), (500, False)):
            session, _, _ = make_session({"https://h.example/robots.txt": response(status)})
            self.assertEqual(session.robots("https://h.example/x", "url").allowed("/x"), expected, status)
        session, _, _ = make_session({"https://h.example/robots.txt": acq.FetchError("dns")})
        self.assertFalse(session.robots("https://h.example/x", "url").allowed("/x"))


class HelperTests(unittest.TestCase):
    def test_host_allowlist(self):
        self.assertTrue(acq.host_allowed("zh.wikisource.org", ["*.wikisource.org"]))
        self.assertFalse(acq.host_allowed("wikisource.org.evil.com", ["*.wikisource.org"]))
        self.assertFalse(acq.host_allowed("evilwikisource.org", ["*.wikisource.org"]))
        self.assertTrue(acq.host_allowed("archive.org", ["archive.org"]))
        self.assertFalse(acq.host_allowed(None, ["archive.org"]))

    def test_html_to_text_keeps_only_content(self):
        text = acq.html_to_text(WIKISOURCE_PAGE, "mw-parser-output")
        self.assertIn("子曰：「學而時習之，不亦說乎？」", text)
        self.assertIn("學而第一\n", text)
        self.assertIn("吾必謂之學已矣。", text, "隐藏的校勘注不得拼进原文")
        for noise in ("var a", "导航", "[编辑]", "[1]", "上一篇", "取自", "版本信息", "序說", "◄", "一無"):
            self.assertNotIn(noise, text)
        self.assertNotIn(" ", text)

    def test_html_to_text_falls_back_without_root(self):
        text = acq.html_to_text("<body><p>甲</p><br><p>乙</p></body>", "mw-parser-output")
        self.assertEqual(text, "甲\n\n乙\n")

    def test_decode_text(self):
        self.assertEqual(acq.decode_text("中文".encode("gb18030"), "text/plain; charset=gbk")[:2], ("中文", "gbk"))
        self.assertEqual(acq.decode_text("﻿中文".encode("utf-8"), "")[0], "中文")

    def test_rights_decision(self):
        self.assertEqual(acq.rights_decision(POLICY, "public_domain"), "allow")
        self.assertEqual(acq.rights_decision(POLICY, "public_domain_us"), "review")
        us = dict(POLICY, jurisdiction="us")
        self.assertEqual(acq.rights_decision(us, "public_domain_us"), "allow")
        self.assertEqual(acq.rights_decision(POLICY, "all_rights_reserved"), "refuse")

    def test_ia_rights_mapping(self):
        cases = {
            "https://creativecommons.org/publicdomain/mark/1.0/": "public_domain",
            "http://creativecommons.org/publicdomain/zero/1.0/": "cc0",
            "https://creativecommons.org/licenses/by-sa/4.0/": "cc-by-sa",
            "https://creativecommons.org/licenses/by-nc/4.0/": "unknown",
        }
        for url, expected in cases.items():
            self.assertEqual(acq.ia_rights({"licenseurl": url})[0], expected, url)
        self.assertEqual(acq.ia_rights({"possible-copyright-status": "NOT_IN_COPYRIGHT"})[0], "public_domain_us")
        self.assertEqual(acq.ia_rights({})[0], "unknown")

    def test_gutenberg_layout(self):
        self.assertEqual(acq.gutenberg_paths(12345)[0], "1/2/3/4/12345/12345-0.txt")
        self.assertEqual(acq.gutenberg_paths(7)[2], "0/7/7.txt")

    def test_target_validation(self):
        for bad in ({"connector": "wikisource", "lang": "zh"}, {"connector": "internet_archive", "identifier": "../x"},
                    {"connector": "gutenberg", "ebook": "abc"}, {"connector": "url", "url": "http://x.org/a"},
                    {"connector": "ftp"}, "not-a-dict"):
            with self.assertRaises(acq.Refused):
                acq.normalize_target(bad)

    def test_target_key_ignores_rights_declaration(self):
        a = acq.normalize_target({"connector": "url", "url": "https://x.org/a", "rights": "public_domain"})
        b = acq.normalize_target({"connector": "url", "url": "https://x.org/a", "rights": "cc0"})
        self.assertEqual(acq.target_key(a), acq.target_key(b))


class RunTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.raw = self.root / "sources" / "demo" / "raw"
        self.log = self.root / "sources" / "demo" / "processed" / "acquisition_log.jsonl"

    def tearDown(self):
        self._td.cleanup()

    def run_targets(self, targets, session, **kw):
        return acq.run_acquisition("demo", targets, root=self.root, session=session, **kw)

    def log_records(self):
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_wikisource_end_to_end(self):
        session, fetcher, clock = make_session(WS_ROUTES)
        [result] = self.run_targets([WS_TARGET], session)
        self.assertEqual(result["event"], "saved", result)
        saved = self.raw / result["path"]
        self.assertTrue(result["path"].startswith("acquired/wikisource/zh-"))
        text = saved.read_text(encoding="utf-8")
        self.assertIn("學而時習之", text)
        self.assertNotIn("\r", saved.read_bytes().decode("utf-8"))
        self.assertEqual(result["rights_status"], "cc-by-sa")
        self.assertEqual(result["converted_from"], "text/html")
        # robots 先于正文；两次请求都带联系方式；同主机第二次请求前等了 min_interval
        self.assertEqual([c[0] for c in fetcher.calls], ["https://zh.wikisource.org/robots.txt", WS_URL])
        self.assertTrue(all("tests@example.invalid" in c[1]["User-Agent"] for c in fetcher.calls))
        self.assertEqual(clock.sleeps, [1.0])
        [logged] = self.log_records()
        self.assertEqual(logged["sha256"], result["sha256"])
        self.assertEqual(logged["schema"], "acquisition-log-v1")

    def test_missing_contact_refuses_before_any_request(self):
        session, fetcher, _ = make_session(WS_ROUTES, contact="")
        [result] = self.run_targets([WS_TARGET], session)
        self.assertEqual((result["event"], result["reason"]), ("refused", "CONTACT_MISSING"))
        self.assertEqual(fetcher.calls, [])
        self.assertFalse(self.raw.exists())

    def test_robots_disallow_blocks_content_request(self):
        routes = dict(WS_ROUTES)
        routes["https://zh.wikisource.org/robots.txt"] = response(body=b"User-agent: *\nDisallow: /wiki/\n")
        session, fetcher, _ = make_session(routes)
        [result] = self.run_targets([WS_TARGET], session)
        self.assertEqual(result["reason"], "ROBOTS_DISALLOWED")
        self.assertEqual(len(fetcher.calls), 1)

    def test_second_run_skips_without_network_and_refresh_refetches(self):
        session, _, _ = make_session(WS_ROUTES)
        self.run_targets([WS_TARGET], session)
        session2, fetcher2, _ = make_session(WS_ROUTES)
        [again] = self.run_targets([WS_TARGET], session2)
        self.assertEqual((again["event"], again["reason"]), ("skipped", "ALREADY_ACQUIRED"))
        self.assertEqual(fetcher2.calls, [])
        session3, fetcher3, _ = make_session(WS_ROUTES)
        [refetched] = self.run_targets([WS_TARGET], session3, refresh=True)
        self.assertEqual(refetched["event"], "saved")
        self.assertEqual(len(fetcher3.calls), 2)

    def test_identical_content_from_another_target_is_duplicate(self):
        routes = dict(WS_ROUTES)
        other = "https://zh.wikisource.org/wiki/%E8%AB%96%E8%AA%9E%E6%B3%A8"
        routes[other] = WS_ROUTES[WS_URL]
        session, _, _ = make_session(routes)
        first, second = self.run_targets([WS_TARGET, {"connector": "wikisource", "lang": "zh", "title": "論語注"}], session)
        self.assertEqual(second["event"], "duplicate")
        self.assertEqual(second["duplicate_of"], first["target_key"])
        self.assertEqual(len(list((self.raw / "acquired" / "wikisource").iterdir())), 1)

    def test_retry_after_is_honoured(self):
        routes = dict(WS_ROUTES)
        routes[WS_URL] = [response(429, headers={"retry-after": "5"}), WS_ROUTES[WS_URL]]
        session, fetcher, clock = make_session(routes)
        [result] = self.run_targets([WS_TARGET], session)
        self.assertEqual(result["event"], "saved")
        self.assertIn(5.0, clock.sleeps)
        self.assertEqual(len(fetcher.calls), 3)

    def test_excessive_retry_after_fails(self):
        routes = dict(WS_ROUTES)
        routes[WS_URL] = response(503, headers={"retry-after": "3600"})
        session, _, _ = make_session(routes)
        [result] = self.run_targets([WS_TARGET], session)
        self.assertEqual((result["event"], result["reason"]), ("failed", "RATE_LIMITED"))

    def test_persistent_5xx_gives_up(self):
        routes = dict(WS_ROUTES)
        routes[WS_URL] = response(502)
        session, fetcher, _ = make_session(routes)
        [result] = self.run_targets([WS_TARGET], session)
        self.assertEqual(result["reason"], "HTTP_502")
        self.assertEqual(len(fetcher.calls), 1 + 1 + POLICY["defaults"]["max_retries"])

    def test_redirect_off_allowlist_is_refused(self):
        routes = dict(WS_ROUTES)
        routes[WS_URL] = response(body=b"<p>x</p>", url="https://evil.example/x")
        session, _, _ = make_session(routes)
        [result] = self.run_targets([WS_TARGET], session)
        self.assertEqual(result["reason"], "REDIRECT_NOT_ALLOWED")
        self.assertFalse(self.raw.exists())

    def test_size_cap(self):
        policy = copy.deepcopy(POLICY)
        policy["connectors"]["wikisource"]["max_bytes"] = 100
        session, _, _ = make_session(WS_ROUTES, policy=policy)
        [result] = self.run_targets([WS_TARGET], session)
        self.assertEqual(result["reason"], "TOO_LARGE")

    def test_budget_exhaustion(self):
        session, _, _ = make_session(WS_ROUTES, max_requests=1)
        [result] = self.run_targets([WS_TARGET], session)
        self.assertEqual((result["event"], result["reason"]), ("refused", "BUDGET_EXHAUSTED"))

    def ia_routes(self, metadata, files=None, body=b"\xe5\xad\x90\xe6\x9b\xb0", name="lunyu_djvu.txt"):
        files = files if files is not None else [{"name": "lunyu.pdf"}, {"name": name}]
        return {
            "https://archive.org/robots.txt": response(body=b"User-agent: *\nDisallow: /control/\n"),
            "https://archive.org/metadata/lunyu": response(body=json.dumps({"metadata": metadata, "files": files}).encode()),
            f"https://archive.org/download/lunyu/{name}": response(
                body=body, headers={"content-type": "text/plain; charset=utf-8"},
                url=f"https://ia800100.us.archive.org/1/items/lunyu/{name}"),
        }

    def test_internet_archive_public_domain(self):
        routes = self.ia_routes({"title": "論語", "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"})
        session, _, _ = make_session(routes)
        [result] = self.run_targets([{"connector": "internet_archive", "identifier": "lunyu"}], session)
        self.assertEqual(result["event"], "saved", result)
        self.assertEqual(result["ia_file"], "lunyu_djvu.txt")
        self.assertEqual(result["rights_status"], "public_domain")
        self.assertEqual((self.raw / result["path"]).read_text(encoding="utf-8"), "子曰")

    def test_internet_archive_unknown_rights_needs_explicit_flag(self):
        routes = self.ia_routes({"title": "論語"})
        session, _, _ = make_session(routes)
        [refused] = self.run_targets([{"connector": "internet_archive", "identifier": "lunyu"}], session)
        self.assertEqual(refused["reason"], "RIGHTS_UNVERIFIED")
        session, _, _ = make_session(routes)
        [saved] = self.run_targets([{"connector": "internet_archive", "identifier": "lunyu"}], session, allow_unverified=True)
        self.assertEqual(saved["event"], "saved")
        self.assertTrue(saved["rights_review_required"])

    def test_internet_archive_restricted_and_private(self):
        session, fetcher, _ = make_session(self.ia_routes({"access-restricted-item": "true"}))
        [result] = self.run_targets([{"connector": "internet_archive", "identifier": "lunyu"}], session)
        self.assertEqual(result["reason"], "ACCESS_RESTRICTED")
        self.assertFalse(any("/download/" in c[0] for c in fetcher.calls))
        routes = self.ia_routes({"licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/"},
                                files=[{"name": "lunyu_djvu.txt", "private": "true"}])
        session, _, _ = make_session(routes)
        [result] = self.run_targets([{"connector": "internet_archive", "identifier": "lunyu"}], session)
        self.assertEqual(result["reason"], "NO_TEXT_FILE")

    def test_gutenberg_requires_mirror(self):
        session, fetcher, _ = make_session({})
        [result] = self.run_targets([{"connector": "gutenberg", "ebook": 12345}], session)
        self.assertEqual(result["reason"], "CONNECTOR_NOT_CONFIGURED")
        self.assertEqual(fetcher.calls, [])

    def test_gutenberg_mirror_tries_filenames_and_flags_us_only_rights(self):
        policy = copy.deepcopy(POLICY)
        policy["connectors"]["gutenberg"]["mirror"] = "https://pg.mirror.example/gutenberg"
        routes = {
            "https://pg.mirror.example/robots.txt": response(404),
            "https://pg.mirror.example/gutenberg/1/2/3/4/12345/12345-8.txt": response(body=b"Call me Ishmael."),
        }
        session, fetcher, _ = make_session(routes, policy=policy)
        [result] = self.run_targets([{"connector": "gutenberg", "ebook": 12345}], session)
        self.assertEqual(result["reason"], "RIGHTS_UNVERIFIED")
        policy["jurisdiction"] = "US"
        session, _, _ = make_session(routes, policy=policy)
        [result] = self.run_targets([{"connector": "gutenberg", "ebook": 12345}], session)
        self.assertEqual(result["event"], "saved")
        self.assertTrue(result["url"].endswith("12345-8.txt"))

    def test_url_connector_needs_allowlisted_host_and_declared_rights(self):
        session, fetcher, _ = make_session({})
        target = {"connector": "url", "url": "https://texts.example/a.txt", "rights": "public_domain"}
        [result] = self.run_targets([target], session)
        self.assertEqual(result["reason"], "HOST_NOT_ALLOWED")
        policy = copy.deepcopy(POLICY)
        policy["connectors"]["url"]["hosts"] = ["texts.example"]
        session, fetcher, _ = make_session({}, policy=policy)
        [result] = self.run_targets([dict(target, rights="")], session)
        self.assertEqual(result["reason"], "RIGHTS_UNDECLARED")
        self.assertEqual(fetcher.calls, [])

    def test_local_import_copies_bytes_and_requires_rights(self):
        src = self.root / "incoming" / "书.txt"
        src.parent.mkdir()
        src.write_bytes("张居正\r\n".encode("gb18030"))
        session, fetcher, _ = make_session({}, contact="")
        [refused] = self.run_targets([{"connector": "local", "path": str(src)}], session)
        self.assertEqual(refused["reason"], "RIGHTS_UNDECLARED")
        [saved] = self.run_targets([{"connector": "local", "path": str(src), "rights": "user_owned_copy"}], session)
        self.assertEqual(saved["event"], "saved", saved)
        self.assertEqual((self.raw / saved["path"]).read_bytes(), src.read_bytes(), "本地导入不得改写字节")
        self.assertNotIn("user_agent", saved)
        bad = self.root / "incoming" / "scan.docx"
        bad.write_bytes(b"x")
        [unsupported] = self.run_targets([{"connector": "local", "path": str(bad), "rights": "user_owned_copy"}], session)
        self.assertEqual(unsupported["reason"], "UNSUPPORTED_TYPE")

    def test_disabled_connector(self):
        policy = copy.deepcopy(POLICY)
        policy["connectors"]["wikisource"]["enabled"] = False
        session, fetcher, _ = make_session(WS_ROUTES, policy=policy)
        [result] = self.run_targets([WS_TARGET], session)
        self.assertEqual(result["reason"], "CONNECTOR_DISABLED")

    def test_dry_run_writes_nothing(self):
        session, fetcher, _ = make_session(WS_ROUTES)
        [result] = self.run_targets([WS_TARGET], session, dry_run=True)
        self.assertEqual(result["event"], "planned")
        self.assertEqual(fetcher.calls, [])
        self.assertFalse(self.log.exists())

    def test_registry_picks_up_rights_from_log(self):
        session, _, _ = make_session(WS_ROUTES)
        [result] = self.run_targets([WS_TARGET], session)
        (self.raw / "own.txt").write_text("自备", encoding="utf-8")
        provenance = registry.load_acquisition_provenance(self.log)
        reg = registry.build_registry(self.raw, provenance=provenance)
        by_path = {r["relative_path"]: r for r in reg["sources"]}
        acquired = by_path[result["path"]]
        self.assertEqual(acquired["rights_status"], "cc-by-sa")
        self.assertEqual(acquired["origin"], "acquired:wikisource")
        self.assertEqual(acquired["canonical_url"], WS_URL)
        self.assertEqual(by_path["own.txt"]["rights_status"], "unverified")
        # 文件被改过（hash 不再吻合）就不再冒用日志里的权利状态
        (self.raw / result["path"]).write_text("改过", encoding="utf-8")
        reg = registry.build_registry(self.raw, provenance=provenance)
        self.assertEqual({r["relative_path"]: r for r in reg["sources"]}[result["path"]]["rights_status"], "unverified")


class CliTests(unittest.TestCase):
    def test_dry_run_json_via_main(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as td:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = acq.main(["demo", "--root", td, "--wikisource", "zh:論語", "--dry-run", "--json",
                                 "--local", str(Path(td) / "missing.txt"), "--rights", "user_owned_copy"])
            results = json.loads(out.getvalue())
            self.assertEqual(code, 1)  # 本地文件不存在 → failed
            self.assertEqual(results[1]["reason"], "NOT_FOUND")
            self.assertIn(results[0]["event"], ("planned", "refused"))  # 取决于是否配置了 MDF_CONTACT

    def test_no_targets_is_an_error(self):
        with tempfile.TemporaryDirectory() as td, self.assertRaises(SystemExit):
            import contextlib
            import io
            with contextlib.redirect_stderr(io.StringIO()):
                acq.main(["demo", "--root", td])


if __name__ == "__main__":
    unittest.main()
