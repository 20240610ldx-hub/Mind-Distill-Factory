"""Validate user_sources.json output."""
import json
import sys

path = r"D:\mind distill factory\sources\richard-feynman\processed\user_sources.json"
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Person: {data['person']}")
print(f"Slug: {data['person_slug']}")
print(f"Source type: {data['source_type']}")
print(f"Total extracts: {len(data['extracts'])}")

# Count by content type
types = {}
for e in data['extracts']:
    t = e['content_type']
    types[t] = types.get(t, 0) + 1
print(f"By content_type: {types}")

# Count by confidence
confs = {}
for e in data['extracts']:
    c = e['confidence']
    confs[c] = confs.get(c, 0) + 1
print(f"By confidence: {confs}")
high_pct = confs.get('high', 0) / len(data['extracts']) * 100
print(f"High confidence: {high_pct:.0f}%")

# Count unique sources
sources = set()
for e in data['extracts']:
    sources.add(e['source_title'])
print(f"\nUnique sources: {len(sources)}")
for s in sorted(sources):
    count = sum(1 for e in data['extracts'] if e['source_title'] == s)
    print(f"  {s}: {count}")

# Count unique topic tags
tags = set()
for e in data['extracts']:
    for t in e['topic_tags']:
        tags.add(t)
print(f"\nUnique topic tags: {len(tags)}")

# Check required fields
required = ['text', 'source_title', 'source_detail', 'language', 'content_type', 'topic_tags', 'confidence']
missing = []
for i, e in enumerate(data['extracts']):
    for r in required:
        if r not in e or not e[r]:
            missing.append(f"Extract {i}: missing {r}")
if missing:
    print(f"\nMissing fields:")
    for m in missing:
        print(f"  {m}")
else:
    print(f"\nAll required fields present in all extracts.")

# Check target: 25-40 extracts, >=60% high confidence
n = len(data['extracts'])
if 25 <= n <= 40:
    print(f"\nExtract count {n} is within target range [25-40].")
else:
    print(f"\nWARNING: Extract count {n} is outside target range [25-40].")

if high_pct >= 60:
    print(f"High confidence {high_pct:.0f}% meets >=60% target.")
else:
    print(f"WARNING: High confidence {high_pct:.0f}% below 60% target.")
