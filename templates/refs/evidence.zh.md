# {person_name_zh} · 证据卡

每条原则一张卡，承载**逐字**原文。此文件是 P1/P2 闸门的输入端——
卡内引文必须逐字出现在 `sources/{person-slug}/` 的语料中，否则 `package` 校验不通过。

若出厂文本与语料有分歧而作者判定出厂文本正确（如底本讹字），
追加 `- textual_note：` 说明分歧，闸门降级为 WARNING 并把分歧记录在案。

---

### 原则 1：{principle_name_zh}

> {逐字原文，一字不改}

- 出处：《{source_title_zh}》{source_detail}
- 语料位置：`sources/{person-slug}/raw/{filename}`
- confidence：high
- 现代转译：{核心层那句「决策规则」如何从这段原文推出}

### 原则 2：{principle_name_zh}

> {逐字原文}

- 出处：《{source_title_zh}》{source_detail}
- 语料位置：`sources/{person-slug}/raw/{filename}`
- confidence：medium
- 现代转译：{……}
- textual_note：{仅在与语料有分歧时填写；说明分歧与裁决依据}
