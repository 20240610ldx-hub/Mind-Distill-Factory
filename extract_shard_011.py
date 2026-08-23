import json

with open(r'D:\mind distill factory\sources\alexander-hamilton\processed\local_shards\shard_011.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

extracts = {
    "shard_id": "shard_011",
    "extracts": []
}

# 1. Opening on reflection vs accident/force
extracts["extracts"].append({
    "text": "whether societies of men are really capable or not of establishing good government from reflection and choice, or whether they are forever destined to depend for their political constitutions on accident and force.",
    "source_title": "The Federalist No. 1",
    "source_detail": "shard_011_p001; opening philosophical statement",
    "language": "en",
    "content_type": "quote",
    "topic_tags": ["governance", "reflection", "choice"],
    "confidence": "high",
    "confidence_reason": "First-hand Hamilton text from user-provided Federalist Papers source (Stage 1A)."
})

# 2. Union's existential importance
extracts["extracts"].append({
    "text": "The subject speaks its own importance; comprehending in its consequences nothing less than the existence of the UNION, the safety and welfare of the parts of which it is composed, the fate of an empire in many respects the most interesting in the world.",
    "source_title": "The Federalist No. 1",
    "source_detail": "shard_011_p001; opening stakes of union",
    "language": "en",
    "content_type": "quote",
    "topic_tags": ["union", "safety", "empire"],
    "confidence": "high",
    "confidence_reason": "First-hand Hamilton text from user-provided Federalist Papers source (Stage 1A)."
})

# 3. Inefficiency of prior system
extracts["extracts"].append({
    "text": "After an unequivocal experience of the inefficiency of the subsisting federal government, you are called upon to deliberate on a new Constitution for the United States of America.",
    "source_title": "The Federalist No. 1",
    "source_detail": "shard_011_p001; opening sentence on necessity of reform",
    "language": "en",
    "content_type": "principle",
    "topic_tags": ["governance", "federal government", "reform"],
    "confidence": "high",
    "confidence_reason": "First-hand Hamilton text from user-provided Federalist Papers source (Stage 1A)."
})

# 4. Consequences of wrong choice
extracts["extracts"].append({
    "text": "a wrong election of the part we shall act may, in this view, deserve to be considered as the general misfortune of mankind.",
    "source_title": "The Federalist No. 1",
    "source_detail": "shard_011_p001; consequence of constitutional choice",
    "language": "en",
    "content_type": "quote",
    "topic_tags": ["governance", "consequences", "choice"],
    "confidence": "high",
    "confidence_reason": "First-hand Hamilton text from user-provided Federalist Papers source (Stage 1A)."
})

# 5. Obstacles from interested men in states
extracts["extracts"].append({
    "text": "Among the most formidable of the obstacles which the new Constitution will have to encounter may readily be distinguished the obvious interest of a certain class of men in every State to resist all changes which may hazard a diminution of the power, emolument, and consequence of the offices they hold under the State establishments.",
    "source_title": "The Federalist No. 1",
    "source_detail": "shard_011_p001; on factional resistance to union",
    "language": "en",
    "content_type": "principle",
    "topic_tags": ["faction", "interest", "resistance", "governance"],
    "confidence": "high",
    "confidence_reason": "First-hand Hamilton text from user-provided Federalist Papers source (Stage 1A)."
})

# 6. Expression sample - measured tone on faction
extracts["extracts"].append({
    "text": "It is not, however, my design to dwell upon observations of this nature. I am well aware that it would be disingenuous to resolve indiscriminately the opposition of any set of men (merely because their situations might subject them to suspicion) into interested or ambitious views. Candor will oblige us to admit that even such men may be actuated by upright intentions.",
    "source_title": "The Federalist No. 1",
    "source_detail": "shard_011_p001; rhetorical stance on opposition",
    "language": "en",
    "content_type": "expression_sample",
    "style_tags": ["measured", "fair-minded", "candid", "reasoned"],
    "confidence": "high",
    "confidence_reason": "First-hand Hamilton text from user-provided Federalist Papers source (Stage 1A)."
})

# 7. Dangers from disunion - domestic factions
extracts["extracts"].append({
    "text": "I shall now proceed to delineate dangers of a different and, perhaps, still more alarming kind - those which will in all probability flow from dissensions between the States themselves, and from domestic factions and convulsions.",
    "source_title": "The Federalist",
    "source_detail": "shard_011_p001; transition to disunion dangers",
    "language": "en",
    "content_type": "principle",
    "topic_tags": ["disunion", "faction", "danger"],
    "confidence": "high",
    "confidence_reason": "First-hand Hamilton text from user-provided Federalist Papers source (Stage 1A)."
})

# 8. Expression sample - analytical style
extracts["extracts"].append({
    "text": "So far is the general sense of mankind from corresponding with the tenets of those who endeavor to lull asleep our apprehensions of discord and hostility between the States, in the event of disunion, that it has from long observation of the progress of society become a sort of axiom in politics, that vicinity, or nearness of situation, constitutes nations natural enemies.",
    "source_title": "The Federalist",
    "source_detail": "shard_011_p001; principle from observation of history",
    "language": "en",
    "content_type": "expression_sample",
    "style_tags": ["empirical", "historical", "logical", "aphoristic"],
    "confidence": "high",
    "confidence_reason": "First-hand Hamilton text from user-provided Federalist Papers source (Stage 1A)."
})

# 9. Neighboring nations as natural enemies
extracts["extracts"].append({
    "text": "from long observation of the progress of society become a sort of axiom in politics, that vicinity, or nearness of situation, constitutes nations natural enemies.",
    "source_title": "The Federalist",
    "source_detail": "shard_011_p001; axiom of statecraft",
    "language": "en",
    "content_type": "principle",
    "topic_tags": ["statecraft", "foreign relations", "geography"],
    "confidence": "high",
    "confidence_reason": "First-hand Hamilton text from user-provided Federalist Papers source (Stage 1A)."
})

# 10. Commerce as source of advantage
extracts["extracts"].append({
    "text": "The extension of our own commerce in our own vessels cannot give pleasure to any nations who possess territories on or near this continent, because the cheapness and excellence of our productions, added to the circumstance of vicinity, and the enterprise and address of our merchants and navigators, will give us a greater share in the advantages which those territories afford.",
    "source_title": "The Federalist",
    "source_detail": "shard_011_p001; on commercial competition between states",
    "language": "en",
    "content_type": "principle",
    "topic_tags": ["commerce", "interest", "competition", "advantage"],
    "confidence": "high",
    "confidence_reason": "First-hand Hamilton text from user-provided Federalist Papers source (Stage 1A)."
})

# 11. Plan outline - necessity of energetic government
extracts["extracts"].append({
    "text": "The utility of the UNION to your political prosperity; The insufficiency of the present Confederation to preserve that Union; The necessity of a government at least equally energetic with the one proposed, to the attainment of this object.",
    "source_title": "The Federalist No. 1",
    "source_detail": "shard_011_p001; outline of the Federalist argument",
    "language": "en",
    "content_type": "principle",
    "topic_tags": ["union", "governance", "energy"],
    "confidence": "high",
    "confidence_reason": "First-hand Hamilton text from user-provided Federalist Papers source (Stage 1A)."
})

# 12. Candor on wise men being wrong
extracts["extracts"].append({
    "text": "So numerous indeed and so powerful are the causes which serve to give a false bias to the judgment, that we, upon many occasions, see wise and good men on the wrong as well as on the right side of questions of the first magnitude to society.",
    "source_title": "The Federalist No. 1",
    "source_detail": "shard_011_p001; on human fallibility",
    "language": "en",
    "content_type": "principle",
    "topic_tags": ["human nature", "judgment", "wisdom"],
    "confidence": "high",
    "confidence_reason": "First-hand Hamilton text from user-provided Federalist Papers source (Stage 1A)."
})

# Save
with open(r'D:\mind distill factory\sources\alexander-hamilton\processed\local_shards\shard_011_extracts.json', 'w', encoding='utf-8') as f:
    json.dump(extracts, f, ensure_ascii=False, indent=2)

print("Extracts written successfully")
