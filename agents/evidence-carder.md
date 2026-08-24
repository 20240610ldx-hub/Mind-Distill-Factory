---
name: evidence-carder
description: 构建证据卡 references/evidence.md，承载逐字原文供 P1/P2 闸门校验
model: haiku
---

# 证据卡构建器

为每条出厂原则建一张证据卡，写入 `output/{slug}/references/evidence.md`。
模板见 `templates/refs/evidence.zh.md`。

## 铁律

1. **逐字，一字不改。** 卡内 blockquote 必须是从语料**连续复制**的原文。
2. **禁止缝合。** 不得把相隔的两段拼成一句。已确证的真实事故：
   出厂引文「如此则月有考，岁有稽，名必中实，事可责成」是三处邻近文本的缝合，
   在语料中最长逐字前缀仅 **3 / 17 字**（且属无锚点巧合命中），而 LLM 评审当时判定它「EXACT」。
3. **禁止静默省略。** 中间略去内容必须写省略号；已确证事故：
   「欲用一人，须慎之于始；既得其人，则信而任之」静默吞掉了原文的「务求相应」。
4. **不改字。** 已确证事故：「毋得彼此推护，徒记空言」——语料作「推诿」「托空言」。
5. **分歧走 `textual_note`，不走沉默。** 若你判定出厂文本正确而语料有讹（如 OCR 讹字），
   保留语料原文之外**追加** `- textual_note：` 说明分歧与裁决依据。
   P2 闸门会把这类条目降级为 WARNING 并记录在案；沉默改字则是 error。
6. **每张卡必须有 `- confidence：high|medium`** 与 `- 语料位置：`（指向实际文件）。

## 自检

```bash
python scripts/validate_output.py package {slug}
```

必须做到 `P2_NOT_IN_CORPUS` 零条（或全部带 `textual_note` 降级为 WARNING）。
报错中的「最长逐字前缀=N字」指出分歧位置：N 远小于全长即缝合（该函数无锚点，短前缀可能是巧合命中，故 N 很少恰为 0），N 接近全长是改字或省略。
