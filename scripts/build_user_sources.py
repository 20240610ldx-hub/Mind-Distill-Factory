#!/usr/bin/env python3
"""Extract structured quotes and principles from Mao Zedong's works (PDF extracts)."""
import json
import sys
import re
import os

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(BASE_DIR, 'sources', 'mao-zedong', 'processed')

with open(os.path.join(PROCESSED_DIR, '_extracted_texts.json'), 'r', encoding='utf-8') as f:
    works = json.load(f)

work_texts = {w['title']: w for w in works}


def find_passage(text, keyword, before=80, after=300):
    idx = text.find(keyword)
    if idx == -1:
        return None
    start = max(0, idx - before)
    end = min(len(text), idx + len(keyword) + after)
    passage = text[start:end].strip()
    passage = re.sub(r'〔\d+〕', '', passage)
    passage = re.sub(r'\n+', ' ', passage).strip()
    return passage


SEARCHES = [
    # === 实践论 ===
    {'work': '实践论', 'kw': '通过实践而发现真理，又通过实践而证实真理和发展真理',
     'type': 'principle', 'tags': ['epistemology', 'practice', 'knowledge']},
    {'work': '实践论', 'kw': '实践、认识、再实践、再认识',
     'type': 'principle', 'tags': ['epistemology', 'methodology', 'iteration']},
    {'work': '实践论', 'kw': '认识的感性阶段，就是感觉和印象',
     'type': 'principle', 'tags': ['epistemology', 'perception', 'understanding']},
    {'work': '实践论', 'kw': '马克思主义者认为人类的生产活动是最基本的实践活动',
     'type': 'principle', 'tags': ['epistemology', 'practice', 'production']},
    # === 矛盾论 ===
    {'work': '矛盾论', 'kw': '事物的矛盾法则，即对立统一的法则',
     'type': 'principle', 'tags': ['dialectics', 'contradiction', 'unity-of-opposites']},
    {'work': '矛盾论', 'kw': '不同质的矛盾，只有用不同质的方法才能解决',
     'type': 'principle', 'tags': ['dialectics', 'specificity', 'method']},
    {'work': '矛盾论', 'kw': '主要的矛盾和主要的矛盾方面',
     'type': 'principle', 'tags': ['dialectics', 'prioritization', 'focus']},
    {'work': '矛盾论', 'kw': '单纯的外部原因只能引起事物的机械的运动',
     'type': 'principle', 'tags': ['dialectics', 'internal-cause', 'external-cause']},
    # === 论持久战 ===
    {'work': '论持久战', 'kw': '中国会亡吗？答复：不会亡',
     'type': 'principle', 'tags': ['strategy', 'confidence', 'analysis']},
    {'work': '论持久战', 'kw': '兵民是胜利之本',
     'type': 'quote', 'tags': ['mass-line', 'people', 'military-strategy']},
    {'work': '论持久战', 'kw': '武器是战争的重要的因素，但不是决定的因素',
     'type': 'principle', 'tags': ['strategy', 'human-factor', 'technology']},
    {'work': '论持久战', 'kw': '保存自己，消灭敌',
     'type': 'principle', 'tags': ['strategy', 'objective', 'survival']},
    {'work': '论持久战', 'kw': '战争的目的',
     'type': 'principle', 'tags': ['strategy', 'war-aim']},
    # === 反对本本主义 ===
    {'work': '反对本本主义', 'kw': '没有调查，没有发言权',
     'type': 'quote', 'tags': ['investigation', 'pragmatism', 'epistemology']},
    {'work': '反对本本主义', 'kw': '调查就是解决问题',
     'type': 'quote', 'tags': ['investigation', 'problem-solving']},
    {'work': '反对本本主义', 'kw': '中国革命斗争的胜利要靠\n中国同志了解中国情况',
     'type': 'principle', 'tags': ['pragmatism', 'local-knowledge', 'independence']},
    {'work': '反对本本主义', 'kw': '一切结论产生于调查情况的末尾',
     'type': 'principle', 'tags': ['investigation', 'evidence-first']},
    # === 关于领导方法的若干问题 ===
    {'work': '关于领导方法的若干问题', 'kw': '从群众中集中起来又到群众中坚持下去',
     'type': 'principle', 'tags': ['mass-line', 'leadership', 'methodology']},
    {'work': '关于领导方法的若干问题', 'kw': '一般和个别相结合',
     'type': 'principle', 'tags': ['methodology', 'general-particular', 'leadership']},
    {'work': '关于领导方法的若干问题', 'kw': '领导和群众相结合',
     'type': 'principle', 'tags': ['mass-line', 'leadership']},
    # === 中国革命战争的战略问题 ===
    {'work': '中国革命战争的战略问题', 'kw': '集中兵力',
     'type': 'principle', 'tags': ['military-strategy', 'concentration-of-force']},
    {'work': '中国革命战争的战略问题', 'kw': '诱敌深入',
     'type': 'principle', 'tags': ['military-strategy', 'strategic-retreat']},
    {'work': '中国革命战争的战略问题', 'kw': '战略退却',
     'type': 'principle', 'tags': ['military-strategy', 'strategic-defense']},
    # === 论十大关系 ===
    {'work': '论十大关系', 'kw': '重工业和轻工业、农业的关系',
     'type': 'principle', 'tags': ['governance', 'balance', 'dialectics']},
    {'work': '论十大关系', 'kw': '中央和地方的关系',
     'type': 'principle', 'tags': ['governance', 'centralization', 'decentralization']},
    {'work': '论十大关系', 'kw': '革命和反革命的关系',
     'type': 'principle', 'tags': ['governance', 'contradiction', 'tolerance']},
    # === 改造我们的学习 ===
    {'work': '改造我们的学习', 'kw': '实事求是',
     'type': 'quote', 'tags': ['pragmatism', 'truth-seeking', 'methodology']},
    {'work': '改造我们的学习', 'kw': '有的放矢',
     'type': 'principle', 'tags': ['pragmatism', 'targeted-action']},
    # === 星星之火，可以燎原 ===
    {'work': '星星之火，可以燎原', 'kw': '星星之火',
     'type': 'quote', 'tags': ['strategy', 'vision', 'small-beginnings']},
    # === 新民主主义论 ===
    {'work': '新民主主义论', 'kw': '无产阶级领导的人民民主专政',
     'type': 'principle', 'tags': ['governance', 'united-front', 'phased-revolution']},
    # === 抗日游击战争的战略问题 ===
    {'work': '抗日游击战争的战略问题', 'kw': '游击战争',
     'type': 'principle', 'tags': ['guerrilla', 'flexibility', 'offense-defense']},
    # === 中国社会各阶级的分析 ===
    {'work': '中国社会各阶级的分析', 'kw': '谁是我们的敌人？谁是我们的朋友？',
     'type': 'quote', 'tags': ['strategy', 'class-analysis', 'prioritization']},
    # === 关于正确处理人民内部矛盾的问题 ===
    {'work': '关于正确处理人民内部矛盾的问题', 'kw': '敌我之间的矛盾',
     'type': 'principle', 'tags': ['governance', 'contradiction-types', 'conflict-resolution']},
    {'work': '关于正确处理人民内部矛盾的问题', 'kw': '百花齐放',
     'type': 'principle', 'tags': ['governance', 'intellectual-freedom', 'diversity']},
]

extracts = []
not_found = []
for s in SEARCHES:
    title = s['work']
    w = work_texts.get(title)
    if not w:
        not_found.append(f"{title} (work not found)")
        continue
    passage = find_passage(w['text'], s['kw'])
    if not passage:
        not_found.append(f"{title} / {s['kw'][:25]}...")
        continue
    extracts.append({
        'text': passage,
        'source_title': f"《{title}》",
        'source_detail': f"{w['date']}，收录于《毛泽东选集》",
        'source_url': '',
        'language': 'zh',
        'content_type': s['type'],
        'topic_tags': s['tags'],
        'confidence': 'high',
        'confidence_reason': '用户提供的一手材料（《毛泽东选集》PDF），直接从原文提取'
    })

output = {
    'person': '毛泽东',
    'person_slug': 'mao-zedong',
    'source_type': 'user_provided',
    'collected_at': '2026-05-01',
    'extracts': extracts,
    'collection_notes': (
        f'从用户提供的《毛泽东选集》（1-7卷）PDF中提取。'
        f'共处理13篇核心著作，约33万字。'
        f'所有提取内容均为原文，confidence为high。'
        f'未找到的搜索: {len(not_found)}个'
    )
}

out_path = os.path.join(PROCESSED_DIR, 'user_sources.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"Extracted {len(extracts)} passages from {len(set(s['work'] for s in SEARCHES))} works")
print(f"Not found: {len(not_found)}")
for nf in not_found:
    print(f"  - {nf}")
print(f"Saved to {out_path}")
