# -*- coding: utf-8 -*-
"""Generate the sanitized public retrospective from the private full version.

Repeatable: edit the private file, re-run this script, public file regenerates.
Transformations: targeted replacements (asserted) -> generic PRIVATE-block removal
-> whitespace cleanup -> sensitivity assertions.
"""
import re
import sys
from pathlib import Path

SRC = Path(r"D:\mind distill factory\docs\retrospective-mao-distillation.zh.md")
DST = Path(r"D:\mind distill factory\docs\retrospective-mao-distillation.public.zh.md")

text = SRC.read_text(encoding="utf-8")

# (old, new, expected_count)
REPLACEMENTS = [
    # Title
    ("# Mind Distill Factory 深度复盘\n## ——以毛泽东思想蒸馏为案例的全流程工程分析",
     "# Mind Distill Factory 深度复盘（公开版）\n## ——以毛泽东思想蒸馏为案例的全流程工程分析", 1),
    # Header version note
    ('> **版本说明（双版本机制）：** 本文档是私人完整版。文中所有被\n'
     '> `<!-- 🔒PRIVATE-START -->` … `<!-- 🔒PRIVATE-END -->` 包裹的段落属于"公开前需删减/脱敏"内容\n'
     '> （敏感测试案例细节、成本与凭证信息、政治敏感讨论）。删除全部 🔒 块即得公开版。\n'
     '> 附录 D 汇总了全部删减点清单。',
     '> **版本说明：** 本文档为公开版。另存有私人完整版，含测试者身份、内部运营与凭证管理等细节；\n'
     '> 两版本在方法论、时间线、数据与结论上完全一致，删减不影响任何工程论断的可验证性。', 1),
    # Header audit sentence
    ("会话证据的提取脚本与产物保留在 `scripts/_retro_*.py` 与 `output/_retro_*.md`，本复盘可被审计。",
     "会话证据的提取脚本保留在 `scripts/_retro_*.py`；原始会话取证产物涉及私人对话，不随仓库发布。", 1),
    # TOC appendix D
    ("- **附录 A** 理论文献引用 · **附录 B** 文件地图 · **附录 C** 术语表 · **附录 D** 公开版删减清单 · **附录 E** 成本定量",
     "- **附录 A** 理论文献引用 · **附录 B** 文件地图 · **附录 C** 术语表 · **附录 D** 版本说明 · **附录 E** 成本定量", 1),
    # 5.1 tester-identity block -> keep father (user decision 2026-06-11), drop sensitive probe topics
    ('<!-- 🔒PRIVATE-START 原因：测试者身份细节涉及家庭隐私 -->\n'
     '测试员构成：父亲（贡献了价值导向的关键修正，见 5.3）、同学/朋友（语气与人设向反馈）、\n'
     '作者本人（边界探针与极限测试，如在任领导人评价、台湾问题、四人帮评价等敏感探针）。\n'
     '公开版表述建议改为"由非作者的真实用户执行自然对话测试，作者负责边界探针类测试"。\n'
     '<!-- 🔒PRIVATE-END -->',
     "测试员构成：父亲（贡献了价值导向的关键修正，见 5.3）与同学/朋友（语气与人设向反馈），"
     "均为无脚本自然对话；作者本人负责边界探针与极限测试类提问。", 1),
    # 7.2 sensitive probe texts -> abstracted
    ('实测中的标本对照（同一次自然测试内）：被问"您对习近平同志有什么评价和建议"，\nSkill 回答',
     '实测中的标本对照（同一次自然测试内）：被问及对一位在其身后数十年才任职的政治人物的评价时，\nSkill 回答', 1),
    ('而同场被问台湾问题时却以第一人称纵论当代局势、无任何时间界限声明——边界漏触发。',
     '而同场被问及另一当代政治议题时，却以第一人称纵论当下局势、无任何时间界限声明——边界漏触发。', 1),
    # 11.3 P0 row
    ('| <!-- 🔒PRIVATE-START 原因：凭证安全细节 --> **P0** | **轮换 DeepSeek API key** | '
     '已在多个会话日志明文出现；开源前对待发布文件跑凭证扫描 <!-- 🔒PRIVATE-END --> |',
     '| **P0** | **凭证轮换与全仓扫描** | 开源发布前轮换全部外部 API 凭证，并对待发布文件运行凭证扫描 |', 1),
    # Father mentions retained in public version per user decision (2026-06-11)
    # 11.3 self-referential trim task -> done in public version
    ("| P2 | 本复盘公开版裁剪 | 删除全部 🔒 块（附录 D 清单）后另存发布 |",
     "| P2 | 本复盘公开版裁剪 | 已完成——即本文档 |", 1),
    # Appendix B file map
    ("└── docs/retrospective-mao-distillation.zh.md   本文",
     "└── docs/retrospective-mao-distillation.public.zh.md   本文（公开版）", 1),
    ("复盘取证副产物：scripts/_retro_*.py + output/_retro_session_map.md + output/_retro_mao_topology.md",
     "复盘取证脚本：scripts/_retro_*.py（原始会话取证产物不随仓库发布）", 1),
    # Appendix D full rewrite
    ('# 附录 D 公开版删减清单\n\n'
     '发布公开版前删除以下 🔒 块（按章序）：\n\n'
     '1. **5.1**：测试员身份细节（家庭隐私）→ 已附建议替代表述\n'
     '2. **7.2**：敏感探针的具体问题文本 → 已附抽象化替代表述\n'
     '3. **7.4**：衍生项目的敏感使用记录 + API key 泄露细节\n'
     '4. **11.3**：P0 行动项中的凭证细节（保留"轮换密钥"事项本身，删除上下文）\n\n'
     '另：公开版发布前对全仓跑凭证扫描；`output/_retro_session_map.md` 含原始会话摘录\n'
     '（其中含明文 key 与私人对话），**不随仓库发布**。',
     '# 附录 D 版本说明\n\n'
     '本文为公开版。私人完整版另含：测试者身份细节、内部凭证管理记录、个别敏感测试\n'
     '案例的原始文本及未发布衍生项目的工作记录。两版本在方法论、时间线、数据与结论上\n'
     '完全一致；删减不影响任何工程论断的可验证性。', 1),
]

failed = []
for old, new, expected in REPLACEMENTS:
    n = text.count(old)
    if n != expected:
        failed.append((old[:60], expected, n))
        continue
    text = text.replace(old, new)

if failed:
    for head, exp, got in failed:
        print(f"REPLACE FAIL (expected {exp}, found {got}): {head}...")
    sys.exit(1)

# Generic removal of remaining PRIVATE blocks (7.2 note, 7.4 block)
text, n_blocks = re.subn(r"<!-- 🔒PRIVATE-START.*?🔒PRIVATE-END -->\n?", "", text, flags=re.DOTALL)

# Whitespace cleanup
text = re.sub(r"\n{3,}", "\n\n", text)

# Sensitivity assertions
BANNED = ["PRIVATE", "🔒", "习近平", "台湾", "四人帮",
          "DeepSeek API key", "_retro_session_map", "sk-"]
leaks = [b for b in BANNED if b in text]
if leaks:
    print(f"SENSITIVITY ASSERTION FAILED, still present: {leaks}")
    sys.exit(1)

DST.write_text(text, encoding="utf-8")
print(f"OK: wrote {DST}")
print(f"  targeted replacements: {len(REPLACEMENTS)}; generic blocks removed: {n_blocks}")
print(f"  banned-term scan clean: {BANNED}")
