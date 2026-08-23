# 开源发布清单（Release Checklist）

> 草案 2026-06-11。决策依据：复盘附录 D + 作者裁决（sources 与测试存档两类全排除）。
> 发布动作执行人：作者本人。

## 一、随仓库发布（include）

- `CLAUDE.md` · `commands/` · `agents/` · `templates/` · `config/`
- `scripts/`（含校验器/状态机/分片流水线；`_retro_*` 取证脚本可留可删）
- `gallery/`（成品 SKILL.md + index.json）
- `evaluation/` 框架部分：`runtime/test_sets/` · `runtime/judge_rubric.json` ·
  `runtime/.env.example` · `fixtures/` · `scripts/` · `mind-skill-evaluator/` ·
  `regression-protocol.md`
- `docs/retrospective-mao-distillation.public.zh.md` · `docs/retrospective-outline.zh.md` ·
  本清单

## 二、排除（exclude，已写入 .gitignore）

| 排除项 | 原因 |
|--------|------|
| `sources/` 全部 | 版权 PDF 与衍生全文提取物 |
| `output/` 全部 | 含未脱敏测试对话存档（测试者真实生活倾诉）、`_retro_*` 取证产物（含私人会话摘录与凭证痕迹） |
| `evaluation/reports/` | 评测对话含敏感探针原文与测试者输入 |
| `evaluation/runtime/.env` | 明文凭证（保留 `.env.example`） |
| `docs/retrospective-mao-distillation.zh.md` | 私人完整版（只发布 .public 版） |
| `*.lnk` 等杂物 | 如 `output/mao-zedong/新加卷 (E).lnk`，发布前直接删除 |

## 三、发布前动作（按序执行）

1. **轮换全部外部 API 凭证**（评测台 .env 及历史日志中出现过的 key）——P0
2. 对待发布文件集运行**凭证扫描**（gitleaks 或等价工具），零命中方可继续
3. **引文长度复核**：抽查 gallery 内各 SKILL 的长引文，确认在合理使用边界内
4. 选择 LICENSE；README 写明**用途边界声明**（在"入厂准入标准"成文前的最低要求）
5. 复核 `gallery/index.json` 与实际目录一致（跑 `validate_output.py gallery`）

## 四、⚠️ 未决决策点

**视频承诺与排除清单冲突**：发布文案承诺开源内容包含"测试对话记录"，
但本清单将原始测试存档全部排除（测试者隐私 + 敏感探针）。三选一：

- [ ] A. 修改发布文案，移除"测试对话记录"承诺
- [ ] B. 发布**脱敏精选样张**（如公开版复盘 9.4 节选 + 1-2 段技术类对话），文案改为"测试对话节选"
- [ ] C. 取得测试者书面同意后发布经其过目的完整记录

（建议 B：成本最低且最诚实——样张已存在于公开版复盘内。）
