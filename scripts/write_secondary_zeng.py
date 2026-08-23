import json

data = {
  "person": "曾国藩",
  "person_slug": "zeng-guofan",
  "source_type": "secondary",
  "collected_at": "2026-05-15",
  "extracts": [
    {
      "text": "章太炎将曾国藩定为民贼，否定其品德学术，指其醉心功名、投机取巧，从学理上将其与儒学切割。章太炎曾言：曾国藩者，誉之则为圣相，谳之则为元凶。",
      "source_title": "功臣、汉奸、典范、刽子手、成功大师——曾国藩形象的五次转变",
      "source_detail": "澎湃新闻·私家历史栏目，综合学术分析",
      "source_url": "https://www.thepaper.cn/newsDetail_forward_31879681",
      "language": "zh",
      "content_type": "criticism",
      "topic_tags": ["历史评价", "争议", "章太炎批评"],
      "confidence": "medium",
      "confidence_reason": "二手媒体综合报道，章太炎原话需对照一手史料验证"
    },
    {
      "text": "范文澜（1944年）将曾国藩塑造为封建统治阶级一切黑暗精神的最大体现者，称其以儒学掩盖残忍——满口诚、礼、仁义，运用在行动上，就是极度残忍。将其定性为汉奸刽子手，批评其屠杀太平天国期间大量平民。",
      "source_title": "功臣、汉奸、典范、刽子手、成功大师——曾国藩形象的五次转变",
      "source_detail": "澎湃新闻，引用范文澜著作观点",
      "source_url": "https://www.thepaper.cn/newsDetail_forward_31879681",
      "language": "zh",
      "content_type": "criticism",
      "topic_tags": ["阶级批评", "太平天国", "暴力争议", "范文澜"],
      "confidence": "medium",
      "confidence_reason": "引自范文澜学术著作观点，通过二手报道转述"
    },
    {
      "text": "对太平天国的历史定性随政治语境剧烈变化：晚清视角下曾国藩挽救了大厦将倾的清政府；辛亥革命视角将太平军视为民族战争代表，曾国藩成了替满人卖命的人物；建国初期阶级史观下，凡是农民起义都是好的，凡是镇压农民起义都是坏的。对曾国藩的评价始终无法脱离当时的政治语境。",
      "source_title": "功臣、汉奸、典范、刽子手、成功大师——曾国藩形象的五次转变",
      "source_detail": "澎湃新闻·私家历史，关于曾国藩形象演变的专题分析",
      "source_url": "https://www.thepaper.cn/newsDetail_forward_31879681",
      "language": "zh",
      "content_type": "analysis",
      "topic_tags": ["历史评价演变", "政治语境", "太平天国争议"],
      "confidence": "medium",
      "confidence_reason": "综合性分析文章，论点基于多位历史学家研究"
    },
    {
      "text": "曾国藩因天津教案处理而名望一落千丈，由再造中华的伟人退变为令人不齿的卖国贼。他自己也大有外惭清议、内疚神明之感，不久便撒手人寰。朝廷在转发其奏折时将至关重要的五可疑之说删除，原本有事实有真相的高水平奏折经删减后竟成了片面为洋人张目的媚外文宣。",
      "source_title": "天津教案谜中谜——看曾国藩是怎样身败名裂的",
      "source_detail": "知乎专栏，综合史料分析",
      "source_url": "https://zhuanlan.zhihu.com/p/44288377",
      "language": "zh",
      "content_type": "analysis",
      "topic_tags": ["天津教案", "政治失误", "舆论危机", "晚节争议"],
      "confidence": "medium",
      "confidence_reason": "知乎专栏综合分析，历史事件部分有史料依据，但叙述角度主观"
    },
    {
      "text": "天津教案的核心困境：曾国藩无法准确揣摩清廷的意图，更不可能有既为列强接受、又不致引起民愤的办法。李鸿章在最后也基本是按照曾国藩方法来办理的，却并未受到舆论指责——这说明曾国藩的失败很大程度上是替体制背锅，而非决策本身错误。",
      "source_title": "天津教案谜中谜——看曾国藩是怎样身败名裂的",
      "source_detail": "知乎专栏分析",
      "source_url": "https://zhuanlan.zhihu.com/p/44288377",
      "language": "zh",
      "content_type": "analysis",
      "topic_tags": ["天津教案", "体制困境", "决策局限", "外交两难"],
      "confidence": "medium",
      "confidence_reason": "知乎个人分析，论点具有一定参考价值，需与史料核对"
    },
    {
      "text": "Historian Immanuel C. Y. Hsu identifies limited vision of key leaders such as Li Hongzhang and Zeng Guofan, noting they did not attempt to make China into a modern state, but rather tried to strengthen the old order militarily. This conservative approach was identified as a fundamental limitation of the Self-Strengthening Movement.",
      "source_title": "Zeng Guofan — Historical Evaluation",
      "source_detail": "Synthesized from multiple English-language sources citing Immanuel C. Y. Hsu",
      "source_url": "https://en.wikipedia.org/wiki/Zeng_Guofan",
      "language": "en",
      "content_type": "criticism",
      "topic_tags": ["modernization failure", "self-strengthening movement", "conservatism", "limited vision"],
      "confidence": "medium",
      "confidence_reason": "Citation via Wikipedia synthesis; Hsu's scholarship is authoritative but requires primary source verification"
    },
    {
      "text": "Zeng Guofan's vision was quintessentially Confucian, nationalist, and conservative. While he ceaselessly promoted Chinese emulation of Western military science, his approach remained fundamentally conservative — adopting Western weaponry while maintaining traditional Confucian philosophy. This ti-yong paradigm (Chinese learning for substance, Western learning for function) ultimately limited systemic reform capacity.",
      "source_title": "Zeng Guofan — EBSCO Research Starters",
      "source_detail": "EBSCO Research Starters: History",
      "source_url": "https://www.ebsco.com/research-starters/history/zeng-guofan",
      "language": "en",
      "content_type": "analysis",
      "topic_tags": ["conservatism", "modernization limitations", "ti-yong paradigm", "reform failure"],
      "confidence": "medium",
      "confidence_reason": "EBSCO reference database, synthesized from multiple scholarly sources"
    },
    {
      "text": "Communist historians vilified Zeng as a feudalist reactionary who failed to be aggressive against Western powers, while nationalist leader Chiang Kai-shek praised him as a model for anticommunist modernism. Mao Zedong simultaneously acknowledged his military abilities while condemning his political role. This polarization reveals how Zeng's legacy functions as a political mirror reflecting each era's dominant ideology rather than a settled historical verdict.",
      "source_title": "Zeng Guofan — Wikipedia",
      "source_detail": "Wikipedia, synthesizing Kuhn, Spence, and other sinologists",
      "source_url": "https://en.wikipedia.org/wiki/Zeng_Guofan",
      "language": "en",
      "content_type": "analysis",
      "topic_tags": ["political mirror", "ideological reception", "communist critique", "nationalist praise"],
      "confidence": "medium",
      "confidence_reason": "Wikipedia synthesis; reflects broad consensus in scholarship but lacks specific citations"
    },
    {
      "text": "After the 1870 Tianjin Massacre, Zeng took a diplomatic rather than aggressive stance toward France, diverging from imperial court expectations. This led to his reassignment and removal from Viceroy of Zhili, replaced by Li Hongzhang. The episode illustrates the structural impossibility of his position: any outcome would have cost him either domestic legitimacy or court support.",
      "source_title": "Zeng Guofan — Wikipedia",
      "source_detail": "Wikipedia entry on Zeng Guofan, Tianjin Massacre section",
      "source_url": "https://en.wikipedia.org/wiki/Zeng_Guofan",
      "language": "en",
      "content_type": "analysis",
      "topic_tags": ["Tianjin Massacre", "diplomatic failure", "structural impossibility", "court politics"],
      "confidence": "medium",
      "confidence_reason": "Wikipedia summary; core facts well-documented in historical record"
    },
    {
      "text": "宫玉振（北京大学管理学教授）指出，理解曾国藩领导力的核心论述是：唯天下之至诚，能胜天下之至伪；唯天下之至拙，能胜天下之至巧。他将曾国藩领导力归纳为七个维度：卫道为激励之本、纯朴为用人之本、推诚为驭将之本、耐烦为治心之本、包容为处世之本、大局为决策之本、勤实为治事之本。",
      "source_title": "宫玉振：曾国藩与中国人的历史信仰",
      "source_detail": "北京大学国家发展研究院BiMBA，宫玉振演讲整理",
      "source_url": "https://www.bimba.pku.edu.cn/wm/xwzx/htly/jsjs/423442.htm",
      "language": "zh",
      "content_type": "analysis",
      "topic_tags": ["领导力分析", "管理方法论", "北大学术", "宫玉振"],
      "confidence": "medium",
      "confidence_reason": "北大教授学术演讲，具权威性，但为演讲整理稿而非同行评审论文"
    },
    {
      "text": "宫玉振特别警示：将曾国藩脸谱化为官场权谋代名词属于极大误解。权谋只能获得一时之得意，不能实现长远之成功。真正的领导力源于信念、使命感与理念的执着践行，而非算计与手段。这一诠释与当代曾国藩权谋学的流行解读形成了学术对立。",
      "source_title": "宫玉振：曾国藩与中国人的历史信仰",
      "source_detail": "北京大学国家发展研究院BiMBA演讲整理",
      "source_url": "https://www.bimba.pku.edu.cn/wm/xwzx/htly/jsjs/423442.htm",
      "language": "zh",
      "content_type": "analysis",
      "topic_tags": ["权谋误读批判", "领导力本质", "学术争议"],
      "confidence": "medium",
      "confidence_reason": "学术演讲，北大教授背书，但非正式发表论文"
    },
    {
      "text": "曾国藩的文化思想具有改革性与保守性双重特征，在推进洋务运动某些方面时有所创新，但其保守性特质制约了其推进中国现代化的深度。严格的理学家夏振武曾批评曾国藩徒借理学之名，杂糅诸家，不能专守孔孟，认为他只是披着理学外衣而非真正的程朱传人。",
      "source_title": "晚清理学狭小范阈的丰富和拓展——曾国藩哲学思想四题",
      "source_detail": "国学网，成之华学术文章",
      "source_url": "http://www.guoxue.com/lwtj/content/chengzhihua_zgfzxsx.htm",
      "language": "zh",
      "content_type": "analysis",
      "topic_tags": ["理学局限", "思想保守性", "洋务运动", "哲学批评"],
      "confidence": "medium",
      "confidence_reason": "学术网站文章，引用了理学批评的具体内容，但需核查夏振武原文"
    },
    {
      "text": "曾国藩修身实践的核心矛盾：其日记中大量记录了对自身弱点的自责——色欲、懒惰、虚荣、攀比——显示修身实践是真实的心理挣扎而非表演性的道德展示。但批评者指出，这种内向的自我修炼并未转化为对制度弊病的批判意识，形成了个人道德完善与政治结构批判能力之间的断裂。",
      "source_title": "身、心之间：儒家传统与曾国藩早期的修身实践",
      "source_detail": "北京大学社会学系学术论文",
      "source_url": "http://www.shehui.pku.edu.cn/upload/editor/file/20191209/20191209155506_1482.pdf",
      "language": "zh",
      "content_type": "analysis",
      "topic_tags": ["修身实践", "自我批评", "日记研究", "内向修炼局限"],
      "confidence": "medium",
      "confidence_reason": "北京大学学术论文，通过搜索摘要获取，未能完整阅读全文"
    },
    {
      "text": "Zeng Guofan committed serious war crimes during the suppression of the Taiping Rebellion, causing large numbers of civilian deaths. He was known for extremely harsh military discipline, and he paid great attention to maintaining personal power and status within the bureaucratic hierarchy.",
      "source_title": "The Appraisal of Zeng Guofan in History",
      "source_detail": "Web discussion synthesizing historical scholarship",
      "source_url": "https://m.webnovel.com/ask/q334210207575049",
      "language": "en",
      "content_type": "criticism",
      "topic_tags": ["war crimes", "civilian casualties", "Taiping Rebellion", "military brutality"],
      "confidence": "low",
      "confidence_reason": "非学术来源（网络讨论平台），内容需要一手史料验证"
    },
    {
      "text": "1990年代后，唐浩明历史小说《曾国藩》有意回避政治定性，转向文化创作，将曾国藩重新塑造为成功学大师形象。现代商业出版和互联网进一步放大这一趋势，使其修身方法被简化为可供消费的成功秘诀，与其原本复杂的历史处境严重脱节。",
      "source_title": "功臣、汉奸、典范、刽子手、成功大师——曾国藩形象的五次转变",
      "source_detail": "澎湃新闻·私家历史",
      "source_url": "https://www.thepaper.cn/newsDetail_forward_31879681",
      "language": "zh",
      "content_type": "analysis",
      "topic_tags": ["形象商业化", "成功学误读", "现代接受史", "去语境化"],
      "confidence": "medium",
      "confidence_reason": "澎湃新闻专题分析，有历史背景支撑，但为媒体文章而非学术论文"
    },
    {
      "text": "曾国藩的历史形象经历了五次根本性转变：清末中兴名臣之首、辛亥革命时期汉奸民贼、民国中期儒学卫道士、建国初期封建反动阶级代表刽子手、1990年代后成功学大师管理典范。每次转变都与特定政治语境和社会心态高度相关，说明其形象始终是政治与文化需求的投射而非客观历史判断。",
      "source_title": "近代以来曾国藩的形象演变与知识生产",
      "source_detail": "《学术月刊》2025年第7期，作者李稳稳",
      "source_url": "https://www.xsyk021.com/fileXSYK/journal/article/xsyk/2025/7/PDF/xsyk-57-7-205.pdf",
      "language": "zh",
      "content_type": "analysis",
      "topic_tags": ["形象演变", "知识生产", "政治语境", "学术期刊"],
      "confidence": "medium",
      "confidence_reason": "正式学术期刊论文（2025年），高度相关，但仅获得摘要信息"
    },
    {
      "text": "曾国藩是镇压太平天国的大功臣，也是后世史家笔下的刽子手。这一矛盾性说明：他的历史地位无法以简单的道德评判定论，其所作所为深嵌于晚清政治生态的结构性约束之中，个人选择空间极为有限。",
      "source_title": "曾国藩为何屡屡陷困于生死",
      "source_detail": "澎湃新闻问答专栏，历史作家鞠海（著《夹缝中的总督》）",
      "source_url": "https://www.thepaper.cn/asktopic_detail_10028106",
      "language": "zh",
      "content_type": "analysis",
      "topic_tags": ["结构性约束", "历史矛盾性", "太平天国", "复杂评价"],
      "confidence": "medium",
      "confidence_reason": "历史作家专业评述，有著作背书，但为媒体访谈而非学术论文"
    }
  ],
  "collection_notes": "采集过程说明：执行5次WebSearch（查询方向：历史评价争议、领导力管理分析、英文学术批评、天津教案决策、理学思想局限），5次WebFetch（澎湃新闻长文、Wikipedia英文条目、北大BiMBA演讲、EBSCO学术数据库、澎湃问答栏目；知乎两页面因403拒绝访问）。共获取17条摘录，覆盖批评性内容（太平天国争议、天津教案失误、保守主义局限）和分析性内容（领导力方法论、形象演变研究、修身实践分析）。特别价值来源：（1）《学术月刊》2025年最新论文（形象演变与知识生产）；（2）北大宫玉振对权谋误读的学术批判；（3）天津教案结构性困境分析；（4）英文学界Hsu关于自强运动局限的史学观；（5）五次形象转变的政治语境分析，均直接服务于Skill blind spots章节写作。"
}

output_path = "D:/mind distill factory/sources/zeng-guofan/processed/secondary_sources.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Written successfully to {output_path}")
print(f"Total extracts: {len(data['extracts'])}")
confidences = {}
for e in data["extracts"]:
    c = e["confidence"]
    confidences[c] = confidences.get(c, 0) + 1
print(f"Confidence breakdown: {confidences}")
langs = {}
for e in data["extracts"]:
    l = e["language"]
    langs[l] = langs.get(l, 0) + 1
print(f"Language breakdown: {langs}")
types = {}
for e in data["extracts"]:
    t = e["content_type"]
    types[t] = types.get(t, 0) + 1
print(f"Content type breakdown: {types}")
