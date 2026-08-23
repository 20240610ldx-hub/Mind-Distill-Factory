# -*- coding: utf-8 -*-
"""Aggregate token usage across all project session transcripts (incl. subagents).

Sums message.usage fields per session, attributes subagent files to parent session,
groups sessions by distillation target, writes a markdown report.
Note: figures are sums of per-message usage events (cache_read counted per event),
i.e. billed-volume proxy, not unique-content size.
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"C:\Users\xx\.claude\projects\D--mind-distill-factory")
OUT = Path(r"D:\mind distill factory\output\_retro_token_usage.md")

LABELS = {
    "4f3635e9-8bc5-435b-8093-7cffc6cd4a72": "mao-zedong（蒸馏+复测）",
    "eaee3f0d-0bcd-40eb-8d05-5d89c6f980f2": "工厂研发（立项/机制升级/复盘）",
    "5de7f04e-99f0-47c0-8e49-f69732826e7f": "sun-tzu",
    "3cad4dbd-e7b6-45cf-b040-9b0424471f09": "wang-yangming",
    "ec8bc25b-bb6a-41a5-8a5e-9e1186e9e74b": "zeng-guofan",
    "9bea0bec-1e93-4655-92f7-959e5ba99c13": "feynman",
    "86f9a573-e88d-4825-8347-b908e9133e04": "chiang-kai-shek",
    "86f1e2ec-9720-4538-b324-a79a67f9731c": "chiang-kai-shek",
    "4be75b20-f7fe-41fc-bbd9-015738388266": "lu-xun",
    "cb744792-9a25-405a-8bbb-1cb0cad4a2cf": "zhang-xueliang",
    "3e7d79b4-95f9-4291-b650-eaa846ac0619": "zhang-xueliang",
    "fc287f34-c5a1-42c5-bd4c-88cfb7825b88": "zhang-xueliang",
    "a1f6aff1-7686-4de3-bd88-ac14edf238d8": "seneca",
    "95d5b238-2c42-4791-add7-6037baa8906b": "su-shi（+内阁规划）",
    "56144b0f-c46b-4217-8ae5-cd36f85adfce": "lincoln",
    "2d7e6ab8-0907-4306-a4fa-401407fec23a": "lee-kuan-yew",
    "308d2352-ff3c-43b4-98aa-e2f1892c2c88": "bismarck",
    "71d8c885-86ad-41ca-9922-97ffbd71095a": "bismarck",
    "c92c9474-51f4-4925-b62f-e5d05bc40f92": "von-neumann",
    "4f53b819-2e92-477e-9e37-dcf696beb517": "von-neumann",
    "45730098-aabe-41fd-8460-550a04d6544e": "leonardo-da-vinci",
    "1be88461-d7d4-4c99-8cf0-3bba2c500ed6": "alexander-hamilton",
    "b710e5dc-0e7f-4654-9b0a-5fa244f3ed83": "kazuo-inamori",
    "cc34ea31-92f3-4cbe-a490-b57e359ecedb": "marcus-aurelius",
    "0bff2ae1-d774-456d-9f3f-3d436c844f81": "zhang-juzheng",
    "248867d3-2732-4d56-b40b-2e5e81675c1a": "description 修复",
}

FIELDS = ("input_tokens", "cache_read_input_tokens",
          "cache_creation_input_tokens", "output_tokens")


def iter_files():
    for p in ROOT.glob("*.jsonl"):
        yield p.stem, p
    for p in ROOT.glob("*/subagents/*.jsonl"):
        yield p.parts[-3], p  # parent session folder name


def main():
    per_session = defaultdict(lambda: defaultdict(int))
    per_model_out = defaultdict(int)
    msg_count = defaultdict(int)

    for session, path in iter_files():
        try:
            with path.open(encoding="utf-8") as fh:
                for raw in fh:
                    try:
                        rec = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("type") != "assistant":
                        continue
                    msg = rec.get("message") or {}
                    usage = msg.get("usage") or {}
                    if not usage:
                        continue
                    msg_count[session] += 1
                    for f in FIELDS:
                        per_session[session][f] += int(usage.get(f) or 0)
                    model = msg.get("model") or "?"
                    per_model_out[model] += int(usage.get("output_tokens") or 0)
        except OSError:
            continue

    # group by label
    grouped = defaultdict(lambda: defaultdict(int))
    g_msgs = defaultdict(int)
    for session, fields in per_session.items():
        label = LABELS.get(session, f"misc/test（{session[:8]}）")
        if label.startswith("misc/test"):
            label = "misc/test（小会话合计）"
        for f, v in fields.items():
            grouped[label][f] += v
        g_msgs[label] += msg_count[session]

    def row(label, d, msgs):
        inp, cr, cc, out = (d[f] for f in FIELDS)
        denom = inp + cr + cc
        hit = (cr / denom * 100) if denom else 0.0
        return (label, msgs, inp, cr, cc, out, hit, inp + cr + cc + out)

    rows = sorted((row(l, d, g_msgs[l]) for l, d in grouped.items()),
                  key=lambda r: -r[7])

    tot = defaultdict(int)
    for l, d in grouped.items():
        for f, v in d.items():
            tot[f] += v
    tot_row = row("**全项目合计**", tot, sum(g_msgs.values()))

    lines = ["# Token usage aggregation (all sessions incl. subagents)\n",
             "| 工作单元 | 消息数 | fresh input | cache read | cache write | output | 缓存命中% | 总计 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows + [tot_row]:
        lines.append("| {} | {} | {:,} | {:,} | {:,} | {:,} | {:.1f}% | {:,} |".format(*r))

    lines.append("\n## output tokens by model\n")
    lines.append("| model | output tokens |")
    lines.append("|---|---:|")
    for m, v in sorted(per_model_out.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {m} | {v:,} |")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"OK wrote {OUT}; sessions={len(per_session)}, labels={len(grouped)}")


if __name__ == "__main__":
    main()
