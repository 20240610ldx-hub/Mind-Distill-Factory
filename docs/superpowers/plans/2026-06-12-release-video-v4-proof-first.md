# 发布视频 V4 证明优先 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用可复核的 v2/v5 同题受控实验重做横竖版发布视频，并保留全部原始证据。

**Architecture:** 先用现有 `evaluation/runtime/run_dialogue_eval.py` 生成六份独立回答，再建立盲评包和证据清单。视频只消费冻结后的实验产物，不在 React 组件中硬编码未经验证的胜负结论。

**Tech Stack:** Python 3、DeepSeek-compatible API、JSON/Markdown、Remotion 4、React 19、Vitest、FFmpeg。

---

### Task 1: 冻结实验输入

**Files:**
- Create: `release-video-v3/experiments/mao-v2-v5-bottleneck/test-set.json`
- Create: `release-video-v3/experiments/mao-v2-v5-bottleneck/PROTOCOL.md`

- [ ] 写入唯一测试题、模型参数、版本输入路径和首次结果冻结规则。
- [ ] 用 `python -m json.tool` 验证测试集 JSON。
- [ ] 计算 v2/v5 Skill 的 SHA-256 并写入协议运行记录。

### Task 2: 生成六份独立回答

**Files:**
- Create: `release-video-v3/experiments/mao-v2-v5-bottleneck/raw/v2/run-01/`
- Create: `release-video-v3/experiments/mao-v2-v5-bottleneck/raw/v2/run-02/`
- Create: `release-video-v3/experiments/mao-v2-v5-bottleneck/raw/v2/run-03/`
- Create: `release-video-v3/experiments/mao-v2-v5-bottleneck/raw/v5/run-01/`
- Create: `release-video-v3/experiments/mao-v2-v5-bottleneck/raw/v5/run-02/`
- Create: `release-video-v3/experiments/mao-v2-v5-bottleneck/raw/v5/run-03/`

- [ ] 每次单独调用 `evaluation/runtime/run_dialogue_eval.py`，使用同一模型与推理强度。
- [ ] 禁用 judge 与 Soul Ten Questions，确保只生成原始回答。
- [ ] 验证六份 `runtime-dialogue-test.md` 均包含且只包含一组 Q/A。
- [ ] 计算所有文件哈希，冻结首次结果。

### Task 3: 建立盲评包

**Files:**
- Create: `release-video-v3/scripts/build_blind_review.py`
- Create: `release-video-v3/scripts/test_blind_review.py`
- Create: `release-video-v3/experiments/mao-v2-v5-bottleneck/blind/`

- [ ] 先写失败测试：六份回答必须生成六个匿名 ID，公开包不得出现 `v2`、`v5` 或原路径。
- [ ] 实现最小匿名化脚本和私有映射文件。
- [ ] 生成两份相同内容的评审表，四项只允许 `PASS`/`FAIL`。
- [ ] 运行测试并人工搜索版本泄漏。

### Task 4: 汇总真人盲评

**Files:**
- Create: `release-video-v3/experiments/mao-v2-v5-bottleneck/reviewers/reviewer-a.md`
- Create: `release-video-v3/experiments/mao-v2-v5-bottleneck/reviewers/reviewer-b.md`
- Create: `release-video-v3/experiments/mao-v2-v5-bottleneck/results.md`

- [ ] 收集两名非作者评审的独立判断。
- [ ] 保留分歧，不由作者静默覆盖。
- [ ] 解盲后按版本汇总四项通过率与中位表现。
- [ ] 如果 v5 未明显胜出，结果文件明确写“实验未证明改进”。

### Task 5: 重写旁白和时间轴

**Files:**
- Modify: `release-video-v3/content/narration.json`
- Modify: `release-video-v3/src/data/video-data.ts`
- Modify: `release-video-v3/src/data/types.ts`
- Test: `release-video-v3/src/data/narration.test.ts`
- Test: `release-video-v3/src/data/timeline.test.ts`

- [ ] 先写失败测试，要求主叙事顺序为难题、v2、v5、盲评、证据、反馈、CTA。
- [ ] 删除规模数字主线和七阶段逐项介绍。
- [ ] 旁白只陈述实验实际结果，不提前宣布 v5 胜出。
- [ ] 重新生成字幕 JSON 和 SRT。

### Task 6: 实现顺序揭示镜头

**Files:**
- Modify: `release-video-v3/src/scenes/shot-registry.tsx`
- Modify: `release-video-v3/src/data/video-data.ts`
- Test: `release-video-v3/src/scenes/shot-registry.test.ts`

- [ ] 先写失败测试，要求新镜头类型覆盖 v2 原文、诊断标记、v5 原文、四项验收和文件证据。
- [ ] 使用 `useCurrentFrame()` 驱动全部动画。
- [ ] 横版展示较完整原句，竖版只展示最能证明差异的原句。
- [ ] 抽象反馈回路只用于证据段之后的转场与高潮。

### Task 7: 修正配音门禁

**Files:**
- Modify: `release-video-v3/scripts/assert_final_audio.py`
- Modify: `release-video-v3/scripts/run_qa.py`
- Test: `release-video-v3/scripts/test_pipeline.py`

- [ ] 先写失败测试：Edge TTS 不得被判定为 ElevenLabs 最终音轨。
- [ ] 最终门禁必须要求 `voiceProvider == elevenlabs`。
- [ ] Edge TTS 保留为 preview 占位模式。
- [ ] 文案锁定后生成 12–15 秒 ElevenLabs A/B 样音，再生成完整音轨。

### Task 8: 验证与小样

**Files:**
- Update: `release-video-v3/QA-REPORT.md`
- Create: `release-video-v3/qa/v4-proof-first/`

- [ ] 运行 `npm test`、`npm run lint` 和 Python 单元测试。
- [ ] 只渲染关键 still 和低清短段，不渲染整片。
- [ ] 检查横竖版文本可读性、字幕安全区和证据哈希。
- [ ] 用户批准关键段后再渲染完整横竖版。

