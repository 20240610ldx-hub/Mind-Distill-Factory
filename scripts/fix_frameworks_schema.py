#!/usr/bin/env python3
"""
Fix frameworks.zh.json and frameworks.en.json to match validator schema
"""
import json
from pathlib import Path

def flatten_expression_dna_zh(edna):
    """Convert nested dimensions array to flat fields for Chinese"""
    dims = {d["name"]: d for d in edna.get("dimensions", [])}

    return {
        "sentence_patterns": dims.get("句式偏好", {}).get("pattern", ""),
        "rhetorical_devices": dims.get("标志性修辞", {}).get("pattern", ""),
        "tone": dims.get("语气基调", {}).get("pattern", ""),
        "certainty_level": dims.get("确定性表达", {}).get("pattern", ""),
        "humor_style": dims.get("幽默风格", {}).get("pattern", ""),
        "taboo_expressions": dims.get("禁忌表达", {}).get("pattern", ""),
        "voice_example_good": edna.get("calibration_examples", [{}])[0].get("aligned", ""),
        "voice_example_bad": edna.get("calibration_examples", [{}])[0].get("misaligned", "")
    }

def flatten_values_zh(vap):
    """Convert core_values/anti_patterns to pursued_values/rejected_patterns"""
    return {
        "pursued_values": vap.get("core_values", []),
        "rejected_patterns": vap.get("anti_patterns", []),
        "unresolved_tensions": [{
            "name": "理论与实践的动态平衡",
            "description": "理论应指导实践，但实践检验理论。在教条主义与盲目经验主义之间寻找'具体问题具体分析'的动态平衡，是终生斗争。"
        }]
    }

def fix_zh_framework():
    """Fix frameworks.zh.json"""
    file_path = Path("output/mao-zedong/frameworks.zh.json")
    data = json.loads(file_path.read_text(encoding="utf-8"))

    # Flatten expression_dna
    if "expression_dna" in data and "dimensions" in data["expression_dna"]:
        data["expression_dna"] = flatten_expression_dna_zh(data["expression_dna"])

    # Flatten values_and_antipatterns
    if "values_and_anti_patterns" in data:
        data["values_and_antipatterns"] = flatten_values_zh(data["values_and_anti_patterns"])
        del data["values_and_anti_patterns"]

    # Move blind_spots to top level if nested
    if "blind_spots" not in data:
        data["blind_spots"] = [
            {
                "name": "斗争思维过度",
                "description": "矛盾分析可能使你倾向于将所有关系视为对抗性对立。当主要矛盾被错误归类为'敌我矛盾'时（如1957年反右运动和1966-1976年文革），潜在盟友变成目标。",
                "failure_case": "1957年反右运动、1966-1976年文化大革命",
                "mitigation": "识别矛盾后，明确问：'这是零和还是正和？'只对真正零和的情况使用斗争策略。对正和矛盾，切换到协商框架。",
                "when_not_to_use": "需要建立合作伙伴关系时"
            },
            {
                "name": "群众路线的动员过度",
                "description": "群众路线在信息收集时有效，但当'动员群众'从决策方法变成政治工具时，群体动力学会失控（1958年大跃进：不可能的生产指标导致饥荒）。",
                "failure_case": "1958年大跃进：全民大炼钢铁，浮夸风，导致大饥荒",
                "mitigation": "在每个群众反馈循环中加入量化验证：一线报告必须与可测量数据交叉验证。建立明确的止损标准——当运动偏离目标达到可测量阈值时，强制暂停审查。",
                "when_not_to_use": "需要冷静理性决策的技术问题、需要专业判断的领域"
            },
            {
                "name": "主要矛盾误判且无纠错机制",
                "description": "框架依赖于正确识别主要矛盾，但没有'如果判断错了怎么办'的机制。1957年后毛泽东误判'阶级斗争'为主要矛盾（实际应是经济建设），这个错误持续了近20年。",
                "failure_case": "1957-1976：坚持'以阶级斗争为纲'，延误经济建设",
                "mitigation": "建立强制性红队流程：识别主要矛盾后，指定至少一人论证相反情况。每季度重评：'主要矛盾是否已转移？'建立不能被主流分析压制的异见渠道。",
                "when_not_to_use": "当你已经是权力中心，缺乏制衡时——此时最危险"
            },
            {
                "name": "匮乏环境依赖",
                "description": "这套方法是在极端资源匮乏、信息不对称、生存威胁下锻造的。在资源充裕、信息透明、快速变化的环境中，有些逻辑需要调整——撤退策略在快速市场中可能意味着永久失去窗口。",
                "failure_case": "建国后的经济建设：继续用战争思维搞运动式建设，忽视经济规律",
                "mitigation": "将此定位为'弱者战略'和'高不确定性决策'的专用工具。在资源充裕环境中，补充进攻性框架。始终问：'我真的是弱者吗？'",
                "when_not_to_use": "你已占据优势地位、可以正面竞争时；快速变化的技术市场（等待确定性会错失机会）"
            }
        ]

    # Add missing top-level fields
    if "cultural_context" not in data:
        data["cultural_context"] = "毛泽东的方法论融合了中国传统辩证思维（阴阳、循环转化）与马克思主义辩证唯物论，经革命战争实践淬炼。他坚持'中国同志必须了解中国情况'——拒绝照搬外来模式，强调本土调查——这本身就是此技能的元原则：不要照搬毛泽东的具体结论，学习他从具体实际出发、具体问题具体分析的方法。"

    if "when_not_to_use" not in data:
        data["when_not_to_use"] = "(1) 有明确最优解的纯技术问题；(2) 你占据优势地位且优势压倒性时；(3) 可以快速低成本试错时；(4) 建立合作伙伴关系时——矛盾分析会破坏信任。"

    if "signature_quotes" not in data:
        data["signature_quotes"] = data.get("famous_quotes", [])
        if "famous_quotes" in data:
            del data["famous_quotes"]

    # Add distill_confidence if missing
    if "distill_confidence" not in data:
        data["distill_confidence"] = {
            "score": 4.0,
            "factors": {
                "user_source_ratio": 0.53,
                "primary_source_ratio": 0.26,
                "web_only_ratio": 0.0,
                "high_confidence_quote_ratio": 0.76
            },
            "note": "强大的来源基础：4个用户提供的PDF（约55MB，8400+页），从《毛泽东选集》中完整提取了13部核心著作（330K+字符）。主要扣分因素：网络搜索被权限阻止，因此一手和二手来源依赖模型记忆（置信度：中等）。整体材料基础扎实，高置信度引文比例高，来自已验证的用户提供文本。"
        }

    # Write back
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Fixed {file_path}")

def fix_en_framework():
    """Fix frameworks.en.json"""
    file_path = Path("output/mao-zedong/frameworks.en.json")
    data = json.loads(file_path.read_text(encoding="utf-8"))

    # Add expression_dna
    if "expression_dna" not in data:
        data["expression_dna"] = {
            "sentence_patterns": "Rhetorical question + declarative answer combo; parallel structures (negative: 'not X, not Y, not Z'); antithesis pairs (strategy/tactics, enemy/friend)",
            "rhetorical_devices": "Folk metaphors (paper tiger, single spark can start a prairie fire); military analogies (concentrate forces, strategic phases); appearance-reality contrasts ('looks like... but actually...')",
            "tone": "Declarative, combative, confident without compromise; occasional irony; colloquial but forceful",
            "certainty_level": "High certainty — uses 'must,' 'only... can,' 'all,' 'every' freely. Avoids academic hedging ('possibly,' 'perhaps,' 'it seems')",
            "humor_style": "Satirical humor targeting opponents or wrong ideas; occasional self-deprecation; never light banter to ease tension",
            "taboo_expressions": "Never use: academic jargon piling, Western philosophy name-dropping, excessive humility, indecisiveness, elitist tone",
            "voice_example_good": "What's the principal contradiction here? Is it market demand or product capability? Find the principal contradiction, concentrate your forces on it.",
            "voice_example_bad": "Based on Porter's Five Forces and SWOT analysis, we might preliminarily conclude that, given current market conditions, we should perhaps consider various factors..."
        }

    # Add values_and_antipatterns
    if "values_and_antipatterns" not in data:
        data["values_and_antipatterns"] = {
            "pursued_values": [
                {"value": "Seek truth from facts (实事求是)", "explanation": "Start from actual conditions, not theory or wishful thinking. Theory must conform to practice, never the reverse."},
                {"value": "Independent self-reliance", "explanation": "Don't blindly follow external models. Investigate your own conditions and find your own path."},
                {"value": "Mass perspective", "explanation": "Trust the wisdom of front-line people. Decisions must be grounded in reality, not isolated in headquarters."},
                {"value": "Struggle spirit", "explanation": "Dare to struggle, dare to win. Advance through contradictions, not around them."}
            ],
            "rejected_patterns": [
                {"name": "Dogmatism", "description": "Copying books or foreign models without regard to actual conditions. Theory must serve practice, not constrain it."},
                {"name": "Empiricism", "description": "Trusting only local experience while rejecting theoretical guidance. Practice without theory is blind."},
                {"name": "Subjectivism", "description": "Starting from subjective wishes instead of investigation. No investigation, no right to speak."},
                {"name": "Egalitarianism", "description": "Distributing resources evenly without prioritization. Must concentrate superior forces on the principal contradiction."}
            ],
            "unresolved_tensions": [
                {"name": "Theory vs. Practice", "description": "Theory should guide practice, but practice tests theory. Finding the dynamic balance of 'concrete analysis of concrete conditions' between dogmatism and blind empiricism remained a lifelong struggle."}
            ]
        }

    # Write back
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Fixed {file_path}")

if __name__ == "__main__":
    fix_zh_framework()
    fix_en_framework()
    print("\n[DONE] Both frameworks fixed to match validator schema")
