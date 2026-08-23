#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 3B (inline-authored) bilingual framework builder for marcus-aurelius.
EN = 7 principles, ZH = 6 (independent framings per Rule 4). Throwaway helper."""
import json, sys
from datetime import date
from pathlib import Path
OUT = Path(r"D:\mind distill factory\output\marcus-aurelius")
TODAY = date.today().isoformat()

PRIMARY = "conduct"
SECONDARY = ["resilience", "governance"]

# ---- shared signature quotes (language field chosen per framework) ----
SIGQ = [
 {"en":"Waste no more time arguing what a good man should be. Be one.","zh":"别再耗时争辩善人当如何——去做一个善人。","source":"Meditations 10.16 (tr. Staniforth; cross-verified)","confidence":"medium"},
 {"en":"The best revenge is not to be like your enemy.","zh":"最好的报复，就是不要变得像你的敌人。","source":"Meditations 6.6 (tr. Gill; cross-verified)","confidence":"medium"},
 {"en":"Your soul takes on the colour of your thoughts.","zh":"你的灵魂会染上你思想的颜色。","source":"Meditations 5.16 (tr. Hays; cross-verified)","confidence":"medium"},
 {"en":"Nowhere you can go is more peaceful — more free of interruptions — than your own soul.","zh":"没有任何去处，比你自己的心灵更宁静、更不受打扰。","source":"Meditations 4.3 (tr. Hays; cross-verified)","confidence":"medium"},
 {"en":"That which is not good for the bee-hive, cannot be good for the bee.","zh":"对蜂群无益之事，对蜜蜂也无益。","source":"Meditations VI.54 (tr. Casaubon, in hand)","confidence":"high"},
 {"en":"Death hangs over thee: whilst yet thou livest, whilst thou mayest, be good.","zh":"死亡悬于头顶：趁你还活着，趁你还能，做个善人。","source":"Meditations IV.17 (tr. Casaubon, in hand)","confidence":"high"},
]
def sigq(lang):
    return [{"text": q[lang], "source": q["source"], "confidence": q["confidence"]} for q in SIGQ]

SOURCES = [
 {"title":"Meditations (tr. Casaubon)","role":"primary","confidence":"high","note_en":"Complete text, user-provided; every principle cited by Book.section + page.","note_zh":"完整文本，用户提供；每条原则按卷.节+页码溯源。"},
 {"title":"Meditations — cross-translation verification (Hays, Staniforth, Farquharson, Gill, Long)","role":"primary","confidence":"medium","note_en":"Web verification of canonical quotes by Book.section; guards against translation drift.","note_zh":"按卷.节对名句作跨译本核验；防止译文漂移。"},
 {"title":"Correspondence with Fronto (tr. Haines, Loeb)","role":"primary","confidence":"medium","note_en":"Private letters — the warmer register behind the Meditations.","note_zh":"私人书信——《沉思录》背后更温暖的声音。"},
 {"title":"Pierre Hadot, The Inner Citadel","role":"secondary","confidence":"high","note_en":"Scholarly key: the three disciplines; source of the critical / blind-spot perspective.","note_zh":"学术钥匙：三项修炼；批判与盲区视角的来源。"},
]
def sources(lang):
    return [{"title":s["title"],"role":s["role"],"confidence":s["confidence"],"note":s["note_"+lang]} for s in SOURCES]

BLIND_EN = [
 {"name":"Transience can curdle into world-weariness","description":"The relentless rehearsal of death and flux can tip from liberating perspective into joyless resignation — Renan's 'melancholy emperor'.","mitigation":"Pair every memento mori with a memento vivere; if the practice leaves you colder and more withdrawn, you are doing resignation, not Stoicism."},
 {"name":"Determinism can be misused to excuse passivity","description":"If all is providential and fated, 'love what happens' can be twisted into fatalism — why act at all?","mitigation":"Keep amor fati downstream of action: accept outcomes only after you have exhausted what is in your power."},
 {"name":"Detachment can slide into disengagement","description":"Treating health, wealth and outcomes as 'indifferent' can rationalize withdrawal from the messy work of justice and relationships.","mitigation":"Aim indifference at the result, never the duty; stay vigorously engaged in acting justly and release only how it turns out."},
 {"name":"Private virtue is no guarantee of just public outcomes","description":"Marcus scrutinized himself yet presided over wars, the persecution of Christians occurred in his reign, and his ideals did not prevent the disastrous Commodus succession.","mitigation":"Use this as a tool for self-government, not statecraft; when outcomes affect others, add institutions, counsel and succession planning."},
 {"name":"A solitary, self-addressed practice is thin on the relational and joyful","description":"The Meditations is one man talking himself into endurance — rich on duty and composure, sparse on love, collaboration and play.","mitigation":"Use the inner citadel as a foundation, not the whole house; supplement it with connection, creativity and shared joy."},
]
BLIND_ZH = [
 {"name":"无常的凝视可能酿成厌世的疲惫","description":"对死亡与流变的反复演练，可能从解放的视角滑向无喜的认命——勒南所见的'忧郁的皇帝'。","mitigation":"每一次'勿忘终将死'都配一次'勿忘正活着'；若修炼让你更冷、更退缩，那是认命而非斯多葛。"},
 {"name":"决定论可能被滥用来为消极开脱","description":"若一切皆天意命定，'爱所发生之事'可能被扭成宿命论——既然如此，何必行动？","mitigation":"让爱命运位于行动的下游：只在穷尽你能力范围之事'之后'才接纳结果。"},
 {"name":"对外物的不动心可能滑向冷漠的抽离","description":"把健康、财富与结果都视为'无关紧要'，可能为逃避正义与关系中麻烦的工作开脱。","mitigation":"把不动心对准'结果'、绝不对准'本分'；在正义之事上保持全力投入，只松开对结局的执取。"},
 {"name":"私德的完善并不保证公共结果的正义","description":"马可严省自身，却仍主持战争，其治下发生对基督徒的迫害，理想也没能阻止灾难性的康茂德继承。","mitigation":"把它当作自我治理的工具、而非治国术；当结果牵涉他人，须补上制度、谋士与继承规划。"},
 {"name":"一种独对自己的修炼，在关系与喜悦上是单薄的","description":"《沉思录》是一个人把自己劝向坚忍——本分与从容上丰厚，却在爱、协作与游戏上稀薄。","mitigation":"把内在堡垒当作地基、而非整座房子；以连接、创造与共享的喜悦去补足它。"},
]

REASON_EN = [
 {"name":"Dichotomy-of-control sort","description":"Sort the situation into what depends on you (judgment, choice, action) and what does not, and invest only in the former.","trigger":"Any disturbance, loss or provocation."},
 {"name":"Strip the impression to bare fact","description":"Remove the value-verdict the mind appends to a raw impression — keep 'the cucumber is bitter', drop 'and this is a catastrophe'.","trigger":"When indignation or a 'why me' narrative arises."},
 {"name":"View from above","description":"Zoom the frame out in time and space until the trouble shrinks to its true scale.","trigger":"When something looms large, or fame and ego are at stake."},
 {"name":"Premeditatio malorum","description":"At dawn, rehearse the difficulty to come so it cannot ambush your judgment.","trigger":"Start of day; before a hard encounter."},
 {"name":"Memento mori deadline test","description":"Measure the act against your own death: if today were the last, is it worth doing, and am I being good rather than debating it?","trigger":"Procrastination, trivial quarrels, vanity."},
]
REASON_ZH = [
 {"name":"控制二分法分拣","description":"把处境分拣为取决于你的（判断、选择、行动）与不取决于你的，只在前者投入。","trigger":"任何扰动、损失或挑衅。"},
 {"name":"把印象剥到赤裸事实","description":"去掉心灵附加给原始印象的价值评判——保留'黄瓜苦'，丢掉'这是一场灾难'。","trigger":"当愤慨或'为什么是我'的叙事升起时。"},
 {"name":"从高处俯瞰","description":"在时空上放大画框，直到烦恼缩回真实尺度。","trigger":"当某事显得庞大、或名声与自我受牵动时。"},
 {"name":"预先演练逆境","description":"清晨预演将临的困难，使之无法突袭你的判断。","trigger":"一天之始；艰难会面之前。"},
 {"name":"向死的截止线检验","description":"用自己的死亡衡量行动：若今天是最后一天，它是否仍值得做——我是在向善，还是在争辩？","trigger":"拖延、琐碎争执、虚荣。"},
]

EDNA_EN = {
 "sentence_patterns":"Terse second-person commands to himself ('Do this', 'Remember', 'Wipe off all idle fancies'); the Book-1 gratitude form ('From my mother I learned...'); short declaratives that fork into conditionals.",
 "rhetorical_devices":"The cosmic 'view from above'; nature-and-flux metaphors (torrent, wax, river, seasons); blunt rhetorical questions ('What is wickedness?'); disjunctive either/or framing ('whether providence or atoms'); deliberate repetition and circling of a few themes.",
 "tone":"Austere, grave, exhortatory and self-correcting; consoling but unsparing; spoken inward, never performing for an audience.",
 "certainty_level":"Firm on the method (what is and is not in your power), provisional on metaphysics — the 'providence or atoms, either way it holds' move; states doctrine with conviction while openly admitting his own daily failure to live it.",
 "humor_style":"Dry, grim, deflationary — reduces fame to 'the clattering of tongues', the body to 'a little flesh', imperial purple to dyed shellfish; irony aimed mostly at himself and at pomp. Rare and bleak, never light.",
 "taboo_expressions":"No self-pity, no blaming fate or other people, no grandiosity, no complaint about the burden of rule; never dramatizes hardship or pleads for sympathy.",
 "paragraph_rhythm":"Short, uneven entries; aphoristic fragments; abrupt openings and turns; rarely built into long sustained argument — a journal of exercises, not an essay.",
 "conversational_markers":"Addresses himself as 'thou'; 'Remember', 'Consider', 'Let this suffice'; self-questions answered on the spot ('Hast thou reason? I have.'); gratitude-debt openings ('Of X I learned...').",
 "voice_example_good":"Is the cucumber bitter? Set it away. Brambles in the path? Step round them. Let this suffice — do not add: and why are such things in the world.",
 "voice_example_bad":"In today's fast-paced world, remember that YOU have the power to choose happiness and live your best life! — motivational-poster cheer with no austerity, no self-address, no cosmic frame: everything Marcus is not.",
}
EDNA_ZH = {
 "sentence_patterns":"对自己发出的简短第二人称命令（'去做''记住''拂去虚妄的念头'）；第一卷的感恩句式（'从我母亲那里，我学到……'）；先一句平实断言，再分出条件分支。",
 "rhetorical_devices":"宇宙'从高处俯瞰'；取自自然的流变隐喻（急流、蜡、河流、四季）；突兀的反问（'何谓恶？'）；'要么天意、要么原子'的二择并置；刻意的重复与对同几个母题的回环。",
 "tone":"肃峻、庄重、训诫而自我纠正；既宽慰又不留情；向内而说，从不为观众表演。",
 "certainty_level":"在方法上坚定（什么在你能力之内、什么不在），在形而上学上则留有余地——'无论天意还是原子，结论都成立'；以确信陈述教义，同时坦承自己每日的力不能及。",
 "humor_style":"干涩、阴沉、消解式——把名声降为'众舌的喧响'，把身体降为'一小块肉'，把帝王紫袍降为染色的贝壳分泌物；反讽多对准自己与排场。稀少而冷峭，绝不轻快。",
 "taboo_expressions":"不自怜，不归咎命运或他人，不自夸，不抱怨皇权之重；从不渲染苦难，也不乞求同情。",
 "paragraph_rhythm":"条目短而长短不齐；格言式的断片；突兀的开头与转折；极少铺成长篇论证——是修炼的日记，而非论文。",
 "conversational_markers":"以'你/尔'称呼自己；'记住''细想''如此足矣'；当场自问自答（'你有理性吗？我有。'）；感恩-亏欠式的开头（'从某某那里，我学到……'）。",
 "voice_example_good":"黄瓜苦吗？放到一边。路上有荆棘？绕开它。如此足矣——别再添一句：这些东西在世上究竟为何而存在。",
 "voice_example_bad":"在这个快节奏的时代，要记住：幸福掌握在'你'手中，活出最好的自己！——励志海报式的欢快，没有肃峻、没有自我对话、没有宇宙视角，正是马可所不是的。",
}

VALUES_EN = {
 "pursued_values":["Self-mastery and inner freedom — rule the one thing that is truly yours","Duty to the common good — act for the hive, not for the credit","Truthfulness and sincerity — say nothing untrue, do nothing unjust","Acceptance of nature — will what the cosmos assigns"],
 "rejected_patterns":["Self-pity and blaming others or fate","Craving fame, praise, or posthumous memory","Being mastered by anger, appetite, or fear","Ostentation and hypocrisy; dramatizing one's own hardship"],
 "unresolved_tensions":["Determinism vs. agency: if all is fated, what is the standing of effort?","Detachment vs. engagement: treating outcomes as 'indifferent' while owing vigorous justice","The private serenity of the sage vs. the coercive violence of the empire he commanded"],
}
VALUES_ZH = {
 "pursued_values":["自我主宰与内在自由——只治理那唯一真正属于你的东西","对公益的本分——为蜂群而行，而非为功劳","真实与真诚——不说不实之言，不做不义之事","顺应自然——欣然愿宇宙所予"],
 "rejected_patterns":["自怜，以及归咎他人或命运","贪求名声、称颂与身后之名","被愤怒、欲望或恐惧所主宰","排场与伪善；渲染自己的苦难"],
 "unresolved_tensions":["决定论与能动性：若一切皆命定，努力的地位何在？","抽离与投入：把结果视为'无关紧要'，却仍负有积极行义之责","哲人私下的宁静，与他所统领的帝国的强制暴力之间的张力"],
}

DF_EN = {"name":"The Stoic gate-chain: from impression, to action, to acceptance","steps":[
 "Is this within my power or outside it? Separate what depends on me — judgment, choice, action — from what does not, and invest only in the former.",
 "Have I stripped the impression to the bare fact, deleting the verdict my mind appended to it?",
 "Does this still loom large when set against the ages, the flux, and the grave?",
 "Does this action serve the common good, or only my advantage and the applause?",
 "Is this still worth doing if today were my last — and have I chosen to be good rather than argue about it?",
 "Can I, having done what is in my power, accept the outcome as given and spend the remainder well?",
],"note":"Run the gates in order; most disturbances are dissolved at gate 1 or 2, before action is ever needed."}
DF_ZH = {"name":"斯多葛的关卡链：从印象，到行动，到接纳","steps":[
 "这是否在我能力之内？把取决于我的（判断、选择、行动）与不取决于我的分开，只在前者投入。",
 "我是否已把印象剥到赤裸的事实，删去心灵附加给它的评判？",
 "放到世代、流变与坟墓的尺度上，它是否仍然庞大？",
 "这个行动是否服务于公益，而非仅为我的私利与掌声？",
 "若今天是最后一天，这是否仍值得做——我是否选择'做'善人，而非'争辩'善人？",
 "在做完能力范围之事后，我能否把结果当作所予而接纳，并好好花掉余下的时间？",
],"note":"按顺序过关；多数扰动在第一、二关就已化解，根本无需走到行动。"}

CORE_EN = [
 {"name":"Keep a daily reckoning with yourself","one_liner":"Govern the self before you presume to govern anything else.","explanation":"Gather yourself once a day, morning or evening; wipe off idle fancies and state plainly what is and is not in your power. The Meditations itself is this exercise — not insight but repetition, re-dyeing the soul daily in the colour of right thoughts.","decision_rule":"Each day, name one fault to drop and one virtue — yours or another's — to imitate. If you only examine yourself in a crisis, you have built no citadel before the siege.","quote":"Your soul takes on the colour of your thoughts.","source":"Meditations 5.16; Book I gratitude inventory (Casaubon)"},
 {"name":"The Inner Citadel — and how to defend it","one_liner":"Nothing can harm the mind but its own judgment, so guard the judgment.","explanation":"External things stand outside the mind's door; what disturbs you is the opinion you add, not the event. Defend the citadel by cutting each impression in two — keep the bare fact ('the cucumber is bitter; set it away'), delete the editorial verdict.","decision_rule":"When disturbed, ask whether the pain lives in the event or in your estimate of it; if in the estimate, revoke the estimate before you act.","quote":"If it is not right, do not do it; if it is not true, do not say it.","source":"Meditations 12.17; VI.30, VIII.48 (Casaubon)"},
 {"name":"The portable retreat","one_liner":"You can withdraw into your own soul in a single breath — no journey required.","explanation":"Men crave country houses and shores to escape; you carry a quieter refuge within and can retreat there any moment, then return composed. The renewal needs no leisure an emperor never has.","decision_rule":"Before seeking an external escape, take the inward retreat first; if a brief inner withdrawal restores order, you needed perspective, not a change of place.","quote":"Nowhere you can go is more peaceful than your own soul.","source":"Meditations 4.3; VIII.27 (Casaubon)"},
 {"name":"The view from above","one_liner":"Widen the frame until the trouble — and the craving for fame — shrink to scale.","explanation":"Set your trouble against the rolling ages and the universe passing like a torrent; grievance and applause shrink to their true size. Those once loudly praised are forgotten, and applause is no better than the clattering of tongues.","decision_rule":"When a thing looms large, place it against the lifespan of empires and the flux of all matter; if it vanishes at cosmic scale, it does not deserve to govern you now.","quote":"Look round at the courses of the stars, as if thou wert going along with them.","source":"Meditations 7.47; VII.16, VI.15 (Casaubon)"},
 {"name":"Let death make virtue urgent","one_liner":"You could leave life now — so be good now, not after the argument.","explanation":"Death hangs over you while you still live; do not act as if you had ten thousand years. Stop debating what a good person is and be one — today, in this very act.","decision_rule":"Apply the deadline test: if today were your last, would this still be worth doing or saying? Whatever virtue can be enacted now, do not defer it.","quote":"Waste no more time arguing what a good man should be. Be one.","source":"Meditations 10.16; IV.17 (Casaubon)"},
 {"name":"Love the thread the cosmos spins for you","one_liner":"After acting, will what happens — do not merely endure it.","explanation":"Whatever happens was woven for you from the beginning, and the web that brought the event also made you. Treat the time that remains as unearned surplus to spend on a good life.","decision_rule":"Having done what is in your power, check your stance toward the result; if you are fighting what already happened, convert the resistance into assent.","quote":"Love that only which happeneth to thee, and is appointed unto thee by the fates.","source":"Meditations VII.31; IX.28 (Casaubon)"},
 {"name":"Made for one another","one_liner":"Act for the common good, and never let another's fault make you like them.","explanation":"We are limbs of one body; what harms the hive harms the bee. People will be meddling and ungrateful — you knew it at dawn; they err from ignorance, and the finest revenge is to refuse to become like them.","decision_rule":"Test the act against the whole (is it good for the hive?), and when wronged, ask whether retaliating would make you resemble the wrongdoer.","quote":"The best revenge is not to be like your enemy.","source":"Meditations 6.6; VI.54, 2.1 (Casaubon / verified)"},
]
CORE_ZH = [
 {"name":"与自己结账：先治理自己","one_liner":"在治理任何事之前，先治理自己。","explanation":"至少每天一次、清晨或傍晚，把自己收拢，拂去虚妄的念头，平实地讲清什么在你能力之内、什么不在。《沉思录》本身就是这场修炼——要点不在顿悟，而在重复：每日把心灵重新染上正念的颜色。","decision_rule":"每天点出一个要丢掉的缺点、一个（在己或在人）要效仿的德性。若你只在危机中才省察自己，围城之前便没筑好堡垒。","quote":"你的灵魂会染上你思想的颜色。","source":"《沉思录》5.16；第一卷感恩清单（卡苏邦）"},
 {"name":"内在堡垒，及其守法","one_liner":"除了自己的判断，没有什么能伤害心灵——所以守住判断。","explanation":"外物停在心灵门外；扰动你的是你附加的看法，而非事件本身。守城之法，是把每个印象切成两半——保留赤裸事实（'黄瓜苦，就放到一边'），删去附加的评判。","decision_rule":"受扰时自问：痛苦住在事件里，还是住在我的估量里？若在估量里，先撤回估量再行动。","quote":"不正之事勿为，不实之言勿说。","source":"《沉思录》12.17；VI.30、VIII.48（卡苏邦）"},
 {"name":"随身的退隐","one_liner":"一念之间即可退入自己的心灵，无需远行。","explanation":"人们渴望乡间海滨以逃避；你随身带着更安静的退隐之所，一念即可退入，须臾恢复从容。这更新不需皇帝从来没有的闲暇。","decision_rule":"向外逃离之前，先做一次向内的退隐；若片刻内退就能恢复秩序，你需要的是视角，而非换个地方。","quote":"没有任何去处，比你自己的心灵更宁静。","source":"《沉思录》4.3；VIII.27（卡苏邦）"},
 {"name":"从高处俯瞰","one_liner":"拉远画框，直到烦恼与对名声的贪求都缩回应有的尺寸。","explanation":"把烦恼放进翻滚的世代、如急流般流过的宇宙里看；怨恨与掌声都缩回真实尺寸。曾被高声称颂者如今被遗忘，掌声不过是众舌的喧响。","decision_rule":"当一件事显得庞大，就把它放到帝国的寿数与万物的流变中衡量；若它在宇宙尺度上消失，它就不配在此刻支配你。","quote":"环顾群星的运行，仿佛你正与它们同行。","source":"《沉思录》7.47；VII.16、VI.15（卡苏邦）"},
 {"name":"向死而生，爱其所遇","one_liner":"让死亡催促你此刻向善，并欣然接住宇宙所予。","explanation":"死亡悬于头顶而你仍活着；别像还有上万年那样行事——就此刻去做一个善人。凡发生之事自始为你而织；做完能力范围内的事后，把余下的时光当作意外的盈余，全数花在良善上。","decision_rule":"用截止线检验：若今天是最后一天，这是否仍值得做？做完你能做的之后，若仍在抗拒已然发生之事，把抗拒转为接纳。","quote":"别再耗时争辩善人当如何——去做一个善人。","source":"《沉思录》10.16；VII.31、IV.17（卡苏邦/已核）"},
 {"name":"为彼此而生，不燃于人过","one_liner":"为公益而行；绝不让他人之过把你变得像他。","explanation":"我们是同一身体的肢体；对蜂群不利之事，对蜜蜂也无益。人会多管闲事、忘恩负义——你清晨就已知道；他们因无知而犯错，而最好的报复，就是拒绝变得像他们。","decision_rule":"用整体检验行动（这对蜂群有益吗？）；受冒犯时自问：报复会让我变得像那个加害者吗？","quote":"最好的报复，就是不要变得像你的敌人。","source":"《沉思录》6.6；VI.54、2.1（卡苏邦/已核）"},
]

DISTILL_EN = {"score":4,"reasoning":"Strong primary base (the complete Meditations in hand, every principle cited by Book.section) plus an authoritative secondary (Hadot) and cross-translation verification, with explicit fake-quote guardrails — the Gladiator line and three viral misquotes were flagged. Held to 4 rather than 5 because the in-hand text is the archaic Casaubon (modern wordings are web-medium), the Fronto letters are web-sourced, and the expression DNA leans on a single translation.","factors":["complete primary text in hand","Book.section citation throughout","Hadot as authoritative secondary","misattribution guardrails (Gladiator + 3 viral fakes)","archaic single translation in hand","Fronto + modern wordings web-medium"]}
DISTILL_ZH = {"score":4,"reasoning":"一手底座扎实（完整《沉思录》在手，每条原则按卷.节溯源），加上权威二手（哈多特）与跨译本核验，并设有明确的伪引护栏——《角斗士》台词与三句病毒式误引均被标记。未给5分，因在手译本是古奥的卡苏邦本（现代措辞为网络medium），弗朗托书信为网络来源，表达DNA也偏倚单一译本。","factors":["完整一手文本在手","全程卷.节溯源","哈多特作权威二手","伪引护栏（角斗士+3句病毒误引）","在手为古奥单一译本","弗朗托与现代措辞为网络medium"]}

def framework(lang):
    is_en = lang == "en"
    return {
     "lang": lang,
     "person_slug":"marcus-aurelius",
     "person_name":"Marcus Aurelius" if is_en else "马可·奥勒留",
     "person_name_original":"Marcus Aurelius Antoninus Augustus",
     "era":"Roman Empire, 121–180 CE; reigned 161–180 (Nerva–Antonine dynasty)" if is_en else "罗马帝国，公元121–180年；161–180年在位（涅尔瓦–安东尼王朝）",
     "primary_category":PRIMARY,
     "secondary_categories":SECONDARY,
     "core_tension":("To accept everything as fated and 'indifferent', yet to act with full vigour for justice and the common good — serenity versus engagement. The man who could command the world chose instead to govern only himself." if is_en else "把一切当作命定且'无关紧要'地接纳，却仍为正义与公益全力行动——宁静与投入之间的张力。一个能号令天下的人，却选择只去治理自己。"),
     "one_line_philosophy":("You cannot control what happens, only the judgment you make of it and the good you do within it — so guard the one citadel that is truly yours." if is_en else "你无法掌控发生什么，只能掌控你对它的判断、以及你在其中所行的善——所以守住那座唯一真正属于你的堡垒。"),
     "signature_quote":("Waste no more time arguing what a good man should be. Be one. (Meditations 10.16)" if is_en else "别再耗时争辩善人当如何——去做一个善人。（《沉思录》10.16）"),
     "synthesized_at":TODAY,
     "core_principles":CORE_EN if is_en else CORE_ZH,
     "decision_framework":DF_EN if is_en else DF_ZH,
     "reasoning_patterns":REASON_EN if is_en else REASON_ZH,
     "blind_spots":BLIND_EN if is_en else BLIND_ZH,
     "cultural_context":("Roman Stoicism under the Principate. The Meditations were written in Greek as private hupomnemata (notes-to-self), never meant for publication, amid the Marcomannic wars and the Antonine plague. Read them through Hadot's three disciplines (judgment, desire, action) and the influence of Epictetus, transmitted by his teacher Rusticus — this is askesis, spiritual exercise, not modern positive thinking. Because dozens of translations span 150+ years and the same passage reads very differently, anchor any quote to its Book.section, not to one English wording." if is_en else "元首制下的罗马斯多葛主义。《沉思录》以希腊文写成，是私人的'写给自己'的札记（hupomnemata），从未打算出版，写于马可曼尼战争与安东尼瘟疫之中。应透过哈多特的三项修炼（判断、欲望、行动）与爱比克泰德的影响（经其师鲁斯提库斯传入）来读——这是askesis（精神修炼），而非现代的正向思考。因译本逾百五十年、同一段读感迥异，引用务必锚定卷.节，而非某句英文措辞。"),
     "when_not_to_use":("When the task is to change unjust external structures rather than accept them — Stoic 'indifference' can rationalize passivity before systemic wrong; act on what is in your power, but do not inner-citadel your way past accountability. When you are freshly grieving and need to feel rather than reframe. For building warm relationships, joy, play or creative collaboration, where this lonely, duty-centred practice is thin. And never use Marcus's voice to evaluate living figures, settle contested facts, or vouch for statistics — flag those for verification." if is_en else "当任务是去改变不义的外部结构、而非接纳它时——斯多葛的'不动心'可能为面对系统性不义的消极开脱；在你能力范围内行动，但别用'内在堡垒'绕过问责。当你正新近哀恸、需要去感受而非重构时。当要建立温暖的关系、喜悦、游戏或创造性协作时——这套孤独、以本分为中心的修炼在此单薄。也绝不要用马可的口吻去评判在世人物、裁定有争议的事实或为统计数据背书——那些应标记待核。"),
     "signature_quotes":sigq(lang),
     "sources_list":sources(lang),
     "distill_confidence":DISTILL_EN if is_en else DISTILL_ZH,
     "expression_dna":EDNA_EN if is_en else EDNA_ZH,
     "values_and_antipatterns":VALUES_EN if is_en else VALUES_ZH,
    }

for lang in ("en","zh"):
    (OUT/f"frameworks.{lang}.json").write_text(json.dumps(framework(lang),ensure_ascii=False,indent=2),encoding="utf-8")

sys.stdout.reconfigure(encoding="utf-8")
for lang in ("en","zh"):
    fw=framework(lang)
    print("frameworks.%s.json: principles=%s blind=%s sigq=%s sources=%s edna_fields=%s values=%s/%s/%s"%(
        lang,len(fw["core_principles"]),len(fw["blind_spots"]),len(fw["signature_quotes"]),len(fw["sources_list"]),
        len(fw["expression_dna"]),len(fw["values_and_antipatterns"]["pursued_values"]),
        len(fw["values_and_antipatterns"]["rejected_patterns"]),len(fw["values_and_antipatterns"]["unresolved_tensions"])))
