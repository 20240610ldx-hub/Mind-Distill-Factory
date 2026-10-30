#!/usr/bin/env python3
"""采集计划：模型列候选，目录核对，用户批准后才交给 `mdf acquire`。

以前「该采哪些书」靠子代理在 collection_notes 里写一段话：书名怎么落成维基文库篇名、Internet Archive 条目号要人去查，
模型凭记忆给的篇名、版本没人核对（墨子 3 篇篇名就标错过）。现在分三段：

1. acquisition-scout 凭记忆写结构化候选 `sources/{slug}/acquisition_candidates.json`（不联网）；
2. 本脚本只查白名单站点的目录，走 acquire 的同一套闸门（https、主机白名单、User-Agent 联系方式、robots.txt、TDMRep、
   请求间隔与上限）：
   - 维基文库：只读 robots.txt 放行的 /wiki/ 页——作者页与作品页。它的搜索接口（/w/api.php、Special:Search）对爬虫是
     Disallow，不调用，也不借本地化的搜索页别名绕开；
   - Internet Archive：advancedsearch.php，排除借阅馆藏（inlibrary / printdisabled / lendinglibrary）；
   - Project Gutenberg：网站禁止自动访问，只读离线目录 pg_catalog.csv（`--gutenberg-catalog` 或策略里的 catalog_csv）。
   凭记忆说出、目录里查不到的不进计划；同名但作者对不上的只算「待选定」；
3. 草稿 `processed/acquisition_plan.draft.json` 与清单 `processed/acquisition_plan.md` 给用户看，`--approve` 之后才写进
   acquire 默认读取的 `sources/{slug}/acquisition_plan.json`。下载本身仍要用户同意后再跑 `mdf acquire`。

法域未设定时（见 acquisition_settings），公有领域判定一律标「待复核」。

    python scripts/mdf.py acquire-plan <slug> --check          # 只校验候选清单（离线，检查点）
    python scripts/mdf.py acquire-plan <slug> --dry-run        # 列出要查哪些目录，不联网
    python scripts/mdf.py acquire-plan <slug>                  # 核对目录，写草稿与清单
    python scripts/mdf.py acquire-plan <slug> --approve c01,c03   # 或 --approve all
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, NamedTuple
from urllib.parse import unquote, urlencode

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:  # 按路径加载本模块时也能找到同目录的 sibling、workspace
    sys.path.insert(0, _SCRIPTS_DIR)
from sibling import load_sibling  # noqa: E402  按路径加载兄弟模块的唯一入口
from workspace import data_root  # noqa: E402  数据根解析规则只在 workspace.py 定义

acquire = load_sibling("acquire")

CANDIDATES_SCHEMA = "acquisition-candidates-v1"
DRAFT_SCHEMA = "acquisition-plan-draft-v1"
PLAN_SCHEMA = "acquisition-plan-v1"
CATALOGS = ("wikisource", "internet_archive", "gutenberg")
CATALOG_LABELS = {"wikisource": "维基文库", "internet_archive": "Internet Archive", "gutenberg": "Project Gutenberg"}
NETWORK_CATALOGS = {"wikisource", "internet_archive"}
KINDS = ("primary", "secondary")
_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
# 维基文库作者页的命名空间。只列确认过的语言；其他语言只按作品页核对。
AUTHOR_NAMESPACES = {"zh": "作者", "ja": "作者", "en": "Author"}
LENDING_COLLECTIONS = ("inlibrary", "printdisabled", "lendinglibrary")
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_FIELDS = ("identifier", "title", "creator", "date", "language", "licenseurl", "possible-copyright-status")
IA_ROWS = 10
MAX_SUBPAGES = 300
PUBLIC_DOMAIN = {"public_domain", "public_domain_us"}
_DISAMBIG_MARKERS = ("消歧義", "消歧义", "Category:Disambiguation", "Disambiguation pages")
# 页面所属分类里有这些，就是「从中选一个」的页：消歧义页、多版本页、多译本页（英文站的《沉思录》就是译本列表页）
CHOICE_CATEGORIES = {"Disambiguation pages", "Versions pages", "Translations pages", "消歧義", "消歧义"}
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_LUCENE_SPECIAL = re.compile(r'[+\-&|!(){}\[\]^"~*?:\\/]')


# ── 值对象 ────────────────────────────────────────────────────────────


class Person(NamedTuple):
    name: str
    aliases: tuple[str, ...]
    death_year: int | None
    wikisource_author: dict[str, str]


class Candidate(NamedTuple):
    """一条候选：凭记忆列出的作品，等目录核对。titles 是各目录可能用的篇名写法（繁简、通行题、译名）。"""
    id: str
    work: str
    titles: tuple[str, ...]
    kind: str
    language: str
    year: int | None
    why: str
    creator: str | None
    catalogs: tuple[str, ...]
    editors: tuple[str, ...] = ()  # 译者、编者、校注者：目录常把他们登记成作者


class CatalogHit(NamedTuple):
    """目录里的一条命中。exact = 篇名与作者都对上；partial = 只有篇名对上，要人选定。"""
    catalog: str
    confidence: str
    title: str
    creator: str
    date: str
    targets: tuple[dict[str, Any], ...]
    rights_status: str
    rights_evidence: str
    evidence_url: str
    note: str = ""


class Resolution(NamedTuple):
    """一条候选的核对结果：resolved（有 exact 命中）/ ambiguous（只有 partial 或消歧义页）/ unresolved。"""
    candidate_id: str
    status: str
    hits: tuple[CatalogHit, ...]
    notes: tuple[str, ...]


# ── 路径 ──────────────────────────────────────────────────────────────


def candidates_path(root: Path, slug: str) -> Path:
    return Path(root) / "sources" / slug / "acquisition_candidates.json"


def draft_path(root: Path, slug: str) -> Path:
    return Path(root) / "sources" / slug / "processed" / "acquisition_plan.draft.json"


def report_path(root: Path, slug: str) -> Path:
    return Path(root) / "sources" / slug / "processed" / "acquisition_plan.md"


def plan_path(root: Path, slug: str) -> Path:
    """acquire 不带参数时默认读的计划文件（acquire.targets_from_args）。"""
    return Path(root) / "sources" / slug / "acquisition_plan.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    """批准记录里的 draft_sha256 用它算；状态表据此判断批准之后草稿有没有重做过。"""
    path = Path(path)
    return _sha256(path.read_bytes()) if path.is_file() else None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_draft(root: Path, slug: str) -> dict[str, Any] | None:
    data = _read_json(draft_path(root, slug))
    return data if isinstance(data, dict) and data.get("schema") == DRAFT_SCHEMA else None


def candidates_sha(root: Path, slug: str) -> str | None:
    return sha256_file(candidates_path(root, slug))


# ── 候选清单 ──────────────────────────────────────────────────────────


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_candidates(data: Any) -> list[str]:
    """逐项核对候选清单，返回全部问题（空 = 合格）。"""
    if not isinstance(data, dict):
        return ["候选清单必须是 JSON 对象"]
    errors: list[str] = []
    if data.get("schema") != CANDIDATES_SCHEMA:
        errors.append(f"schema 应为 {CANDIDATES_SCHEMA}，实际 {data.get('schema')!r}")
    person = data.get("person")
    if not isinstance(person, dict) or not _nonempty_str(person.get("name")):
        errors.append("person.name 必填（人物名）")
        person = person if isinstance(person, dict) else {}
    aliases = person.get("aliases", [])
    if not isinstance(aliases, list) or not all(_nonempty_str(a) for a in aliases):
        errors.append("person.aliases 应为非空字符串列表")
    death = person.get("death_year")
    if death is not None and (not isinstance(death, int) or isinstance(death, bool)):
        errors.append(f"person.death_year 应为整数（公元前写负数），实际 {death!r}")
    authors = person.get("wikisource_author", {})
    if not isinstance(authors, dict) or not all(
            acquire._LANG_RE.fullmatch(str(k)) and _nonempty_str(v) for k, v in authors.items()):
        errors.append("person.wikisource_author 应为 {语言代码: 维基文库作者页名}")
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return errors + ["candidates 必须是非空列表"]
    seen: set[str] = set()
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            errors.append(f"candidates[{index}] 不是对象")
            continue
        cid = item.get("id")
        label = cid if isinstance(cid, str) else f"candidates[{index}]"
        if not isinstance(cid, str) or not _ID_RE.fullmatch(cid):
            errors.append(f"{label}：id 只能用小写字母、数字、- 与 _（如 c01）")
        elif cid in seen:
            errors.append(f"{label}：id 重复")
        else:
            seen.add(cid)
        if not _nonempty_str(item.get("work")):
            errors.append(f"{label}：work 必填（作品名）")
        titles = item.get("titles")
        if not isinstance(titles, list) or not titles or not all(_nonempty_str(t) for t in titles):
            errors.append(f"{label}：titles 至少一个篇名写法")
        if item.get("kind") not in KINDS:
            errors.append(f"{label}：kind 应为 {'/'.join(KINDS)}，实际 {item.get('kind')!r}")
        if not isinstance(item.get("language"), str) or not acquire._LANG_RE.fullmatch(item["language"]):
            errors.append(f"{label}：language 应为语言代码（如 zh、en），实际 {item.get('language')!r}")
        if not _nonempty_str(item.get("why")):
            errors.append(f"{label}：why 必填（为什么需要这部作品）")
        year = item.get("year")
        if year is not None and (not isinstance(year, int) or isinstance(year, bool)):
            errors.append(f"{label}：year 应为整数")
        if item.get("creator") is not None and not _nonempty_str(item.get("creator")):
            errors.append(f"{label}：creator 应为非空字符串（他人所写的作品才填）")
        editors = item.get("editors", [])
        if not isinstance(editors, list) or not all(_nonempty_str(e) for e in editors):
            errors.append(f"{label}：editors 应为译者、编者名字的列表")
        catalogs = item.get("catalogs", list(CATALOGS))
        if not isinstance(catalogs, list) or not catalogs:
            errors.append(f"{label}：catalogs 应为非空列表")
        else:
            unknown = [c for c in catalogs if c not in CATALOGS]
            if unknown:
                errors.append(f"{label}：没有这些目录 {unknown}（可用：{'、'.join(CATALOGS)}）")
    return errors


def parse_candidates(data: Any) -> tuple[Person, list[Candidate]]:
    errors = check_candidates(data)
    if errors:
        raise ValueError("候选清单不合格：\n- " + "\n- ".join(errors))
    raw_person = data["person"]
    person = Person(
        name=raw_person["name"].strip(),
        aliases=tuple(a.strip() for a in raw_person.get("aliases", [])),
        death_year=raw_person.get("death_year"),
        wikisource_author={k: v.strip() for k, v in raw_person.get("wikisource_author", {}).items()},
    )
    candidates = [
        Candidate(
            id=item["id"], work=item["work"].strip(), titles=tuple(t.strip() for t in item["titles"]),
            kind=item["kind"], language=item["language"], year=item.get("year"), why=item["why"].strip(),
            creator=(item.get("creator") or "").strip() or None,
            catalogs=tuple(dict.fromkeys(item.get("catalogs", list(CATALOGS)))),
            editors=tuple(e.strip() for e in item.get("editors", [])),
        )
        for item in data["candidates"]
    ]
    return person, candidates


def load_candidates(path: Path) -> tuple[Person, list[Candidate]]:
    return parse_candidates(json.loads(Path(path).read_text(encoding="utf-8")))


# ── 名称比对 ──────────────────────────────────────────────────────────


def _fold(text: str) -> str:
    """比对用的规整：NFKC、小写、去掉空白与标点（《》、括号、引号一并去掉）。"""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text or "").lower())


def titles_match(a: str, b: str) -> bool:
    return bool(_fold(a)) and _fold(a) == _fold(b)


def names_match(name: str, field: str) -> bool:
    """作者名对得上吗。中日文名按规整后的子串；西文名要求每个词都出现（「Lu, Xun, 1881-1936」对得上 Lu Xun）。"""
    if not name or not field:
        return False
    if _CJK_RE.search(name):
        return _fold(name) in _fold(field)
    words = re.findall(r"[^\W\d_]+", unicodedata.normalize("NFKC", name).lower())
    field_words = set(re.findall(r"[^\W\d_]+", unicodedata.normalize("NFKC", field).lower()))
    return bool(words) and all(w in field_words for w in words)


def _author_names(person: Person, candidate: Candidate) -> list[str]:
    names = [candidate.creator] if candidate.creator else [person.name, *person.aliases]
    return list(dict.fromkeys(names + list(candidate.editors)))


def creator_matches(person: Person, candidate: Candidate, field: str) -> bool:
    return any(names_match(n, field) for n in _author_names(person, candidate))


def _year_text(year: int) -> str:
    return f"公元前 {-year} 年" if year < 0 else f"{year} 年"


# ── 维基文库 ──────────────────────────────────────────────────────────


class _Links(HTMLParser):
    """收集正文（mw-parser-output）里的站内链接，并记下有没有消歧义标记。"""

    def __init__(self, lang: str | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = lang
        self.stack: list[bool] = []
        self.root_open = 0
        self.found_root = False
        self.root_links: list[str] = []
        self.all_links: list[str] = []
        self.disambig = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if "disambig" in (attributes.get("id") or "").lower() or any("disambig" in c.lower() for c in classes):
            self.disambig = True
        if tag == "a" and attributes.get("href"):
            title = wiki_title(attributes["href"] or "", self.lang)
            if title:
                self.all_links.append(title)
                if self.root_open:
                    self.root_links.append(title)
        if tag in acquire.VOID_TAGS:
            return
        is_root = "mw-parser-output" in classes and self.root_open == 0
        self.found_root |= is_root
        self.stack.append(is_root)
        self.root_open += is_root

    def handle_endtag(self, tag: str) -> None:
        if tag in acquire.VOID_TAGS or not self.stack:
            return
        self.root_open -= self.stack.pop()


def wiki_title(href: str, lang: str | None = None) -> str | None:
    """`/wiki/墳/題記#x` → 「墳/題記」。英文站把站内链接渲染成绝对地址，同一个语言站的
    `https://{lang}.wikisource.org/wiki/…` 也算；编辑链接、红链、别的站返回 None。"""
    prefixes = ["/wiki/"] + ([f"https://{lang}.wikisource.org/wiki/", f"//{lang}.wikisource.org/wiki/"] if lang else [])
    prefix = next((p for p in prefixes if href.startswith(p)), None)
    if prefix is None:
        return None
    path = href[len(prefix):].split("#", 1)[0]
    if "?" in path:
        return None
    title = unquote(path).replace("_", " ").strip()
    return title or None


def analyze_page(markup: str, lang: str | None = None) -> tuple[list[str], bool]:
    """返回（正文里的内容页链接，按出现顺序去重；是不是要从中选一个的页）。带命名空间（含「:」）的链接不算内容页。
    消歧义、多版本、多译本页都算「选一个」：看消歧义标记，也看页面分类（分类链接在正文之外）。"""
    parser = _Links(lang)
    parser.feed(markup)
    parser.close()
    links = parser.root_links if parser.found_root else parser.all_links
    content = [t for t in dict.fromkeys(links) if ":" not in t]
    categories = {t.split(":", 1)[1] for t in parser.all_links if t.startswith("Category:")}
    text = unquote(html.unescape(markup))
    return content, (parser.disambig or bool(categories & CHOICE_CATEGORIES)
                     or any(m in text for m in _DISAMBIG_MARKERS))


def _mentions(markup: str, names: list[str]) -> bool:
    folded = _fold(unquote(html.unescape(markup)))
    return any(_fold(n) and _fold(n) in folded for n in names)


class WikisourceCatalog:
    """一次核对里共享的维基文库读取：作者页与作品页各取一次。只读 /wiki/ 页（robots.txt 放行的路径）。"""

    def __init__(self, session: Any):
        self.session = session
        self._pages: dict[tuple[str, str], str | None] = {}

    def page(self, lang: str, title: str) -> str | None:
        key = (lang, title)
        if key not in self._pages:
            try:
                response = self.session.get(acquire.wikisource_url(lang, title), "wikisource")
            except acquire.Failed as exc:
                if exc.code != "NOT_FOUND":
                    raise
                self._pages[key] = None
            else:
                self._pages[key] = response.body.decode("utf-8", errors="replace")
        return self._pages[key]

    def author_titles(self, lang: str, name: str) -> list[str]:
        namespace = AUTHOR_NAMESPACES.get(lang)
        markup = self.page(lang, f"{namespace}:{name}") if namespace else None
        return analyze_page(markup, lang)[0] if markup else []

    def hits(self, person: Person, candidate: Candidate) -> tuple[list[CatalogHit], list[str], bool]:
        lang = candidate.language
        conn = self.session.policy["connectors"]["wikisource"]
        author = None if candidate.creator else person.wikisource_author.get(lang)
        listed = self.author_titles(lang, author) if author else []
        found, from_author_page, markup = None, False, None
        for link in listed:
            if any(titles_match(link, t) for t in candidate.titles):
                found, from_author_page = link, True
                markup = self.page(lang, link)
                break
        if markup is None:
            for title in candidate.titles:
                markup = self.page(lang, title)
                if markup is not None:
                    found, from_author_page = title, False
                    break
        if markup is None or found is None:
            where = f"作者页「{AUTHOR_NAMESPACES.get(lang)}:{author}」没有列出，" if author else ""
            return [], [f"维基文库（{lang}）：{where}也没有《{'》《'.join(candidate.titles)}》这一页"], False
        links, disambig = analyze_page(markup, lang)
        url = acquire.wikisource_url(lang, found)
        if disambig:
            options = "、".join(links[:10]) or "（页面上没有可选条目）"
            return [], [f"维基文库《{found}》是消歧义或多版本页，可选：{options}——把准确篇名写进候选的 titles 再核对"], True
        exact = from_author_page or _mentions(markup, _author_names(person, candidate))
        subpages = [t for t in links if t.startswith(found + "/")]
        note = ""
        if subpages:
            note = f"《{found}》是目录页，展开为 {min(len(subpages), MAX_SUBPAGES)} 篇子页面"
            if len(subpages) > MAX_SUBPAGES:
                note += f"（共 {len(subpages)} 篇，只取前 {MAX_SUBPAGES} 篇）"
            subpages = subpages[:MAX_SUBPAGES]
        targets = tuple({"connector": "wikisource", "lang": lang, "title": t} for t in (subpages or [found]))
        if not exact:
            note = (note + "；" if note else "") + "页面上找不到作者名，可能是同名的别的作品"
        hit = CatalogHit(
            catalog="wikisource", confidence="exact" if exact else "partial", title=found,
            creator=(author or candidate.creator or "") if exact else "", date="", targets=targets,
            rights_status=conn.get("rights_status", "cc-by-sa"), rights_evidence=conn.get("rights_evidence", ""),
            evidence_url=url, note=note,
        )
        return [hit], [], False


# ── Internet Archive ──────────────────────────────────────────────────


def creator_clause(names: list[str] | tuple[str, ...]) -> str:
    """作者条件：中日文名按短语，西文名每个词都要有（「Aurelius, Marcus」也能对上 Marcus Aurelius）。单字母缩写不进查询。"""
    parts = []
    for name in names:
        if _CJK_RE.search(name):
            phrase = _LUCENE_SPECIAL.sub("", name).strip()
            if phrase:
                parts.append(f'"{phrase}"')
        else:
            words = [w for w in re.findall(r"[^\W\d_]+", unicodedata.normalize("NFKC", name)) if len(w) > 1]
            if words:
                parts.append("(" + " AND ".join(words) + ")")
    return " OR ".join(dict.fromkeys(parts))


def ia_query(candidate: Candidate, names: list[str] | tuple[str, ...] = ()) -> str:
    titles = " OR ".join('"' + t.replace('"', "") + '"' for t in candidate.titles)
    creators = creator_clause(names)
    return (f"title:({titles}) " + (f"AND creator:({creators}) " if creators else "") + "AND mediatype:(texts) "
            f"AND NOT collection:({' OR '.join(LENDING_COLLECTIONS)})")


def ia_search_url(candidate: Candidate, names: list[str] | tuple[str, ...] = ()) -> str:
    params = [("q", ia_query(candidate, names)), *[("fl[]", f) for f in IA_FIELDS], ("rows", str(IA_ROWS)),
              ("output", "json")]
    return f"{IA_SEARCH}?{urlencode(params)}"


def _rights_rank(policy: dict[str, Any], status: str) -> int:
    """同一部书有多个副本时的先后：权利能放行的 → 有公有领域依据的（法域未定，待复核）→ 未核实 → 不放行。"""
    decision = acquire.rights_decision(policy, status)
    if decision == "allow":
        return 0
    return 1 if status in PUBLIC_DOMAIN else (2 if decision == "review" else 3)


def ia_hits(session: Any, person: Person, candidate: Candidate) -> tuple[list[CatalogHit], list[str]]:
    """先按「篇名 + 作者」查：通用篇名（如 Meditations）只按篇名查，本人的书会被同名书挤出结果。查不到再退回只按篇名，
    让同名别人的书作为「待选定」露出来。"""
    exact: list[CatalogHit] = []
    partial: list[CatalogHit] = []
    for names in (_author_names(person, candidate), ()):
        response = session.get(ia_search_url(candidate, names), "internet_archive")
        try:
            docs = json.loads(response.body.decode("utf-8"))["response"]["docs"]
        except (UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
            return [], [f"Internet Archive：检索结果不是预期的 JSON（{exc}）"]
        exact, partial = _ia_classify(docs if isinstance(docs, list) else [], person, candidate)
        if exact or partial:
            break
    exact.sort(key=lambda h: _rights_rank(session.policy, h.rights_status))
    notes = [] if exact or partial else [
        f"Internet Archive：没有篇名对得上的公开文本（{'/'.join(candidate.titles)}；借阅馆藏不算）"]
    return exact + partial, notes


def _ia_classify(docs: list[Any], person: Person, candidate: Candidate) -> tuple[list[CatalogHit], list[CatalogHit]]:
    exact: list[CatalogHit] = []
    partial: list[CatalogHit] = []
    for doc in docs:
        identifier = str(doc.get("identifier") or "")
        title = acquire._first(doc.get("title"))
        if not acquire._IA_ID_RE.fullmatch(identifier) or not any(titles_match(title, t) for t in candidate.titles):
            continue
        creator = acquire._first(doc.get("creator"))
        rights, evidence = acquire.ia_rights(doc)
        matched = creator_matches(person, candidate, creator)
        hit = CatalogHit(
            catalog="internet_archive", confidence="exact" if matched else "partial", title=title,
            creator=creator[:200], date=acquire._first(doc.get("date"))[:10],
            targets=({"connector": "internet_archive", "identifier": identifier},),
            rights_status=rights, rights_evidence=evidence, evidence_url=f"https://archive.org/details/{identifier}",
            note="" if matched else "作者对不上，可能是同名的别的书",
        )
        (exact if matched else partial).append(hit)
    return exact, partial


# ── Project Gutenberg（离线目录）────────────────────────────────────


def read_gutenberg_catalog(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def gutenberg_hits(rows: list[dict[str, str]] | None, policy: dict[str, Any], person: Person,
                   candidate: Candidate) -> tuple[list[CatalogHit], list[str]]:
    if rows is None:
        return [], ["Project Gutenberg：CATALOG_NOT_CONFIGURED——网站禁止自动访问，只能查离线目录。下载 pg_catalog.csv 后"
                    "用 --gutenberg-catalog 指定，或填 connectors.gutenberg.catalog_csv"]
    conn = policy["connectors"]["gutenberg"]
    exact: list[CatalogHit] = []
    partial: list[CatalogHit] = []
    for row in rows:
        title = (row.get("Title") or "").split("\n", 1)[0].strip()
        if row.get("Type") != "Text" or not any(titles_match(title, t) for t in candidate.titles):
            continue
        try:
            ebook = int(row.get("Text#") or "")
        except ValueError:
            continue
        creator = row.get("Authors") or ""
        matched = creator_matches(person, candidate, creator)
        hit = CatalogHit(
            catalog="gutenberg", confidence="exact" if matched else "partial", title=title, creator=creator[:200],
            date=row.get("Issued") or "", targets=({"connector": "gutenberg", "ebook": ebook},),
            rights_status=conn.get("rights_status", "public_domain_us"), rights_evidence=conn.get("rights_evidence", ""),
            evidence_url=f"https://www.gutenberg.org/ebooks/{ebook}", note="" if matched else "作者对不上",
        )
        (exact if matched else partial).append(hit)
    notes = [] if exact or partial else [f"Project Gutenberg：离线目录里没有《{'/'.join(candidate.titles)}》"]
    return exact + partial, notes


# ── 核对 ──────────────────────────────────────────────────────────────


def _enabled(policy: dict[str, Any], catalog: str) -> bool:
    return bool(policy.get("connectors", {}).get(catalog, {}).get("enabled", False))


def needs_network(policy: dict[str, Any], candidates: list[Candidate]) -> bool:
    return any(c in NETWORK_CATALOGS and _enabled(policy, c) for cand in candidates for c in cand.catalogs)


def resolve(person: Person, candidates: list[Candidate], *, session: Any,
            gutenberg_catalog: Path | None = None) -> list[Resolution]:
    policy = session.policy
    wikisource = WikisourceCatalog(session)
    rows = read_gutenberg_catalog(gutenberg_catalog) if gutenberg_catalog else None
    results: list[Resolution] = []
    for candidate in candidates:
        hits: list[CatalogHit] = []
        notes: list[str] = []
        ambiguous = False
        for catalog in candidate.catalogs:
            label = CATALOG_LABELS[catalog]
            if not _enabled(policy, catalog):
                notes.append(f"{label}：CONNECTOR_DISABLED——acquisition_policy.json 里未启用，没有查")
                continue
            try:
                if catalog == "wikisource":
                    found, more, flagged = wikisource.hits(person, candidate)
                    ambiguous |= flagged
                elif catalog == "internet_archive":
                    found, more = ia_hits(session, person, candidate)
                else:
                    found, more = gutenberg_hits(rows, policy, person, candidate)
            except acquire.AcquireError as exc:
                found, more = [], [f"{label}：{exc.code} {exc.message}"]
            hits += found
            notes += more
        exact = [h for h in hits if h.confidence == "exact"]
        status = "resolved" if exact else ("ambiguous" if hits or ambiguous else "unresolved")
        ordered = exact + [h for h in hits if h.confidence != "exact"]
        results.append(Resolution(candidate.id, status, tuple(ordered), tuple(notes)))
    return results


def assess_rights(hit: CatalogHit, person: Person, policy: dict[str, Any]) -> dict[str, Any]:
    """计划阶段的权利预判。法域未设定时公有领域一律待复核（用户 2026-10-24 决定）；最终仍以 acquire 取回时的判定为准。"""
    decision = acquire.rights_decision(policy, hit.rights_status)
    law = acquire.jurisdiction(policy)
    public_domain = hit.rights_status in PUBLIC_DOMAIN
    review = decision != "allow" or (public_domain and not law)
    parts = [f"{hit.rights_status}（{hit.rights_evidence or '目录未给依据'}）"]
    if public_domain:
        if person.death_year is not None:
            parts.append(f"作者卒于 {_year_text(person.death_year)}")
        parts.append("法域未设定，公有领域判定待复核" if not law else f"法域 {law}")
    if decision == "review" and not public_domain:
        parts.append("权利未核实，待复核")
    if decision == "refuse":
        parts.append("不在允许的权利状态里，不能采集")
    return {"rights_status": hit.rights_status, "rights_evidence": hit.rights_evidence, "decision": decision,
            "review_required": review, "note": "；".join(parts)}


def _blockers(session: Any, targets: tuple[dict[str, Any], ...]) -> list[str]:
    """acquire 不联网就能判定的闸门（连接器启用、联系方式、镜像配置……）：过不了的目标批准了也下载不了。"""
    found: list[str] = []
    for target in targets:
        try:
            acquire.offline_checks(session.policy, session, acquire.normalize_target(target))
        except acquire.AcquireError as exc:
            if exc.code not in found:
                found.append(exc.code)
    return found


def _hit_dict(hit: CatalogHit) -> dict[str, Any]:
    return {"catalog": hit.catalog, "confidence": hit.confidence, "title": hit.title, "creator": hit.creator,
            "date": hit.date, "evidence_url": hit.evidence_url, "targets": [dict(t) for t in hit.targets],
            "note": hit.note}


def build_draft(slug: str, person: Person, candidates: list[Candidate], resolutions: list[Resolution], *,
                session: Any, candidates_sha256: str, now: str) -> dict[str, Any]:
    policy = session.policy
    by_id = {r.candidate_id: r for r in resolutions}
    entries = []
    for candidate in candidates:
        res = by_id[candidate.id]
        chosen = res.hits[0] if res.status == "resolved" else None
        rights = assess_rights(chosen, person, policy) if chosen else None
        blockers = _blockers(session, chosen.targets) if chosen else []
        if rights and rights["decision"] == "refuse":
            blockers.append("RIGHTS_NOT_ALLOWED")
        entries.append({
            "candidate_id": candidate.id, "work": candidate.work, "kind": candidate.kind, "why": candidate.why,
            "status": res.status,
            "chosen": _hit_dict(chosen) if chosen else None,
            "targets": [dict(t) for t in chosen.targets] if chosen else [],
            "rights": rights,
            "downloadable": bool(chosen) and not blockers,
            "blockers": blockers,
            "alternatives": [_hit_dict(h) for h in res.hits if h is not chosen],
            "notes": list(res.notes),
        })
    return {
        "schema": DRAFT_SCHEMA, "slug": slug, "person": person.name, "candidates_sha256": candidates_sha256,
        "resolved_at": now, "jurisdiction": acquire.jurisdiction(policy), "entries": entries,
    }


def _policy_catalog(policy: dict[str, Any], root: Path) -> Path | None:
    value = policy.get("connectors", {}).get("gutenberg", {}).get("catalog_csv") or ""
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(root) / path


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_plan(root: Path, slug: str, *, session: Any, gutenberg_catalog: Path | None = None,
             now: str | None = None) -> dict[str, Any]:
    """读候选 → 核对目录 → 写草稿与清单，返回草稿。缺联系方式时在发出任何请求前抛 acquire.Refused。"""
    raw = candidates_path(root, slug).read_bytes()
    person, candidates = parse_candidates(json.loads(raw.decode("utf-8")))
    if needs_network(session.policy, candidates):
        session.require_contact()
    catalog = gutenberg_catalog or _policy_catalog(session.policy, root)
    resolutions = resolve(person, candidates, session=session, gutenberg_catalog=catalog)
    draft = build_draft(slug, person, candidates, resolutions, session=session,
                        candidates_sha256=_sha256(raw), now=now or _now())
    _write_json(draft_path(root, slug), draft)
    report_path(root, slug).write_text(render_markdown(draft), encoding="utf-8", newline="\n")
    return draft


# ── 批准 ──────────────────────────────────────────────────────────────


def _selection(value: str | list[str]) -> list[str] | str:
    if isinstance(value, str):
        if value.strip().lower() == "all":
            return "all"
        value = value.split(",")
    return [v.strip() for v in value if v.strip()]


def approve(root: Path, slug: str, selection: str | list[str], *, now: str | None = None) -> dict[str, Any]:
    """把用户批准的候选写进 acquisition_plan.json（acquire 默认读的计划）。只认已核对、能下载的条目。"""
    draft = read_draft(root, slug)
    if draft is None:
        raise ValueError(f"还没有采集计划草稿：先运行 python scripts/mdf.py acquire-plan {slug}")
    if candidates_sha(root, slug) != draft.get("candidates_sha256"):
        raise ValueError(f"候选清单在核对之后改过，草稿已过期：先重跑 python scripts/mdf.py acquire-plan {slug}")
    entries = {e["candidate_id"]: e for e in draft["entries"]}
    chosen = _selection(selection)
    if chosen == "all":
        ids = [cid for cid, e in entries.items() if e["status"] == "resolved" and e["downloadable"]]
        if not ids:
            raise ValueError("草稿里没有已核对、能下载的条目")
    else:
        problems = []
        for cid in chosen:
            entry = entries.get(cid)
            if entry is None:
                problems.append(f"{cid}：草稿里没有这一条")
            elif entry["status"] != "resolved":
                problems.append(f"{cid}：{entry['status']}，不能批准——在候选里写准篇名（或换目录）后重跑核对")
            elif not entry["downloadable"]:
                problems.append(f"{cid}：下载不了（{'、'.join(entry['blockers'])}）")
        if problems or not chosen:
            raise ValueError("不能批准：\n- " + "\n- ".join(problems or ["没有给出候选 id"]))
        ids = list(dict.fromkeys(chosen))
    path = plan_path(root, slug)
    existing = _read_json(path)
    if isinstance(existing, list):  # 手写的计划可以只是目标列表
        existing = {"targets": existing}
    plan = existing if isinstance(existing, dict) else {}
    plan.setdefault("schema", PLAN_SCHEMA)
    plan.setdefault("targets", [])
    plan.setdefault("approvals", [])
    keys = {acquire.target_key(acquire.normalize_target(t)) for t in plan["targets"]}
    added = 0
    for cid in ids:
        for target in entries[cid]["targets"]:
            key = acquire.target_key(acquire.normalize_target(target))
            if key not in keys:
                keys.add(key)
                plan["targets"].append({**target, "candidate_id": cid})
                added += 1
    plan["approvals"].append({"approved_at": now or _now(), "candidates": ids, "targets_added": added,
                              "draft_sha256": sha256_file(draft_path(root, slug))})
    _write_json(path, plan)
    return {"approved": ids, "targets_added": added, "plan_path": path.as_posix()}


# ── 输出 ──────────────────────────────────────────────────────────────

STATUS_LABELS = {"resolved": "✅ 已核对", "ambiguous": "⚠️ 待选定", "unresolved": "❌ 查不到"}


def _describe_targets(targets: list[dict[str, Any]]) -> str:
    if not targets:
        return "—"
    first = targets[0]
    if first["connector"] == "wikisource":
        head = f"{first['lang']}:{first['title']}"
        return head if len(targets) == 1 else f"{head} 等 {len(targets)} 篇"
    if first["connector"] == "internet_archive":
        return f"IA {first['identifier']}"
    return f"PG #{first['ebook']}"


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(draft: dict[str, Any]) -> str:
    slug = draft["slug"]
    law = draft.get("jurisdiction") or "未设定（公有领域判定一律待复核）"
    lines = [
        f"# 采集计划草稿：{draft.get('person') or slug}",
        "",
        f"核对时间：{draft.get('resolved_at')} · 法域：{law}",
        "",
        "只列出目录里确实存在的条目；⚠️ 待选定、❌ 查不到的不会被下载。批准后才写进 `acquisition_plan.json`：",
        f"`python scripts/mdf.py acquire-plan {slug} --approve <候选 id，逗号分隔|all>`。下载仍要用户同意后再跑 "
        f"`python scripts/mdf.py acquire {slug} --dry-run` 与 `python scripts/mdf.py acquire {slug}`。",
        "",
        "| 候选 | 作品 | 结果 | 来源 | 下载目标 | 权利 | 说明 |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in draft["entries"]:
        status = STATUS_LABELS.get(entry["status"], entry["status"])
        if entry["status"] == "resolved" and not entry["downloadable"]:
            status += f"（⛔ 下载不了：{'、'.join(entry['blockers'])}）"
        chosen = entry.get("chosen") or {}
        source = (f"[{CATALOG_LABELS.get(chosen.get('catalog'), '')}]({chosen.get('evidence_url')})"
                  if chosen else "—")
        rights = entry.get("rights") or {}
        rights_text = (rights.get("rights_status", "") + ("（待复核）" if rights.get("review_required") else "")) or "—"
        notes = [n for n in [chosen.get("note", ""), rights.get("note", "") if rights.get("review_required") else ""] if n]
        notes += entry["notes"]
        if entry["alternatives"]:
            notes.append("备选：" + "；".join(
                f"{CATALOG_LABELS.get(a['catalog'], a['catalog'])}《{a['title']}》{a['creator']}"
                + (f"（{a['note']}）" if a.get("note") else "") for a in entry["alternatives"][:3]))
        lines.append("| " + " | ".join(_cell(x) for x in (
            entry["candidate_id"], entry["work"], status, source, _describe_targets(entry["targets"]), rights_text,
            "；".join(notes) or "—")) + " |")
    return "\n".join(lines) + "\n"


def _dry_run_lines(policy: dict[str, Any], candidates: list[Candidate]) -> list[str]:
    lines = []
    for c in candidates:
        planned = [CATALOG_LABELS[x] + ("" if _enabled(policy, x) else "（未启用，跳过）") for x in c.catalogs]
        lines.append(f"- {c.id} 《{c.work}》：{'、'.join(planned)}；篇名 {' / '.join(c.titles)}")
    return lines


def main(argv: list[str] | None = None, *, fetcher: Any = None, sleep: Callable[[float], None] | None = None) -> int:
    slug_arg = load_sibling("slug_rules").slug_arg
    parser = argparse.ArgumentParser(description="采集计划：候选清单 → 白名单站点目录核对 → 用户批准")
    parser.add_argument("slug", type=slug_arg)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只校验候选清单（离线）")
    mode.add_argument("--dry-run", action="store_true", help="列出要查的目录，不联网、不写盘")
    mode.add_argument("--approve", metavar="IDS", help="用户批准的候选 id（逗号分隔），或 all")
    parser.add_argument("--gutenberg-catalog", help="Project Gutenberg 离线目录 pg_catalog.csv 的路径")
    parser.add_argument("--max-requests", type=int, help="覆盖本次核对的请求上限")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", help="数据根目录（默认 MDF_DATA_ROOT，再默认仓库根）")
    args = parser.parse_args(argv)
    root = data_root(args.root)

    if args.approve:
        try:
            summary = approve(root, args.slug, args.approve)
        except ValueError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 1
        print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else
              f"✅ 已批准 {'、'.join(summary['approved'])}，新增 {summary['targets_added']} 个下载目标 → {summary['plan_path']}\n"
              f"下载前先问用户，再跑 python scripts/mdf.py acquire {args.slug} --dry-run")
        return 0

    path = candidates_path(root, args.slug)
    if not path.is_file():
        print(f"❌ 没有候选清单 {path.as_posix()}：先派 acquisition-scout 凭记忆列候选"
              f"（python scripts/mdf.py brief {args.slug} plan）", file=sys.stderr)
        return 1
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"❌ 候选清单不是合法 JSON：{exc}", file=sys.stderr)
        return 1
    errors = check_candidates(data)
    if errors:
        print("❌ 候选清单不合格：\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    person, candidates = parse_candidates(data)
    if args.check:
        print(f"✅ 候选清单合格：{len(candidates)} 条（{person.name}）")
        return 0
    policy = acquire.load_policy(root=root)
    if args.dry_run:
        print("\n".join([f"将核对 {len(candidates)} 条候选（不联网、不写盘）：", *_dry_run_lines(policy, candidates)]))
        return 0
    session = acquire.Session(policy, fetcher, max_requests=args.max_requests,
                              **({"sleep": sleep} if sleep is not None else {}))
    catalog = Path(args.gutenberg_catalog) if args.gutenberg_catalog else None
    try:
        draft = run_plan(root, args.slug, session=session, gutenberg_catalog=catalog)
    except acquire.Refused as exc:
        print(f"⛔ {exc.message}", file=sys.stderr)
        return 2
    print(json.dumps(draft, ensure_ascii=False, indent=2) if args.json else render_markdown(draft), end="")
    return 0


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    sys.exit(main())
