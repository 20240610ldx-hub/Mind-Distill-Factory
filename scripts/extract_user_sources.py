#!/usr/bin/env python3
"""
从 _extracted_texts.intermediate 提取关键段落，生成 user_sources.json
"""
import json
import re
from pathlib import Path

# 关键文章列表（优先提取）
KEY_ARTICLES = [
    "实践论", "矛盾论", "论持久战", "中国革命战争的战略问题",
    "反对本本主义", "关于领导方法的若干问题", "中国社会各阶级的分析",
    "战争和战略问题", "论十大关系", "关于正确处理人民内部矛盾的问题",
    "星星之火，可以燎原", "湖南农民运动考察报告"
]

# 关键主题标签映射
TOPIC_PATTERNS = {
    "contradiction": ["矛盾", "对立统一", "主要矛盾", "矛盾的主要方面"],
    "practice": ["实践", "认识", "理论", "检验"],
    "investigation": ["调查", "研究", "没有调查", "实事求是"],
    "strategy": ["战略", "战术", "敌我", "形势"],
    "protracted-war": ["持久战", "阶段", "防御", "相持", "反攻"],
    "mass-line": ["群众", "群众路线", "从群众中来", "到群众中去"],
    "concentration": ["集中", "优势兵力", "各个击破"],
    "guerrilla": ["游击", "运动战", "敌进我退"],
}

def extract_topic_tags(text):
    """根据文本内容提取主题标签"""
    tags = []
    for tag, patterns in TOPIC_PATTERNS.items():
        if any(p in text for p in patterns):
            tags.append(tag)
    return tags[:5]  # 最多5个标签

def extract_key_passages(article_data):
    """从文章中提取关键段落"""
    extracts = []
    title = article_data.get("title", "")
    text = article_data.get("text", "")
    date = article_data.get("date", "")

    # 按段落分割
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]

    for para in paragraphs:
        # 跳过太短的段落
        if len(para) < 50:
            continue

        # 跳过纯数字、标题等
        if para.isdigit() or para.startswith("第") and para.endswith("章"):
            continue

        # 识别名言（短句、有标点、有力度）
        is_quote = len(para) < 200 and any(marker in para for marker in ["。", "！", "？"])

        # 识别原则表述
        is_principle = any(marker in para for marker in [
            "原则", "方法", "规律", "法则", "必须", "应当", "要", "不要"
        ])

        # 提取主题标签
        tags = extract_topic_tags(para)

        # 如果没有相关标签，跳过
        if not tags:
            continue

        # 确定内容类型
        if is_quote and len(para) < 100:
            content_type = "quote"
        elif is_principle:
            content_type = "principle"
        else:
            content_type = "passage"

        extract = {
            "text": para,
            "source_title": f"《{title}》",
            "source_detail": f"{date}，毛泽东选集" if date else "毛泽东选集",
            "source_url": "",
            "language": "zh",
            "content_type": content_type,
            "topic_tags": tags,
            "confidence": "high",
            "confidence_reason": "用户提供的第一手PDF资料，直接提取"
        }
        extracts.append(extract)

    return extracts

def main():
    # 读取中间文件
    intermediate_file = Path("sources/mao-zedong/processed/_extracted_texts.intermediate")

    print(f"Reading {intermediate_file}...")
    with open(intermediate_file, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    all_extracts = []

    # 优先处理关键文章
    for article in articles:
        title = article.get("title", "")
        if any(key in title for key in KEY_ARTICLES):
            print(f"Processing: {title}")
            extracts = extract_key_passages(article)
            all_extracts.extend(extracts)
            print(f"  Extracted {len(extracts)} passages")

    # 去重（基于文本内容）
    seen_texts = set()
    unique_extracts = []
    for ext in all_extracts:
        text_key = ext["text"][:100]  # 用前100字符作为去重key
        if text_key not in seen_texts:
            seen_texts.add(text_key)
            unique_extracts.append(ext)

    print(f"\nTotal unique extracts: {len(unique_extracts)}")

    # 构建输出JSON
    output = {
        "person": "毛泽东",
        "person_slug": "mao-zedong",
        "source_type": "user_provided",
        "collected_at": "2026-05-02",
        "extracts": unique_extracts,
        "collection_notes": f"从用户提供的4个PDF中提取，共{len(unique_extracts)}条高质量extracts，覆盖{len(KEY_ARTICLES)}篇关键文章"
    }

    # 写入输出文件
    output_file = Path("sources/mao-zedong/processed/user_sources.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Written to {output_file}")
    print(f"  Total extracts: {len(unique_extracts)}")
    print(f"  Quotes: {sum(1 for e in unique_extracts if e['content_type'] == 'quote')}")
    print(f"  Principles: {sum(1 for e in unique_extracts if e['content_type'] == 'principle')}")
    print(f"  Passages: {sum(1 for e in unique_extracts if e['content_type'] == 'passage')}")

if __name__ == "__main__":
    main()
