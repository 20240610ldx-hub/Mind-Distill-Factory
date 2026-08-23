#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 2 (inline-authored) principle builder for marcus-aurelius.
Pulls supporting_extracts verbatim from the processed source files so archaic
English is never re-typed. Writes principles_user_sources.json (10 core) and
principles_secondary_sources.json (5 blind-spot seeds). Throwaway helper."""
import json, sys, io
from datetime import date
from pathlib import Path

BASE = Path(r"D:\mind distill factory\sources\marcus-aurelius\processed")
OUT = Path(r"D:\mind distill factory\output\marcus-aurelius")
OUT.mkdir(parents=True, exist_ok=True)

def load(name): return json.loads((BASE/name).read_text(encoding="utf-8-sig"))["extracts"]
US, SEC, PRI = load("user_sources.json"), load("secondary_sources.json"), load("primary_sources.json")

def find(lst, needle):
    for e in lst:
        if needle.lower() in e["text"].lower():
            return e
    raise SystemExit("NEEDLE NOT FOUND: " + needle)

def ev(lst, needle, detail=None, conf=None):
    e = find(lst, needle)
    return {"text": e["text"], "source_title": e["source_title"],
            "source_detail": detail or e["source_detail"],
            "confidence": conf or e.get("confidence", "high")}

def evp(needle, detail=None):
    return ev(PRI, needle, detail, "medium")

def evk(needles, n=3):
    out, seen = [], set()
    for e in SEC:
        if any(k.lower() in e["text"].lower() for k in needles):
            key = e["text"][:60]
            if key in seen: continue
            seen.add(key)
            out.append({"text": e["text"], "source_title": e["source_title"],
                        "source_detail": e["source_detail"], "confidence": e.get("confidence", "high")})
            if len(out) >= n: break
    if not out:
        raise SystemExit("BLIND-SPOT KEYWORDS MATCHED NOTHING: " + repr(needles))
    return out

core = [
{"id":"mac_core_01",
 "name_en":"The Inner Citadel: your judgment is the one thing truly yours",
 "name_zh":"内在堡垒：唯有判断真正属于你",
 "uniqueness_score":5,
 "explanation_en":"External things stand outside the mind's door and cannot touch it; what disturbs you is never the event itself but the judgment you add to it. That ruling faculty is the one citadel no force can storm — withdraw the assent and the harm dissolves.",
 "explanation_zh":"外物停在心灵门外，本身触不到你；真正扰动你的，从来不是事件本身，而是你为它附加的判断。那个主导的心灵是无人能攻破的唯一堡垒——撤回认可，伤害随之消散。",
 "decision_rule_en":"Separate event from judgment: if the distress actually lives in your opinion rather than in the bare fact, withdraw the opinion before you act — the thing itself has no power to harm the mind.",
 "decision_rule_zh":"把事件与判断分开：若痛苦其实住在你的看法里、而非赤裸的事实中，先撤回看法再行动——事物本身无力伤害心灵。",
 "topic_tags":["inner-citadel","judgment","dichotomy-of-control","assent"],
 "supporting_extracts":[ev(US,"I consist of body and soul"), ev(US,"dogmata"), ev(US,"Is the cucumber bitter")],
 "notable_quotes":[{"text_en":"If it is not right, do not do it; if it is not true, do not say it.","text_zh":"不正之事勿为，不实之言勿说。","confidence":"medium"}]},

{"id":"mac_core_02",
 "name_en":"The portable refuge: retreat into yourself, not into the hills",
 "name_zh":"随身的退隐：退入自身，而非退入山林",
 "uniqueness_score":4,
 "explanation_en":"People crave country houses, shores and mountains to escape, but you carry a quieter retreat within — your own soul — and can withdraw there in a single breath, then return composed. The renewal needs no travel and no leisure an emperor never has.",
 "explanation_zh":"人们渴望乡间、海滨、山林以逃避，但你随身带着更安静的退隐之所——自己的心灵，一念之间即可退入，须臾即恢复从容。这种更新不需远行，也不需皇帝从来没有的闲暇。",
 "decision_rule_en":"Before seeking an external escape, take the inward retreat first: gather a few settled thoughts on what is actually in your power. If a brief inner withdrawal restores order, you needed perspective, not a change of place.",
 "decision_rule_zh":"在向外逃离之前，先做一次向内的退隐：把心思收回到真正在你能力之内的事上。若片刻的内退就能恢复秩序，你需要的是视角，而非换个地方。",
 "topic_tags":["retreat","self-renewal","inner-life","composure"],
 "supporting_extracts":[evp("more peaceful"), ev(US,"Wipe off all idle fancies"), ev(US,"gather thyself together")]},

{"id":"mac_core_03",
 "name_en":"Made for each other: act for the common good or you injure yourself",
 "name_zh":"为彼此而生：不为公益而行，即是自伤",
 "uniqueness_score":4,
 "explanation_en":"We are limbs of one body, rational beings made for cooperation as feet, hands and eyelids are. What harms the hive harms the bee; to act against the community is to act against your own nature, and the work — not the credit — is the point.",
 "explanation_zh":"我们是同一身体的肢体，如手足眼睑般为协作而生。对蜂群不利之事，对蜜蜂也无益；与共同体作对，就是与自己的本性作对——重点在事功本身，而非功劳归谁。",
 "decision_rule_en":"Test any action against the whole: if it is not good for the hive, it cannot be good for you — choose the common good over private advantage, and over being seen to do it.",
 "decision_rule_zh":"用整体检验每一个行动：若它对蜂群无益，就不可能对你有益——在私利与公益之间、在'被看见'与'做正确'之间，选择后者。",
 "topic_tags":["common-good","social-nature","cooperation","public-duty"],
 "supporting_extracts":[ev(US,"bee-hive"), ev(US,"good and expedient for the public"), ev(US,"gifts and virtues")]},

{"id":"mac_core_04",
 "name_en":"Memento mori as a spur: you could leave life now, so be good now",
 "name_zh":"向死而生的鞭策：你随时可能离场——那就此刻向善",
 "uniqueness_score":4,
 "explanation_en":"Death hangs over you while you still live; do not act as if you had ten thousand years. Stop debating what a good person is and be one — today, in this very act; mortality is not morbid but the deadline that makes virtue urgent.",
 "explanation_zh":"死亡悬于头顶，而你仍活着；别像还有上万年可活那样行事。停止争辩何谓善人——就此刻、就这一个行动里，去做一个善人；向死不是阴郁，而是让美德变得紧迫的截止线。",
 "decision_rule_en":"Apply the deadline test: if today were your last, would this still be worth doing, saying, or withholding? Whatever virtue can be enacted now, do not defer it to a tomorrow you may not have.",
 "decision_rule_zh":"用截止线检验：若今天是最后一天，这件事还值得做、值得说、或值得忍住不做吗？凡此刻能践行的德性，别推给一个未必到来的明天。",
 "topic_tags":["memento-mori","urgency","virtue-now","mortality"],
 "supporting_extracts":[ev(US,"Death hangs over thee","Book IV.17 (tr. Casaubon)"), evp("Waste no more time"), ev(US,"cessation from the impression")],
 "notable_quotes":[{"text_en":"Waste no more time arguing what a good man should be. Be one.","text_zh":"别再耗时争辩善人当如何——去做一个善人。","confidence":"medium"}]},

{"id":"mac_core_05",
 "name_en":"Amor fati: love the thread the cosmos spins for you",
 "name_zh":"爱命运：欣然接住宇宙为你纺出的那根线",
 "uniqueness_score":4,
 "explanation_en":"Whatever happens was woven for you from the beginning, and the same web that brought the event also made you. Do not merely endure what comes — will it, love it, and treat the time that remains as unearned surplus to spend on a good life.",
 "explanation_zh":"凡发生之事自始就为你而织，带来事件的那张网也织成了你。不要仅仅忍受降临之事——要主动愿它、爱它，把余下的时光当作意外的盈余，全数花在良善的生活上。",
 "decision_rule_en":"After doing what is in your power, check your stance toward the result: if you are still fighting what has already happened, convert the resistance into assent — accept what is given as fitting and spend the remainder well.",
 "decision_rule_zh":"做完能力范围内的事后，检验你对结果的姿态：若你仍在抗拒已然发生之事，把抗拒转为接纳——把所予之事当作合宜，并好好花掉余下的时间。",
 "topic_tags":["amor-fati","acceptance","providence","resilience"],
 "supporting_extracts":[ev(US,"whatsoever it be that happeneth"), ev(US,"mind of the universe"), ev(US,"Is the cucumber bitter")]},

{"id":"mac_core_06",
 "name_en":"The view from above: widen the frame until the trouble shrinks to scale",
 "name_zh":"从高处俯瞰：拉远视角，直到烦恼缩回它应有的尺寸",
 "uniqueness_score":5,
 "explanation_en":"Set your trouble against the whole — the rolling ages, the substance of the universe passing like a torrent, the earth that will cover us all. Seen from that height, grievance, craving and fame shrink to their true size; even a Socrates and an Epictetus the age has already swallowed.",
 "explanation_zh":"把你的烦恼放进整体里看——翻滚的世代、如急流般流过的宇宙实体、终将覆盖我们所有人的大地。从那个高度看去，怨恨、贪求与名声都缩回真实的尺寸；连苏格拉底、爱比克泰德这样的人，时代也早已吞没。",
 "decision_rule_en":"When a thing looms large, widen the frame in time and space: place it against the lifespan of empires and the flux of all matter. If it vanishes at cosmic scale, it does not deserve to govern you now.",
 "decision_rule_zh":"当一件事显得庞大，就在时空上放大画框：把它放到帝国的寿数与万物的流变中衡量。若它在宇宙尺度上消失不见，它就不配在此刻支配你。",
 "topic_tags":["view-from-above","cosmic-perspective","transience","right-sizing"],
 "supporting_extracts":[ev(US,"as through a torrent"), ev(US,"earth shall cover us all"), ev(US,"Perpetual fluxes"), ev(US,"so much wax")],
 "notable_quotes":[{"text_en":"Look round at the courses of the stars, as if thou wert going along with them.","text_zh":"环顾群星的运行，仿佛你正与它们同行。","confidence":"medium"}]},

{"id":"mac_core_07",
 "name_en":"Fame is the clatter of tongues: do right, ignore the applause",
 "name_zh":"名声不过是众舌的喧响：行其当行，不顾掌声",
 "uniqueness_score":4,
 "explanation_en":"Those once loudly praised are forgotten, and those who praised them are dust; applause is no better than the clattering of tongues, and posthumous fame a brief echo soon silenced. Let the worth of the deed, not the noise around it, be what you pursue.",
 "explanation_zh":"曾被高声称颂的人如今被遗忘，称颂者自己也早已成尘；掌声不过是众舌的喧响，身后之名是很快归于沉寂的短促回响。让你追求的是行为本身的价值，而非围绕它的噪音。",
 "decision_rule_en":"Strip the audience from the choice: if you would not do this without witnesses or any memory of it, your motive is reputation rather than virtue — re-decide on the merit of the act alone.",
 "decision_rule_zh":"把观众从抉择中抽走：若没有人看见、也无人记得你便不会做这件事，那你的动机是名声而非德性——只凭行为本身的是非重新决定。",
 "topic_tags":["fame","indifference-to-praise","integrity","motive"],
 "supporting_extracts":[ev(US,"good and expedient for the public"), ev(US,"clattering"), ev(US,"truly simple, good, sincere")]},

{"id":"mac_core_08",
 "name_en":"The discipline of perception: see the bare thing, drop the story you add",
 "name_zh":"感知的修炼：看赤裸的事实，丢掉你附加的故事",
 "uniqueness_score":5,
 "explanation_en":"Confine yourself to the first bare impression — the cucumber is bitter, so set it away — and refuse the second layer the mind adds: the indignation, the 'why me', the narrative of harm. Do not imagine the offence the wrongdoer wants you to imagine; look into the matter itself and see what it truly is.",
 "explanation_zh":"把自己限制在第一层赤裸的印象上——黄瓜苦，就放到一边——拒绝心灵添加的第二层：愤慨、'为什么是我'、受害的叙事。别按加害者希望你设想的去设想，而要看进事情本身，看清它究竟是什么。",
 "decision_rule_en":"Cut the impression in two: keep the objective fact, delete the editorial verdict appended to it. If what wounds you is the added commentary and not the fact, refuse the commentary.",
 "decision_rule_zh":"把印象切成两半：保留客观事实，删去附在其上的评判。若刺痛你的是那层附加的评注、而非事实本身，就拒绝那评注。",
 "topic_tags":["discipline-of-perception","objective-judgment","reframing","assent"],
 "supporting_extracts":[ev(US,"Is the cucumber bitter"), ev(US,"WHAT IS WICKEDNESS"), ev(US,"he that wrongeth thee","Book IV (tr. Casaubon)")]},

{"id":"mac_core_09",
 "name_en":"On others' faults: understand, do not burn, and never become like them",
 "name_zh":"对他人之过：理解，而非燃烧——且绝不让自己变得像他们",
 "uniqueness_score":4,
 "explanation_en":"People will be meddling, ungrateful and arrogant — you knew this at dawn. They err from ignorance of good and evil and are your kin; another's fault cannot truly harm you, nor implicate you in ugliness, unless you consent. The finest revenge is simply to refuse to become like the one who wronged you.",
 "explanation_zh":"人会多管闲事、忘恩负义、傲慢无礼——你在清晨就已知道。他们因不明善恶而犯错，且是你的同类；除非你认可，他人的过错既不能真正伤你，也不能把你拖进丑陋。最好的报复，不过是拒绝变得像那个伤害你的人。",
 "decision_rule_en":"When wronged, run two checks: does this person act from ignorance rather than malice (then anger is misplaced), and would retaliating make me resemble them (then the only worthy response is to stay unlike them)?",
 "decision_rule_zh":"受到冒犯时做两道检验：此人是出于无知而非恶意吗（若是，愤怒便是错置）？报复会让我变得像他吗（若会，唯一值得的回应就是保持与他不同）？",
 "topic_tags":["forbearance","relationships","anger","best-revenge"],
 "supporting_extracts":[evp("meddling, ungrateful"), ev(US,"best kind of revenge","Book VI.6 (tr. Casaubon)"), ev(US,"he that wrongeth thee","Book IV (tr. Casaubon)")],
 "notable_quotes":[{"text_en":"The best revenge is not to be like your enemy.","text_zh":"最好的报复，就是不要变得像你的敌人。","confidence":"medium"}]},

{"id":"mac_core_10",
 "name_en":"Keep a reckoning with yourself: govern the self before you govern anything",
 "name_zh":"与自己结账：在治理任何事之前，先治理自己",
 "uniqueness_score":5,
 "explanation_en":"Gather yourself at least once a day, morning or evening; wipe off idle fancies and tell yourself plainly what is and is not in your power. Inventory the virtues of those around you and the debts you owe your teachers — for the point of the practice is not insight but repetition, re-dyeing the soul daily in the colour of right thoughts.",
 "explanation_zh":"至少每天一次、清晨或傍晚，把自己收拢起来；拂去虚妄的念头，平实地对自己讲清什么在你能力之内、什么不在。清点身边人的德性，也清点你欠师长的债——这修炼的要点不在顿悟，而在重复：每日把心灵重新染上正念的颜色。",
 "decision_rule_en":"Make the audit recurring, not occasional: each day name one fault to drop and one virtue — in yourself or another — to imitate. If you only examine yourself in a crisis, you have built no citadel before the siege.",
 "decision_rule_zh":"让这场盘点成为日课而非偶发：每天点出一个要丢掉的缺点、一个（在己或在人身上）要效仿的德性。若你只在危机中才省察自己，围城之前你便没有筑好堡垒。",
 "topic_tags":["self-examination","daily-practice","self-discipline","habit"],
 "supporting_extracts":[ev(US,"gather thyself together"), ev(US,"Wipe off all idle fancies"), ev(US,"gifts and virtues"), ev(US,"Of my mother I have learned"), ev(US,"Such as thy thoughts","Book V.16 (tr. Casaubon)")],
 "notable_quotes":[{"text_en":"Your soul takes on the colour of your thoughts.","text_zh":"你的灵魂会染上你思想的颜色。","confidence":"medium"}]},
]

blind = [
{"id":"mac_blind_01",
 "name_en":"Transience can curdle into world-weariness",
 "name_zh":"无常的凝视可能酿成厌世的疲惫",
 "uniqueness_score":2,
 "explanation_en":"The constant rehearsal of death, flux and the smallness of all things can tip from liberating perspective into joyless resignation — the 'melancholy emperor' Renan saw. Hadot argues the exercise was meant to affirm life, yet the texture often reads as weariness.",
 "explanation_zh":"对死亡、流变与万物渺小的反复演练，可能从'解放的视角'滑向'无喜的认命'——勒南所见的'忧郁的皇帝'。哈多特指出这套修炼本意是肯定生命，但其文字质地常读来如倦怠。",
 "decision_rule_en":"Pair every memento mori with a memento vivere: after right-sizing a trouble, deliberately name one thing to engage and enjoy. If the practice leaves you colder and more withdrawn, you are doing resignation, not Stoicism.",
 "decision_rule_zh":"每一次'勿忘你终将死'都配一次'勿忘你正活着'：在把烦恼缩小之后，刻意指出一件要投入、要享受的事。若修炼让你更冷、更退缩，你做的是认命，而非斯多葛。",
 "topic_tags":["risk-melancholy","blind-spot","resignation"],
 "supporting_extracts": evk(["melanchol","pessim","Renan","weariness","weary"])},

{"id":"mac_blind_02",
 "name_en":"Determinism can be misused to excuse passivity",
 "name_zh":"决定论可能被滥用来为消极开脱",
 "uniqueness_score":2,
 "explanation_en":"If everything is providential and fated, the discipline of desire ('love what happens') can be twisted into fatalism: why act at all? Hadot flags the genuine tension between cosmic necessity and human freedom.",
 "explanation_zh":"若一切皆天意与命定，'爱所发生之事'的欲望修炼就可能被扭成宿命论——既然如此，何必行动？哈多特点出宇宙必然与人的自由之间存在真实张力。",
 "decision_rule_en":"Keep amor fati downstream of action, never upstream: accept outcomes only after you have exhausted what is in your power. If 'it was fated' arrives before you have acted, it is an excuse, not Stoicism.",
 "decision_rule_zh":"让'爱命运'永远位于行动的下游、而非上游：只在穷尽你能力范围之事'之后'才接纳结果。若'这是命定'在你行动之前就到来，那是借口，不是斯多葛。",
 "topic_tags":["risk-determinism","blind-spot","passivity"],
 "supporting_extracts": evk(["determin","freedom","necessity","fated","providence vs"])},

{"id":"mac_blind_03",
 "name_en":"Detachment from externals can slide into disengagement",
 "name_zh":"对外物的不动心可能滑向冷漠的抽离",
 "uniqueness_score":2,
 "explanation_en":"Treating health, wealth, reputation and outcomes as 'indifferent' can rationalize withdrawal from the messy work of justice and relationships. Hadot answers that Marcus's discipline of action mandates vigorous engagement, but the text's serenity is easily misread as quietism.",
 "explanation_zh":"把健康、财富、名声与结果都视为'无关紧要'，可能为逃避正义与关系中那些麻烦的工作开脱。哈多特回应说马可的'行动修炼'要求积极投入，但文本的宁静易被误读为政治上的退避。",
 "decision_rule_en":"Aim indifference at the result, never at the duty: stay fully and energetically engaged in acting justly, and release only your grip on how it turns out. If detachment is reducing your effort, you have pointed it at the wrong target.",
 "decision_rule_zh":"把不动心对准'结果'，绝不对准'本分'：在正义之事上保持全力、充满活力的投入，只松开你对结局的执取。若抽离正在降低你的努力，你就把它瞄错了靶子。",
 "topic_tags":["risk-detachment","blind-spot","quietism"],
 "supporting_extracts": evk(["passiv","detachment","detach","disengage","quietism","withdraw"])},

{"id":"mac_blind_04",
 "name_en":"Private virtue is no guarantee of just public outcomes",
 "name_zh":"私德的完善并不保证公共结果的正义",
 "uniqueness_score":3,
 "explanation_en":"Marcus scrutinized himself relentlessly yet presided over wars, the persecution of Christians occurred in his reign, and his Stoic ideals did not prevent handing the empire to the disastrous Commodus. The inner citadel governs the self; it does not by itself produce wise institutions or sound succession.",
 "explanation_zh":"马可严苛地省察自己，却仍主持战争，其治下发生了对基督徒的迫害，而他的斯多葛理想也没能阻止把帝国交给灾难性的康茂德。内在堡垒治理的是自我，它本身并不产出明智的制度或稳妥的继承。",
 "decision_rule_en":"Treat this framework as a tool for self-government, not statecraft: when outcomes affect others, add institutional design, counsel and succession planning — do not trust personal virtue alone to deliver just results.",
 "decision_rule_zh":"把这套框架当作'自我治理'的工具、而非'治国术'：当结果牵涉他人时，要补上制度设计、谋士进言与继承规划——别指望仅凭个人德性就能交付正义的结果。",
 "topic_tags":["risk-power-gap","blind-spot","institutions"],
 "supporting_extracts": evk(["brotherhood","imperial","coercive","ideal","gap","power","reality"])},

{"id":"mac_blind_05",
 "name_en":"A solitary, self-addressed practice is thin on the relational and the joyful",
 "name_zh":"一种独对自己的修炼，在关系与喜悦上是单薄的",
 "uniqueness_score":2,
 "explanation_en":"The Meditations is one man talking himself into endurance; it is rich on duty and composure but sparse on love, collaboration, play and building things with others. Hadot notes its lonely register; as a life-operating-system it is necessary but not complete.",
 "explanation_zh":"《沉思录》是一个人把自己劝向坚忍；它在本分与从容上丰厚，却在爱、协作、游戏与共同创造上稀薄。哈多特注意到它孤独的音调；作为一套人生操作系统，它必要却不完整。",
 "decision_rule_en":"Use the inner citadel as a foundation, not the whole house: deliberately supplement it with practices of connection, creativity and shared joy. If the framework is making you more self-enclosed, balance it with sources oriented to relationship and delight.",
 "decision_rule_zh":"把内在堡垒当作地基、而非整座房子：刻意用连接、创造与共享的喜悦去补足它。若这框架正让你愈发自我封闭，就用面向关系与欢愉的源泉来平衡它。",
 "topic_tags":["risk-solitude","blind-spot","relational-gap"],
 "supporting_extracts": evk(["solitude","lonely","alone","never intended for publication","personal","private"])},
]

def wrap(src_type, principles):
    return {"person":"Marcus Aurelius","person_slug":"marcus-aurelius","source_type":src_type,
            "synthesized_at":date.today().isoformat(),"principles":principles}

# integrity asserts
for p in core+blind:
    assert p["supporting_extracts"], "EMPTY EVIDENCE: "+p["id"]
    assert 1 <= p["uniqueness_score"] <= 5

(OUT/"principles_user_sources.json").write_text(json.dumps(wrap("user_provided",core),ensure_ascii=False,indent=2),encoding="utf-8")
(OUT/"principles_secondary_sources.json").write_text(json.dumps(wrap("secondary",blind),ensure_ascii=False,indent=2),encoding="utf-8")

# ascii-only report
def ar(p): return "%s u=%s ev=%s nq=%s" % (p["id"], p["uniqueness_score"], len(p["supporting_extracts"]), len(p.get("notable_quotes",[])))
sys.stdout.reconfigure(encoding="utf-8")
print("WROTE principles_user_sources.json:", len(core), "core")
for p in core: print("  ", ar(p))
print("WROTE principles_secondary_sources.json:", len(blind), "blind-spot seeds")
for p in blind: print("  ", ar(p), "evtitles=", sorted(set(e["source_title"] for e in p["supporting_extracts"])))
