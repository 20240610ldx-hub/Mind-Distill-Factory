#!/usr/bin/env python3
"""合规文献采集：按 config/acquisition_policy.json 从白名单来源取文本，写入
sources/{slug}/raw/acquired/{connector}/。

每个目标依次过这些闸门，任何一道不过就拒绝并记日志（fail-closed）：

    连接器启用 → https + 主机白名单 → User-Agent 联系方式 → 请求预算
    → robots.txt（RFC 9309，最长匹配）→ TDMRep 站点级保留（W3C）→ 主机间隔 / 429·5xx 退避
    → TDMRep 响应头 / HTML meta 保留
    → 权利状态 → 内容类型与大小 → 去重 → 原子写入

所有结果（saved / duplicate / skipped / refused / failed）都追加到
sources/{slug}/processed/acquisition_log.jsonl；source_registry 据此回填
rights_status 与来源 URL。网络访问经可注入的 fetcher 完成，测试全部离线。

    python scripts/mdf.py acquire <slug> --wikisource zh:論語
    python scripts/mdf.py acquire <slug> --ia <identifier>[/<file>]
    python scripts/mdf.py acquire <slug> --local D:/books/x.pdf --rights user_owned_copy
    python scripts/mdf.py acquire <slug> --plan sources/<slug>/acquisition_plan.json --dry-run
"""

import argparse
import email.utils
import functools
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, unquote, urlsplit

CODE_ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.0"
AGENT_TOKEN = "MindDistillFactory-acquire"
POLICY_SCHEMA = "acquisition-policy-v1"
LOG_SCHEMA = "acquisition-log-v1"
# 与 local_source_pipeline 能抽取的格式一致（EPUB 暂不支持，宁可拒收也不让它在 index 时被静默跳过）。
LOCAL_SUFFIXES = {".txt", ".md", ".markdown", ".pdf"}
NETWORK_CONNECTORS = {"wikisource", "internet_archive", "gutenberg", "url"}
DECLARED_RIGHTS_CONNECTORS = {"url", "local"}


class AcquireError(Exception):
    event = "failed"

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class Refused(AcquireError):
    """合规闸门拒绝：需要人处理（改策略、补授权），重试无用。"""

    event = "refused"


class Failed(AcquireError):
    """技术失败：网络、404、过大……修正目标或稍后重试。"""

    event = "failed"


# ── 策略 ──────────────────────────────────────────────────────────────


def load_policy(path: Path | None = None) -> dict[str, Any]:
    path = path or CODE_ROOT / "config" / "acquisition_policy.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema") != POLICY_SCHEMA:
        raise ValueError(f"{path}: schema 应为 {POLICY_SCHEMA}")
    return policy


def resolve_contact(policy: dict[str, Any], env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return str(policy.get("contact") or env.get("MDF_CONTACT") or "").strip()


def build_user_agent(contact: str) -> str:
    # Wikimedia 要求格式 `<client>/<version> (<contact>) <library>/<version>`。
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    return f"{AGENT_TOKEN}/{VERSION} ({contact}) python-urllib/{py}"


def setting(policy: dict[str, Any], connector: str, key: str) -> Any:
    conn = policy.get("connectors", {}).get(connector, {})
    return conn[key] if key in conn else policy.get("defaults", {}).get(key)


def rights_decision(policy: dict[str, Any], rights: str) -> str:
    """allow / review / refuse。public_domain_us 只在美国法域直接放行。"""
    if rights == "public_domain_us" and str(policy.get("jurisdiction") or "").upper() == "US":
        return "allow"
    if rights in policy.get("allowed_rights", []):
        return "allow"
    if rights in policy.get("review_rights", []):
        return "review"
    return "refuse"


def host_allowed(host: str | None, patterns: list[str]) -> bool:
    host = (host or "").lower().rstrip(".")
    if not host:
        return False
    for pattern in patterns:
        pattern = pattern.lower()
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]):
                return True
        elif host == pattern:
            return True
    return False


# ── robots.txt（RFC 9309）────────────────────────────────────────────

_PATTERN_SAFE = "/?=&*$%:;@+,!~'()#[]-._"


@functools.lru_cache(maxsize=1024)
def _pattern_regex(pattern: str) -> "re.Pattern[str]":
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile(regex + ("$" if anchored else ""))


class RobotsRules:
    """按 RFC 9309 解析 robots.txt：匹配本工具的组，否则用 `*` 组；最长匹配胜出，等长时 allow 胜出。"""

    def __init__(self, groups: list[tuple[list[str], list[tuple[bool, str]]]], default: bool | None = None):
        self.groups = groups
        self.default = default  # True=全部允许，False=全部禁止，None=按规则

    @classmethod
    def allow_everything(cls) -> "RobotsRules":
        return cls([], default=True)

    @classmethod
    def disallow_everything(cls) -> "RobotsRules":
        return cls([], default=False)

    @classmethod
    def parse(cls, text: str) -> "RobotsRules":
        groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] | None = None
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if rules is not None:  # 规则之后再出现 user-agent：新的一组
                    groups.append((agents, rules))
                    agents, rules = [], None
                agents.append(value.lower())
            elif key in ("allow", "disallow") and agents:
                rules = rules if rules is not None else []
                rules.append((key == "allow", value))
        if agents:
            groups.append((agents, rules or []))
        return cls(groups)

    def rules_for(self, token: str) -> list[tuple[bool, str]]:
        token = token.lower()
        matched = [r for agents, r in self.groups if any(a not in ("", "*") and a in token for a in agents)]
        if not matched:
            matched = [r for agents, r in self.groups if "*" in agents]
        return [rule for group in matched for rule in group]

    def allowed(self, path: str, token: str = AGENT_TOKEN) -> bool:
        if self.default is not None:
            return self.default
        if path == "/robots.txt":
            return True
        best_len, best_allow = -1, True
        for allow, pattern in self.rules_for(token):
            if not pattern:  # 空 Disallow 表示不限制
                continue
            encoded = quote(pattern, safe=_PATTERN_SAFE)
            if _pattern_regex(encoded).match(path):
                if len(encoded) > best_len or (len(encoded) == best_len and allow):
                    best_len, best_allow = len(encoded), allow
        return best_allow


# ── TDMRep（W3C TDM Reservation Protocol）────────────────────────────
#
# EU DSM 指令第 4 条允许权利人用机器可读方式保留文本与数据挖掘（TDM）权利。TDMRep 有三处
# 表达：站点 /.well-known/tdmrep.json、响应头 tdm-reservation、HTML <meta name="tdm-reservation">；
# 后者依次覆盖前者，缺省的属性不清除已有值。值只有 "1"（保留）与 "0"（不保留），其他值是
# 协议错误，按「未设置」处理且不覆盖已有值。tdmrep.json 不存在或无效＝站点未实现该协议。
# 依据：https://www.w3.org/community/reports/tdmrep/CG-FINAL-tdmrep-20240510/

TDM_WELL_KNOWN = "/.well-known/tdmrep.json"


def _tdm_value(value: Any) -> int | None:
    text = str(value).strip() if value is not None and not isinstance(value, bool) else ""
    return int(text) if text in ("0", "1") else None


class TdmRules:
    """tdmrep.json 的规则表：location 按路径整段匹配（`*` 任意串，`$` 结尾），按顺序首个匹配生效。"""

    def __init__(self, rules: list[tuple[str, int | None, str | None]]):
        self.rules = rules

    @classmethod
    def parse(cls, text: str) -> "TdmRules":
        try:
            data = json.loads(text)
        except ValueError:
            return cls([])
        rules = []
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict) and isinstance(item.get("location"), str):
                policy = item.get("tdm-policy")
                rules.append((item["location"], _tdm_value(item.get("tdm-reservation")),
                              policy if isinstance(policy, str) and policy else None))
        return cls(rules)

    def lookup(self, path: str) -> tuple[int | None, str | None]:
        decoded = unquote(path)
        for location, reservation, policy in self.rules:
            pattern = unquote(location)
            body = pattern[:-1] if pattern.endswith("$") else pattern
            regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
            if re.fullmatch(regex, decoded):
                return reservation, policy
        return None, None


class _TdmMeta(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            attr = {k.lower(): (v or "") for k, v in attrs}
            name = attr.get("name", "").strip().lower()
            if name in ("tdm-reservation", "tdm-policy") and name not in self.values:
                self.values[name] = attr.get("content", "")


def tdm_from_html(body: bytes) -> dict[str, str]:
    parser = _TdmMeta()
    try:
        parser.feed(body[:256_000].decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 - 坏 HTML 不该让采集崩溃，按「没有声明」处理
        return {}
    return parser.values


def merge_tdm(state: dict[str, Any], reservation: Any, policy: Any, source: str) -> dict[str, Any]:
    """后出现的声明覆盖先前的；无效或缺省的值不覆盖。"""
    value = _tdm_value(reservation)
    if value is None:
        return state
    return {"reservation": value, "policy": (str(policy).strip() or None) if policy else None, "source": source}


# ── 网络 ──────────────────────────────────────────────────────────────


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str


class FetchError(Exception):
    pass


class UrllibFetcher:
    """标准库实现；HTTP 错误码作为 Response 返回，只有连不上才抛 FetchError。"""

    def fetch(self, url: str, headers: dict[str, str], max_bytes: int, timeout: float) -> Response:
        request = urllib.request.Request(url, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - https only, checked by caller
        except urllib.error.HTTPError as e:
            body = e.read(max_bytes + 1) if e.fp else b""
            return Response(e.code, {k.lower(): v for k, v in e.headers.items()}, body, e.geturl() or url)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise FetchError(f"{type(e).__name__}: {getattr(e, 'reason', e)}") from e
        with response:
            body = response.read(max_bytes + 1)
            headers = {k.lower(): v for k, v in response.headers.items()}
            return Response(response.status, headers, body, response.geturl())


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Session:
    """一次采集运行：共享请求预算、各主机的上次请求时间与 robots 缓存。"""

    def __init__(
        self,
        policy: dict[str, Any],
        fetcher: Any = None,
        *,
        contact: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], str] = _utc_now,
        max_requests: int | None = None,
    ):
        self.policy = policy
        self.fetcher = fetcher or UrllibFetcher()
        self.contact = resolve_contact(policy) if contact is None else contact.strip()
        self.clock, self.sleep, self.now = clock, sleep, now
        defaults = policy.get("defaults", {})
        self.budget = int(max_requests if max_requests is not None else defaults.get("max_requests_per_run", 60))
        self.requests = 0
        self._last: dict[str, float] = {}
        self._robots: dict[tuple[str, str], RobotsRules] = {}
        self._tdm_sites: dict[tuple[str, str], TdmRules] = {}
        self.tdm_seen: dict[str, dict[str, Any]] = {}  # 请求 URL → 该资源最终的 TDMRep 状态（写进采集日志）

    @property
    def user_agent(self) -> str:
        return build_user_agent(self.contact)

    def hosts_for(self, connector: str) -> list[str]:
        hosts = list(setting(self.policy, connector, "hosts") or [])
        if connector == "gutenberg":
            mirror = self.policy.get("connectors", {}).get("gutenberg", {}).get("mirror") or ""
            if mirror:
                hosts.append(urlsplit(mirror).hostname or "")
        return hosts

    def require_contact(self) -> None:
        if not self.contact:
            raise Refused("CONTACT_MISSING", "User-Agent 需要联系方式：在 config/acquisition_policy.json 填 contact，或设环境变量 MDF_CONTACT")

    def _request(self, url: str, connector: str) -> Response:
        if self.requests >= self.budget:
            raise Refused("BUDGET_EXHAUSTED", f"本次运行已发出 {self.requests} 个请求（上限 {self.budget}，可用 --max-requests 调整）")
        host = urlsplit(url).hostname or ""
        interval = float(setting(self.policy, connector, "min_interval_s") or 0)
        last = self._last.get(host)
        if last is not None:
            wait = last + interval - self.clock()
            if wait > 0:
                self.sleep(wait)
        self.requests += 1
        try:
            return self.fetcher.fetch(
                url,
                {"User-Agent": self.user_agent},
                int(setting(self.policy, connector, "max_bytes") or 30_000_000),
                float(setting(self.policy, connector, "timeout_s") or 30),
            )
        except FetchError as e:
            raise Failed("NETWORK_ERROR", str(e)) from e
        finally:
            self._last[host] = self.clock()

    def robots(self, url: str, connector: str) -> RobotsRules:
        parts = urlsplit(url)
        key = (parts.scheme, (parts.hostname or "").lower())
        if key not in self._robots:
            try:
                response = self._request(f"{parts.scheme}://{parts.netloc}/robots.txt", connector)
            except Failed:
                rules = RobotsRules.disallow_everything()  # RFC 9309 §2.3.1.4：不可达视为全部禁止
            else:
                if response.status == 200:
                    rules = RobotsRules.parse(response.body[:512_000].decode("utf-8", errors="replace"))
                elif 400 <= response.status < 500 and response.status != 429:
                    rules = RobotsRules.allow_everything()  # §2.3.1.3：不存在视为不限制
                else:
                    rules = RobotsRules.disallow_everything()
            self._robots[key] = rules
        return self._robots[key]

    def tdm_site(self, url: str, connector: str) -> TdmRules:
        """站点级 TDMRep 规则（每主机取一次并缓存）。取不到或格式无效＝站点未实现协议，规则表为空。"""
        parts = urlsplit(url)
        key = (parts.scheme, (parts.hostname or "").lower())
        if key not in self._tdm_sites:
            try:
                response = self._request(f"{parts.scheme}://{parts.netloc}{TDM_WELL_KNOWN}", connector)
            except Failed:
                rules = TdmRules([])
            else:
                final = urlsplit(response.url or "")
                same_site = final.scheme == "https" and host_allowed(final.hostname, self.hosts_for(connector))
                ok = response.status == 200 and same_site
                rules = TdmRules.parse(response.body[:512_000].decode("utf-8", errors="replace")) if ok else TdmRules([])
            self._tdm_sites[key] = rules
        return self._tdm_sites[key]

    def respects_tdm(self) -> bool:
        # 只有符合 DSM 第 3 条的科研机构/文化遗产机构才可以不受保留约束；默认一律尊重。
        return bool(self.policy.get("defaults", {}).get("respect_tdm_reservation", True))

    def _refuse_if_reserved(self, state: dict[str, Any], url: str) -> None:
        if state.get("reservation") == 1 and self.respects_tdm():
            where = {"well-known": TDM_WELL_KNOWN, "header": "响应头", "meta": "HTML meta"}.get(state.get("source"), "")
            policy = f"；授权条件见 {state['policy']}" if state.get("policy") else ""
            raise Refused(
                "TDM_RESERVED",
                f"权利人通过 TDMRep（{where}）保留了文本与数据挖掘权利：{url}{policy}。"
                "取得授权后用 --local 导入并声明 --rights permission_granted",
            )

    def _retry_delay(self, response: Response, attempt: int) -> float:
        cap = float(self.policy["defaults"].get("max_retry_after_s", 120))
        value = response.headers.get("retry-after", "").strip()
        delay: float | None = None
        if value.isdigit():
            delay = float(value)
        elif value:
            try:
                delay = max(0.0, email.utils.parsedate_to_datetime(value).timestamp() - time.time())
            except (TypeError, ValueError):
                delay = None
        if delay is None:
            delay = float(self.policy["defaults"].get("backoff_base_s", 2.0)) * (2 ** attempt)
        if delay > cap:
            raise Failed("RATE_LIMITED", f"服务器要求等待 {delay:.0f}s，超过上限 {cap:.0f}s；稍后再跑")
        return delay

    def get(self, url: str, connector: str) -> Response:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise Refused("INSECURE_URL", f"只允许 https：{url}")
        hosts = self.hosts_for(connector)
        if not host_allowed(parts.hostname, hosts):
            raise Refused("HOST_NOT_ALLOWED", f"{parts.hostname} 不在 {connector} 连接器的白名单里（config/acquisition_policy.json）")
        self.require_contact()
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if not self.robots(url, connector).allowed(path):
            raise Refused("ROBOTS_DISALLOWED", f"{parts.hostname} 的 robots.txt 不允许抓取 {path}")
        reservation, policy = self.tdm_site(url, connector).lookup(parts.path or "/")
        tdm = merge_tdm({"reservation": None, "policy": None, "source": None}, reservation, policy, "well-known")
        self.tdm_seen[url] = tdm
        self._refuse_if_reserved(tdm, url)  # 站点级保留：正文一个字节都不取
        retries = int(self.policy["defaults"].get("max_retries", 3))
        max_bytes = int(setting(self.policy, connector, "max_bytes") or 30_000_000)
        for attempt in range(retries + 1):
            response = self._request(url, connector)
            final = urlsplit(response.url or url)
            if final.scheme != "https" or not host_allowed(final.hostname, hosts):
                raise Refused("REDIRECT_NOT_ALLOWED", f"重定向到白名单外：{response.url}")
            if response.status == 429 or response.status >= 500:
                if attempt == retries:
                    raise Failed(f"HTTP_{response.status}", f"重试 {retries} 次后仍失败：{url}")
                self.sleep(self._retry_delay(response, attempt))
                continue
            if response.status == 404:
                raise Failed("NOT_FOUND", url)
            if response.status != 200:
                raise Failed(f"HTTP_{response.status}", url)
            if len(response.body) > max_bytes:
                raise Failed("TOO_LARGE", f"超过 {max_bytes} 字节：{url}")
            tdm = merge_tdm(tdm, response.headers.get("tdm-reservation"), response.headers.get("tdm-policy"), "header")
            if "html" in response.headers.get("content-type", "").lower():
                meta = tdm_from_html(response.body)
                tdm = merge_tdm(tdm, meta.get("tdm-reservation"), meta.get("tdm-policy"), "meta")
            self.tdm_seen[url] = tdm
            self._refuse_if_reserved(tdm, url)
            return response
        raise Failed("UNREACHABLE", url)  # pragma: no cover - 循环必然 return 或 raise


# ── HTML → 文本 ───────────────────────────────────────────────────────

BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "dl", "dd", "dt", "tr", "table", "blockquote", "pre",
    "section", "article", "hr", "center", "poem", "h1", "h2", "h3", "h4", "h5", "h6",
}
SKIP_TAGS = {"script", "style", "noscript", "head", "template", "svg", "math", "nav", "footer", "button"}
VOID_TAGS = {"br", "img", "hr", "meta", "link", "input", "wbr", "source", "area", "base", "col", "embed", "param", "track"}
DROP_CLASSES = {
    "mw-editsection", "reference", "references", "noprint", "navbox", "ws-noexport", "mw-cite-backlink",
    "catlinks", "printfooter", "licenseContainer", "mw-jump-link", "toc", "mw-heading-anchor",
    "ws-header",  # 维基文库页眉：上一篇/下一篇导航与姊妹计划
}
# class 里含这些片段的元素一律丢弃：靠样式表隐藏的悬浮注释（如维基文库的 variant-tooltip
# 校勘注）若拼进正文，会把「學已矣」变成「學已一無「已」字矣」，破坏逐字溯源。
DROP_CLASS_FRAGMENTS = ("tooltip",)


class _TextExtractor(HTMLParser):
    def __init__(self, root_class: str | None, drop_classes: set[str]):
        super().__init__(convert_charrefs=True)
        self.root_class = root_class
        self.drop = drop_classes
        self.stack: list[tuple[str, bool, bool]] = []
        self.root_open = 0
        self.skip_open = 0
        self.found_root = False
        self.parts: list[str] = []

    @property
    def capturing(self) -> bool:
        return (self.root_class is None or self.root_open > 0) and self.skip_open == 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag in VOID_TAGS:
            if self.capturing and tag in ("br", "hr"):
                self.parts.append("\n")
            return
        is_root = bool(self.root_class) and self.root_class in classes and self.root_open == 0
        hidden = "display:none" in (attributes.get("style") or "").replace(" ", "").lower()
        is_skip = (
            tag in SKIP_TAGS or bool(classes & self.drop) or hidden
            or any(fragment in c for c in classes for fragment in DROP_CLASS_FRAGMENTS)
        )
        self.found_root |= is_root
        self.stack.append((tag, is_root, is_skip))
        self.root_open += is_root
        self.skip_open += is_skip
        if self.capturing and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                break
        else:
            return  # 没有对应的开标签：忽略
        was_capturing = self.capturing
        while len(self.stack) > index:
            _, is_root, is_skip = self.stack.pop()
            self.root_open -= is_root
            self.skip_open -= is_skip
        if was_capturing and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.capturing:
            self.parts.append(data)


def html_to_text(markup: str, root_class: str | None = None, drop_classes: set[str] | None = None) -> str:
    """抽正文：可只取 class 含 root_class 的元素（找不到则退回整页），丢弃脚本、导航和指定 class。"""
    drop = DROP_CLASSES if drop_classes is None else drop_classes
    parser = _TextExtractor(root_class, drop)
    parser.feed(markup)
    parser.close()
    if root_class and not parser.found_root:
        return html_to_text(markup, None, drop)
    text = "".join(parser.parts).replace("\r", "")
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def decode_text(body: bytes, content_type: str) -> tuple[str, str, int]:
    """返回（文本, 实际编码, U+FFFD 个数）。依次试 UTF-8、声明的 charset、GB18030。"""
    declared = re.search(r"charset=([\w.-]+)", content_type or "", re.IGNORECASE)
    candidates = ["utf-8-sig"] + ([declared.group(1)] if declared else []) + ["gb18030"]
    for encoding in candidates:
        try:
            return body.decode(encoding), encoding, 0
        except (UnicodeDecodeError, LookupError):
            continue
    text = body.decode("utf-8", errors="replace")
    return text, "utf-8(replace)", text.count("\ufffd")


# ── 目标与连接器 ──────────────────────────────────────────────────────

_LANG_RE = re.compile(r"[a-z]{2,3}(?:-[a-z]{2,8})?")
_IA_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


def normalize_target(raw: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化单个目标；不合格抛 Refused(BAD_TARGET)。"""
    if not isinstance(raw, dict):
        raise Refused("BAD_TARGET", f"目标必须是对象：{raw!r}")
    connector = raw.get("connector")

    def bad(message: str) -> Refused:
        return Refused("BAD_TARGET", f"{connector}: {message}")

    if connector == "wikisource":
        lang, title = str(raw.get("lang") or "").lower(), str(raw.get("title") or "").strip()
        if not _LANG_RE.fullmatch(lang) or not title:
            raise bad("需要 lang（如 zh）与 title")
        return {"connector": connector, "lang": lang, "title": title}
    if connector == "internet_archive":
        identifier, name = str(raw.get("identifier") or ""), str(raw.get("file") or "")
        if not _IA_ID_RE.fullmatch(identifier):
            raise bad(f"identifier 不合法：{identifier!r}")
        if name and (name.startswith("/") or ".." in Path(name).parts):
            raise bad(f"file 不合法：{name!r}")
        return {"connector": connector, "identifier": identifier, **({"file": name} if name else {})}
    if connector == "gutenberg":
        try:
            ebook = int(raw.get("ebook"))
        except (TypeError, ValueError):
            raise bad("ebook 必须是正整数") from None
        if ebook <= 0:
            raise bad("ebook 必须是正整数")
        return {"connector": connector, "ebook": ebook}
    if connector == "url":
        url = str(raw.get("url") or "").strip()
        if urlsplit(url).scheme != "https" or not urlsplit(url).hostname:
            raise bad(f"需要 https URL：{url!r}")
        return {"connector": connector, "url": url, "rights": str(raw.get("rights") or ""),
                "rights_evidence": str(raw.get("rights_evidence") or "")}
    if connector == "local":
        path = str(raw.get("path") or "").strip()
        if not path:
            raise bad("需要 path")
        return {"connector": connector, "path": path, "rights": str(raw.get("rights") or ""),
                "rights_evidence": str(raw.get("rights_evidence") or "")}
    raise Refused("BAD_TARGET", f"未知连接器：{connector!r}")


def target_key(target: dict[str, Any]) -> str:
    """同一来源的稳定标识；改权利声明不算换目标。"""
    stable = {k: v for k, v in target.items() if k not in ("rights", "rights_evidence")}
    if stable.get("connector") == "local":
        stable["path"] = str(Path(stable["path"]).expanduser().resolve()).lower()
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True)
    return "tgt_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


@dataclass
class Fetched:
    body: bytes
    content_type: str
    url: str
    rights_status: str
    rights_evidence: str
    title: str
    name_hint: str = ""
    html_root: str | None = None
    http_status: int | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def _first(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value or "")


def ia_rights(metadata: dict[str, Any]) -> tuple[str, str]:
    """从 Internet Archive 元数据推断权利状态；NC/ND 等限制性许可一律 unknown（人工判断）。"""
    license_url = _first(metadata.get("licenseurl")).strip()
    lowered = license_url.lower()
    if "publicdomain/zero" in lowered:
        return "cc0", license_url
    if "publicdomain" in lowered:
        return "public_domain", license_url
    match = re.search(r"creativecommons\.org/licenses/([a-z-]+)/", lowered)
    if match:
        return {"by": "cc-by", "by-sa": "cc-by-sa"}.get(match.group(1), "unknown"), license_url
    status = _first(metadata.get("possible-copyright-status"))
    if status.strip().upper() == "NOT_IN_COPYRIGHT":
        return "public_domain_us", f"possible-copyright-status: {status}"
    rights = _first(metadata.get("rights"))
    return "unknown", (f"rights: {rights[:200]}" if rights else "元数据未声明许可")


def _ia_pick_file(files: list[dict[str, Any]], wanted: str) -> dict[str, Any]:
    public = [f for f in files if isinstance(f, dict) and str(f.get("private", "")).lower() != "true"]
    if wanted:
        for f in public:
            if f.get("name") == wanted:
                return f
        raise Failed("NOT_FOUND", f"条目里没有可公开下载的文件 {wanted}")
    for predicate in (
        lambda n: n.endswith("_djvu.txt"),
        lambda n: n.endswith(".txt"),
        lambda n: n.endswith(".pdf"),
    ):
        for f in public:
            if predicate(str(f.get("name", "")).lower()):
                return f
    raise Failed("NO_TEXT_FILE", "条目里没有可公开下载的 txt/pdf 文件")


def fetch_wikisource(session: Session, target: dict[str, Any]) -> Fetched:
    conn = session.policy["connectors"]["wikisource"]
    title = target["title"].replace(" ", "_")
    # /wiki/ 页面是 robots.txt 允许的路径（/w/ 与 /api/ 对爬虫是 Disallow）。
    url = f"https://{target['lang']}.wikisource.org/wiki/{quote(title, safe='/:()')}"
    response = session.get(url, "wikisource")
    return Fetched(
        body=response.body, content_type=response.headers.get("content-type", "text/html"), url=url,
        rights_status=conn.get("rights_status", "cc-by-sa"), rights_evidence=conn.get("rights_evidence", ""),
        title=target["title"], name_hint=f"{target['lang']}-{target['title']}", html_root="mw-parser-output",
        http_status=response.status,
    )


def fetch_internet_archive(session: Session, target: dict[str, Any]) -> Fetched:
    identifier = target["identifier"]
    meta_response = session.get(f"https://archive.org/metadata/{identifier}", "internet_archive")
    try:
        meta = json.loads(meta_response.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise Failed("BAD_METADATA", f"元数据不是 JSON：{e}") from e
    if not meta or not isinstance(meta, dict) or "metadata" not in meta:
        raise Failed("NOT_FOUND", f"Internet Archive 没有条目 {identifier}")
    metadata = meta.get("metadata") or {}
    if str(_first(metadata.get("access-restricted-item"))).lower() == "true":
        raise Refused("ACCESS_RESTRICTED", f"{identifier} 是受限借阅条目，不得批量下载")
    rights, evidence = ia_rights(metadata)
    chosen = _ia_pick_file(meta.get("files") or [], target.get("file", ""))
    name = str(chosen["name"])
    url = f"https://archive.org/download/{identifier}/{quote(name)}"
    response = session.get(url, "internet_archive")
    content_type = response.headers.get("content-type", "")
    if name.lower().endswith(".txt") and "text/" not in content_type:
        content_type = "text/plain"
    return Fetched(
        body=response.body, content_type=content_type, url=url, rights_status=rights, rights_evidence=evidence,
        title=_first(metadata.get("title")) or identifier, name_hint=identifier, http_status=response.status,
        extras={"ia_file": name, "ia_creator": _first(metadata.get("creator"))[:200]},
    )


def gutenberg_paths(ebook: int) -> list[str]:
    """PG 镜像目录布局：#12345 → 1/2/3/4/12345/；个位数编号在 0/{n}/。"""
    digits = str(ebook)
    directory = "/".join(digits[:-1]) + f"/{digits}/" if len(digits) > 1 else f"0/{digits}/"
    return [f"{directory}{digits}-0.txt", f"{directory}{digits}-8.txt", f"{directory}{digits}.txt"]


def fetch_gutenberg(session: Session, target: dict[str, Any]) -> Fetched:
    conn = session.policy["connectors"]["gutenberg"]
    mirror = (conn.get("mirror") or "").rstrip("/")
    if not mirror:
        raise Refused(
            "CONNECTOR_NOT_CONFIGURED",
            "Project Gutenberg 网站禁止自动化访问；先建私有镜像并在 acquisition_policy.json 填 connectors.gutenberg.mirror",
        )
    last_error: Failed | None = None
    for path in gutenberg_paths(target["ebook"]):
        url = f"{mirror}/{path}"
        try:
            response = session.get(url, "gutenberg")
        except Failed as e:
            if e.code != "NOT_FOUND":
                raise
            last_error = e
            continue
        return Fetched(
            body=response.body, content_type="text/plain", url=url,
            rights_status=conn.get("rights_status", "public_domain_us"), rights_evidence=conn.get("rights_evidence", ""),
            title=f"Project Gutenberg #{target['ebook']}", name_hint=f"pg{target['ebook']}", http_status=response.status,
        )
    raise last_error or Failed("NOT_FOUND", f"镜像里找不到 #{target['ebook']}")


def fetch_url(session: Session, target: dict[str, Any]) -> Fetched:
    response = session.get(target["url"], "url")
    stem = Path(urlsplit(target["url"]).path).stem
    return Fetched(
        body=response.body, content_type=response.headers.get("content-type", ""), url=target["url"],
        rights_status=target["rights"], rights_evidence=target.get("rights_evidence", ""),
        title=stem or target["url"], name_hint=stem, http_status=response.status,
    )


def read_local(session: Session, target: dict[str, Any]) -> Fetched:
    path = Path(target["path"]).expanduser()
    if not path.is_file():
        raise Failed("NOT_FOUND", f"本地文件不存在：{path}")
    suffix = path.suffix.lower()
    if suffix not in LOCAL_SUFFIXES:
        raise Refused("UNSUPPORTED_TYPE", f"不支持的格式 {suffix}（只收 {'/'.join(sorted(LOCAL_SUFFIXES))}）")
    types = {".pdf": "application/pdf", ".md": "text/markdown",
             ".markdown": "text/markdown", ".txt": "text/plain"}
    return Fetched(
        body=path.read_bytes(), content_type=types[suffix], url="", rights_status=target["rights"],
        rights_evidence=target.get("rights_evidence", ""), title=path.name, name_hint=path.stem,
        extras={"local_source": str(path.resolve()), "keep_bytes": True},
    )


CONNECTORS: dict[str, Callable[[Session, dict[str, Any]], Fetched]] = {
    "wikisource": fetch_wikisource,
    "internet_archive": fetch_internet_archive,
    "gutenberg": fetch_gutenberg,
    "url": fetch_url,
    "local": read_local,
}


# ── 落盘与日志 ────────────────────────────────────────────────────────


def materialize(fetched: Fetched) -> tuple[bytes, str, dict[str, Any]]:
    """把取回的内容变成要写进 raw 的字节：HTML 转文本、文本统一 UTF-8 + LF，PDF/EPUB 原样。"""
    content_type = fetched.content_type.split(";", 1)[0].strip().lower()
    body = fetched.body
    if content_type == "application/pdf" or body.startswith(b"%PDF-"):
        if not body.startswith(b"%PDF-"):
            raise Failed("BAD_CONTENT", "声明为 PDF 但内容不是 PDF")
        return body, ".pdf", {}
    if fetched.extras.get("keep_bytes"):
        # 本地文本原样保存：编码问题交给清洗闸门如实报告，不在导入时悄悄改写。
        suffix = ".md" if content_type == "text/markdown" else ".txt"
        return body, suffix, {}
    if content_type in ("text/html", "application/xhtml+xml"):
        text, encoding, bad = decode_text(body, fetched.content_type)
        text = html_to_text(text, fetched.html_root)
        extras = {"converted_from": content_type, "source_encoding": encoding, "decode_replacements": bad}
    elif content_type.startswith("text/"):
        text, encoding, bad = decode_text(body, fetched.content_type)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        extras = {"source_encoding": encoding, "decode_replacements": bad}
    else:
        raise Failed("UNSUPPORTED_TYPE", f"不支持的内容类型 {content_type or '（未声明）'}")
    if not text.strip():
        raise Failed("EMPTY_CONTENT", "转换后没有文本")
    return text.encode("utf-8"), ".txt", extras


def _ascii_hint(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_log(log_path: Path) -> list[dict[str, Any]]:
    records = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue  # 损坏行不影响其余记录；index/status 会报告
            if isinstance(record, dict):
                records.append(record)
    return records


def append_log(log_path: Path, record: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def offline_checks(policy: dict[str, Any], session: Session, target: dict[str, Any]) -> None:
    """不联网能判定的闸门：连接器启用、联系方式、白名单、声明的权利、本地文件存在。"""
    connector = target["connector"]
    if not policy.get("connectors", {}).get(connector, {}).get("enabled", False):
        raise Refused("CONNECTOR_DISABLED", f"连接器 {connector} 在 acquisition_policy.json 里未启用")
    if connector in DECLARED_RIGHTS_CONNECTORS:
        rights = target.get("rights") or ""
        if not rights:
            raise Refused("RIGHTS_UNDECLARED", f"{connector} 目标必须用 --rights 声明权利状态")
        if rights_decision(policy, rights) == "refuse":
            raise Refused("RIGHTS_NOT_ALLOWED", f"权利状态 {rights} 不在 allowed_rights / review_rights 里")
    if connector in NETWORK_CONNECTORS:
        session.require_contact()
    if connector == "url" and not host_allowed(urlsplit(target["url"]).hostname, session.hosts_for("url")):
        raise Refused("HOST_NOT_ALLOWED", f"{urlsplit(target['url']).hostname} 不在 url 连接器白名单里")
    if connector == "gutenberg" and not policy["connectors"]["gutenberg"].get("mirror"):
        raise Refused("CONNECTOR_NOT_CONFIGURED", "Project Gutenberg 需先配置私有镜像（connectors.gutenberg.mirror）")
    if connector == "local" and not Path(target["path"]).expanduser().is_file():
        raise Failed("NOT_FOUND", f"本地文件不存在：{target['path']}")


def run_acquisition(
    slug: str,
    targets: list[dict[str, Any]],
    *,
    root: Path,
    session: Session,
    allow_unverified: bool = False,
    refresh: bool = False,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    policy = session.policy
    raw_dir = root / "sources" / slug / "raw"
    log_path = root / "sources" / slug / "processed" / "acquisition_log.jsonl"
    history = read_log(log_path)
    saved_by_key = {r["target_key"]: r for r in history if r.get("event") == "saved" and r.get("target_key")}
    saved_by_sha = {r["sha256"]: r for r in history if r.get("event") == "saved" and r.get("sha256")}
    results: list[dict[str, Any]] = []
    for raw_target in targets:
        record: dict[str, Any] = {
            "schema": LOG_SCHEMA, "retrieved_at": session.now(),
            "connector": raw_target.get("connector") if isinstance(raw_target, dict) else None,
        }
        try:
            target = normalize_target(raw_target)
            key = target_key(target)
            record.update(target_key=key, target=target)
            previous = saved_by_key.get(key)
            previous_path = raw_dir / previous["path"] if previous else None
            if (
                previous and not refresh and previous_path is not None and previous_path.is_file()
                and _sha256(previous_path.read_bytes()) == previous["sha256"]
            ):
                record.update(event="skipped", reason="ALREADY_ACQUIRED", path=previous["path"], sha256=previous["sha256"])
            else:
                offline_checks(policy, session, target)
                if dry_run:
                    record.update(event="planned")
                else:
                    record.update(_acquire_one(session, target, key, raw_dir, saved_by_sha, allow_unverified))
                    if record["event"] == "saved":
                        saved_by_key[key] = record
                        saved_by_sha[record["sha256"]] = record
        except AcquireError as e:
            record.update(event=e.event, reason=e.code, message=e.message)
        if not dry_run:
            append_log(log_path, record)
        results.append(record)
    return results


def _acquire_one(
    session: Session, target: dict[str, Any], key: str, raw_dir: Path,
    saved_by_sha: dict[str, dict[str, Any]], allow_unverified: bool,
) -> dict[str, Any]:
    connector = target["connector"]
    fetched = CONNECTORS[connector](session, target)
    decision = rights_decision(session.policy, fetched.rights_status)
    if decision == "refuse":
        raise Refused("RIGHTS_NOT_ALLOWED", f"权利状态 {fetched.rights_status}（{fetched.rights_evidence}）不允许采集")
    if decision == "review" and not allow_unverified:
        raise Refused(
            "RIGHTS_UNVERIFIED",
            f"权利状态 {fetched.rights_status}（{fetched.rights_evidence}）需人工核实；核实后加 --allow-unverified-rights",
        )
    data, suffix, extras = materialize(fetched)
    digest = _sha256(data)
    common = {
        "url": fetched.url, "http_status": fetched.http_status, "content_type": fetched.content_type,
        "title": fetched.title, "rights_status": fetched.rights_status, "rights_evidence": fetched.rights_evidence,
        "rights_review_required": decision == "review", "sha256": digest, "bytes": len(data),
        **({"user_agent": session.user_agent, "tdm": session.tdm_seen.get(fetched.url)}
           if connector in NETWORK_CONNECTORS else {}),
        **{k: v for k, v in fetched.extras.items() if k != "keep_bytes"}, **extras,
    }
    duplicate = saved_by_sha.get(digest)
    if duplicate and duplicate.get("target_key") != key:
        return {"event": "duplicate", "duplicate_of": duplicate["target_key"], "path": duplicate["path"], **common}
    hint = _ascii_hint(fetched.name_hint)
    name = f"{hint}-{key[4:12]}{suffix}" if hint else f"{key}{suffix}"
    relative = f"acquired/{connector}/{name}"
    _write_atomic(raw_dir / relative, data)
    return {"event": "saved", "path": relative, **common}


# ── CLI ───────────────────────────────────────────────────────────────

EVENT_LABELS = {
    "saved": "✅ 已保存", "duplicate": "➖ 重复", "skipped": "➖ 已有", "planned": "📝 待采集",
    "refused": "⛔ 拒绝", "failed": "❌ 失败",
}


def describe_target(target: dict[str, Any] | None, record: dict[str, Any]) -> str:
    if not target:
        return str(record.get("connector") or "?")
    connector = target["connector"]
    label = {
        "wikisource": lambda t: f"维基文库 {t['lang']}:{t['title']}",
        "internet_archive": lambda t: f"Internet Archive {t['identifier']}" + (f"/{t['file']}" if t.get("file") else ""),
        "gutenberg": lambda t: f"Gutenberg #{t['ebook']}",
        "url": lambda t: t["url"],
        "local": lambda t: f"本地 {Path(t['path']).name}",
    }[connector](target)
    return label.replace("|", "\\|")


def render_results(slug: str, results: list[dict[str, Any]]) -> str:
    lines = [f"## 文献采集：{slug}", "", "| # | 来源 | 结果 | 说明 |", "|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        if r["event"] in ("saved", "duplicate", "skipped"):
            note = f"`raw/{r.get('path', '')}`"
            if r.get("rights_status"):
                note += f"，权利 {r['rights_status']}" + ("（待人工核实）" if r.get("rights_review_required") else "")
        elif r["event"] == "planned":
            note = "离线闸门通过"
        else:
            note = f"{r.get('reason')}：{r.get('message', '')}"
        lines.append(f"| {i} | {describe_target(r.get('target'), r)} | {EVENT_LABELS.get(r['event'], r['event'])} | {note.replace('|', '/')} |")
    counts: dict[str, int] = {}
    for r in results:
        counts[r["event"]] = counts.get(r["event"], 0) + 1
    lines += ["", "合计：" + "，".join(f"{EVENT_LABELS.get(k, k)} {v}" for k, v in counts.items())]
    return "\n".join(lines) + "\n"


def _load_sibling(name: str) -> Any:
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_acquire_{name}", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def targets_from_args(args: argparse.Namespace, root: Path) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    plan = Path(args.plan) if args.plan else root / "sources" / args.slug / "acquisition_plan.json"
    explicit = args.wikisource or args.ia or args.gutenberg or args.url or args.local
    if args.plan or (plan.exists() and not explicit):
        data = json.loads(plan.read_text(encoding="utf-8"))
        targets.extend(data.get("targets", []) if isinstance(data, dict) else data)
    for item in args.wikisource or []:
        lang, _, title = item.partition(":")
        targets.append({"connector": "wikisource", "lang": lang, "title": title})
    for item in args.ia or []:
        identifier, _, name = item.partition("/")
        targets.append({"connector": "internet_archive", "identifier": identifier, **({"file": name} if name else {})})
    for ebook in args.gutenberg or []:
        targets.append({"connector": "gutenberg", "ebook": ebook})
    for url in args.url or []:
        targets.append({"connector": "url", "url": url, "rights": args.rights or "", "rights_evidence": args.rights_evidence or ""})
    for path in args.local or []:
        targets.append({"connector": "local", "path": path, "rights": args.rights or "", "rights_evidence": args.rights_evidence or ""})
    return targets


def main(argv: list[str] | None = None) -> int:
    slug_arg = _load_sibling("slug_rules").slug_arg
    parser = argparse.ArgumentParser(description="合规文献采集（白名单 + robots.txt + 速率限制 + 权利闸门）")
    parser.add_argument("slug", type=slug_arg)
    parser.add_argument("--plan", help="采集计划 JSON（默认 sources/{slug}/acquisition_plan.json）")
    parser.add_argument("--wikisource", action="append", metavar="LANG:TITLE", help="维基文库页面，如 zh:論語")
    parser.add_argument("--ia", action="append", metavar="ID[/FILE]", help="Internet Archive 条目")
    parser.add_argument("--gutenberg", action="append", type=int, metavar="N", help="Project Gutenberg 编号（需配置镜像）")
    parser.add_argument("--url", action="append", help="白名单主机上的 https URL（需 --rights）")
    parser.add_argument("--local", action="append", metavar="PATH", help="导入本地文件（需 --rights）")
    parser.add_argument("--rights", help="--url/--local 的权利状态，如 public_domain、user_owned_copy")
    parser.add_argument("--rights-evidence", help="权利依据（出版年、作者卒年、授权链接……）")
    parser.add_argument("--allow-unverified-rights", action="store_true", help="放行 review_rights 里的状态（记为待人工核实）")
    parser.add_argument("--refresh", action="store_true", help="已采集过的目标也重新获取")
    parser.add_argument("--max-requests", type=int, help="覆盖本次运行的请求上限")
    parser.add_argument("--dry-run", action="store_true", help="只跑离线闸门，不联网、不写盘")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", help="数据根目录（默认 MDF_DATA_ROOT，再默认仓库根）")
    args = parser.parse_args(argv)

    root = Path(args.root or os.environ.get("MDF_DATA_ROOT") or CODE_ROOT).resolve()
    targets = targets_from_args(args, root)
    if not targets:
        parser.error("没有采集目标：用 --wikisource/--ia/--gutenberg/--url/--local，或写 sources/{slug}/acquisition_plan.json")
    session = Session(load_policy(), max_requests=args.max_requests)
    results = run_acquisition(
        args.slug, targets, root=root, session=session,
        allow_unverified=args.allow_unverified_rights, refresh=args.refresh, dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(render_results(args.slug, results), end="")
    return 1 if any(r["event"] in ("refused", "failed") for r in results) else 0


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    sys.exit(main())
