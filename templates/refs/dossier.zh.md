# {person_name_zh} 蒸馏档案

> 本文件给人读，不进 `~/.claude/skills/`。它记录管线内部的判断过程。

## 一、语料规模与来源

| 文件 | 大小 | 类型 | OCR 质量 | 已知讹字 |
|---|---|---|---|---|
| {filename} | {size} | 一手 / 二手 | {good/fair/poor} | {notes} |

分片：{n} shards / {tokens} tok；采样：{sampled}/{total}

## 二、原则推导链

| cluster_id | 候选原则 | 是否出厂 | 理由 |
|---|---|---|---|
| {cluster_id} | {candidate_name} | ✅ 原则 {n} | {why} |
| {cluster_id} | {candidate_name} | ❌ 舍弃 | {why_rejected} |

**被舍弃的候选原则及理由**是本节的重点——它记录了蒸馏做过的取舍。

## 三、盲区与缓解

{每条盲区 + 缓解建议}

## 四、质量审查结论

- distill_confidence：{n}/5
- 逐字引文校验：{pass}/{total}
- 案例覆盖：{clusters_covered}/{clusters_total}，反例 {counter_count} 个

## 五、已知风险

- {误归属陷阱：如小说/影视/后世注评混入}
- {OCR 讹字与底本分歧}
- {语料时代局限}
