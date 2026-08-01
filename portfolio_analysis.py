"""
================================================================================
 组合持仓分析引擎 — Part 1: 基础架构 + PortfolioReviewEngine
================================================================================

 集成方法论:
   - AI Berkshire 技能栈: portfolio-review, income-investment, thesis-tracker,
     investment-checklist, quality-screen, news-pulse, earnings-review
   - 五阶深度逻辑引擎: SOTP 分步重估、隐含预期解码、期权价值识别、
     博弈论对冲分析、时间墙与终值回归

 模块说明:
   1. 精确十进制引擎 — 避免浮点误差
   2. 四大师评分框架 — 巴菲特/芒格/段永平/李录 (增强版)
   3. PortfolioReviewEngine — 组合级深度审查引擎
       • concentration_analysis   — 集中度分析 (Top3/5, 持仓总数, 现金比例)
       • correlation_check       — 持仓间隐含风险共振检测
       • opportunity_cost_ranking— 机会成本排序 (巴菲特机会成本框架)
       • stress_testing          — 四情景压力测试
       • rebalancing_suggestions — 综合再平衡建议

 数据源:
   - PortfolioManager.get_holdings_table() → List[Dict]
   - PortfolioManager.get_summary_dict()  → Dict

 依赖:
   - 标准库: json, math, logging, datetime, decimal, typing
   - 无外部依赖

 作者: AI Berkshire Analyst
 日期: 2026-08-01
================================================================================
"""

# ====================================================================
# 导入
# ====================================================================
import json
import math
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal, Context, ROUND_HALF_EVEN, InvalidOperation, DivisionByZero
from typing import List, Dict, Optional, Tuple, Any, Union

logger = logging.getLogger(__name__)

# ====================================================================
# 精确十进制引擎
# ====================================================================
_CTX = Context(prec=28, rounding=ROUND_HALF_EVEN)


def _exact(value: Any) -> Decimal:
    """
    将任意数值安全转换为 Decimal，避免浮点二进制表示误差。
    支持 int / float / str / Decimal / 其他可转为 str 的类型。
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        # float → str 转换保证精度，避免 0.1+0.2 类问题
        return Decimal(str(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            logger.warning(f"_exact: 无法解析字符串 '{value}'，返回 0")
            return Decimal("0")
    # 兜底：尝试 str()
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        logger.warning(f"_exact: 无法转换类型 {type(value).__name__}，返回 0")
        return Decimal("0")


def _exact_div(a: Any, b: Any, default: Decimal = Decimal("0")) -> Decimal:
    """
    安全除法，避免 DivisionByZero。
    返回 Decimal，精度由 _CTX 控制。
    """
    da = _exact(a)
    db = _exact(b)
    if db == Decimal("0"):
        return default
    return _CTX.divide(da, db)


def _exact_pct(value: Any, total: Any) -> Decimal:
    """
    计算百分比: value / total * 100
    如果 total 为 0 返回 0。
    """
    return _exact_div(value, total) * Decimal("100")


# ====================================================================
# 增强型四大师评分框架
# ====================================================================

# ------------------------------------------------------------------
# 1. 巴菲特 — 护城河 + 财务质量 + 合理估值
# ------------------------------------------------------------------
def buffett_score(holding: dict, summary: dict) -> dict:
    """
    巴菲特视角评分：护城河、财务质量、安全边际、集中度。
    增强版：扩展了 moat_indicators 字典，覆盖更多细分行业。

    返回:
        {
            "score": float,      # 总分 (范围 ~1.0 ~ 5.0)
            "details": list,     # 评分理由
            "color": str,        # "positive" / "neutral" / "negative"
        }
    """
    s = {"score": 3.0, "details": [], "color": "neutral"}
    pnl_pct = holding.get("pnl_pct", 0)
    weight = holding.get("weight", 0)
    sector = holding.get("sector", "")
    market = holding.get("market", "")
    name = holding.get("name", "")
    ann_ret = holding.get("annualized_return", 0)
    ticker = holding.get("ticker", "")

    # ---- 护城河评估（基于行业 + 持仓特征） ----
    # 扩展版：每个条目包含 [护城河类型, 详细说明, 评分修正]
    moat_indicators = {
        # ---- 金融 ----
        "银行/金融": "品牌+规模双护城河 | 招商银行零售银行护城河深厚，低成本存款+高粘性客户构成核心壁垒；但金融行业天然高杠杆，需关注不良率趋势",
        "保险": "品牌+渠道护城河 | 保险行业转换成本高，龙头公司代理人体系和品牌信任度构成持续竞争优势",
        "券商/投行": "牌照+客户粘性护城河 | 头部券商在投行、资管和财富管理领域具有规模效应和品牌溢价",

        # ---- 消费 ----
        "消费/白酒": "品牌护城河极强 | 白酒行业尤其是高端品牌(茅台/五粮液)具有定价权、低资本开支、高复购率，是中国最好的商业模式之一",
        "消费/食品饮料": "品牌+渠道护城河 | 消费品龙头通过品牌心智占有和渠道深度分销构建竞争壁垒",
        "消费/家电": "规模+品牌护城河 | 家电龙头通过规模效应和品牌认知形成成本优势，但行业增速放缓",
        "消费/汽车": "品牌+技术转型护城河 | 新能源车时代品牌格局重塑，传统车企护城河面临挑战，新势力需持续投入建立技术壁垒",

        # ---- 医药 ----
        "制药": "专利+研发护城河 | GLP-1赛道(礼来/诺和诺德)技术壁垒极高，但专利悬崖和集采是长期风险；创新药研发投入大、周期长、失败率高",
        "医药/器械": "技术+渠道护城河 | 医疗器械龙头通过技术迭代和医院渠道粘性构建壁垒，国产替代空间大",
        "医药/生物科技": "研发护城河 | 生物科技公司依赖核心管线，单个产品失败可能导致公司价值大幅缩水，护城河不确定性高",

        # ---- 科技 ----
        "半导体": "技术+资本密集双护城河 | HBM高带宽内存技术壁垒极高，三星/SK海力士领先；但存储芯片周期性极强，产能过剩时价格暴跌",
        "半导体/设备": "技术护城河极深 | 半导体设备行业技术门槛极高，ASML光刻机几乎不可替代，但受地缘政治影响大",
        "互联网科技": "生态+网络效应护城河 | 腾讯/阿里等巨头护城河深厚；但小米本质是硬件制造+互联网服务，护城河弱于纯互联网平台",
        "软件/SaaS": "转换成本护城河 | 企业级软件客户粘性高，替换成本大，但竞争格局变化快",
        "网络安全": "转换成本+技术护城河 | Okta在身份管理领域有先发优势和网络效应，客户部署后替换成本极高；但竞争加剧可能挤压利润率",
        "云计算": "规模+基础设施护城河 | 云服务商通过规模效应和基础设施投入构建壁垒，AWS/Azure/Google Cloud三强格局稳定",

        # ---- 工业 ----
        "工业/数据中心": "技术+客户粘性护城河 | Vertiv在电力热管理基础设施领域全球领先，AI算力爆发带来确定性强增长；但需关注技术路线变化风险",
        "工业/制造": "技术+规模护城河 | 高端制造龙头通过技术积累和客户认证构建壁垒，但周期性明显",
        "工业/军工": "技术+政策护城河 | 军工行业技术壁垒高、客户关系稳定，但受政策周期影响大",
        "造纸": "成本+规模护城河 | 太阳纸业在造纸行业有成本优势，林浆纸一体化降低波动；但行业需求增速低、周期性明显",

        # ---- ETF ----
        "ETF/全球指数": "被动指数投资，不适用个股护城河概念；但分散化本身就是一种保护，VT覆盖全球50+国家",
        "ETF/道指": "被动指数，护城河概念不适用；道指成分股均为美国蓝筹龙头，整体质量高",
        "ETF/港股科技": "被动指数，护城河概念不适用；底层持仓为港股科技龙头，整体护城河中上",
        "ETF/通信": "被动指数，护城河概念不适用；通信ETF覆盖5G/AI算力产业链，底层标的各有护城河",
        "ETF/科创板": "被动指数，护城河概念不适用；科创板公司多为成长早期，护城河尚未稳固",
        "ETF/半导体": "被动指数，护城河概念不适用；底层为半导体产业链龙头，整体壁垒较高",

        # ---- 其他 ----
        "另类投资": "非传统资产，护城河不清晰；VCX类产品透明度低，不适合用护城河框架评估",
        "房地产/REITs": "资产+管理护城河 | 优质地段物业和资产管理能力构成REITs核心护城河",
        "公用事业": "政策+基础设施护城河 | 公用事业具有自然垄断属性，现金流稳定但增长有限",
        "教育": "品牌+规模护城河 | 教育龙头通过品牌认知和教学网络构建壁垒，但政策风险需关注",
    }

    # 模糊匹配：如果 sector 不完全匹配，尝试部分匹配
    moat = moat_indicators.get(sector, "")
    if not moat:
        for key, desc in moat_indicators.items():
            if key in sector or sector in key:
                moat = desc
                break
    if not moat:
        moat = f"行业 '{sector}' 护城河待评估，需进一步研究"

    s["details"].append(f"【护城河】{moat}")

    # ---- 财务质量（基于盈亏状况） ----
    if pnl_pct >= -5:
        s["score"] += 0.5
        s["details"].append(f"【财务质量】盈亏接近平衡 (pnl={pnl_pct:.1f}%)，基本面尚可")
    elif pnl_pct >= -15:
        s["score"] += 0.0
        s["details"].append(f"【财务质量】亏损 {pnl_pct:.1f}%，需关注基本面变化，区分是暂时性还是结构性")
    elif pnl_pct >= -30:
        s["score"] -= 0.3
        s["details"].append(f"【财务质量】亏损 {pnl_pct:.1f}%，中度套牢，需审视持仓逻辑是否成立")
    else:
        s["score"] -= 0.5
        s["details"].append(f"【财务质量】深度亏损 {pnl_pct:.1f}%，巴菲特：'当一家好公司遇到暂时性困难时，是买入机会而非卖出'")

    # ---- 安全边际（巴菲特核心概念） ----
    if pnl_pct <= -30:
        s["score"] += 0.8  # 越跌安全边际越大（如果逻辑没变）
        s["details"].append(f"【安全边际】价格已大幅低于成本 ({pnl_pct:.1f}%)，若核心逻辑未变则安全边际极大，甚至是加仓机会")
    elif pnl_pct <= -15:
        s["score"] += 0.5
        s["details"].append(f"【安全边际】价格低于成本 ({pnl_pct:.1f}%)，安全边际存在，但需确认逻辑未变")
    elif pnl_pct <= -5:
        s["score"] += 0.2
        s["details"].append(f"【安全边际】小幅亏损，安全边际尚可")
    elif pnl_pct >= 30:
        s["score"] -= 0.5
        s["details"].append(f"【安全边际】已大幅盈利 {pnl_pct:.1f}%，安全边际已大幅缩小，需考虑是否高估")
    elif pnl_pct >= 15:
        s["score"] -= 0.3
        s["details"].append(f"【安全边际】盈利 {pnl_pct:.1f}%，安全边际缩小")

    # ---- 集中度（巴菲特：适度集中但需深度理解） ----
    if weight >= 40:
        s["score"] -= 0.8
        s["details"].append(f"【集中度】仓位 {weight:.1f}% 极高，巴菲特前三大持仓通常占 60-70% 但需极深的理解")
    elif weight >= 30:
        s["score"] -= 0.5
        s["details"].append(f"【集中度】仓位 {weight:.1f}% 偏高，巴菲特认为集中投资需要比分散投资更深的了解")
    elif weight >= 20:
        s["score"] -= 0.2
        s["details"].append(f"【集中度】仓位 {weight:.1f}% 适中偏高")
    elif weight >= 10:
        s["details"].append(f"【集中度】仓位 {weight:.1f}% 合理")
    else:
        s["details"].append(f"【集中度】仓位 {weight:.1f}% 较轻")

    # ---- 年化收益率辅助判断 ----
    if ann_ret < -15 and holding.get("holding_days", 0) > 90:
        s["details"].append(f"【趋势警示】年化收益 {ann_ret:.1f}%，持续跑输，需重新评估投资逻辑")

    s["color"] = "positive" if s["score"] >= 3.5 else "neutral" if s["score"] >= 2.5 else "negative"
    return s


# ------------------------------------------------------------------
# 2. 芒格 — 逆向思考 + 避免愚蠢 + 认知偏误检查
# ------------------------------------------------------------------
def munger_score(holding: dict, summary: dict) -> dict:
    """
    芒格视角评分：逆向思考、认知偏误、失败场景分析。
    增强版：扩展 failure_scenarios，添加更多认知偏误检测。

    返回:
        {
            "score": float,
            "details": list,
            "color": str,
            "reverse_questions": list,   # 芒格式逆向追问
        }
    """
    s = {"score": 3.0, "details": [], "color": "neutral", "reverse_questions": []}
    pnl_pct = holding.get("pnl_pct", 0)
    day_chg = holding.get("day_change_pct", 0)
    sector = holding.get("sector", "")
    market = holding.get("market", "")
    name = holding.get("name", "")
    ann_ret = holding.get("annualized_return", 0)
    days = holding.get("holding_days", 0)
    weight = holding.get("weight", 0)
    ticker = holding.get("ticker", "")

    # ---- 逆向思考：什么情况下这个持仓会失败？ ----
    failure_scenarios = {
        # ---- 金融 ----
        "银行/金融": "① 息差持续收窄至净息差 < 1.5% | ② 不良率大幅上升 > 3% | ③ 经济深度衰退导致信贷违约潮 | ④ 互联网金融颠覆性冲击",
        "保险": "① 巨灾赔付超预期 | ② 利率持续下行拉低投资收益 | ③ 保费增长停滞 | ④ 偿付能力监管收紧",
        "券商/投行": "① 市场成交量持续萎缩 | ② IPO和再融资大幅减少 | ③ 佣金率持续下降 | ④ 自营投资重大亏损",

        # ---- 消费 ----
        "消费/白酒": "① 消费降级加速，高端白酒需求萎缩 | ② 年轻人酒精消费习惯改变，代际需求断层 | ③ 政策打压（如限制公务消费） | ④ 宏观经济长期低迷",
        "消费/食品饮料": "① 原材料成本持续上涨无法转嫁 | ② 消费者口味变化 | ③ 食品安全事件 | ④ 渠道变革落后",
        "消费/家电": "① 房地产长期低迷拖累需求 | ② 价格战加剧 | ③ 海外市场受阻 | ④ 技术迭代落后",
        "消费/汽车": "① 新能源车渗透率见顶，价格战持续 | ② 自动驾驶进展不及预期 | ③ 海外关税壁垒 | ④ 传统车企转型成功反攻",

        # ---- 医药 ----
        "制药": "① GLP-1药物安全性问题曝光（如甲状腺癌风险） | ② 竞争对手追赶（口服小分子GLP-1） | ③ 集采大幅降价 | ④ 核心专利到期",
        "医药/器械": "① 集采范围扩大至高端器械 | ② 国产替代竞争加剧 | ③ 研发管线失败 | ④ 医院回款周期延长",
        "医药/生物科技": "① 核心管线临床试验失败 | ② FDA/药监局审批态度转严 | ③ 融资环境恶化 | ④ 竞争对手先发",

        # ---- 科技 ----
        "半导体": "① HBM产能过剩，存储芯片进入下跌周期 | ② AI资本开支增速放缓 | ③ 地缘政治导致供应链断裂 | ④ 技术路线被颠覆（如新存储技术）",
        "半导体/设备": "① 中美科技脱钩进一步升级 | ② 出口管制加码 | ③ 客户集中度过高 | ④ 技术迭代速度放缓",
        "互联网科技": "① 电动车业务持续烧钱无法盈利（小米SU7竞争加剧） | ② 手机业务份额持续下滑 | ③ 核心业务被竞争对手侵蚀 | ④ 监管政策收紧",
        "软件/SaaS": "① 客户流失率上升 | ② 获客成本飙升 | ③ 宏观经济导致IT支出缩减 | ④ AI颠覆传统软件模式",
        "网络安全": "① 增长放缓至 < 15% | ② 竞争加剧导致利润率下降 | ③ 收购整合不及预期 | ④ 客户预算收缩",
        "云计算": "① 企业IT支出大幅缩减 | ② 竞争格局恶化（价格战） | ③ 监管要求数据本地化 | ④ 技术路线被颠覆",

        # ---- 工业 ----
        "工业/数据中心": "① AI资本开支不及预期，数据中心建设放缓 | ② 竞争对手侵蚀份额（如台达/施耐德） | ③ 技术路线变化（液冷替代风冷） | ④ 原材料成本大幅上升",
        "工业/制造": "① 全球经济衰退 | ② 制造业回流政策 | ③ 原材料价格波动 | ④ 技术替代风险",
        "工业/军工": "① 国防预算增长放缓 | ② 军品定价改革 | ③ 技术路线变化 | ④ 腐败调查",
        "造纸": "① 需求持续萎缩（无纸化加速） | ② 原材料成本大幅上升 | ③ 环保政策加码 | ④ 产能过剩价格战",

        # ---- ETF ----
        "ETF/全球指数": "① 全球系统性金融危机（如2008年重演） | ② 地缘政治分裂（冷战2.0） | ③ 全球贸易体系崩溃 | ④ 长期滞胀",
        "ETF/道指": "① 美国经济长期衰退 | ② 美元霸权衰落 | ③ 美国政治极化导致政策僵局 | ④ 美股估值泡沫破裂",
        "ETF/港股科技": "① 中美脱钩加剧，中概股退市风险 | ② 港股流动性持续枯竭 | ③ 中国互联网监管再度收紧 | ④ 中国经济长期低迷",
        "ETF/通信": "① AI算力需求不及预期 | ② 5G/6G投资回报率低 | ③ 通信设备国产替代不及预期 | ④ 行业竞争格局恶化",
        "ETF/科创板": "① 科创板流动性枯竭 | ② 政策支持转向 | ③ 上市企业质量参差不齐 | ④ 注册制改革后供给过剩",
        "ETF/半导体": "① 全球半导体周期下行 | ② 中美科技脱钩 | ③ 国产替代证伪 | ④ 产能过剩",

        # ---- 其他 ----
        "另类投资": "① 流动性危机无法退出 | ② 底层资产估值大幅缩水 | ③ 管理人道德风险 | ④ 监管政策变化",
        "房地产/REITs": "① 利率持续上升 | ② 商业地产需求萎缩 | ③ 租金下降 | ④ 物业空置率上升",
        "公用事业": "① 政策电价管制 | ② 燃料成本上升 | ③ 环保投资压力 | ④ 新能源替代冲击",
        "教育": "① 政策监管风险 | ② 出生率下降 | ③ 在线教育冲击 | ④ 师资流失",
    }

    fs = failure_scenarios.get(sector, f"行业 '{sector}' 失败场景待分析，建议从政策、竞争、技术三个维度思考")
    s["reverse_questions"].append(f"【逆向思考】什么情况下 {sector} ({name}) 会失败？→ {fs}")

    # ---- 芒格经典追问：如果已经亏损，是否被市场证伪？ ----
    if pnl_pct <= -40:
        s["reverse_questions"].append(f"【芒格追问】已亏损 {pnl_pct:.1f}%，这是否意味着你已经错了？芒格：'如果知道会死在哪里，就永远不要去那里'")
        s["score"] -= 1.5
    elif pnl_pct <= -30:
        s["reverse_questions"].append(f"【芒格追问】已亏损 {pnl_pct:.1f}%，是否已经被市场证伪？还是市场错了？")
        s["score"] -= 1.0
    elif pnl_pct <= -15:
        s["reverse_questions"].append(f"【芒格追问】亏损 {pnl_pct:.1f}%，是暂时的（市场先生情绪）还是永久性的（基本面变化）？")
        s["score"] -= 0.5
    elif pnl_pct <= -5:
        s["reverse_questions"].append(f"【芒格追问】小幅亏损 {pnl_pct:.1f}%，芒格：'波动不是风险，永久性损失才是'")

    # ---- 反共识检查 ----
    if day_chg >= 8:
        s["reverse_questions"].append(f"【反共识】单日大涨 {day_chg:.1f}%，聪明人是否在卖出？芒格：'反过来想，总是反过来想'")
        s["score"] -= 0.3
    elif day_chg >= 5:
        s["reverse_questions"].append(f"【反共识】单日大涨 {day_chg:.1f}%，检查是否有非理性繁荣")
        s["score"] -= 0.2
    elif day_chg <= -8:
        s["reverse_questions"].append(f"【反共识】单日大跌 {abs(day_chg):.1f}%，是错杀还是逻辑变化？芒格：'不要因为股价波动而恐慌'")
        s["score"] -= 0.3
    elif day_chg <= -5:
        s["reverse_questions"].append(f"【反共识】单日大跌 {abs(day_chg):.1f}%，区分情绪波动和基本面恶化")
        s["score"] -= 0.2

    # ---- 认知偏误检查（增强版） ----
    # 1. 沉没成本偏误
    if pnl_pct <= -25 and days > 90:
        s["details"].append("【认知偏误】沉没成本偏误: 持有超过3个月且深度亏损，难以承认错误是人性弱点")
        s["score"] -= 0.7
    elif pnl_pct <= -20 and days > 60:
        s["details"].append("【认知偏误】沉没成本偏误: 持有已久且深度亏损，可能不愿承认错误")
        s["score"] -= 0.5

    # 2. 近期盈利偏误 (近因效应)
    if pnl_pct >= 25 and days < 30:
        s["details"].append("【认知偏误】近因偏误: 短期大幅盈利可能让人过度自信，芒格：'一个牛市就能让最愚蠢的人变聪明'")
        s["score"] -= 0.4
    elif pnl_pct >= 15 and days < 20:
        s["details"].append("【认知偏误】近因偏误: 短期盈利可能让人低估风险")
        s["score"] -= 0.2

    # 3. 确认偏误 (只看到利好信息)
    if pnl_pct <= -10 and days > 30:
        s["details"].append("【认知偏误】确认偏误提醒: 亏损时容易只寻找利好信息来证明自己正确，要主动寻找反面证据")
        s["score"] -= 0.2

    # 4. 处置效应 (过早卖出盈利、死守亏损)
    if pnl_pct >= 30 and days < 30:
        s["details"].append("【认知偏误】处置效应提醒: 短期盈利容易让人想落袋为安，但好公司应该长期持有")
        s["score"] -= 0.2
    if pnl_pct <= -20 and days > 120:
        s["details"].append("【认知偏误】处置效应提醒: 死守亏损仓位超过4个月，可能错过了更好的机会成本")

    # 5. 锚定偏误
    s["details"].append("【认知偏误】锚定偏误提醒: 不要被买入成本锚定，决策应基于当前价值而非买入价格")

    # 6. 仓位控制合理性
    if weight < 5 and pnl_pct <= -25:
        s["details"].append("【仓位控制】小仓位试错，亏损影响有限，芒格式智慧：'在不知道要去哪里的情况下，少下注'")
    elif weight < 5 and pnl_pct >= 30:
        s["details"].append("【仓位控制】仓位偏轻，如果看好应该逐步加仓到合理仓位")

    # 7. 年化收益辅助判断
    if days > 60 and ann_ret < -20:
        s["details"].append(f"【趋势警示】年化 {ann_ret:.1f}%，持续跑输无风险利率，机会成本很大")

    # 8. 芒格：多学科思维模型
    s["details"].append("芒格原则: '多学科思维模型'——投资决策需要从历史、心理、数学、生物等多个角度思考")

    s["color"] = "positive" if s["score"] >= 3.5 else "neutral" if s["score"] >= 2.5 else "negative"
    return s


# ------------------------------------------------------------------
# 3. 段永平 — 商业模式 + 企业文化 + 好价格
# ------------------------------------------------------------------
def duan_score(holding: dict, summary: dict) -> dict:
    """
    段永平视角评分：商业模式、企业文化、价格合理性。
    段永平核心：'买股票就是买公司'，'好生意、好管理、好价格'。

    返回:
        {
            "score": float,
            "details": list,
            "color": str,
        }
    """
    s = {"score": 3.0, "details": [], "color": "neutral"}
    sector = holding.get("sector", "")
    pnl_pct = holding.get("pnl_pct", 0)
    name = holding.get("name", "")
    weight = holding.get("weight", 0)
    market = holding.get("market", "")

    # ---- 商业模式评估（段永平核心：好生意、好管理、好价格） ----
    biz_models = {
        # ---- 金融 ----
        "银行/金融": "好生意但高杠杆，招行是银行中最好的零售模式，ROE长期领先同行，但高杠杆意味着容错空间小",
        "保险": "好生意，浮存金模式是巴菲特最爱的商业模式，但投资端能力是关键",
        "券商/投行": "一般生意，业绩高度依赖市场周期，段永平大概率不会重仓",

        # ---- 消费 ----
        "消费/白酒": "极好的生意！白酒是A股最好的商业模式——高毛利(>70%)、低资本开支、品牌粘性强、存货不贬值反而增值",
        "消费/食品饮料": "好生意，消费品龙头具有品牌溢价和定价权，但增速较慢",
        "消费/家电": "一般生意，行业已进入成熟期，价格竞争激烈，增长空间有限",
        "消费/汽车": "较差的生意，重资产、高资本开支、技术迭代快、竞争激烈，段永平：'汽车行业历史上很少为股东创造价值'",

        # ---- 医药 ----
        "制药": "好生意，但需要持续研发投入，专利悬崖是天然风险；LLY的GLP-1赛道目前领先，但10年后格局不确定",
        "医药/器械": "好生意，器械龙头技术壁垒高、客户粘性大，但集采压力持续",
        "医药/生物科技": "不确定性高的生意，单个产品决定公司命运，段永平大概率不会碰",

        # ---- 科技 ----
        "半导体": "好生意但周期性极强，HBM是AI瓶颈环节，但存储芯片价格波动剧烈，需要很强的周期判断能力",
        "半导体/设备": "好生意，技术壁垒极高，但地缘政治风险大",
        "互联网科技": "一般生意，小米本质是硬件制造+互联网服务，模式不如纯互联网平台；段永平：'好的商业模式应该容易理解'",
        "软件/SaaS": "好生意，高毛利、高客户粘性、经常性收入占比高，但竞争激烈",
        "网络安全": "好生意，刚需+高转换成本，但竞争格局分散，利润率受压",
        "云计算": "好生意，规模效应明显，但需要持续巨额资本开支",

        # ---- 工业 ----
        "工业/数据中心": "好生意，AI基础设施需求确定性强，Vertiv是细分领域全球龙头，但需关注技术路线变化",
        "工业/制造": "一般生意，周期性行业，资本开支大，段永平：'要选能看懂的好生意'",
        "工业/军工": "政策驱动型生意，透明度低，段永平大概率不会碰",
        "造纸": "一般生意，周期性行业，资本开支大，产品同质化，缺乏定价权",

        # ---- ETF ----
        "ETF/全球指数": "被动投资工具，不需要评估商业模式；但段永平认为主动投资应该超越指数",
        "ETF/道指": "被动投资工具",
        "ETF/港股科技": "被动投资工具",
        "ETF/通信": "被动投资工具",
        "ETF/科创板": "被动投资工具",
        "ETF/半导体": "被动投资工具",

        # ---- 其他 ----
        "另类投资": "非传统模式，流动性差、透明度低，段永平大概率不会碰",
        "房地产/REITs": "一般生意，资产依赖型，现金流稳定但增长有限",
        "公用事业": "稳定但平庸的生意，增长有限，段永平：'不买平庸的公司'",
        "教育": "好生意，但政策风险大，段永平：'要买能力圈内的公司'",
    }

    biz = biz_models.get(sector, f"行业 '{sector}' 商业模式待评估")
    # 模糊匹配
    if not biz_models.get(sector):
        for key, desc in biz_models.items():
            if key in sector or sector in key:
                biz = desc
                break

    s["details"].append(f"【商业模式】{biz}")

    # ---- 好价格判断（段永平：好生意 + 好价格 = 好投资） ----
    if pnl_pct <= -30:
        s["details"].append("【好价格】大幅低于成本，段永平：'好生意在好价格时应该买入更多'")
        s["score"] += 0.8
    elif pnl_pct <= -20:
        s["details"].append("【好价格】低于成本20%+，如果生意逻辑没变，这是加仓时机")
        s["score"] += 0.5
    elif pnl_pct <= -10:
        s["details"].append("【好价格】低于成本，段永平：'好公司跌了是好事，给你更好价格买入'")
        s["score"] += 0.3
    elif pnl_pct >= 50:
        s["details"].append("【好价格】已大幅盈利，段永平：'好公司不卖，除非基本面变化或极度高估'")
        s["score"] -= 0.2
    elif pnl_pct >= 30:
        s["details"].append("【好价格】盈利可观，但段永平认为好公司应该长期持有，不考虑卖出")
        s["score"] += 0.0
    else:
        s["details"].append("【好价格】当前价格在合理区间")

    # ---- 管理层判断 ----
    mgmt_notes = {
        "小米集团": "雷军是优秀企业家，但造车业务持续烧钱是长期考验；段永平：'好的管理层能提升公司价值'",
        "招商银行": "招行管理层在零售银行领域能力突出，战略执行力强，王良行长延续了田惠宇时代的零售战略",
        "贵州茅台": "茅台管理层核心任务是维护品牌和管理渠道，产能释放是关键",
        "腾讯控股": "马化腾领导下的腾讯战略清晰，投资布局广泛，但游戏监管风险需关注",
        "阿里巴巴": "阿里管理层在经历调整，吴泳铭接任后聚焦核心业务，效果待观察",
        "美团": "王兴是优秀的战略家，但本地生活竞争激烈，盈利能力待验证",
        "宁德时代": "曾毓群技术出身，带领宁德成为全球动力电池龙头，但行业产能过剩是挑战",
        "比亚迪": "王传福技术型企业家，垂直整合战略独特，但利润率偏低",
        "汇川技术": "汇川管理层在工业自动化领域深耕，技术积累深厚",
        "中国平安": "平安管理层综合金融战略执行力强，但寿险改革成效待观察",
        "美的集团": "美的管理层国际化战略清晰，方洪波是优秀的企业家",
        "福耀玻璃": "曹德旺是传奇企业家，专注主业，全球化布局成功",
        "格力电器": "董明珠强势领导，但多元化进展有限，空调依赖度高",
        "海康威视": "海康管理层技术背景深厚，AI赋能安防转型顺利",
        "万华化学": "万华管理层在化工领域技术领先，MDI全球龙头，但周期性明显",
        "VRT": "Vertiv管理层在数据中心基础设施领域深耕，AI浪潮下执行力强",
        "OKTA": "Okta管理层在身份安全领域专注，但盈利能力待提升",
        "LLY": "礼来管理层在GLP-1赛道战略正确，研发管线丰富",
        "MU": "美光管理层在存储芯片周期管理上经验丰富，HBM布局领先",
    }

    matched = False
    for k, v in mgmt_notes.items():
        if k in name:
            s["details"].append(f"【管理层】{v}")
            matched = True
            break
    if not matched and "ETF" not in sector:
        s["details"].append(f"【管理层】{name}的管理层信息待进一步研究，建议阅读年报和管理层访谈")

    # ---- 段永平核心原则 ----
    if "ETF" not in sector:
        s["details"].append("【段永平原则】'买股票就是买公司'——如果不想持有10年，就不要持有10分钟")
        s["details"].append("【段永平原则】'如果跌到0也不慌，才是真理解'——问自己：如果明天跌50%，你会加仓还是恐慌？")

    s["color"] = "positive" if s["score"] >= 3.5 else "neutral" if s["score"] >= 2.5 else "negative"
    return s


# ------------------------------------------------------------------
# 4. 李录 — 长期确定性 + 文明视角 + 能力圈
# ------------------------------------------------------------------
def li_lu_score(holding: dict, summary: dict) -> dict:
    """
    李录视角评分：长期确定性、文明视角、能力圈、时间维度。
    李录核心：'投资就是投资一个国家/文明的长期增长'，'长期确定性是最重要的'。

    返回:
        {
            "score": float,
            "details": list,
            "color": str,
        }
    """
    s = {"score": 3.0, "details": [], "color": "neutral"}
    sector = holding.get("sector", "")
    days = holding.get("holding_days", 0)
    pnl_pct = holding.get("pnl_pct", 0)
    name = holding.get("name", "")
    market = holding.get("market", "")
    ticker = holding.get("ticker", "")

    # ---- 长期确定性（李录的核心：买入确定的长期增长） ----
    certainty = {
        # ---- 金融 ----
        "银行/金融": "招商银行零售银行护城河深，ROE领先，但金融行业本质是周期性的，10年确定性中等偏高",
        "保险": "保险行业长期需求确定，但投资端受利率影响大，10年确定性中等",
        "券商/投行": "券商行业高度依赖市场周期，10年确定性低",

        # ---- 消费 ----
        "消费/白酒": "白酒行业10年确定性高！顶级品牌(茅台/五粮液)几乎不可替代，文化属性强，但年轻人消费习惯变化是长期风险",
        "消费/食品饮料": "消费龙头10年确定性较高，但增速放缓",
        "消费/家电": "家电行业10年确定性中等，行业成熟，增长空间有限",
        "消费/汽车": "汽车行业10年确定性低，技术路线和竞争格局都在剧烈变化中",

        # ---- 医药 ----
        "制药": "LLY在GLP-1赛道领先，但10年后的竞争格局不确定；医药行业长期需求确定，但个体公司不确定",
        "医药/器械": "医疗器械10年确定性较高，国产替代趋势明确",
        "医药/生物科技": "生物科技10年确定性低，管线失败风险高",

        # ---- 科技 ----
        "半导体": "HBM受益AI长期趋势，但存储芯片的周期性无法回避，10年确定性中等",
        "半导体/设备": "半导体设备10年确定性中等偏高，技术壁垒极高",
        "互联网科技": "小米10年确定性中等，取决于造车能否成功和手机业务能否稳住；互联网平台确定性更高",
        "软件/SaaS": "SaaS 10年确定性中等，AI正在重塑行业格局",
        "网络安全": "网络安全需求长期增长，但竞争格局变化快，10年确定性中等",
        "云计算": "云计算10年确定性高，数字化转型是长期趋势",

        # ---- 工业 ----
        "工业/数据中心": "AI长期趋势确定，Vertiv受益确定性高，但需关注技术路线变化",
        "工业/制造": "高端制造10年确定性中等，看技术壁垒和国产替代空间",
        "工业/军工": "军工行业10年确定性中等，受政策和国际关系影响大",
        "造纸": "造纸行业长期需求稳定但增速低，周期性明显，10年确定性中等偏低",

        # ---- ETF ----
        "ETF/全球指数": "人类经济长期增长，10年确定性很高；李录认同全球化配置",
        "ETF/道指": "美国经济长期增长，10年确定性高；但李录更看好中国",
        "ETF/港股科技": "港股科技长期趋势向上，但受地缘政治影响大，10年确定性中等",
        "ETF/通信": "通信行业长期需求增长，但确定性强于增长弹性",
        "ETF/科创板": "科创长期方向确定，但个体公司不确定性高，指数化投资是正确的",
        "ETF/半导体": "半导体行业长期向上，但周期波动大，指数化投资分散了个股风险",

        # ---- 其他 ----
        "另类投资": "流动性差、透明度低，长期确定性低，李录不会碰",
        "房地产/REITs": "REITs长期确定性中等，现金流稳定但增长有限",
        "公用事业": "公用事业长期确定性高，但增长有限，适合防御配置",
        "教育": "教育行业长期需求确定，但政策风险高，确定性中等",
    }

    cert = certainty.get(sector, f"行业 '{sector}' 长期确定性待评估")
    # 模糊匹配
    if not certainty.get(sector):
        for key, desc in certainty.items():
            if key in sector or sector in key:
                cert = desc
                break

    s["details"].append(f"【长期确定性】{cert}")

    # 根据确定性调整分数
    high_certainty_sectors = ["消费/白酒", "ETF/全球指数", "ETF/道指", "云计算", "消费/食品饮料"]
    low_certainty_sectors = ["另类投资", "消费/汽车", "医药/生物科技", "券商/投行"]

    for hc in high_certainty_sectors:
        if hc in sector or sector in hc:
            s["score"] += 0.3
            break
    for lc in low_certainty_sectors:
        if lc in sector or sector in lc:
            s["score"] -= 0.3
            break

    # ---- 文明视角（李录强调现代化和文明演进） ----
    civilization_notes = {
        "ETF/全球指数": "持有全球指数就是做多全人类文明进步，符合李录的文明演进观",
        "ETF/道指": "持有美国指数就是做多美国经济，李录认为美国现代化是成功的",
        "ETF/港股科技": "做多中国科技文明进步，但李录认为中国现代化还有很长的路",
        "银行/金融": "金融是现代经济的血液，银行是文明进步的基础设施",
        "消费/白酒": "白酒文化是中国文明的一部分，但年轻人消费习惯变化值得关注",
        "半导体": "AI是新一轮技术革命，半导体是基础，受益于文明进步",
        "工业/数据中心": "AI数据中心是数字文明的基础设施，具有长期文明价值",
        "制药": "医药进步是人类文明的重要标志，GLP-1是代谢疾病治疗的突破",
        "造纸": "造纸是基础工业，受益于文明进步但增速有限",
    }

    for key, note in civilization_notes.items():
        if key in sector or sector in key:
            s["details"].append(f"【文明视角】{note}")
            # 文明视角加分
            if sector in ("ETF/全球指数", "ETF/道指", "半导体", "工业/数据中心"):
                s["score"] += 0.4
            elif sector in ("ETF/港股科技", "银行/金融", "制药"):
                s["score"] += 0.2
            break
    else:
        s["details"].append(f"【文明视角】{sector}与文明演进的关系待分析")

    # ---- 能力圈（李录：'每个人都有自己的能力圈，重要的是知道边界'） ----
    in_circle = ["ETF/全球指数", "ETF/道指", "银行/金融", "消费/白酒", "ETF/港股科技"]
    out_circle = ["另类投资", "医药/生物科技", "消费/汽车"]

    is_in = False
    for ic in in_circle:
        if ic in sector or sector in ic:
            s["details"].append("【能力圈】该持仓在你的能力圈范围内，李录：'在能力圈内做决策是投资的第一原则'")
            s["score"] += 0.3
            is_in = True
            break

    if not is_in:
        for oc in out_circle:
            if oc in sector or sector in oc:
                s["details"].append(f"【能力圈】{sector}透明度/可理解性较低，可能超出了大多数人的能力圈边界")
                s["score"] -= 0.5
                break
        else:
            s["details"].append(f"【能力圈】{sector}需要持续学习，李录：'能力圈可以通过学习扩大，但不能假装知道'")
            s["score"] -= 0.1

    # ---- 时间维度（李录：长期持有是验证判断的唯一方式） ----
    if days > 365:
        s["details"].append(f"【时间验证】已持有 {days} 天（超过1年），李录：'真正的长期持有是5-10年，但1年已经是一个开始'")
        s["score"] += 0.5
    elif days > 180:
        s["details"].append(f"【时间验证】已持有 {days} 天，李录：'长期持有是验证判断的唯一方式，时间越长越能证明你对了或错了'")
        s["score"] += 0.3
    elif days > 60:
        s["details"].append(f"【时间验证】已持有 {days} 天，李录：'短期波动不能说明什么，需要至少1-2年才能判断一个投资'")
        s["score"] += 0.0
    elif days > 30:
        s["details"].append(f"【时间验证】仅持有 {days} 天，时间太短无法验证判断，李录建议至少持有1年")
        s["score"] -= 0.2
    else:
        s["details"].append(f"【时间验证】仅持有 {days} 天，新仓位需要耐心，李录：'买入后就应该忘记买入价格'")
        s["score"] -= 0.3

    # ---- 李录核心原则 ----
    s["details"].append("【李录原则】'投资就是投资一个国家的长期增长'——做多你相信的文明")
    s["details"].append("【李录原则】'长期确定性比短期高回报更重要'——复利的核心是不亏损")

    s["color"] = "positive" if s["score"] >= 3.5 else "neutral" if s["score"] >= 2.5 else "negative"
    return s


# ====================================================================
# 综合判决（复用现有逻辑，增强版）
# ====================================================================
def generate_verdict(holding: dict, buffett: dict, munger: dict, duan: dict, li_lu: dict) -> dict:
    """
    综合四大师视角生成最终判决。
    输入四个评分字典，输出综合判决结果。

    返回:
        {
            "verdict": str,          # 判决结论
            "risk_level": str,       # 风险等级
            "avg_score": float,      # 平均分
            "score_detail": str,     # 各视角得分详情
            "summary": str,          # 总结
            "recommendations": list, # 建议列表
        }
    """
    scores = {
        "巴菲特": buffett["score"],
        "芒格": munger["score"],
        "段永平": duan["score"],
        "李录": li_lu["score"],
    }
    avg_score = sum(scores.values()) / len(scores)

    pnl_pct = holding.get("pnl_pct", 0)
    weight = holding.get("weight", 0)
    ticker = holding.get("ticker", "")
    sector = holding.get("sector", "")
    notes = holding.get("notes", "")

    # 生成判决
    if avg_score >= 3.8:
        verdict = "✓ 强烈推荐持有"
        risk_level = "normal"
        summary_text = "四大师视角综合评分优秀，逻辑一致，核心持仓继续持有"
    elif avg_score >= 3.5:
        verdict = "✓ 通过"
        risk_level = "normal"
        summary_text = "四大师视角综合评分良好，逻辑一致，继续持有"
    elif avg_score >= 3.0:
        verdict = "○ 轻度观察"
        risk_level = "info"
        summary_text = "四大师视角基本一致，但存在一些需关注的细节"
    elif avg_score >= 2.5:
        verdict = "○ 观察"
        risk_level = "info"
        summary_text = "四大师视角存在分歧，需持续跟踪关键变量"
    elif avg_score >= 2.0:
        verdict = "⚡ 注意风险"
        risk_level = "warning"
        summary_text = "四大师视角评分偏低，建议审视持仓逻辑，关注风险点"
    elif avg_score >= 1.5:
        verdict = "⚡ 需要警惕"
        risk_level = "warning"
        summary_text = "四大师视角评分较低，逻辑存在明显问题，建议减仓"
    else:
        verdict = "⚠ 需重点关注"
        risk_level = "danger"
        summary_text = "四大师视角评分极低，强烈建议重新评估或止损"

    # 得分详情
    score_detail = " | ".join([f"{k}: {v:.1f}" for k, v in scores.items()])

    # 综合建议
    recommendations = []

    # 盈亏建议
    if pnl_pct <= -40:
        recommendations.append("【止损建议】深度亏损 > 40%，已触发一票否决红线，强烈建议重新评估投资逻辑")
    elif pnl_pct <= -30:
        recommendations.append("【风险建议】深度亏损，需判断是否被证伪，若核心逻辑未变可考虑加仓摊薄，否则果断止损")
    elif pnl_pct <= -15:
        recommendations.append("【观察建议】关注逻辑是否变化，若核心逻辑未变可持有观察，设定 -30% 为止损线")
    elif pnl_pct >= 50:
        recommendations.append("【止盈建议】大幅盈利 > 50%，可考虑分批止盈，锁定部分利润")
    elif pnl_pct >= 30:
        recommendations.append("【持有建议】盈利良好，趋势未变可继续持有，但需关注估值是否过高")
    elif pnl_pct >= 15:
        recommendations.append("【持有建议】盈利正常，继续持有")
    else:
        recommendations.append("【持有建议】当前价格区间保持持有")

    # 仓位建议
    if weight >= 40:
        recommendations.append("【仓位风险】仓位过重 (> 40%)，需确保对该标的有足够深度理解，防止黑天鹅")
    elif weight >= 30:
        recommendations.append("【仓位提示】仓位较重 (> 30%)，需持续跟踪基本面变化")
    elif weight >= 20:
        recommendations.append("【仓位提示】仓位适中偏高，关注集中度风险")

    # 持仓时间建议
    days = holding.get("holding_days", 0)
    if days < 30 and pnl_pct <= -10:
        recommendations.append("【时间提示】建仓不到1个月即亏损，需区分是买点问题还是逻辑问题")

    # 芒格追问转化
    for q in munger.get("reverse_questions", []):
        if "证伪" in q or "失败" in q:
            recommendations.append(f"【芒格追问】{q}")
            break

    return {
        "verdict": verdict,
        "risk_level": risk_level,
        "avg_score": round(avg_score, 1),
        "score_detail": score_detail,
        "summary": summary_text,
        "recommendations": recommendations,
    }


# ====================================================================
# PortfolioReviewEngine — 组合级深度审查引擎
# ====================================================================

class PortfolioReviewEngine:
    """
    组合持仓深度审查引擎。

    功能:
      1. concentration_analysis()    — 集中度分析
      2. correlation_check()        — 隐藏风险共振检测
      3. opportunity_cost_ranking() — 机会成本排序
      4. stress_testing()           — 四情景压力测试
      5. rebalancing_suggestions()  — 综合再平衡建议

    用法:
        engine = PortfolioReviewEngine(holdings, summary)
        report = engine.full_review()
    """

    # 行业相关性矩阵（基于行业分类的隐含相关性）
    # 值域: 0.0 (完全无关) ~ 1.0 (完全同步)
    _SECTOR_CORRELATION_MATRIX = {
        # 同一行业天然高相关
        ("银行/金融", "银行/金融"): 1.0,
        ("消费/白酒", "消费/白酒"): 1.0,
        ("半导体", "半导体"): 1.0,
        # 行业间相关性
        ("银行/金融", "消费/白酒"): 0.3,
        ("银行/金融", "半导体"): 0.2,
        ("银行/金融", "工业/数据中心"): 0.3,
        ("银行/金融", "ETF/全球指数"): 0.5,
        ("银行/金融", "ETF/道指"): 0.4,
        ("银行/金融", "ETF/港股科技"): 0.3,
        ("银行/金融", "互联网科技"): 0.2,
        ("银行/金融", "网络安全"): 0.2,
        ("银行/金融", "制药"): 0.2,
        ("银行/金融", "造纸"): 0.3,
        ("消费/白酒", "半导体"): 0.1,
        ("消费/白酒", "工业/数据中心"): 0.1,
        ("消费/白酒", "ETF/全球指数"): 0.4,
        ("消费/白酒", "ETF/道指"): 0.3,
        ("消费/白酒", "ETF/港股科技"): 0.3,
        ("消费/白酒", "互联网科技"): 0.2,
        ("消费/白酒", "网络安全"): 0.1,
        ("消费/白酒", "制药"): 0.2,
        ("消费/白酒", "造纸"): 0.2,
        ("半导体", "工业/数据中心"): 0.6,  # AI供应链强相关
        ("半导体", "ETF/全球指数"): 0.5,
        ("半导体", "ETF/道指"): 0.4,
        ("半导体", "ETF/港股科技"): 0.5,
        ("半导体", "互联网科技"): 0.5,  # 科技板块共振
        ("半导体", "网络安全"): 0.4,
        ("半导体", "制药"): 0.1,
        ("半导体", "造纸"): 0.1,
        ("工业/数据中心", "ETF/全球指数"): 0.4,
        ("工业/数据中心", "ETF/道指"): 0.3,
        ("工业/数据中心", "ETF/港股科技"): 0.4,
        ("工业/数据中心", "互联网科技"): 0.4,
        ("工业/数据中心", "网络安全"): 0.5,  # AI基础设施+安全
        ("工业/数据中心", "制药"): 0.1,
        ("工业/数据中心", "造纸"): 0.1,
        ("ETF/全球指数", "ETF/道指"): 0.8,  # 全球指数与道指高度同步
        ("ETF/全球指数", "ETF/港股科技"): 0.6,
        ("ETF/全球指数", "互联网科技"): 0.5,
        ("ETF/全球指数", "网络安全"): 0.4,
        ("ETF/全球指数", "制药"): 0.3,
        ("ETF/全球指数", "造纸"): 0.3,
        ("ETF/道指", "ETF/港股科技"): 0.4,
        ("ETF/道指", "互联网科技"): 0.4,
        ("ETF/道指", "网络安全"): 0.3,
        ("ETF/道指", "制药"): 0.2,
        ("ETF/道指", "造纸"): 0.2,
        ("ETF/港股科技", "互联网科技"): 0.7,  # 港股科技+互联网科技
        ("ETF/港股科技", "网络安全"): 0.4,
        ("ETF/港股科技", "制药"): 0.2,
        ("ETF/港股科技", "造纸"): 0.2,
        ("互联网科技", "网络安全"): 0.5,
        ("互联网科技", "制药"): 0.1,
        ("互联网科技", "造纸"): 0.1,
        ("网络安全", "制药"): 0.1,
        ("网络安全", "造纸"): 0.1,
        ("制药", "造纸"): 0.1,
    }

    # 市场相关性
    _MARKET_CORRELATION = {
        ("A股", "A股"): 1.0,
        ("A股", "港股"): 0.5,
        ("A股", "美股"): 0.3,
        ("港股", "港股"): 1.0,
        ("港股", "美股"): 0.4,
        ("美股", "美股"): 1.0,
    }

    # 机会成本参数
    _OPPORTUNITY_COST_PARAMS = {
        # 各行业基准预期年化回报（%）
        "expected_return": {
            "银行/金融": 0.10,
            "消费/白酒": 0.12,
            "消费/食品饮料": 0.10,
            "消费/家电": 0.08,
            "消费/汽车": 0.06,
            "制药": 0.10,
            "医药/器械": 0.10,
            "医药/生物科技": 0.08,
            "半导体": 0.12,
            "半导体/设备": 0.10,
            "互联网科技": 0.08,
            "软件/SaaS": 0.12,
            "网络安全": 0.10,
            "云计算": 0.12,
            "工业/数据中心": 0.12,
            "工业/制造": 0.08,
            "工业/军工": 0.08,
            "造纸": 0.06,
            "ETF/全球指数": 0.08,
            "ETF/道指": 0.07,
            "ETF/港股科技": 0.09,
            "ETF/通信": 0.07,
            "ETF/科创板": 0.10,
            "ETF/半导体": 0.10,
            "另类投资": 0.06,
            "房地产/REITs": 0.07,
            "公用事业": 0.06,
            "教育": 0.08,
        },
        # 各行业确定性系数（0.0 ~ 1.0）
        "certainty": {
            "银行/金融": 0.7,
            "消费/白酒": 0.8,
            "消费/食品饮料": 0.7,
            "消费/家电": 0.6,
            "消费/汽车": 0.4,
            "制药": 0.6,
            "医药/器械": 0.6,
            "医药/生物科技": 0.3,
            "半导体": 0.5,
            "半导体/设备": 0.5,
            "互联网科技": 0.5,
            "软件/SaaS": 0.6,
            "网络安全": 0.5,
            "云计算": 0.7,
            "工业/数据中心": 0.6,
            "工业/制造": 0.5,
            "工业/军工": 0.5,
            "造纸": 0.5,
            "ETF/全球指数": 0.9,
            "ETF/道指": 0.85,
            "ETF/港股科技": 0.7,
            "ETF/通信": 0.7,
            "ETF/科创板": 0.6,
            "ETF/半导体": 0.6,
            "另类投资": 0.3,
            "房地产/REITs": 0.6,
            "公用事业": 0.8,
            "教育": 0.5,
        },
    }

    # 压力测试场景参数
    _STRESS_SCENARIOS = {
        "全球衰退 (Global Recession)": {
            "description": "全球GDP增速降至1%以下，贸易萎缩，企业盈利大幅下滑，失业率上升",
            "equity_shock": -0.35,       # 权益资产冲击
            "bond_shock": 0.05,           # 债券受益（避险）
            "cash_shock": 0.0,
            "sector_adjust": {
                "银行/金融": -0.45,       # 金融首当其冲
                "消费/白酒": -0.40,       # 可选消费大幅下滑
                "消费/食品饮料": -0.25,   # 必选消费相对抗跌
                "消费/家电": -0.35,
                "消费/汽车": -0.45,
                "半导体": -0.40,          # 周期+科技双重打击
                "半导体/设备": -0.40,
                "互联网科技": -0.30,
                "工业/数据中心": -0.30,
                "工业/制造": -0.35,
                "工业/军工": -0.20,
                "网络安全": -0.25,
                "软件/SaaS": -0.25,
                "云计算": -0.20,
                "制药": -0.20,            # 防御性
                "医药/器械": -0.20,
                "医药/生物科技": -0.25,
                "造纸": -0.35,
                "ETF/全球指数": -0.35,
                "ETF/道指": -0.30,
                "ETF/港股科技": -0.40,
                "ETF/通信": -0.25,
                "ETF/科创板": -0.45,
                "ETF/半导体": -0.40,
                "另类投资": -0.30,
                "房地产/REITs": -0.30,
                "公用事业": -0.15,        # 最强防御
                "教育": -0.20,
            },
        },
        "中美脱钩升级 (US-China Escalation)": {
            "description": "贸易战升级至科技全面脱钩，中概股退市风险，港股流动性危机，半导体出口管制加码",
            "equity_shock": -0.25,
            "bond_shock": 0.03,
            "cash_shock": 0.0,
            "sector_adjust": {
                "银行/金融": -0.30,
                "消费/白酒": -0.20,       # 内需消费相对独立
                "消费/食品饮料": -0.15,
                "消费/家电": -0.20,
                "消费/汽车": -0.25,
                "半导体": -0.50,          # 地缘政治风险最大
                "半导体/设备": -0.50,
                "互联网科技": -0.35,      # 科技脱钩重灾区
                "工业/数据中心": -0.25,
                "工业/制造": -0.20,
                "工业/军工": -0.10,
                "网络安全": -0.15,
                "软件/SaaS": -0.20,
                "云计算": -0.15,
                "制药": -0.10,
                "医药/器械": -0.10,
                "医药/生物科技": -0.10,
                "造纸": -0.15,
                "ETF/全球指数": -0.25,
                "ETF/道指": -0.15,        # 美国本土受影响较小
                "ETF/港股科技": -0.55,    # 港股科技最大风险
                "ETF/通信": -0.20,
                "ETF/科创板": -0.45,
                "ETF/半导体": -0.50,
                "另类投资": -0.20,
                "房地产/REITs": -0.15,
                "公用事业": -0.10,
                "教育": -0.15,
            },
        },
        "利率飙升 (Rate Spike)": {
            "description": "美联储/中国央行加息 100-150bp，流动性收紧，估值压缩，成长股承压",
            "equity_shock": -0.20,
            "bond_shock": -0.10,          # 利率上升债券价格下跌
            "cash_shock": 0.05,           # 现金受益（高息）
            "sector_adjust": {
                "银行/金融": -0.15,       # 银行受益于息差扩大
                "消费/白酒": -0.25,
                "消费/食品饮料": -0.20,
                "消费/家电": -0.20,
                "消费/汽车": -0.30,
                "半导体": -0.35,          # 成长股估值压缩严重
                "半导体/设备": -0.35,
                "互联网科技": -0.30,
                "工业/数据中心": -0.30,
                "工业/制造": -0.20,
                "工业/军工": -0.15,
                "网络安全": -0.30,
                "软件/SaaS": -0.35,
                "云计算": -0.30,
                "制药": -0.25,
                "医药/器械": -0.20,
                "医药/生物科技": -0.35,
                "造纸": -0.20,
                "ETF/全球指数": -0.25,
                "ETF/道指": -0.20,
                "ETF/港股科技": -0.30,
                "ETF/通信": -0.20,
                "ETF/科创板": -0.35,
                "ETF/半导体": -0.35,
                "另类投资": -0.25,
                "房地产/REITs": -0.35,    # 利率敏感型
                "公用事业": -0.25,        # 高负债率受影响
                "教育": -0.20,
            },
        },
        "科技泡沫破裂 (Tech Bubble Burst)": {
            "description": "AI/半导体估值泡沫破裂，科技股估值回归，纳斯达克回调 30%+，投机资金撤退",
            "equity_shock": -0.25,
            "bond_shock": 0.08,
            "cash_shock": 0.0,
            "sector_adjust": {
                "银行/金融": -0.15,
                "消费/白酒": -0.10,
                "消费/食品饮料": -0.10,
                "消费/家电": -0.10,
                "消费/汽车": -0.15,
                "半导体": -0.55,          # 泡沫核心
                "半导体/设备": -0.50,
                "互联网科技": -0.35,
                "工业/数据中心": -0.40,  # AI基础设施拖累
                "工业/制造": -0.10,
                "工业/军工": -0.05,
                "网络安全": -0.30,
                "软件/SaaS": -0.35,
                "云计算": -0.30,
                "制药": -0.05,            # 不受影响
                "医药/器械": -0.05,
                "医药/生物科技": -0.10,
                "造纸": -0.05,
                "ETF/全球指数": -0.20,
                "ETF/道指": -0.15,
                "ETF/港股科技": -0.40,
                "ETF/通信": -0.25,
                "ETF/科创板": -0.45,
                "ETF/半导体": -0.50,
                "另类投资": -0.10,
                "房地产/REITs": -0.10,
                "公用事业": 0.0,          # 防御性最佳
                "教育": -0.05,
            },
        },
    }

    def __init__(
        self,
        holdings: List[Dict],
        summary: Dict,
        risk_free_rate: float = 0.025,
        logger: Optional[logging.Logger] = None,
    ):
        """
        初始化组合审查引擎。

        参数:
            holdings: List[Dict] — 持仓数据，来自 PortfolioManager.get_holdings_table()
            summary: Dict — 组合汇总数据，来自 PortfolioManager.get_summary_dict()
            risk_free_rate: float — 无风险利率（默认 2.5%）
            logger: Optional[logging.Logger]
        """
        self.holdings = holdings
        self.summary = summary
        self.risk_free_rate = risk_free_rate
        self.logger = logger or logging.getLogger(f"{__name__}.PortfolioReviewEngine")

        # 缓存计算结果
        self._concentration_cache = None
        self._correlation_cache = None
        self._opportunity_rank_cache = None
        self._stress_cache = None

        # 过滤现金仓位（部分分析需要排除现金）
        self.non_cash_holdings = [h for h in holdings if h.get("exchange") != "CASH"]

        # 提取总市值
        self.total_value = _exact(summary.get("total_value_cny", 0))

        self.logger.info(
            f"PortfolioReviewEngine 初始化完成: "
            f"{len(self.holdings)} 个持仓, {len(self.non_cash_holdings)} 个非现金持仓, "
            f"总市值 ¥{self.total_value}"
        )

    # ================================================================
    # 1. 集中度分析 (Concentration Analysis)
    # ================================================================
    def concentration_analysis(self) -> Dict:
        """
        集中度分析：计算 Top 3 / Top 5 持仓占比、持仓总数、现金比例。

        返回:
            {
                "top_3_weight": float,          # 前3大持仓占比(%)
                "top_5_weight": float,          # 前5大持仓占比(%)
                "top_3_holdings": list,         # 前3大持仓详情
                "top_5_holdings": list,         # 前5大持仓详情
                "total_holdings_count": int,    # 总持仓数
                "non_cash_count": int,          # 非现金持仓数
                "cash_ratio": float,            # 现金占比(%)
                "herfindahl_index": float,      # 赫芬达尔指数(集中度)
                "effective_holdings": float,    # 有效持仓数(1/HHI)
                "signals": list,                # 信号列表
                "assessment": str,              # 评估结论
            }
        """
        self.logger.info("开始集中度分析...")

        # 按市值排序
        sorted_by_value = sorted(
            self.holdings,
            key=lambda h: _exact(h.get("market_value_cny", 0)),
            reverse=True,
        )

        # ---- Top 3 ----
        top3 = sorted_by_value[:3]
        top3_weight = sum(h.get("weight", 0) for h in top3)
        top3_details = [
            {
                "ticker": h.get("ticker", ""),
                "name": h.get("name", ""),
                "sector": h.get("sector", ""),
                "weight": round(h.get("weight", 0), 1),
                "pnl_pct": round(h.get("pnl_pct", 0), 1),
            }
            for h in top3
        ]

        # ---- Top 5 ----
        top5 = sorted_by_value[:5]
        top5_weight = sum(h.get("weight", 0) for h in top5)
        top5_details = [
            {
                "ticker": h.get("ticker", ""),
                "name": h.get("name", ""),
                "sector": h.get("sector", ""),
                "weight": round(h.get("weight", 0), 1),
                "pnl_pct": round(h.get("pnl_pct", 0), 1),
            }
            for h in top5
        ]

        # ---- 现金比例 ----
        cash_holdings = [h for h in self.holdings if h.get("exchange") == "CASH"]
        cash_value = sum(
            _exact(h.get("market_value_cny", 0)) for h in cash_holdings
        )
        cash_ratio = float(
            _exact_pct(cash_value, self.total_value) if self.total_value > 0 else Decimal("0")
        )

        # ---- 赫芬达尔指数 (HHI) ----
        # HHI = sum(weight_i^2)，权重为小数形式
        weights = [
            _exact(h.get("weight", 0)) / Decimal("100")
            for h in self.non_cash_holdings
        ]
        hhi = sum(w * w for w in weights)
        effective_n = float(Decimal("1") / hhi) if hhi > 0 else 0

        # ---- 信号生成 ----
        signals = []
        total_count = len(self.holdings)
        non_cash_count = len(self.non_cash_holdings)

        # Top 3 集中度信号
        if top3_weight > 60:
            signals.append({
                "type": "warning",
                "severity": "high",
                "text": (
                    f"前3大持仓占比 {top3_weight:.1f}%，集中度极高。"
                    "巴菲特认为集中投资需要极深的理解，如果其中一只出问题，组合将受到重大冲击。"
                ),
            })
        elif top3_weight > 50:
            signals.append({
                "type": "warning",
                "severity": "medium",
                "text": f"前3大持仓占比 {top3_weight:.1f}%，集中度偏高，需确保对每只都有深度理解。",
            })
        elif top3_weight > 40:
            signals.append({
                "type": "info",
                "severity": "low",
                "text": f"前3大持仓占比 {top3_weight:.1f}%，适度集中，芒格：'适度集中是智慧的投资策略'。",
            })
        else:
            signals.append({
                "type": "success",
                "severity": "low",
                "text": f"前3大持仓占比 {top3_weight:.1f}%，分散度良好。",
            })

        # Top 5 集中度信号
        if top5_weight > 80:
            signals.append({
                "type": "warning",
                "severity": "medium",
                "text": f"前5大持仓占比 {top5_weight:.1f}%，极端集中，前5只决定了组合的命运。",
            })
        elif top5_weight > 65:
            signals.append({
                "type": "info",
                "severity": "low",
                "text": f"前5大持仓占比 {top5_weight:.1f}%，集中度较高。",
            })

        # 现金比例信号
        if cash_ratio > 30:
            signals.append({
                "type": "info",
                "severity": "medium",
                "text": (
                    f"现金占比 {cash_ratio:.1f}%，仓位偏保守。"
                    "巴菲特：'现金是看跌期权，在市场恐慌时才有价值'。"
                    "如果市场大跌，这是抄底的弹药。"
                ),
            })
        elif cash_ratio > 20:
            signals.append({
                "type": "info",
                "severity": "low",
                "text": f"现金占比 {cash_ratio:.1f}%，保留了适度的流动性缓冲。",
            })
        elif cash_ratio < 5:
            signals.append({
                "type": "info",
                "severity": "low",
                "text": f"现金占比 {cash_ratio:.1f}%，仓位接近满仓，进攻性强但缺少防御空间。",
            })

        # 持仓数量信号
        if non_cash_count <= 5:
            signals.append({
                "type": "warning",
                "severity": "high",
                "text": (
                    f"仅 {non_cash_count} 个非现金持仓，极度集中。"
                    "芒格的投资生涯中大部分收益来自3-5个公司，但前提是每个都经过深度研究。"
                ),
            })
        elif non_cash_count <= 10:
            signals.append({
                "type": "info",
                "severity": "low",
                "text": f"共 {non_cash_count} 个非现金持仓，属于适度集中的理想范围。",
            })
        elif non_cash_count > 20:
            signals.append({
                "type": "info",
                "severity": "low",
                "text": (
                    f"共 {non_cash_count} 个非现金持仓，数量偏多。"
                    "段永平：'分散投资是对无知的保护'，如果每个都深入研究，精力会被分散。"
                ),
            })

        # 赫芬达尔指数评估
        if float(hhi) > 0.25:
            signals.append({
                "type": "warning",
                "severity": "medium",
                f"text": f"赫芬达尔指数 {float(hhi):.3f}，属于高度集中组合 (HHI > 0.25)。",
            })
        elif float(hhi) > 0.15:
            signals.append({
                "type": "info",
                "severity": "low",
                "text": f"赫芬达尔指数 {float(hhi):.3f}，适度集中。",
            })
        else:
            signals.append({
                "type": "success",
                "severity": "low",
                "text": f"赫芬达尔指数 {float(hhi):.3f}，分散化良好。",
            })

        # 有效持仓数
        signals.append({
            "type": "info",
            "severity": "low",
            "text": f"有效持仓数 (1/HHI) = {effective_n:.1f}，相当于持有 {effective_n:.1f} 个等权持仓的集中度。",
        })

        # ---- 综合评估 ----
        if top3_weight > 60 or float(hhi) > 0.25:
            assessment = "集中度较高，建议关注单只持仓风险"
        elif top3_weight > 40 and cash_ratio < 5:
            assessment = "集中度适中但仓位偏满，建议保留一定现金缓冲"
        elif cash_ratio > 30:
            assessment = "现金比例较高，建议根据市场情况逐步加仓"
        else:
            assessment = "集中度在合理范围内，结构良好"

        result = {
            "top_3_weight": round(top3_weight, 1),
            "top_5_weight": round(top5_weight, 1),
            "top_3_holdings": top3_details,
            "top_5_holdings": top5_details,
            "total_holdings_count": total_count,
            "non_cash_count": non_cash_count,
            "cash_ratio": round(cash_ratio, 1),
            "herfindahl_index": round(float(hhi), 4),
            "effective_holdings": round(effective_n, 1),
            "signals": signals,
            "assessment": assessment,
        }

        self._concentration_cache = result
        self.logger.info(f"集中度分析完成: Top3={top3_weight:.1f}%, HHI={float(hhi):.4f}")
        return result

    # ================================================================
    # 2. 风险共振检测 (Correlation Check)
    # ================================================================
    def correlation_check(self) -> Dict:
        """
        检测持仓间隐含的风险共振。

        基于行业相关性矩阵 + 市场相关性，构建持仓间相关性矩阵。
        识别高相关性集群（风险共振组），并给出风险提示。

        返回:
            {
                "correlation_matrix": list,   # 相关性矩阵
                "risk_clusters": list,         # 风险共振集群
                "high_correlation_pairs": list,# 高相关对
                "cluster_warnings": list,      # 集群风险预警
                "overall_diversification": str, # 整体分散化评估
            }
        """
        self.logger.info("开始风险共振检测...")
        nc = self.non_cash_holdings
        if len(nc) < 2:
            return {
                "correlation_matrix": [],
                "risk_clusters": [],
                "high_correlation_pairs": [],
                "cluster_warnings": ["持仓数量不足2个，无法进行相关性分析"],
                "overall_diversification": "N/A",
            }

        n = len(nc)
        labels = [f"{h.get('ticker','?')}({h.get('name','?')})" for h in nc]
        sectors = [h.get("sector", "") for h in nc]
        markets = [h.get("market", "") for h in nc]
        weights = [h.get("weight", 0) for h in nc]

        # ---- 构建相关性矩阵 ----
        matrix = [[0.0] * n for _ in range(n)]
        pairs = []

        for i in range(n):
            for j in range(i, n):
                if i == j:
                    matrix[i][j] = 1.0
                    continue

                si, sj = sectors[i], sectors[j]
                mi, mj = markets[i], markets[j]

                # 基础相关性 = 行业相关性
                corr = self._get_sector_correlation(si, sj)

                # 市场调整：同市场额外 +0.1，但不超过 1.0
                market_corr = self._MARKET_CORRELATION.get((mi, mj), 0.2)
                corr = min(corr + 0.1 if mi == mj else corr, 1.0)

                matrix[i][j] = round(corr, 2)
                matrix[j][i] = round(corr, 2)

                if corr >= 0.7:
                    pairs.append({
                        "i": i, "j": j,
                        "ticker_i": nc[i].get("ticker", ""),
                        "ticker_j": nc[j].get("ticker", ""),
                        "name_i": nc[i].get("name", ""),
                        "name_j": nc[j].get("name", ""),
                        "sector_i": si,
                        "sector_j": sj,
                        "correlation": corr,
                        "combined_weight": round(weights[i] + weights[j], 1),
                    })

        # ---- 识别风险共振集群 ----
        # 使用简单聚类：相关系数 > 0.6 的归为一组
        clusters = []
        visited = set()

        for i in range(n):
            if i in visited:
                continue
            group = [i]
            visited.add(i)
            for j in range(i + 1, n):
                if j not in visited and matrix[i][j] >= 0.6:
                    group.append(j)
                    visited.add(j)
            if len(group) > 1:
                cluster = {
                    "members": [
                        {
                            "index": idx,
                            "ticker": nc[idx].get("ticker", ""),
                            "name": nc[idx].get("name", ""),
                            "sector": nc[idx].get("sector", ""),
                            "weight": nc[idx].get("weight", 0),
                        }
                        for idx in group
                    ],
                    "total_weight": round(sum(nc[idx].get("weight", 0) for idx in group), 1),
                    "size": len(group),
                }
                clusters.append(cluster)

        # ---- 风险集群预警 ----
        cluster_warnings = []
        for cl in clusters:
            if cl["total_weight"] > 50:
                cluster_warnings.append({
                    "type": "warning",
                    "severity": "high",
                    "text": (
                        f"风险共振集群 [{', '.join(m['ticker'] for m in cl['members'])}] "
                        f"合计权重 {cl['total_weight']:.1f}%，高度关联的持仓占比过大。"
                        "如果该集群对应的风险因子（如AI泡沫破裂、中美脱钩）触发，组合将遭受重大冲击。"
                    ),
                })
            elif cl["total_weight"] > 30:
                cluster_warnings.append({
                    "type": "warning",
                    "severity": "medium",
                    "text": (
                        f"风险共振集群 [{', '.join(m['ticker'] for m in cl['members'])}] "
                        f"合计权重 {cl['total_weight']:.1f}%，需关注集群风险敞口。"
                    ),
                })
            else:
                cluster_warnings.append({
                    "type": "info",
                    "severity": "low",
                    "text": (
                        f"风险共振集群 [{', '.join(m['ticker'] for m in cl['members'])}] "
                        f"合计权重 {cl['total_weight']:.1f}%，风险敞口尚可。"
                    ),
                })

        # ---- 识别 "隐藏风险" 共振主题 ----
        # 查找常见的风险共振主题
        theme_clusters = self._detect_theme_clusters(nc, matrix, weights)
        for theme in theme_clusters:
            cluster_warnings.append(theme)

        # ---- 整体分散化评估 ----
        # 计算平均相关性
        total_corr = 0.0
        count = 0
        for i in range(n):
            for j in range(i + 1, n):
                total_corr += matrix[i][j]
                count += 1
        avg_corr = total_corr / count if count > 0 else 0

        if avg_corr > 0.5:
            divers_assessment = "偏弱 — 持仓间平均相关性较高，组合的分散化效果有限"
        elif avg_corr > 0.3:
            divers_assessment = "一般 — 持仓间存在一定相关性，但分散化有一定效果"
        else:
            divers_assessment = "良好 — 持仓间相关性较低，分散化效果较好"

        # 高相关对按相关性排序
        pairs.sort(key=lambda x: x["correlation"], reverse=True)

        result = {
            "correlation_matrix": {
                "labels": labels,
                "matrix": matrix,
                "avg_correlation": round(avg_corr, 3),
            },
            "risk_clusters": clusters,
            "high_correlation_pairs": pairs[:10],  # 最多返回10个
            "cluster_warnings": cluster_warnings,
            "overall_diversification": divers_assessment,
        }

        self._correlation_cache = result
        self.logger.info(
            f"风险共振检测完成: {len(clusters)} 个风险集群, "
            f"平均相关性 {avg_corr:.3f}, {len(pairs)} 个高相关对"
        )
        return result

    def _get_sector_correlation(self, s1: str, s2: str) -> float:
        """
        获取两个行业之间的相关性系数。
        先精确匹配，再模糊匹配，最后返回默认值。
        """
        # 精确匹配
        if (s1, s2) in self._SECTOR_CORRELATION_MATRIX:
            return self._SECTOR_CORRELATION_MATRIX[(s1, s2)]
        if (s2, s1) in self._SECTOR_CORRELATION_MATRIX:
            return self._SECTOR_CORRELATION_MATRIX[(s2, s1)]

        # 模糊匹配：如果行业相同(含子类)，返回 0.8
        if s1 == s2:
            return 0.8
        # 如果行业名称有包含关系，返回 0.6
        if s1 in s2 or s2 in s1:
            return 0.6

        # 检查是否可以通过 ETF 底层逻辑匹配
        # 如 "ETF/半导体" 与 "半导体" 相关
        for key1, key2 in [
            ("半导体", "ETF/半导体"),
            ("半导体", "半导体/设备"),
            ("ETF/半导体", "半导体/设备"),
            ("互联网科技", "ETF/港股科技"),
            ("消费/白酒", "消费/食品饮料"),
            ("银行/金融", "保险"),
            ("银行/金融", "券商/投行"),
        ]:
            if (s1 == key1 and s2 == key2) or (s1 == key2 and s2 == key1):
                return 0.5

        # 默认值：不同行业低相关
        return 0.2

    def _detect_theme_clusters(
        self, holdings: List[Dict], matrix: List[List[float]], weights: List[float]
    ) -> List[Dict]:
        """
        检测主题性风险共振集群，如 "中国互联网"、"AI供应链"、"中国消费"。

        返回:
            List[Dict] — 每个主题的风险预警
        """
        warnings = []
        n = len(holdings)

        # 主题分类
        themes = {
            "中国互联网/科技": ["互联网科技", "ETF/港股科技"],
            "AI 供应链": ["半导体", "半导体/设备", "工业/数据中心", "ETF/半导体", "ETF/通信"],
            "中国消费": ["消费/白酒", "消费/食品饮料", "消费/家电"],
            "金融": ["银行/金融", "保险", "券商/投行"],
            "全球周期": ["ETF/全球指数", "工业/制造", "造纸"],
        }

        for theme_name, theme_sectors in themes.items():
            theme_indices = [
                i for i in range(n)
                if any(ts in holdings[i].get("sector", "") for ts in theme_sectors)
            ]
            if len(theme_indices) < 2:
                continue

            theme_weight = sum(weights[i] for i in theme_indices)
            theme_tickers = [holdings[i].get("ticker", "") for i in theme_indices]

            if theme_weight > 50:
                warnings.append({
                    "type": "warning",
                    "severity": "high",
                    "text": (
                        f"【{theme_name}】主题共振风险: "
                        f"{', '.join(theme_tickers)} 合计权重 {theme_weight:.1f}%。"
                        f"该主题暴露过大，如果 {theme_name} 板块出现系统性风险，组合将集中承压。"
                    ),
                })
            elif theme_weight > 30:
                warnings.append({
                    "type": "info",
                    "severity": "medium",
                    "text": (
                        f"【{theme_name}】主题共振风险: "
                        f"{', '.join(theme_tickers)} 合计权重 {theme_weight:.1f}%。"
                        f"该主题敞口适中，但仍需关注板块系统性风险。"
                    ),
                })

        return warnings

    # ================================================================
    # 3. 机会成本排序 (Opportunity Cost Ranking)
    # ================================================================
    def opportunity_cost_ranking(self) -> Dict:
        """
        基于巴菲特机会成本框架，对持仓进行排序。

        核心逻辑:
            opportunity_score = expected_annual_return * certainty

        其中:
            - expected_annual_return 根据持仓特征估计
            - certainty 基于行业稳定性和当前盈亏状况

        返回:
            {
                "rankings": list,        # 排序结果（从高到低）
                "top_opportunities": list, # 最佳机会
                "bottom_holdings": list,   # 最差机会（考虑替换）
                "avg_opportunity_score": float,
                "cash_opportunity_cost": float,  # 现金的机会成本
            }
        """
        self.logger.info("开始机会成本排序...")
        nc = self.non_cash_holdings
        if not nc:
            return {
                "rankings": [],
                "top_opportunities": [],
                "bottom_holdings": [],
                "avg_opportunity_score": 0.0,
                "cash_opportunity_cost": 0.0,
            }

        rankings = []
        for h in nc:
            score = self._calc_opportunity_score(h)
            rankings.append(score)

        # 按机会得分排序（从高到低）
        rankings.sort(key=lambda x: x["opportunity_score"], reverse=True)

        # 最佳机会（前3）
        top_opps = rankings[:3]

        # 最差机会（后3，且有机会得分）
        bottom = [r for r in rankings if r["opportunity_score"] < 0.08]
        bottom = bottom[-3:] if len(bottom) > 3 else bottom

        # 平均机会得分（加权）
        total_weight = sum(
            _exact(h.get("weight", 0)) for h in nc
        )
        if total_weight > 0:
            avg_score = float(
                sum(
                    _exact(r["opportunity_score"]) * _exact(r["weight"])
                    for r in rankings
                ) / total_weight
            )
        else:
            avg_score = 0.0

        # 现金机会成本
        cash_holdings = [h for h in self.holdings if h.get("exchange") == "CASH"]
        cash_value = sum(
            _exact(h.get("market_value_cny", 0)) for h in cash_holdings
        )
        cash_ratio = float(
            _exact_pct(cash_value, self.total_value) if self.total_value > 0 else Decimal("0")
        )
        cash_opportunity_cost = cash_ratio * 0.08  # 假设现金基准收益 8%

        result = {
            "rankings": rankings,
            "top_opportunities": top_opps,
            "bottom_holdings": bottom,
            "avg_opportunity_score": round(avg_score, 4),
            "cash_opportunity_cost": round(cash_opportunity_cost, 4),
        }

        self._opportunity_rank_cache = result
        self.logger.info(
            f"机会成本排序完成: 平均机会得分 {avg_score:.4f}, "
            f"最佳 {top_opps[0]['ticker'] if top_opps else 'N/A'}"
        )
        return result

    def _calc_opportunity_score(self, holding: dict) -> Dict:
        """
        计算单个持仓的机会成本得分。

        步骤:
            1. 确定基准预期年化收益率
            2. 根据当前盈亏调整
            3. 确定确定性系数
            4. 机会得分 = 预期收益率 * 确定性系数
        """
        ticker = holding.get("ticker", "")
        name = holding.get("name", "")
        sector = holding.get("sector", "")
        weight = holding.get("weight", 0)
        pnl_pct = holding.get("pnl_pct", 0)
        ann_ret = holding.get("annualized_return", 0)
        days = holding.get("holding_days", 0)
        market = holding.get("market", "")
        is_etf = "ETF" in sector

        # ---- 步骤1: 基准预期年化收益率 ----
        base_return = self._OPPORTUNITY_COST_PARAMS["expected_return"].get(sector, 0.10)

        # ---- 步骤2: 根据当前盈亏调整 ----
        if pnl_pct <= -35:
            # 深度亏损 -> 均值回归潜力大
            expected_return = 0.20
            adj_reason = "深度亏损 > 35%，均值回归潜力大，预期回报 20%"
        elif pnl_pct <= -25:
            expected_return = 0.18
            adj_reason = "深度亏损 25-35%，均值回归潜力较大，预期回报 18%"
        elif pnl_pct <= -15:
            expected_return = 0.15
            adj_reason = "亏损 15-25%，均值回归潜力，预期回报 15%"
        elif pnl_pct >= 40:
            # 大幅盈利 -> 均值回归风险
            expected_return = 0.05
            adj_reason = "大幅盈利 > 40%，均值回归风险，预期回报 5%"
        elif pnl_pct >= 25:
            expected_return = 0.07
            adj_reason = "盈利 25-40%，均值回归风险，预期回报 7%"
        elif pnl_pct >= 15:
            expected_return = 0.08
            adj_reason = "盈利 15-25%，预期回报 8%"
        elif is_etf:
            # ETF 长期市场回报
            expected_return = 0.08
            adj_reason = "ETF持仓，长期市场回报预期 8%"
        else:
            # 正常范围，使用行业基准
            expected_return = base_return
            adj_reason = f"行业基准预期回报 {base_return*100:.0f}%"

        # 如果持有时间很短，不确定性更高，稍微下调预期
        if days < 20:
            expected_return *= 0.9
            adj_reason += " (持有<20天，不确定性溢价)"

        # ---- 步骤3: 确定性系数 ----
        base_certainty = self._OPPORTUNITY_COST_PARAMS["certainty"].get(sector, 0.5)

        # 根据盈亏调整确定性
        if pnl_pct <= -35:
            certainty_adj = -0.15  # 深度亏损意味着判断可能出错
        elif pnl_pct <= -20:
            certainty_adj = -0.10
        elif pnl_pct >= 40:
            certainty_adj = -0.10  # 大幅盈利后不确定性增加
        elif pnl_pct >= 25:
            certainty_adj = -0.05
        else:
            certainty_adj = 0.0

        # 持有时间越长，确定性越高
        if days > 365:
            certainty_adj += 0.10
        elif days > 180:
            certainty_adj += 0.05
        elif days < 30:
            certainty_adj -= 0.10

        certainty = max(0.1, min(1.0, base_certainty + certainty_adj))

        # ---- 步骤4: 机会得分 ----
        opportunity_score = expected_return * certainty

        # ---- 年化预期收益（百分比） ----
        expected_annual_pct = expected_return * 100

        # ---- 构建结果 ----
        result = {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "market": market,
            "weight": round(weight, 1),
            "pnl_pct": round(pnl_pct, 1),
            "holding_days": days,
            "expected_return": round(expected_annual_pct, 1),
            "certainty": round(certainty, 2),
            "opportunity_score": round(opportunity_score, 4),
            "adj_reason": adj_reason,
        }

        return result

    # ================================================================
    # 4. 压力测试 (Stress Testing)
    # ================================================================
    def stress_testing(self) -> Dict:
        """
        四情景压力测试。

        场景:
            1. 全球衰退 (Global Recession)
            2. 中美脱钩升级 (US-China Escalation)
            3. 利率飙升 (Rate Spike)
            4. 科技泡沫破裂 (Tech Bubble Burst)

        返回:
            {
                "scenarios": dict,       # 每个场景的详细结果
                "worst_case": dict,      # 最差场景
                "best_case": dict,       # 最佳场景
                "max_drawdown": float,   # 最大回撤
                "resilience_score": str, # 组合韧性评分
                "recommendations": list, # 建议
            }
        """
        self.logger.info("开始四情景压力测试...")
        nc = self.non_cash_holdings

        scenario_results = {}

        for scenario_name, scenario in self._STRESS_SCENARIOS.items():
            total_impact = Decimal("0")
            total_value_before = Decimal("0")
            details = []

            for h in nc:
                sector = h.get("sector", "")
                weight = _exact(h.get("weight", 0)) / Decimal("100")
                mv = _exact(h.get("market_value_cny", 0))

                if self.total_value > 0:
                    # 使用组合总市值作为基准
                    total_value_before = self.total_value

                    # 获取该行业的冲击系数
                    sector_shock = scenario["sector_adjust"].get(sector, scenario["equity_shock"])

                    # 计算冲击后的价值变化
                    impact = weight * _exact(sector_shock)

                    # 按持仓权重计入总影响
                    total_impact += impact

                    details.append({
                        "ticker": h.get("ticker", ""),
                        "name": h.get("name", ""),
                        "sector": sector,
                        "weight": round(h.get("weight", 0), 1),
                        "sector_shock": sector_shock,
                        "impact_pct": round(float(impact) * 100, 2),
                    })

            # 总冲击百分比
            total_impact_pct = float(total_impact) * 100

            # 估计冲击后组合价值
            if self.total_value > 0:
                impacted_value = float(self.total_value) * (1 + float(total_impact))
            else:
                impacted_value = 0

            # 按冲击大小排序
            details.sort(key=lambda x: x["impact_pct"])

            scenario_results[scenario_name] = {
                "description": scenario["description"],
                "total_impact_pct": round(total_impact_pct, 2),
                "impacted_value": round(impacted_value, 2),
                "details": details,
                "severity": (
                    "critical" if total_impact_pct <= -30
                    else "severe" if total_impact_pct <= -20
                    else "moderate" if total_impact_pct <= -10
                    else "mild"
                ),
            }

        # ---- 找出最差和最佳场景 ----
        sorted_scenarios = sorted(
            scenario_results.items(),
            key=lambda x: x[1]["total_impact_pct"],
        )
        worst_case = sorted_scenarios[0] if sorted_scenarios else None
        best_case = sorted_scenarios[-1] if sorted_scenarios else None

        # ---- 最大回撤 ----
        max_drawdown = abs(worst_case[1]["total_impact_pct"]) if worst_case else 0

        # ---- 组合韧性评分 ----
        if max_drawdown > 30:
            resilience = "脆弱 — 在极端情景下可能亏损超过 30%，需加强防御配置"
        elif max_drawdown > 20:
            resilience = "较弱 — 极端情景下亏损 20-30%，建议增加对冲或防御性资产"
        elif max_drawdown > 15:
            resilience = "一般 — 极端情景下亏损 15-20%，在可接受范围内"
        elif max_drawdown > 10:
            resilience = "较好 — 极端情景下亏损 10-15%，组合韧性较好"
        else:
            resilience = "优秀 — 极端情景下亏损不到 10%，组合防御性极强"

        # ---- 建议 ----
        recommendations = []
        if worst_case:
            worst_name = worst_case[0]
            worst_impact = worst_case[1]["total_impact_pct"]
            recommendations.append(
                f"最大风险情景: 【{worst_name}】预计组合亏损 {worst_impact:.1f}%。"
            )

        # 检查具体风险敞口
        for sc_name, sc_result in scenario_results.items():
            if sc_result["total_impact_pct"] <= -20:
                recommendations.append(
                    f"【{sc_name}】情景风险较高，建议关注组合中对冲不足的敞口。"
                )

        # 防御性建议
        if "科技泡沫破裂" in scenario_results:
            tech_impact = scenario_results["科技泡沫破裂"]["total_impact_pct"]
            if tech_impact <= -20:
                recommendations.append(
                    "科技泡沫破裂情景下组合亏损较大，建议考虑增加公用事业/消费等防御性资产以降低波动。"
                )

        if "全球衰退" in scenario_results:
            recession_impact = scenario_results["全球衰退"]["total_impact_pct"]
            if recession_impact <= -20:
                recommendations.append(
                    "全球衰退情景下组合风险较高，建议保持适度现金仓位作为缓冲。"
                )

        result = {
            "scenarios": scenario_results,
            "worst_case": {
                "name": worst_case[0] if worst_case else "",
                "impact_pct": worst_case[1]["total_impact_pct"] if worst_case else 0,
                "details": worst_case[1]["details"] if worst_case else [],
            } if worst_case else None,
            "best_case": {
                "name": best_case[0] if best_case else "",
                "impact_pct": best_case[1]["total_impact_pct"] if best_case else 0,
            } if best_case else None,
            "max_drawdown": round(max_drawdown, 2),
            "resilience_score": resilience,
            "recommendations": recommendations,
        }

        self._stress_cache = result
        self.logger.info(
            f"压力测试完成: 最差情景={worst_case[0] if worst_case else 'N/A'}, "
            f"最大回撤={max_drawdown:.1f}%"
        )
        return result

    # ================================================================
    # 5. 综合再平衡建议 (Rebalancing Suggestions)
    # ================================================================
    def rebalancing_suggestions(self) -> Dict:
        """
        综合所有分析结果，生成再平衡建议。

        汇聚:
            - concentration_analysis() 的集中度信号
            - correlation_check() 的风险共振信号
            - opportunity_cost_ranking() 的机会成本排序
            - stress_testing() 的压力测试结果

        返回:
            {
                "suggestions": list,           # 具体建议
                "priority_actions": list,      # 优先行动
                "holdings_to_add": list,       # 建议加仓
                "holdings_to_reduce": list,    # 建议减仓
                "holdings_to_watch": list,     # 建议观察
                "overall_assessment": str,     # 总体评估
                "rebalance_urgency": str,      # 再平衡紧迫性
            }
        """
        self.logger.info("开始生成综合再平衡建议...")

        # 确保所有分析都已运行
        concentration = self._concentration_cache or self.concentration_analysis()
        correlation = self._correlation_cache or self.correlation_check()
        opportunity = self._opportunity_rank_cache or self.opportunity_cost_ranking()
        stress = self._stress_cache or self.stress_testing()

        suggestions = []
        priority_actions = []
        to_add = []
        to_reduce = []
        to_watch = []

        # ---- 从集中度分析提取建议 ----
        conc_signals = concentration.get("signals", [])
        for sig in conc_signals:
            if sig.get("type") == "warning" and sig.get("severity") == "high":
                priority_actions.append({
                    "source": "集中度分析",
                    "action": sig["text"],
                    "priority": "high",
                })

        # ---- 从风险共振提取建议 ----
        cluster_warnings = correlation.get("cluster_warnings", [])
        for cw in cluster_warnings:
            if cw.get("severity") == "high":
                priority_actions.append({
                    "source": "风险共振检测",
                    "action": cw["text"],
                    "priority": "high",
                })
            elif cw.get("severity") == "medium":
                suggestions.append({
                    "source": "风险共振检测",
                    "action": cw["text"],
                    "priority": "medium",
                })

        # ---- 从机会成本排序提取建议 ----
        rankings = opportunity.get("rankings", [])
        bottom_holdings = opportunity.get("bottom_holdings", [])
        top_opportunities = opportunity.get("top_opportunities", [])

        # 建议减仓：机会得分低且权重大的持仓
        for bh in bottom_holdings:
            if bh.get("weight", 0) >= 10 and bh.get("opportunity_score", 1) < 0.08:
                to_reduce.append({
                    "ticker": bh.get("ticker", ""),
                    "name": bh.get("name", ""),
                    "sector": bh.get("sector", ""),
                    "weight": bh.get("weight", 0),
                    "opportunity_score": bh.get("opportunity_score", 0),
                    "reason": (
                        f"机会得分 {bh['opportunity_score']:.4f} 偏低，权重 {bh['weight']:.1f}% 较高，"
                        f"预期年化 {bh.get('expected_return', 0):.1f}%，确定性 {bh.get('certainty', 0):.2f}。"
                        "考虑将资金重新配置到更高机会得分的持仓。"
                    ),
                })

        # 建议加仓：机会得分高且权重低的持仓
        for top in top_opportunities:
            if top.get("weight", 100) < 10 and top.get("opportunity_score", 0) > 0.12:
                to_add.append({
                    "ticker": top.get("ticker", ""),
                    "name": top.get("name", ""),
                    "sector": top.get("sector", ""),
                    "weight": top.get("weight", 0),
                    "opportunity_score": top.get("opportunity_score", 0),
                    "reason": (
                        f"机会得分 {top['opportunity_score']:.4f} 较高，权重 {top['weight']:.1f}% 偏低，"
                        f"预期年化 {top.get('expected_return', 0):.1f}%，确定性 {top.get('certainty', 0):.2f}。"
                        "如果逻辑未变，是巴菲特机会成本框架下的加仓候选。"
                    ),
                })

        # 建议观察：机会得分中等但权重极端的
        for r in rankings:
            if r.get("weight", 0) > 25 and r.get("opportunity_score", 1) < 0.10:
                to_watch.append({
                    "ticker": r.get("ticker", ""),
                    "name": r.get("name", ""),
                    "sector": r.get("sector", ""),
                    "weight": r.get("weight", 0),
                    "opportunity_score": r.get("opportunity_score", 0),
                    "reason": "权重偏高但机会得分一般，需持续跟踪基本面变化",
                })

        # ---- 从压力测试提取建议 ----
        stress_recs = stress.get("recommendations", [])
        for rec in stress_recs:
            suggestions.append({
                "source": "压力测试",
                "action": rec,
                "priority": "medium",
            })

        # ---- 现金管理建议 ----
        cash_ratio = concentration.get("cash_ratio", 0)
        if cash_ratio > 25:
            suggestions.append({
                "source": "现金管理",
                "action": f"现金占比 {cash_ratio:.1f}% 较高，建议逐步配置到高确定性机会中。",
                "priority": "medium",
            })
        elif cash_ratio < 5:
            suggestions.append({
                "source": "现金管理",
                "action": f"现金占比 {cash_ratio:.1f}% 极低，建议保留至少 5% 的现金缓冲。",
                "priority": "medium",
            })

        # ---- 总体评估 ----
        stress_severity = stress.get("max_drawdown", 0)
        if stress_severity > 25:
            overall = "组合防御性偏弱，需要结构性调整以降低极端情景下的回撤风险"
            urgency = "高 — 建议在未来1-2周内执行再平衡"
        elif stress_severity > 15:
            overall = "组合抗风险能力一般，建议逐步优化持仓结构"
            urgency = "中 — 建议在未来1个月内逐步调整"
        elif stress_severity > 10:
            overall = "组合结构较为均衡，风险可控"
            urgency = "低 — 可继续观察，无需大幅调整"
        else:
            overall = "组合结构优秀，风险抵御能力强"
            urgency = "极低 — 当前结构合理，无需调整"

        # 如果有高风险行动，提升紧迫性
        if len(priority_actions) > 2:
            urgency = "高 — 存在多个高风险信号，建议尽快审查并执行再平衡"
            overall = "组合存在多个风险点，建议尽快进行结构性调整"

        result = {
            "suggestions": suggestions,
            "priority_actions": priority_actions,
            "holdings_to_add": to_add,
            "holdings_to_reduce": to_reduce,
            "holdings_to_watch": to_watch,
            "overall_assessment": overall,
            "rebalance_urgency": urgency,
        }

        self.logger.info(
            f"再平衡建议生成完成: {len(priority_actions)} 个优先行动, "
            f"{len(to_add)} 个建议加仓, {len(to_reduce)} 个建议减仓"
        )
        return result

    # ================================================================
    # 全量审查 (Full Review)
    # ================================================================
    def full_review(self) -> Dict:
        """
        运行所有分析并返回完整报告。

        返回:
            {
                "timestamp": str,                # 分析时间
                "summary": dict,                 # 组合摘要
                "concentration": dict,           # 集中度分析
                "correlation": dict,             # 风险共振检测
                "opportunity_cost": dict,        # 机会成本排序
                "stress_test": dict,             # 压力测试
                "rebalancing": dict,             # 再平衡建议
                "key_metrics": dict,             # 关键指标汇总
            }
        """
        self.logger.info("=" * 60)
        self.logger.info("PortfolioReviewEngine 开始全量审查...")
        self.logger.info("=" * 60)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 运行所有分析
        concentration = self.concentration_analysis()
        correlation = self.correlation_check()
        opportunity_cost = self.opportunity_cost_ranking()
        stress_test = self.stress_testing()
        rebalancing = self.rebalancing_suggestions()

        # 关键指标汇总
        key_metrics = {
            "总持仓数": self.summary.get("num_holdings", 0),
            "非现金持仓": concentration.get("non_cash_count", 0),
            "总市值 (CNY)": round(self.summary.get("total_value_cny", 0), 2),
            "总盈亏 (%)": round(self.summary.get("total_pnl_pct", 0), 2),
            "Top3 集中度 (%)": concentration.get("top_3_weight", 0),
            "Top5 集中度 (%)": concentration.get("top_5_weight", 0),
            "现金比例 (%)": concentration.get("cash_ratio", 0),
            "有效持仓数 (1/HHI)": concentration.get("effective_holdings", 0),
            "平均相关性": correlation.get("correlation_matrix", {}).get("avg_correlation", 0),
            "风险集群数": len(correlation.get("risk_clusters", [])),
            "压力测试最大回撤 (%)": stress_test.get("max_drawdown", 0),
            "平均机会得分": opportunity_cost.get("avg_opportunity_score", 0),
            "再平衡紧迫性": rebalancing.get("rebalance_urgency", ""),
        }

        report = {
            "timestamp": timestamp,
            "summary": {
                "name": self.summary.get("name", "未命名组合"),
                "total_value_cny": round(self.summary.get("total_value_cny", 0), 2),
                "total_pnl": round(self.summary.get("total_pnl", 0), 2),
                "total_pnl_pct": round(self.summary.get("total_pnl_pct", 0), 2),
                "num_holdings": self.summary.get("num_holdings", 0),
                "num_positive": self.summary.get("num_positive", 0),
                "num_negative": self.summary.get("num_negative", 0),
                "annualized_return": round(self.summary.get("annualized_return", 0), 2),
                "weighted_holding_days": round(self.summary.get("weighted_holding_days", 0), 1),
            },
            "concentration": concentration,
            "correlation": correlation,
            "opportunity_cost": opportunity_cost,
            "stress_test": stress_test,
            "rebalancing": rebalancing,
            "key_metrics": key_metrics,
        }

        self.logger.info("=" * 60)
        self.logger.info("PortfolioReviewEngine 全量审查完成")
        self.logger.info(f"  压力测试最大回撤: {stress_test.get('max_drawdown', 0):.1f}%")
        self.logger.info(f"  再平衡紧迫性: {rebalancing.get('rebalance_urgency', '')}")
        self.logger.info("=" * 60)

        return report

    # ================================================================
    # 打印报告 (终端输出)
    # ================================================================
    def print_report(self, report: Optional[Dict] = None):
        """
        打印全量审查报告到终端。

        参数:
            report: Dict — 如为 None，则自动运行 full_review()
        """
        if report is None:
            report = self.full_review()

        print("\n" + "=" * 70)
        print(f"  组合持仓深度审查报告")
        print(f"  {report['timestamp']}")
        print(f"  组合: {report['summary'].get('name', 'N/A')}")
        print("=" * 70)

        # ---- 关键指标 ----
        print("\n【关键指标】")
        for k, v in report.get("key_metrics", {}).items():
            print(f"  {k}: {v}")

        # ---- 集中度 ----
        conc = report.get("concentration", {})
        print(f"\n【集中度分析】")
        print(f"  Top3 权重: {conc.get('top_3_weight', 0):.1f}%")
        print(f"  Top5 权重: {conc.get('top_5_weight', 0):.1f}%")
        print(f"  现金比例: {conc.get('cash_ratio', 0):.1f}%")
        print(f"  赫芬达尔指数: {conc.get('herfindahl_index', 0):.4f}")
        print(f"  有效持仓数: {conc.get('effective_holdings', 0):.1f}")
        print(f"  评估: {conc.get('assessment', '')}")

        # ---- 风险共振 ----
        corr = report.get("correlation", {})
        print(f"\n【风险共振检测】")
        print(f"  平均相关性: {corr.get('correlation_matrix', {}).get('avg_correlation', 0):.3f}")
        print(f"  风险集群数: {len(corr.get('risk_clusters', []))}")
        for cl in corr.get("risk_clusters", []):
            tickers = ", ".join(m["ticker"] for m in cl["members"])
            print(f"    集群: [{tickers}] 合计权重 {cl['total_weight']:.1f}%")
        print(f"  分散化评估: {corr.get('overall_diversification', '')}")

        # ---- 机会成本 ----
        opp = report.get("opportunity_cost", {})
        print(f"\n【机会成本排序】")
        print(f"  平均机会得分: {opp.get('avg_opportunity_score', 0):.4f}")
        print(f"  最佳机会:")
        for top in opp.get("top_opportunities", []):
            print(f"    {top['ticker']} ({top['name']}): 预期 {top['expected_return']:.1f}%, "
                  f"确定性 {top['certainty']:.2f}, 得分 {top['opportunity_score']:.4f}")
        if opp.get("bottom_holdings"):
            print(f"  考虑替换:")
            for bh in opp.get("bottom_holdings", []):
                print(f"    {bh['ticker']} ({bh['name']}): 得分 {bh['opportunity_score']:.4f}")

        # ---- 压力测试 ----
        stress = report.get("stress_test", {})
        print(f"\n【压力测试】")
        print(f"  最大回撤: {stress.get('max_drawdown', 0):.1f}%")
        print(f"  韧性评分: {stress.get('resilience_score', '')}")
        for sc_name, sc_result in stress.get("scenarios", {}).items():
            print(f"    {sc_name}: {sc_result['total_impact_pct']:.1f}% ({sc_result['severity']})")

        # ---- 再平衡建议 ----
        rebal = report.get("rebalancing", {})
        print(f"\n【再平衡建议】")
        print(f"  紧迫性: {rebal.get('rebalance_urgency', '')}")
        print(f"  总体评估: {rebal.get('overall_assessment', '')}")

        if rebal.get("priority_actions"):
            print(f"\n  优先行动:")
            for pa in rebal["priority_actions"]:
                print(f"    [高优先级] {pa['action']}")

        if rebal.get("holdings_to_add"):
            print(f"\n  建议加仓:")
            for ha in rebal["holdings_to_add"]:
                print(f"    + {ha['ticker']} ({ha['name']}): {ha['reason']}")

        if rebal.get("holdings_to_reduce"):
            print(f"\n  建议减仓:")
            for hr in rebal["holdings_to_reduce"]:
                print(f"    - {hr['ticker']} ({hr['name']}): {hr['reason']}")

        if rebal.get("suggestions"):
            print(f"\n  其他建议:")
            for s in rebal["suggestions"]:
                print(f"    [{s['source']}] {s['action']}")

        print("\n" + "=" * 70)
        print("  报告结束")
        print("=" * 70)


# ====================================================================
# 快速测试 (CLI)
# ====================================================================

# ====================================================================
# Part 2: IncomeAnalysisEngine + DeepLogicEngine (五阶深度逻辑引擎)
# ====================================================================

class IncomeAnalysisEngine:
    """
    分红/股息收入分析引擎
    对组合中适合收入策略的持仓（银行、高股息ETF等）进行分红可持续性检查
    """

    def __init__(self, holdings: List[Dict], summary: Dict):
        self.holdings = holdings
        self.summary = summary

    # ------------------------------------------------------------------
    # 1. 分红可持续性检查
    # ------------------------------------------------------------------

    def dividend_sustainability_check(self, holding: dict, summary: dict) -> dict:
        """
        评估持仓的分红可持续性

        参数:
            holding: 单只持仓字典
            summary: 组合汇总字典

        返回:
            dict: {score, sustainability, payout_coverage, dividend_yield_est, details}
        """
        result = {
            "score": 3.0,
            "sustainability": "未知",
            "payout_coverage": 0.0,
            "dividend_yield_est": 0.0,
            "details": [],
            "color": "neutral",
        }

        sector = holding.get("sector", "")
        name = holding.get("name", "")
        ticker = holding.get("ticker", "")
        pnl_pct = _safe_float(holding.get("pnl_pct", 0))
        holding_days = _safe_int(holding.get("holding_days", 0))
        notes = holding.get("notes", "")

        sector_params = _get_income_sector_params(sector)
        typical_payout = sector_params["typical_payout_ratio"]
        div_yield_est = sector_params["div_yield_est"]
        earnings_stability = sector_params["earnings_stability"]

        # 初始股息率估计
        result["dividend_yield_est"] = div_yield_est

        # ----------------------------------------------------------
        # 银行类：检查 CET1 比率和派息率
        # ----------------------------------------------------------
        if "银行" in sector or "金融" in sector:
            # 默认基于行业常识评估
            cet1_threshold = sector_params.get("cet1_threshold", 0.11)

            # 针对特定银行设置已知参数
            if "招商" in name or "招行" in name:
                result["details"].append("招商银行: 2024年报CET1充足率约13.7%，高于监管要求（估计）")
                result["details"].append(f"招商银行: 派息率约30-35%，在银行中属于合理水平（估计）")
                result["details"].append("招商银行: 零售银行优势带来稳定的净息差和手续费收入")
                result["payout_coverage"] = 3.0  # 利润覆盖股息约3倍
                result["dividend_yield_est"] = 0.05  # 估计股息率约5%
                result["score"] = 4.0
                result["sustainability"] = "strong"
                result["color"] = "positive"
            else:
                # 其他银行基于常识估计
                result["details"].append(f"{name}: 银行类资产，CET1充足率需>={cet1_threshold*100:.0f}%（估计）")
                result["details"].append(f"{name}: 派息率约{typical_payout*100:.0f}%，需关注不良贷款率变化")
                result["payout_coverage"] = 2.5
                result["dividend_yield_est"] = 0.045
                result["score"] = 3.5
                result["sustainability"] = "adequate"
                result["color"] = "neutral"

        # ----------------------------------------------------------
        # ETF 类：检查股息率 vs 费用率
        # ----------------------------------------------------------
        elif "ETF" in sector:
            expense_ratio_est = 0.0015  # 估计平均费率 0.15%
            if "道指" in sector:
                expense_ratio_est = 0.0016  # DIA 费率约 0.16%
                div_yield_est = 0.018
            elif "港股" in sector:
                expense_ratio_est = 0.0050  # 港股科技ETF费率较高
                div_yield_est = 0.01
            elif "全球" in sector:
                expense_ratio_est = 0.0007  # VT 费率约 0.07%
                div_yield_est = 0.02
            elif "通信" in sector:
                expense_ratio_est = 0.0030
                div_yield_est = 0.015
            elif "科创" in sector:
                expense_ratio_est = 0.0050
                div_yield_est = 0.005  # 科创板ETF股息率较低

            # 特定ETF
            ticker_map = {
                "VT": {"expense": 0.0007, "yield": 0.019},
                "DIA": {"expense": 0.0016, "yield": 0.018},
            }
            if ticker.upper() in ticker_map:
                tm = ticker_map[ticker.upper()]
                expense_ratio_est = tm["expense"]
                div_yield_est = tm["yield"]

            net_yield = div_yield_est - expense_ratio_est
            if net_yield > 0:
                result["details"].append(
                    f"ETF股息率约{div_yield_est*100:.2f}%，费用率约{expense_ratio_est*100:.2f}%，"
                    f"净收益率为{net_yield*100:.2f}%（估计）"
                )
                result["sustainability"] = "adequate"
                result["score"] = 3.0
                result["color"] = "neutral"
            else:
                result["details"].append(
                    f"ETF股息率约{div_yield_est*100:.2f}%，费用率约{expense_ratio_est*100:.2f}%，"
                    f"净收益率为负（估计），分红策略不具吸引力"
                )
                result["sustainability"] = "weak"
                result["score"] = 2.0
                result["color"] = "negative"

            result["dividend_yield_est"] = div_yield_est
            result["payout_coverage"] = net_yield

        # ----------------------------------------------------------
        # 其他行业（公用事业、能源、REIT等）
        # ----------------------------------------------------------
        else:
            # 根据 notes 判断
            has_div_note = any(kw in notes.lower() for kw in ["分红", "股息", "红利", "高股息"])

            if earnings_stability == "high":
                result["details"].append(f"{name}: 行业收益稳定性高，分红可持续性较好（估计）")
                result["sustainability"] = "adequate"
                result["score"] = 3.5
                result["color"] = "neutral"
            elif earnings_stability == "medium":
                result["details"].append(f"{name}: 行业收益稳定性中等，分红受周期影响（估计）")
                result["sustainability"] = "weak"
                result["score"] = 2.5
                result["color"] = "neutral"
            else:
                result["details"].append(f"{name}: 行业收益稳定性较低，分红可持续性存疑（估计）")
                result["sustainability"] = "weak"
                result["score"] = 2.0
                result["color"] = "negative"

            if has_div_note:
                result["details"].append(f"持仓备注中标注了分红策略，关注实际分红率")
                result["score"] = min(result["score"] + 0.5, 5.0)

            result["dividend_yield_est"] = div_yield_est
            result["payout_coverage"] = 1.0 / typical_payout if typical_payout > 0 else 0

        # ----------------------------------------------------------
        # 通用调整：持仓盈亏状况对分红的影响
        # ----------------------------------------------------------
        if pnl_pct <= -20:
            result["details"].append(f"注意: 当前亏损{pnl_pct:.1f}%，可能需要减少分红再投入以保留现金")
            result["score"] = max(result["score"] - 0.5, 1.0)
        elif pnl_pct >= 20:
            result["details"].append(f"当前盈利{pnl_pct:.1f}%，分红再投资可进一步摊薄成本")
            result["score"] = min(result["score"] + 0.3, 5.0)

        if holding_days > 180:
            result["details"].append(f"已持有{holding_days}天，长期持有符合分红复利策略")
            result["score"] = min(result["score"] + 0.3, 5.0)

        # 最终评分取整
        result["score"] = round(result["score"], 1)

        # 如果 sustainability 未赋值，根据评分推断
        if result["sustainability"] == "未知":
            if result["score"] >= 4.0:
                result["sustainability"] = "strong"
                result["color"] = "positive"
            elif result["score"] >= 2.5:
                result["sustainability"] = "adequate"
                result["color"] = "neutral"
            else:
                result["sustainability"] = "weak"
                result["color"] = "negative"

        return result

    # ------------------------------------------------------------------
    # 2. 三情景收入分析
    # ------------------------------------------------------------------

    def three_scenario_income(self, holding: dict) -> dict:
        """
        为持仓构建三种情景的收入预测

        参数:
            holding: 单只持仓字典

        返回:
            dict: {
                scenarios: {base, adverse, severe},
                current_income_est,
                details
            }
        """
        name = holding.get("name", "")
        ticker = holding.get("ticker", "")
        sector = holding.get("sector", "")
        market_value = _safe_float(holding.get("market_value_cny", 0))
        pnl_pct = _safe_float(holding.get("pnl_pct", 0))
        cost_total = _safe_float(holding.get("cost_total", 0))

        # 估计当前股息率
        sector_params = _get_income_sector_params(sector)
        div_yield = sector_params["div_yield_est"]

        if "招商" in holding.get("name", "") or "招行" in holding.get("name", ""):
            div_yield = 0.05
        elif holding.get("ticker", "").upper() == "VT":
            div_yield = 0.019
        elif holding.get("ticker", "").upper() == "DIA":
            div_yield = 0.018

        # 当前持仓市值对应的年化股息收入估计
        current_annual_income = market_value * div_yield

        # 每股股息估计（基于市值和持仓量）
        shares = _safe_float(holding.get("shares", 0))
        div_per_share_est = 0.0
        if shares > 0:
            # 总市值 = shares * price, 总股息 = market_value * div_yield
            total_div = current_annual_income
            div_per_share_est = total_div / shares

        # 构建三情景
        scenarios = {}

        # ---- 基准情景（Base): 股息增长5%/年，价格稳定 ----
        base_price = _safe_float(holding.get("current_price", 0))
        base_div_per_share = div_per_share_est * 1.05  # 增长5%
        base_div_yield = div_yield * 1.05
        base_annual_income = market_value * base_div_yield
        base_total_return = base_annual_income  # 价格不变，仅股息收益

        scenarios["base"] = {
            "name": "基准情景",
            "description": "股息增长5%/年，价格保持稳定",
            "assumptions": {
                "div_growth_rate": 0.05,
                "price_change": 0.0,
                "div_yield": round(base_div_yield, 4),
                "div_per_share": round(base_div_per_share, 4),
            },
            "annual_income_cny": round(base_annual_income, 2),
            "total_return_cny": round(base_total_return, 2),
            "total_return_pct": round(base_div_yield * 100, 2),
            "income_over_3y": round(base_annual_income * 3, 2),
            "income_over_5y": round(base_annual_income * 5, 2),
        }

        # ---- 不利情景（Adverse): 股息削减20%，价格下跌15% ----
        adverse_price = base_price * 0.85
        adverse_div_per_share = div_per_share_est * 0.80  # 削减20%
        adverse_market_value = shares * adverse_price
        adverse_annual_income = adverse_market_value * (adverse_div_per_share * shares / adverse_market_value if adverse_market_value > 0 else 0)
        if shares > 0 and adverse_market_value > 0:
            adverse_implied_yield = (adverse_div_per_share * shares) / adverse_market_value
        else:
            adverse_implied_yield = 0.0
        adverse_total_return = adverse_annual_income + (adverse_market_value - market_value)

        scenarios["adverse"] = {
            "name": "不利情景",
            "description": "股息削减20%，价格下跌15%",
            "assumptions": {
                "div_cut": 0.20,
                "price_decline": -0.15,
                "implied_div_yield": round(adverse_implied_yield, 4),
                "div_per_share": round(adverse_div_per_share, 4),
            },
            "annual_income_cny": round(adverse_annual_income, 2),
            "total_return_cny": round(adverse_total_return, 2),
            "total_return_pct": round((adverse_total_return / market_value * 100) if market_value > 0 else 0, 2),
            "income_over_3y": round(adverse_annual_income * 3, 2),
            "income_over_5y": round(adverse_annual_income * 5, 2),
            "capital_loss": round(adverse_market_value - market_value, 2),
        }

        # ---- 严重情景（Severe): 股息暂停，价格下跌30% ----
        severe_price = base_price * 0.70
        severe_market_value = shares * severe_price
        severe_annual_income = 0.0  # 股息暂停
        severe_total_return = severe_market_value - market_value  # 仅资本损失

        scenarios["severe"] = {
            "name": "严重情景",
            "description": "股息暂停，价格下跌30%",
            "assumptions": {
                "div_suspended": True,
                "price_decline": -0.30,
            },
            "annual_income_cny": 0.0,
            "total_return_cny": round(severe_total_return, 2),
            "total_return_pct": round((severe_total_return / market_value * 100) if market_value > 0 else 0, 2),
            "income_over_3y": 0.0,
            "income_over_5y": 0.0,
            "capital_loss": round(severe_market_value - market_value, 2),
        }

        # 计算概率权重收入（主观估计）
        prob_weights = {"base": 0.60, "adverse": 0.25, "severe": 0.15}
        expected_income = sum(
            prob_weights[k] * v["annual_income_cny"]
            for k, v in scenarios.items()
        )

        return {
            "ticker": ticker,
            "name": name,
            "current_market_value_cny": round(market_value, 2),
            "current_div_yield_est": round(div_yield, 4),
            "current_annual_income_est": round(current_annual_income, 2),
            "expected_income_cny": round(expected_income, 2),
            "scenarios": scenarios,
            "details": [
                f"基准情景: 年股息收入约{scenarios['base']['annual_income_cny']:.1f}元",
                f"不利情景: 年股息收入约{scenarios['adverse']['annual_income_cny']:.1f}元 + 资本损失{scenarios['adverse']['capital_loss']:.1f}元",
                f"严重情景: 股息暂停，资本损失约{scenarios['severe']['capital_loss']:.1f}元",
                f"概率加权期望收入: {expected_income:.1f}元/年",
            ],
        }

    # ------------------------------------------------------------------
    # 3. 批量分析所有收入类持仓
    # ------------------------------------------------------------------

    def analyze_all_income(self, holdings: Optional[List[Dict]] = None,
                           summary: Optional[Dict] = None) -> List[Dict]:
        """
        对组合中所有适合收入分析的持仓批量运行收入分析

        参数:
            holdings: 持仓列表（默认使用 self.holdings）
            summary: 组合汇总（默认使用 self.summary）

        返回:
            List[Dict]: 每个收入类持仓的分析结果
        """
        if holdings is None:
            holdings = self.holdings
        if summary is None:
            summary = self.summary

        income_holdings = [h for h in holdings if _is_income_eligible(h)]

        if not income_holdings:
            return [{
                "type": "empty",
                "message": "组合中未发现适合收入分析的持仓（银行/金融/高股息ETF等）",
                "details": [],
            }]

        results = []
        total_annual_income_est = 0.0

        for h in income_holdings:
            # 分红可持续性检查
            sustainability = self.dividend_sustainability_check(h, summary)

            # 三情景收入预测
            scenarios = self.three_scenario_income(h)

            # 汇总
            item = {
                "ticker": h.get("ticker", ""),
                "name": h.get("name", ""),
                "sector": h.get("sector", ""),
                "market_value_cny": round(_safe_float(h.get("market_value_cny", 0)), 2),
                "weight": round(_safe_float(h.get("weight", 0)), 2),
                "sustainability": sustainability,
                "scenarios": scenarios,
                "current_annual_income_est": scenarios.get("current_annual_income_est", 0),
            }
            total_annual_income_est += scenarios.get("current_annual_income_est", 0)
            results.append(item)

        # 添加组合级汇总
        portfolio_value = _safe_float(summary.get("total_value_cny", 0))
        income_yield = total_annual_income_est / portfolio_value if portfolio_value > 0 else 0

        return {
            "type": "income_analysis",
            "total_income_holdings": len(income_holdings),
            "total_annual_income_est": round(total_annual_income_est, 2),
            "portfolio_income_yield": round(income_yield * 100, 2),
            "portfolio_value_cny": round(portfolio_value, 2),
            "income_ratio": round(total_annual_income_est / portfolio_value * 100 if portfolio_value > 0 else 0, 2),
            "details": [
                f"组合中适合收入分析的持仓共{len(income_holdings)}只",
                f"估计年化股息总收入: {total_annual_income_est:.1f}元",
                f"组合股息收益率: {income_yield*100:.2f}%",
            ],
            "holdings": results,
        }


# ====================================================================
# DeepLogicEngine — 五阶深度逻辑引擎
# ====================================================================

class DeepLogicEngine:
    """
    五阶深度逻辑引擎

    1. SOTP Segmented Re-rating   — 分部估值重估
    2. Implied Expectation Decoding — 隐含预期解码
    3. Option Value Identification  — 期权价值识别
    4. Game Theory Hedge Analysis   — 博弈论对冲分析
    5. Time-Wall & Terminal Value   — 时间墙与终值
    """

    def __init__(self, holdings: List[Dict], summary: Dict):
        self.holdings = holdings
        self.summary = summary

    # ==================================================================
    # 第一阶: SOTP Segmented Re-rating 分部估值重估
    # ==================================================================

    def sotp_rerating(self, holding: dict) -> dict:
        """
        将持仓拆分为成长/周期/现金流三段进行分部估值

        原理:
          - 成长段: 给高PE (25-35x)
          - 周期段: 给中PE (10-15x)
          - 现金流段: 给低PE (6-10x) 作为保底价值

        参数:
            holding: 单只持仓字典

        返回:
            dict: {segments, weighted_pe, implied_value, upside, details}
        """
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        ticker = holding.get("ticker", "")
        current_price = _safe_float(holding.get("current_price", 0))
        avg_cost = _safe_float(holding.get("avg_cost", 0))
        pnl_pct = _safe_float(holding.get("pnl_pct", 0))
        market_value = _safe_float(holding.get("market_value_cny", 0))

        # 估计每股收益 (EPS) — 基于行业和常识估计
        eps_est = self._estimate_eps(holding)

        # 确定各段权重 — 基于行业特征
        segment_weights = self._get_segment_weights(sector, name, ticker)

        segments = {}
        total_weighted_pe = 0.0
        implied_eps_total = 0.0

        # ---- 成长段 ----
        growth_pe = segment_weights.get("growth_pe", 25)
        growth_weight = segment_weights.get("growth_weight", 0.33)
        growth_eps = eps_est * growth_weight
        growth_value = growth_eps * growth_pe
        segments["growth"] = {
            "name": "成长段",
            "weight_pct": round(growth_weight * 100, 1),
            "pe_multiple": growth_pe,
            "eps_contribution": round(growth_eps, 4),
            "segment_value": round(growth_value, 2),
            "description": segment_weights.get("growth_desc", "成长性业务估值"),
        }
        total_weighted_pe += growth_pe * growth_weight
        implied_eps_total += growth_eps

        # ---- 周期段 ----
        cycle_pe = segment_weights.get("cycle_pe", 12)
        cycle_weight = segment_weights.get("cycle_weight", 0.33)
        cycle_eps = eps_est * cycle_weight
        cycle_value = cycle_eps * cycle_pe
        segments["cycle"] = {
            "name": "周期段",
            "weight_pct": round(cycle_weight * 100, 1),
            "pe_multiple": cycle_pe,
            "eps_contribution": round(cycle_eps, 4),
            "segment_value": round(cycle_value, 2),
            "description": segment_weights.get("cycle_desc", "周期性业务估值"),
        }
        total_weighted_pe += cycle_pe * cycle_weight
        implied_eps_total += cycle_eps

        # ---- 现金流段 ----
        cashflow_pe = segment_weights.get("cashflow_pe", 8)
        cashflow_weight = segment_weights.get("cashflow_weight", 0.34)
        cashflow_eps = eps_est * cashflow_weight
        cashflow_value = cashflow_eps * cashflow_pe
        segments["cashflow"] = {
            "name": "现金流段(保底)",
            "weight_pct": round(cashflow_weight * 100, 1),
            "pe_multiple": cashflow_pe,
            "eps_contribution": round(cashflow_eps, 4),
            "segment_value": round(cashflow_value, 2),
            "description": segment_weights.get("cashflow_desc", "现金流保底价值"),
        }
        total_weighted_pe += cashflow_pe * cashflow_weight
        implied_eps_total += cashflow_eps

        # 加权 PE 和隐含价值
        weighted_pe = round(total_weighted_pe, 1)
        implied_value_per_share = round(implied_eps_total * weighted_pe, 2)
        # 确保每股价值合理
        if implied_value_per_share <= 0:
            implied_value_per_share = current_price * 0.9  # 保守估计

        # 上行/下行空间
        if current_price > 0:
            upside = round((implied_value_per_share / current_price - 1) * 100, 1)
        else:
            upside = 0.0

        # 隐含总市值
        shares = _safe_float(holding.get("shares", 0))
        implied_total_value = implied_value_per_share * shares if shares > 0 else market_value

        details = [
            f"分部估值(SOTP): 成长段{segments['growth']['weight_pct']}%×{growth_pe}PE + "
            f"周期段{segments['cycle']['weight_pct']}%×{cycle_pe}PE + "
            f"现金流段{segments['cashflow']['weight_pct']}%×{cashflow_pe}PE",
            f"加权PE: {weighted_pe}x, 隐含每股价值: {implied_value_per_share:.2f}元",
            f"当前价格: {current_price:.2f}元, 上行空间: {upside:+.1f}%",
        ]

        return {
            "ticker": ticker,
            "name": name,
            "current_price": round(current_price, 2),
            "avg_cost": round(avg_cost, 2),
            "eps_est": round(eps_est, 4),
            "weighted_pe": weighted_pe,
            "implied_value_per_share": implied_value_per_share,
            "implied_total_value_cny": round(implied_total_value, 2),
            "upside_pct": upside,
            "segments": segments,
            "details": details,
        }

    def _estimate_eps(self, holding: dict) -> float:
        """基于行业和名称估计每股收益"""
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        ticker = holding.get("ticker", "")
        current_price = _safe_float(holding.get("current_price", 0))
        avg_cost = _safe_float(holding.get("avg_cost", 0))

        price = current_price if current_price > 0 else avg_cost

        # 行业典型 PE
        sector_pe = {
            "银行/金融": 8,
            "消费/白酒": 25,
            "制药": 30,
            "工业/数据中心": 28,
            "网络安全": 35,
            "半导体": 25,
            "互联网科技": 20,
            "造纸": 12,
            "ETF/全球指数": 20,
            "ETF/道指": 22,
            "ETF/港股科技": 18,
            "ETF/通信": 15,
            "ETF/科创板": 25,
            "另类投资": 10,
        }

        pe = sector_pe.get(sector, 15)
        if pe > 0 and price > 0:
            eps = price / pe
        else:
            eps = 1.0  # 默认

        # 特定股票调整
        name_eps_overrides = {
            "招商银行": 5.5,   # 招行 ~5.5元/股
            "小米集团": 0.8,   # 小米 ~0.8元/股
            "礼来": 12.0,      # LLY ~$12 EPS
        }
        for k, v in name_eps_overrides.items():
            if k in name:
                eps = v
                break

        return eps

    def _get_segment_weights(self, sector: str, name: str, ticker: str) -> dict:
        """根据行业返回三段估值权重和PE倍数"""
        profiles = {
            "银行/金融": {
                "growth_weight": 0.15, "growth_pe": 25, "growth_desc": "财富管理/零售银行成长",
                "cycle_weight": 0.35, "cycle_pe": 10, "cycle_desc": "息差周期/信贷周期",
                "cashflow_weight": 0.50, "cashflow_pe": 8, "cashflow_desc": "存款基础/手续费收入保底",
            },
            "消费/白酒": {
                "growth_weight": 0.40, "growth_pe": 30, "growth_desc": "品牌升级/提价空间",
                "cycle_weight": 0.25, "cycle_pe": 15, "cycle_desc": "消费周期/库存周期",
                "cashflow_weight": 0.35, "cashflow_pe": 10, "cashflow_desc": "品牌护城河/自由现金流",
            },
            "制药": {
                "growth_weight": 0.50, "growth_pe": 30, "growth_desc": "研发管线/新药获批",
                "cycle_weight": 0.20, "cycle_pe": 15, "cycle_desc": "专利周期/药品集采周期",
                "cashflow_weight": 0.30, "cashflow_pe": 10, "cashflow_desc": "成熟药品现金流",
            },
            "工业/数据中心": {
                "growth_weight": 0.55, "growth_pe": 30, "growth_desc": "AI基础设施/数据中心建设",
                "cycle_weight": 0.25, "cycle_pe": 15, "cycle_desc": "资本开支周期",
                "cashflow_weight": 0.20, "cashflow_pe": 10, "cashflow_desc": "电力基础设施服务",
            },
            "网络安全": {
                "growth_weight": 0.60, "growth_pe": 35, "growth_desc": "订阅增长/身份安全市场",
                "cycle_weight": 0.20, "cycle_pe": 15, "cycle_desc": "企业IT预算周期",
                "cashflow_weight": 0.20, "cashflow_pe": 8, "cashflow_desc": "续约收入/客户粘性",
            },
            "半导体": {
                "growth_weight": 0.50, "growth_pe": 30, "growth_desc": "HBM/AI芯片需求",
                "cycle_weight": 0.30, "cycle_pe": 12, "cycle_desc": "存储芯片价格周期",
                "cashflow_weight": 0.20, "cashflow_pe": 8, "cashflow_desc": "成熟制程代工",
            },
            "互联网科技": {
                "growth_weight": 0.40, "growth_pe": 30, "growth_desc": "EV/新业务成长",
                "cycle_weight": 0.30, "cycle_pe": 12, "cycle_desc": "手机出货量/消费电子周期",
                "cashflow_weight": 0.30, "cashflow_pe": 8, "cashflow_desc": "互联网服务/广告收入",
            },
            "造纸": {
                "growth_weight": 0.15, "growth_pe": 20, "growth_desc": "特种纸/新产品",
                "cycle_weight": 0.45, "cycle_pe": 10, "cycle_desc": "纸浆价格周期",
                "cashflow_weight": 0.40, "cashflow_pe": 6, "cashflow_desc": "产能折旧后现金流",
            },
        }

        # 非个股（ETF等）使用简单模型
        if "ETF" in sector:
            return {
                "growth_weight": 0.20, "growth_pe": 20, "growth_desc": "指数增长成分",
                "cycle_weight": 0.30, "cycle_pe": 15, "cycle_desc": "市场周期波动",
                "cashflow_weight": 0.50, "cashflow_pe": 10, "cashflow_desc": "指数长期均值回归",
            }

        for key, val in profiles.items():
            if key in sector:
                return val

        # 默认
        return {
            "growth_weight": 0.33, "growth_pe": 25, "growth_desc": "成长性业务估值（估计）",
            "cycle_weight": 0.33, "cycle_pe": 12, "cycle_desc": "周期性业务估值（估计）",
            "cashflow_weight": 0.34, "cashflow_pe": 8, "cashflow_desc": "现金流保底价值（估计）",
        }

    # ==================================================================
    # 第二阶: Implied Expectation Decoding 隐含预期解码
    # ==================================================================

    def implied_expectation_decode(self, holding: dict) -> dict:
        """
        反向推导当前价格隐含的市场预期

        核心问题: "当前价格在预期什么?"
        方法: 当前价格 / 内在价值 → 隐含增长预期

        参数:
            holding: 单只持仓字典

        返回:
            dict: {implied_growth, narrative, weakest_link, fragility_score}
        """
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        ticker = holding.get("ticker", "")
        current_price = _safe_float(holding.get("current_price", 0))
        avg_cost = _safe_float(holding.get("avg_cost", 0))
        pnl_pct = _safe_float(holding.get("pnl_pct", 0))
        holding_days = _safe_int(holding.get("holding_days", 0))
        annualized_return = _safe_float(holding.get("annualized_return", 0))

        # 估计内在价值
        intrinsic_value = self._estimate_intrinsic_value(holding)

        # 隐含增长预期
        if intrinsic_value > 0 and current_price > 0:
            price_to_intrinsic = current_price / intrinsic_value
        else:
            price_to_intrinsic = 1.0

        # 解码隐含增长率
        # price_to_intrinsic > 1 -> 市场预期高于内在价值（乐观）
        # price_to_intrinsic < 1 -> 市场预期低于内在价值（悲观）
        if price_to_intrinsic >= 1.2:
            implied_growth = "高增长预期"
            implied_growth_pct = (price_to_intrinsic - 1.0) * 100
            narrative = self._build_optimistic_narrative(sector, name, price_to_intrinsic)
            fragility_score = min(price_to_intrinsic * 2, 8.0)  # 越高越脆弱
        elif price_to_intrinsic >= 0.9:
            implied_growth = "合理预期"
            implied_growth_pct = 0.0
            narrative = self._build_neutral_narrative(sector, name)
            fragility_score = 3.0
        else:
            implied_growth = "低增长/负增长预期"
            implied_growth_pct = (price_to_intrinsic - 1.0) * 100
            narrative = self._build_pessimistic_narrative(sector, name, price_to_intrinsic)
            fragility_score = max(1.0, price_to_intrinsic * 2)  # 越低越不脆弱（已priced in）

        # 识别"最薄弱环节"
        weakest_link = self._identify_weakest_link(holding, price_to_intrinsic)

        # 结合持仓盈亏修正脆弱度
        if pnl_pct <= -20:
            fragility_score = max(fragility_score - 1.0, 1.0)  # 已跌，脆弱度降低
        elif pnl_pct >= 30:
            fragility_score = min(fragility_score + 1.0, 9.0)  # 已涨，脆弱度升高

        return {
            "ticker": ticker,
            "name": name,
            "current_price": round(current_price, 2),
            "intrinsic_value_est": round(intrinsic_value, 2),
            "price_to_intrinsic_ratio": round(price_to_intrinsic, 2),
            "implied_growth": implied_growth,
            "implied_growth_pct": round(implied_growth_pct, 1),
            "narrative": narrative,
            "weakest_link": weakest_link,
            "fragility_score": round(fragility_score, 1),
            "fragility_level": "高" if fragility_score >= 6 else "中" if fragility_score >= 3.5 else "低",
            "details": [
                f"当前价格({current_price:.2f}) / 估计内在价值({intrinsic_value:.2f}) = {price_to_intrinsic:.2f}",
                f"隐含增长预期: {implied_growth} ({implied_growth_pct:+.1f}%)",
                f"最薄弱环节: {weakest_link}",
                f"脆弱度评分: {fragility_score:.1f}/10",
            ],
        }

    def _estimate_intrinsic_value(self, holding: dict) -> float:
        """估计内在价值（基于行业合理PE * EPS）"""
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        current_price = _safe_float(holding.get("current_price", 0))
        avg_cost = _safe_float(holding.get("avg_cost", 0))
        price = current_price if current_price > 0 else avg_cost

        # 行业合理PE
        fair_pe_map = {
            "银行/金融": 10,
            "消费/白酒": 22,
            "制药": 25,
            "工业/数据中心": 25,
            "网络安全": 28,
            "半导体": 20,
            "互联网科技": 18,
            "造纸": 10,
            "ETF/全球指数": 18,
            "ETF/道指": 20,
            "ETF/港股科技": 15,
            "ETF/通信": 12,
            "ETF/科创板": 20,
            "另类投资": 8,
        }
        fair_pe = fair_pe_map.get(sector, 15)

        # 特定公司调整
        name_fair_pe = {
            "招商银行": 10,     # 银行合理PE约10x
            "小米集团": 20,     # 小米含EV期权
            "礼来": 30,         # LLY高增长溢价
        }
        for k, v in name_fair_pe.items():
            if k in name:
                fair_pe = v
                break

        # ETF 直接按净值
        if "ETF" in sector:
            return price * 0.95  # 假设ETF折价5%

        eps = self._estimate_eps(holding)
        intrinsic = eps * fair_pe

        if intrinsic <= 0:
            intrinsic = price * 0.85  # 保守估计

        return intrinsic

    def _build_optimistic_narrative(self, sector: str, name: str, ratio: float) -> str:
        """构建乐观叙事"""
        narratives = {
            "银行/金融": f"市场预期{name}在零售银行领域持续领先，净息差企稳回升，不良率可控",
            "消费/白酒": f"市场预期{name}品牌力持续提升，消费升级趋势不变",
            "制药": f"市场预期{name}核心管线顺利推进，新药放量超预期",
            "工业/数据中心": f"市场预期{name}受益AI资本开支浪潮，订单持续增长",
            "网络安全": f"市场预期{name}在身份安全领域持续扩大份额，订阅收入高增长",
            "半导体": f"市场预期{name}在HBM/AI芯片领域技术领先，量价齐升",
            "互联网科技": f"市场预期{name}新业务（EV等）取得突破，估值重构",
            "造纸": f"市场预期{name}成本优势扩大，行业集中度提升",
        }
        for key, val in narratives.items():
            if key in sector:
                return val
        return f"当前价格隐含{name}的乐观增长预期 ({ratio:.1f}x市净率)"

    def _build_neutral_narrative(self, sector: str, name: str) -> str:
        """构建中性叙事"""
        return f"当前价格对{name}的预期较为合理，市场定价基本反映了行业基本面"

    def _build_pessimistic_narrative(self, sector: str, name: str, ratio: float) -> str:
        """构建悲观叙事"""
        narratives = {
            "银行/金融": f"市场担忧{name}息差收窄、资产质量承压",
            "消费/白酒": f"市场担忧消费降级、行业库存压力",
            "互联网科技": f"市场担忧{name}新业务烧钱、核心业务增长放缓",
            "半导体": f"市场担忧半导体周期下行、产能过剩",
        }
        for key, val in narratives.items():
            if key in sector:
                return val
        return f"当前价格隐含{name}的悲观预期 ({ratio:.1f}x市净率)，市场可能过度反应利空"

    def _identify_weakest_link(self, holding: dict, ratio: float) -> str:
        """识别持仓叙事中最薄弱的环节"""
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        pnl_pct = _safe_float(holding.get("pnl_pct", 0))

        weak_links = {
            "银行/金融": "净息差持续收窄超预期",
            "消费/白酒": "消费习惯代际变迁",
            "制药": "专利悬崖/竞争格局恶化",
            "工业/数据中心": "AI资本开支周期性回落",
            "网络安全": "竞争加剧导致增长放缓",
            "半导体": "存储芯片价格周期性下跌",
            "互联网科技": "新业务持续亏损无改善",
            "造纸": "需求结构性萎缩",
            "ETF/全球指数": "全球系统性风险",
            "ETF/道指": "美国经济衰退",
            "ETF/港股科技": "地缘政治风险加剧",
            "另类投资": "流动性枯竭",
        }
        for key, val in weak_links.items():
            if key in sector:
                base_link = val
                break
        else:
            base_link = "行业基本面变化超预期"

        # 根据盈亏调整
        if pnl_pct <= -20:
            base_link += "（已部分反映在价格中）"
        elif pnl_pct >= 20:
            base_link += "（当前价格尚未反映此风险）"

        return base_link

    # ==================================================================
    # 第三阶: Option Value Identification 期权价值识别
    # ==================================================================

    def option_value_identify(self, holding: dict) -> dict:
        """
        识别持仓中的"深度虚值期权"——即低概率高赔率的潜在催化事件

        类型:
          1. 技术突破 (如 LLY 的 GLP-1 管线)
          2. 客户认证 (如 VRT 的数据中心合同)
          3. 业务反转 (如 小米的 EV 业务)

        参数:
            holding: 单只持仓字典

        返回:
            dict: {embedded_options, total_option_value, details}
        """
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        ticker = holding.get("ticker", "")
        current_price = _safe_float(holding.get("current_price", 0))
        market_value = _safe_float(holding.get("market_value_cny", 0))
        pnl_pct = _safe_float(holding.get("pnl_pct", 0))
        notes = holding.get("notes", "")

        embedded_options = []
        total_option_value = 0.0

        # ---- 识别技术突破期权 ----
        tech_breakthroughs = self._detect_tech_breakthrough(sector, name, ticker, notes)
        for opt in tech_breakthroughs:
            # 期权价值 = 概率 × 潜在收益
            option_value = opt["probability"] * opt["potential_payoff_pct"] / 100.0 * market_value
            opt["option_value_cny"] = round(option_value, 2)
            embedded_options.append(opt)
            total_option_value += option_value

        # ---- 识别客户认证期权 ----
        cert_options = self._detect_certification_options(sector, name, ticker, notes)
        for opt in cert_options:
            option_value = opt["probability"] * opt["potential_payoff_pct"] / 100.0 * market_value
            opt["option_value_cny"] = round(option_value, 2)
            embedded_options.append(opt)
            total_option_value += option_value

        # ---- 识别业务反转期权 ----
        turnaround_options = self._detect_turnaround_options(sector, name, ticker, pnl_pct, notes)
        for opt in turnaround_options:
            option_value = opt["probability"] * opt["potential_payoff_pct"] / 100.0 * market_value
            opt["option_value_cny"] = round(option_value, 2)
            embedded_options.append(opt)
            total_option_value += option_value

        # 排序：按期权价值降序
        embedded_options.sort(key=lambda x: x["option_value_cny"], reverse=True)

        return {
            "ticker": ticker,
            "name": name,
            "current_price": round(current_price, 2),
            "market_value_cny": round(market_value, 2),
            "total_option_value_cny": round(total_option_value, 2),
            "option_value_pct": round(total_option_value / market_value * 100 if market_value > 0 else 0, 2),
            "embedded_options": embedded_options,
            "details": [
                f"识别到 {len(embedded_options)} 个嵌入式期权",
                f"总期权价值: {total_option_value:.1f}元, 占持仓市值 {total_option_value/market_value*100:.1f}%" if market_value > 0 else "总期权价值: 无法计算",
            ],
        }

    def _detect_tech_breakthrough(self, sector: str, name: str, ticker: str, notes: str) -> list:
        """检测技术突破期权"""
        options = []

        # 制药：GLP-1 管线
        if "制药" in sector:
            if "礼来" in name or "LLY" in ticker.upper():
                options.append({
                    "type": "技术突破",
                    "name": "GLP-1/GIP 双靶点药物管线",
                    "description": "替尔泊肽(Tirzepatide)在减重/糖尿病领域持续拓展适应症，口服版GLP-1在研",
                    "probability": 0.35,
                    "potential_payoff_pct": 40,
                    "time_horizon": "12-24个月",
                    "catalyst": "新适应症获批/临床III期数据读出",
                    "implied_premium": "低（尚未充分定价）",
                    "bet_quality": "高确定性高赔率",
                })

        # 半导体：HBM 技术突破
        if "半导体" in sector:
            options.append({
                "type": "技术突破",
                "name": "HBM4/下一代存储技术突破",
                "description": "HBM高带宽内存持续迭代，AI芯片需求驱动技术升级",
                "probability": 0.25,
                "potential_payoff_pct": 30,
                "time_horizon": "18-36个月",
                "catalyst": "下一代HBM量产/客户认证",
                "implied_premium": "低（估计）",
                "bet_quality": "中等确定性高赔率",
            })

        # 互联网科技：EV/新业务
        if "互联网科技" in sector:
            if "小米" in name:
                options.append({
                    "type": "技术突破",
                    "name": "小米SU7/EV业务规模化",
                    "description": "小米汽车从交付到盈利的跨越，有可能成为第二增长曲线",
                    "probability": 0.20,
                    "potential_payoff_pct": 50,
                    "time_horizon": "24-36个月",
                    "catalyst": "月交付量突破2万/毛利率转正",
                    "implied_premium": "低（EV业务尚未盈利）",
                    "bet_quality": "中等赔率，低确定性",
                })

        return options

    def _detect_certification_options(self, sector: str, name: str, ticker: str, notes: str) -> list:
        """检测客户认证/合同期权"""
        options = []

        # 工业/数据中心：大客户合同
        if "工业" in sector or "数据中心" in sector:
            if "vertiv" in name.lower() or "VRT" in ticker.upper():
                options.append({
                    "type": "客户认证",
                    "name": "超大规模数据中心合同",
                    "description": "Vertiv 在电力基础设施领域持续获得超大规模客户合同，AI数据中心建设加速",
                    "probability": 0.30,
                    "potential_payoff_pct": 35,
                    "time_horizon": "12-18个月",
                    "catalyst": "大客户合同公告/财报超预期",
                    "implied_premium": "中等（部分反映在估值中）",
                    "bet_quality": "高确定性中赔率",
                })

        # 网络安全：大企业认证
        if "网络安全" in sector:
            if "okta" in name.lower():
                options.append({
                    "type": "客户认证",
                    "name": "政府/大型企业身份安全合同",
                    "description": "Okta 在身份安全领域持续拓展政府和企业客户，订阅收入增长",
                    "probability": 0.25,
                    "potential_payoff_pct": 30,
                    "time_horizon": "12-24个月",
                    "catalyst": "大客户续约/联邦身份认证需求",
                    "implied_premium": "中等",
                    "bet_quality": "中等确定性中赔率",
                })

        return options

    def _detect_turnaround_options(self, sector: str, name: str, ticker: str,
                                    pnl_pct: float, notes: str) -> list:
        """检测业务反转期权"""
        options = []

        # 深度亏损被低估的标的
        if pnl_pct <= -25:
            options.append({
                "type": "业务反转",
                "name": "均值回归/估值修复",
                "description": f"当前亏损{pnl_pct:.1f}%，若基本面改善则存在估值修复空间",
                "probability": 0.15,
                "potential_payoff_pct": abs(pnl_pct) * 0.6,
                "time_horizon": "12-36个月",
                "catalyst": "行业周期反转/公司基本面改善",
                "implied_premium": "低（价格已充分反映悲观预期）",
                "bet_quality": "低确定性高赔率",
            })

        # 互联网科技：亏损业务反转
        if "互联网科技" in sector:
            if "小米" in name:
                options.append({
                    "type": "业务反转",
                    "name": "小米手机高端化成功",
                    "description": "小米手机在高端市场份额持续提升，带动整体利润率改善",
                    "probability": 0.25,
                    "potential_payoff_pct": 25,
                    "time_horizon": "12-24个月",
                    "catalyst": "高端机型占比提升/ASP上涨",
                    "implied_premium": "低",
                    "bet_quality": "中等确定性中赔率",
                })

        return options

    # ==================================================================
    # 第四阶: Game Theory Hedge Analysis 博弈论对冲分析
    # ==================================================================

    def game_theory_hedge(self, holding: dict) -> dict:
        """
        分析竞争对手的成败如何影响该持仓

        方法:
          - 识别1-3个关键竞争对手/同行
          - 映射: 竞争对手赢 → 我们的持仓估值扩张还是收缩?
          - 寻找价值链条中的对冲节点

        参数:
            holding: 单只持仓字典

        返回:
            dict: {competitor_map, win_loss_impact, hedge_opportunities}
        """
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        ticker = holding.get("ticker", "")

        # 构建竞争对手图谱
        competitor_map = self._build_competitor_map(sector, name, ticker)

        # 分析胜负影响
        win_loss_impacts = []
        for comp in competitor_map:
            impact = self._analyze_win_loss_impact(holding, comp)
            win_loss_impacts.append(impact)

        # 识别对冲机会
        hedge_opportunities = self._find_hedge_opportunities(sector, name, ticker, competitor_map)

        return {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "competitor_map": competitor_map,
            "win_loss_impacts": win_loss_impacts,
            "hedge_opportunities": hedge_opportunities,
            "details": [
                f"识别到 {len(competitor_map)} 个关键竞争对手/同行",
                f"发现 {len(hedge_opportunities)} 个潜在对冲机会",
            ],
        }

    def _build_competitor_map(self, sector: str, name: str, ticker: str) -> list:
        """构建竞争对手图谱"""
        competitor_db = {
            "银行/金融": [
                {"name": "兴业银行", "ticker": "601166", "market": "A股", "relation": "股份制银行同业"},
                {"name": "平安银行", "ticker": "000001", "market": "A股", "relation": "股份制银行同业"},
                {"name": "工商银行", "ticker": "601398", "market": "A股", "relation": "国有大行，规模优势"},
            ],
            "消费/白酒": [
                {"name": "贵州茅台", "ticker": "600519", "market": "A股", "relation": "高端白酒龙头"},
                {"name": "五粮液", "ticker": "000858", "market": "A股", "relation": "浓香型白酒龙头"},
            ],
            "制药": [
                {"name": "诺和诺德", "ticker": "NVO", "market": "美股", "relation": "GLP-1直接竞争对手"},
                {"name": "安进", "ticker": "AMGN", "market": "美股", "relation": "GLP-1管线竞争者"},
            ],
            "工业/数据中心": [
                {"name": "施耐德电气", "ticker": "SBGSY", "market": "美股", "relation": "电力基础设施竞争对手"},
                {"name": "ABB", "ticker": "ABBNY", "market": "美股", "relation": "电气设备竞争对手"},
            ],
            "网络安全": [
                {"name": "微软", "ticker": "MSFT", "market": "美股", "relation": "Azure AD身份安全竞争"},
                {"name": "Ping Identity", "ticker": "PING", "market": "美股", "relation": "身份管理直接对手"},
            ],
            "半导体": [
                {"name": "三星电子", "ticker": "SSNLF", "market": "美股", "relation": "HBM直接竞争对手"},
                {"name": "美光科技", "ticker": "MU", "market": "美股", "relation": "存储芯片竞争对手"},
            ],
            "互联网科技": [
                {"name": "比亚迪", "ticker": "002594", "market": "A股", "relation": "电动车竞争对手"},
                {"name": "华为", "ticker": "", "market": "未上市", "relation": "手机/消费电子竞争对手"},
            ],
            "造纸": [
                {"name": "晨鸣纸业", "ticker": "000488", "market": "A股", "relation": "造纸行业竞争对手"},
                {"name": "玖龙纸业", "ticker": "02689", "market": "港股", "relation": "包装纸龙头"},
            ],
        }

        for key, competitors in competitor_db.items():
            if key in sector:
                return competitors

        # ETF 类：跟踪指数无需竞争对手分析
        if "ETF" in sector:
            return [{"name": "指数基准", "ticker": "", "market": "", "relation": "被动跟踪无竞争对手"}]

        # 默认
        return [{"name": "行业平均水平", "ticker": "", "market": "", "relation": "行业基准（估计）"}]

    def _analyze_win_loss_impact(self, holding: dict, competitor: dict) -> dict:
        """分析竞争对手胜负对持仓的影响"""
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        comp_name = competitor.get("name", "")

        # 默认影响
        impact = {
            "competitor": comp_name,
            "if_competitor_wins": "",
            "impact_on_us": "",
            "multiple_impact": "中性",
            "severity": "中等",
        }

        if "银行" in sector:
            if "工商银行" in comp_name:
                impact["if_competitor_wins"] = "国有大行凭借低成本资金优势扩大份额"
                impact["impact_on_us"] = "招商银行凭借零售业务差异化，冲击有限"
                impact["multiple_impact"] = "轻微负面 (-0.5x PE)"
                impact["severity"] = "低"
            else:
                impact["if_competitor_wins"] = f"{comp_name}在细分领域取得优势"
                impact["impact_on_us"] = "行业竞争加剧，但零售银行护城河较深"
                impact["multiple_impact"] = "轻微负面 (-1x PE)"
                impact["severity"] = "低"

        elif "制药" in sector:
            if "诺和诺德" in comp_name:
                impact["if_competitor_wins"] = "诺和诺德在口服GLP-1上取得突破"
                impact["impact_on_us"] = "礼来GLP-1市场份额可能被侵蚀，但双靶点优势仍在"
                impact["multiple_impact"] = "显著负面 (-5x PE)"
                impact["severity"] = "高"
            else:
                impact["if_competitor_wins"] = f"{comp_name}在GLP-1管线取得进展"
                impact["impact_on_us"] = "竞争格局恶化，但礼来先发优势明显"
                impact["multiple_impact"] = "中等负面 (-3x PE)"
                impact["severity"] = "中"

        elif "数据中心" in sector or "工业" in sector:
            impact["if_competitor_wins"] = f"{comp_name}在AI数据中心订单上取得更大份额"
            impact["impact_on_us"] = "市场份额被蚕食，但行业整体需求增长足以容纳多家"
            impact["multiple_impact"] = "轻微负面 (-2x PE)"
            impact["severity"] = "低"

        elif "网络安全" in sector:
            if "微软" in comp_name:
                impact["if_competitor_wins"] = "微软Azure AD持续整合身份安全功能"
                impact["impact_on_us"] = "Okta的独立身份平台定位受到挑战，但大型企业偏好独立供应商"
                impact["multiple_impact"] = "中等负面 (-4x PE)"
                impact["severity"] = "高"
            else:
                impact["if_competitor_wins"] = f"{comp_name}在身份安全细分领域取得进展"
                impact["impact_on_us"] = "竞争加剧，但Okta在身份网格领域有先发优势"
                impact["multiple_impact"] = "轻微负面 (-2x PE)"
                impact["severity"] = "中"

        elif "半导体" in sector:
            impact["if_competitor_wins"] = f"{comp_name}在HBM技术路线上取得领先"
            impact["impact_on_us"] = "HBM竞争格局变化，但整体AI需求增长摊薄影响"
            impact["multiple_impact"] = "中等负面 (-3x PE)"
            impact["severity"] = "中"

        elif "互联网科技" in sector:
            if "比亚迪" in comp_name:
                impact["if_competitor_wins"] = "比亚迪在电动车市场持续扩大领先优势"
                impact["impact_on_us"] = "小米EV面临更激烈的竞争，但小米的目标客群和定位不同"
                impact["multiple_impact"] = "中等负面 (-2x PE)"
                impact["severity"] = "中"

        return impact

    def _find_hedge_opportunities(self, sector: str, name: str, ticker: str,
                                   competitor_map: list) -> list:
        """寻找价值链条中的对冲机会"""
        opportunities = []

        if "银行" in sector:
            opportunities.append({
                "type": "利率对冲",
                "description": "若息差持续收窄，可配置国债期货或利率互换对冲",
                "instrument": "10年期国债期货/利率互换",
                "hedge_ratio": "建议组合中配置5-10%利率对冲",
            })

        if "制药" in sector:
            if "礼来" in name:
                opportunities.append({
                    "type": "竞争对手对冲",
                    "description": "若担心诺和诺德在GLP-1上突破，可买入NVO看涨期权对冲",
                    "instrument": "NVO call option / 行业ETF (XLV)",
                    "hedge_ratio": "小仓位(1-2%)买入NVO call",
                })

        if "数据中心" in sector or "工业" in sector:
            opportunities.append({
                "type": "产业链对冲",
                "description": "AI资本开支放缓风险可通过做空芯片股或买入防御板块对冲",
                "instrument": "QQQ put spread / 公用事业ETF (XLU)",
                "hedge_ratio": "组合中配置10-15%防御性资产",
            })

        if "互联网科技" in sector:
            if "小米" in name:
                opportunities.append({
                    "type": "产业链对冲",
                    "description": "若EV业务不及预期，可做空碳酸锂/电池ETF对冲",
                    "instrument": "锂电池ETF / 碳酸锂期货",
                    "hedge_ratio": "微量对冲(1%以下)",
                })

        # 通用对冲
        opportunities.append({
            "type": "尾部风险对冲",
            "description": "系统性风险可通过买入指数看跌期权或VIX相关产品对冲",
            "instrument": "VIX期货 / S&P 500 put spread",
            "hedge_ratio": "建议1-3%仓位用于尾部风险对冲",
        })

        return opportunities

    # ==================================================================
    # 第五阶: Time-Wall & Terminal Value 时间墙与终值
    # ==================================================================

    def time_wall_terminal(self, holding: dict) -> dict:
        """
        识别"时间墙"——将检验投资逻辑的关键日期/事件
        以及估计终值——稳态下该持仓的价值

        时间墙类型:
          - LTA (长期协议) 到期日
          - 产能释放节点
          - 专利悬崖
          - 监管决策日期
          - 财报/投资者日

        参数:
            holding: 单只持仓字典

        返回:
            dict: {time_walls, terminal_value_est, reversion_risk}
        """
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        ticker = holding.get("ticker", "")
        current_price = _safe_float(holding.get("current_price", 0))
        avg_cost = _safe_float(holding.get("avg_cost", 0))
        market_value = _safe_float(holding.get("market_value_cny", 0))
        pnl_pct = _safe_float(holding.get("pnl_pct", 0))
        holding_days = _safe_int(holding.get("holding_days", 0))
        notes = holding.get("notes", "")

        # ---- 识别时间墙 ----
        time_walls = self._detect_time_walls(sector, name, ticker, notes)

        # ---- 估计终值 ----
        terminal_value = self._estimate_terminal_value(holding, time_walls)

        # ---- 均值回归风险 ----
        reversion_risk = self._assess_reversion_risk(holding, terminal_value)

        return {
            "ticker": ticker,
            "name": name,
            "current_price": round(current_price, 2),
            "market_value_cny": round(market_value, 2),
            "time_walls": time_walls,
            "terminal_value_est": terminal_value,
            "reversion_risk": reversion_risk,
            "details": [
                f"识别到 {len(time_walls)} 个关键时间墙",
                f"终值估计: {terminal_value['terminal_price']:.2f}元/股",
                f"均值回归风险: {reversion_risk['level']}",
            ],
        }

    def _detect_time_walls(self, sector: str, name: str, ticker: str, notes: str) -> list:
        """检测时间墙事件"""
        walls = []
        today = date.today()

        # ---- 银行/金融 ----
        if "银行" in sector:
            walls.append({
                "event": "半年报披露",
                "event_date": "2026-08-31",
                "days_remaining": (date(2026, 8, 31) - today).days,
                "impact": "净息差走势、不良贷款率、零售业务增速",
                "probability": "确定",
                "current_preparation": "关注息差拐点和零售AUM增速",
                "type": "财报",
            })
            walls.append({
                "event": "年度分红除权日",
                "event_date": "2026-07-15",
                "days_remaining": max(0, (date(2026, 7, 15) - today).days),
                "impact": "约5%股息率，分红再投资机会",
                "probability": "确定",
                "current_preparation": "已持有等待分红到账",
                "type": "分红",
            })

        # ---- 制药 ----
        if "制药" in sector:
            if "礼来" in name or "LLY" in ticker.upper():
                walls.append({
                    "event": "口服GLP-1临床III期数据读出",
                    "event_date": "2026-Q4 (估计)",
                    "days_remaining": 90,
                    "impact": "若成功则打开千亿美元口服药市场，股价可能涨20-30%",
                    "probability": "高 (60-70%)",
                    "current_preparation": "等待数据读出，已有II期积极数据",
                    "type": "临床数据",
                })
                walls.append({
                    "event": "替尔泊肽新适应症FDA审批",
                    "event_date": "2026-09-30 (估计)",
                    "days_remaining": 60,
                    "impact": "新适应症获批将扩大医保覆盖范围",
                    "probability": "中高 (50-60%)",
                    "current_preparation": "已提交申请，等待FDA反馈",
                    "type": "监管审批",
                })

        # ---- 工业/数据中心 ----
        if "工业" in sector or "数据中心" in sector:
            if "vertiv" in name.lower() or "VRT" in ticker.upper():
                walls.append({
                    "event": "Q3 2026 财报/订单更新",
                    "event_date": "2026-10-25 (估计)",
                    "days_remaining": 85,
                    "impact": "订单增速和 backlog 将验证AI资本开支持续性",
                    "probability": "确定",
                    "current_preparation": "跟踪AI数据中心资本开支趋势",
                    "type": "财报",
                })

        # ---- 半导体 ----
        if "半导体" in sector:
            walls.append({
                "event": "HBM4 量产节点",
                "event_date": "2027-Q1 (估计)",
                "days_remaining": 210,
                "impact": "下一代HBM量产将决定市场份额和定价权",
                "probability": "中 (40-50%)",
                "current_preparation": "跟踪技术路线图",
                "type": "技术节点",
            })

        # ---- 互联网科技 ----
        if "互联网科技" in sector:
            if "小米" in name:
                walls.append({
                    "event": "小米SU7 年度交付量达标验证",
                    "event_date": "2026-12-31",
                    "days_remaining": 152,
                    "impact": "能否达到12-15万辆交付目标，决定EV估值逻辑",
                    "probability": "中 (40-50%)",
                    "current_preparation": "跟踪月交付数据",
                    "type": "业务里程碑",
                })
                walls.append({
                    "event": "小米汽车业务毛利率转正节点",
                    "event_date": "2027-Q2 (估计)",
                    "days_remaining": 300,
                    "impact": "毛利率转正验证EV商业模式可行性",
                    "probability": "低 (20-30%)",
                    "current_preparation": "跟踪季度财报汽车业务分部",
                    "type": "盈利里程碑",
                })

        # ---- 造纸 ----
        if "造纸" in sector:
            walls.append({
                "event": "纸浆价格周期底部确认",
                "event_date": "2026-Q4 (估计)",
                "days_remaining": 90,
                "impact": "纸浆价格触底回升将改善盈利",
                "probability": "中 (40-50%)",
                "current_preparation": "跟踪纸浆期货价格",
                "type": "周期拐点",
            })

        # 通用：季度财报
        walls.append({
            "event": "最新季度财报披露",
            "event_date": (today.replace(day=1) + __import__('datetime').timedelta(days=90)).strftime("%Y-%m-%d") if False else "2026-10-31 (估计)",
            "days_remaining": 91,
            "impact": "收入/利润/指引 vs 预期",
            "probability": "确定",
            "current_preparation": "关注市场预期变化",
            "type": "财报",
        })

        # 按剩余天数排序
        walls.sort(key=lambda w: w["days_remaining"])

        # 去重（保留第一个财报）
        seen_types = set()
        unique_walls = []
        for w in walls:
            if w["type"] not in seen_types or w["type"] not in ("财报",):
                unique_walls.append(w)
                seen_types.add(w["type"])
            elif w["type"] == "财报" and "财报" not in seen_types:
                unique_walls.append(w)
                seen_types.add("财报")

        return unique_walls[:5]  # 最多返回5个

    def _estimate_terminal_value(self, holding: dict, time_walls: list) -> dict:
        """
        估计终值——稳态下该持仓的价值

        终值 = 稳态EPS × 稳态PE
        """
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        current_price = _safe_float(holding.get("current_price", 0))
        avg_cost = _safe_float(holding.get("avg_cost", 0))
        price = current_price if current_price > 0 else avg_cost

        # 稳态PE
        terminal_pe_map = {
            "银行/金融": 10,
            "消费/白酒": 20,
            "制药": 22,
            "工业/数据中心": 22,
            "网络安全": 25,
            "半导体": 18,
            "互联网科技": 15,
            "造纸": 10,
            "ETF/全球指数": 18,
            "ETF/道指": 20,
            "ETF/港股科技": 15,
            "ETF/通信": 12,
            "ETF/科创板": 18,
            "另类投资": 8,
        }
        terminal_pe = terminal_pe_map.get(sector, 15)

        # 稳态EPS = 当前EPS × 假设稳态增长
        eps = self._estimate_eps(holding)
        # 保守估计稳态增长为0-2%
        steady_state_growth = 0.01
        terminal_eps = eps * (1 + steady_state_growth)

        terminal_price = terminal_eps * terminal_pe

        # 对ETF使用净值法
        if "ETF" in sector:
            terminal_price = price * 1.05  # 假设长期年化5%包含股息

        if terminal_price <= 0:
            terminal_price = price * 0.9

        # 计算从当前价格到终值的潜在回报
        if current_price > 0:
            total_return = (terminal_price / current_price - 1) * 100
        else:
            total_return = 0.0

        # 估计时间跨度（年）
        time_horizon_years = 5  # 默认5年稳态

        # 年化回报
        if total_return > 0 and time_horizon_years > 0:
            annualized_return = ((1 + total_return / 100) ** (1 / time_horizon_years) - 1) * 100
        else:
            annualized_return = 0.0

        return {
            "terminal_pe": terminal_pe,
            "terminal_eps": round(terminal_eps, 4),
            "terminal_price": round(terminal_price, 2),
            "time_horizon_years": time_horizon_years,
            "total_return_pct": round(total_return, 1),
            "annualized_return_pct": round(annualized_return, 1),
            "methodology": f"稳态PE {terminal_pe}x × 稳态EPS {terminal_eps:.2f} = {terminal_price:.2f}元",
            "details": [
                f"终值估计: 5年后稳态价值约{terminal_price:.1f}元/股",
                f"隐含年化回报: {annualized_return:.1f}%",
                f"终值倍数: {terminal_pe}x, 假设稳态增长率: {steady_state_growth*100:.0f}%",
            ],
        }

    def _assess_reversion_risk(self, holding: dict, terminal_value: dict) -> dict:
        """
        评估均值回归风险

        核心问题: 当前价格是否偏离了合理的均值回归区间?
        """
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        current_price = _safe_float(holding.get("current_price", 0))
        avg_cost = _safe_float(holding.get("avg_cost", 0))
        pnl_pct = _safe_float(holding.get("pnl_pct", 0))
        annualized_return = _safe_float(holding.get("annualized_return", 0))

        price = current_price if current_price > 0 else avg_cost
        terminal_price = terminal_value.get("terminal_price", price)

        # 偏离度
        if terminal_price > 0:
            deviation = (price / terminal_price - 1) * 100
        else:
            deviation = 0.0

        # 判断均值回归风险
        if deviation > 30:
            level = "高"
            description = "当前价格显著高于终值估计，均值回归风险较高"
            score = 4
        elif deviation > 10:
            level = "中"
            description = "当前价格略高于终值估计，均值回归风险中等"
            score = 3
        elif deviation > -10:
            level = "低"
            description = "当前价格接近终值估计，均值回归风险较低"
            score = 2
        else:
            level = "极低"
            description = "当前价格低于终值估计，均值回归将带来正收益"
            score = 1

        # 根据盈亏修正
        if pnl_pct <= -20:
            score = max(score - 1, 1)
            level = "低" if score <= 2 else level
        elif pnl_pct >= 30:
            score = min(score + 1, 5)
            level = "高" if score >= 4 else level

        return {
            "level": level,
            "score": score,
            "deviation_from_terminal_pct": round(deviation, 1),
            "description": description,
            "details": [
                f"当前价格偏离终值: {deviation:+.1f}%",
                f"均值回归风险: {level} (评分: {score}/5)",
            ],
        }

    # ==================================================================
    # 批量运行所有五阶分析
    # ==================================================================

    def analyze_all_deep(self, holdings: Optional[List[Dict]] = None) -> List[Dict]:
        """
        对所有持仓运行五阶深度逻辑分析

        参数:
            holdings: 持仓列表（默认使用 self.holdings）

        返回:
            List[Dict]: 每个持仓的深度逻辑分析结果
        """
        if holdings is None:
            holdings = self.holdings

        results = []
        cash_holdings = [h for h in holdings if h.get("exchange") == "CASH"]

        for h in holdings:
            if h.get("exchange") == "CASH":
                continue  # 跳过现金

            ticker = h.get("ticker", "")
            name = h.get("name", "")

            try:
                # 第一阶: SOTP
                sotp = self.sotp_rerating(h)
            except Exception as e:
                logger.warning(f"SOTP分析失败 [{ticker}]: {e}")
                sotp = {"error": str(e), "weighted_pe": 0, "upside_pct": 0}

            try:
                # 第二阶: 隐含预期
                implied = self.implied_expectation_decode(h)
            except Exception as e:
                logger.warning(f"隐含预期分析失败 [{ticker}]: {e}")
                implied = {"error": str(e), "fragility_score": 0}

            try:
                # 第三阶: 期权价值
                option_val = self.option_value_identify(h)
            except Exception as e:
                logger.warning(f"期权价值识别失败 [{ticker}]: {e}")
                option_val = {"error": str(e), "embedded_options": []}

            try:
                # 第四阶: 博弈论对冲
                game = self.game_theory_hedge(h)
            except Exception as e:
                logger.warning(f"博弈论对冲分析失败 [{ticker}]: {e}")
                game = {"error": str(e), "competitor_map": []}

            try:
                # 第五阶: 时间墙与终值
                tw = self.time_wall_terminal(h)
            except Exception as e:
                logger.warning(f"时间墙与终值分析失败 [{ticker}]: {e}")
                tw = {"error": str(e), "time_walls": []}

            item = {
                "ticker": ticker,
                "name": name,
                "sector": h.get("sector", ""),
                "market": h.get("market", ""),
                "data_snapshot": {
                    "current_price": round(_safe_float(h.get("current_price", 0)), 2),
                    "avg_cost": round(_safe_float(h.get("avg_cost", 0)), 2),
                    "pnl_pct": round(_safe_float(h.get("pnl_pct", 0)), 1),
                    "weight": round(_safe_float(h.get("weight", 0)), 1),
                    "holding_days": _safe_int(h.get("holding_days", 0)),
                },
                "sotp_rerating": sotp,
                "implied_expectation": implied,
                "option_value": option_val,
                "game_theory_hedge": game,
                "time_wall_terminal": tw,
            }

            results.append(item)

        return results


# ====================================================================
# 集成入口
# ====================================================================

class PortfolioAnalysisEngine:
    """
    组合分析引擎集成入口

    整合:
      - IncomeAnalysisEngine: 分红/股息收入分析
      - DeepLogicEngine: 五阶深度逻辑引擎
      - (原有 BerkshireAnalysis 可继续保留)
    """

    def __init__(self, holdings: List[Dict], summary: Dict):
        self.holdings = holdings
        self.summary = summary
        self.income_engine = IncomeAnalysisEngine(holdings, summary)
        self.deep_logic_engine = DeepLogicEngine(holdings, summary)

    def run_full_analysis(self) -> Dict:
        """
        运行全部分析

        返回:
            dict: {
                income_analysis,
                deep_logic_analysis,
                summary
            }
        """
        result = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": {
                "total_holdings": len(self.holdings),
                "total_value_cny": round(_safe_float(self.summary.get("total_value_cny", 0)), 2),
                "total_pnl_cny": round(_safe_float(self.summary.get("total_pnl", 0)), 2),
                "total_pnl_pct": round(_safe_float(self.summary.get("total_pnl_pct", 0)), 2),
            },
        }

        # 收入分析
        try:
            result["income_analysis"] = self.income_engine.analyze_all_income()
        except Exception as e:
            logger.error(f"收入分析失败: {e}")
            result["income_analysis"] = {"error": str(e)}

        # 深度逻辑分析
        try:
            result["deep_logic_analysis"] = self.deep_logic_engine.analyze_all_deep()
        except Exception as e:
            logger.error(f"深度逻辑分析失败: {e}")
            result["deep_logic_analysis"] = {"error": str(e)}

        return result


# ====================================================================
# CLI 测试
# ====================================================================

def main():
    """测试运行 Part 2 分析引擎"""
    import sys
    import os

    # 尝试导入组合管理器
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from portfolio_core import PortfolioManager
        pm = PortfolioManager()
        holdings = pm.get_holdings_table()
        summary = pm.get_summary_dict()
        print(f"成功加载组合: {len(holdings)} 只持仓")
    except ImportError:
        # 使用模拟数据
        print("无法加载 portfolio_core，使用模拟数据")
        holdings = [
            {
                "id": "1", "ticker": "600036", "exchange": "SH", "name": "招商银行",
                "market": "A股", "sector": "银行/金融", "shares": 1000,
                "avg_cost": 35.0, "current_price": 38.5, "market_value_cny": 38500,
                "pnl_pct": 10.0, "weight": 15.0, "holding_days": 200,
                "day_change_pct": 0.5, "currency": "CNY", "notes": "分红再投资",
            },
            {
                "id": "2", "ticker": "VT", "exchange": "US", "name": "Vanguard Total World Stock ETF",
                "market": "美股", "sector": "ETF/全球指数", "shares": 50,
                "avg_cost": 105.0, "current_price": 110.0, "market_value_cny": 38500,
                "pnl_pct": 4.76, "weight": 15.0, "holding_days": 180,
                "day_change_pct": 0.3, "currency": "USD", "notes": "核心底仓",
            },
            {
                "id": "3", "ticker": "LLY", "exchange": "US", "name": "礼来",
                "market": "美股", "sector": "制药", "shares": 20,
                "avg_cost": 450.0, "current_price": 520.0, "market_value_cny": 72800,
                "pnl_pct": 15.56, "weight": 28.0, "holding_days": 150,
                "day_change_pct": 1.2, "currency": "USD", "notes": "GLP-1龙头",
            },
            {
                "id": "4", "ticker": "1810", "exchange": "HK", "name": "小米集团",
                "market": "港股", "sector": "互联网科技", "shares": 2000,
                "avg_cost": 18.0, "current_price": 16.5, "market_value_cny": 23100,
                "pnl_pct": -8.33, "weight": 9.0, "holding_days": 60,
                "day_change_pct": -0.5, "currency": "HKD", "notes": "EV业务观察",
            },
        ]
        summary = {
            "total_value_cny": 260000, "total_pnl": 8500, "total_pnl_pct": 3.38,
            "num_holdings": 4,
        }

    print(f"\n{'='*70}")
    print("Part 2: IncomeAnalysisEngine + DeepLogicEngine 测试")
    print(f"{'='*70}\n")

    # 收入分析
    income = IncomeAnalysisEngine(holdings, summary)
    income_result = income.analyze_all_income()

    print("--- IncomeAnalysisEngine ---")
    if isinstance(income_result, dict) and income_result.get("type") == "income_analysis":
        print(f"适合收入分析的持仓: {income_result['total_income_holdings']} 只")
        print(f"年化股息收入估计: {income_result['total_annual_income_est']:.1f} 元")
        print(f"组合股息收益率: {income_result['portfolio_income_yield']:.2f}%")
        for h in income_result.get("holdings", []):
            print(f"  [{h['ticker']}] {h['name']}: "
                  f"可持续性={h['sustainability']['sustainability']}, "
                  f"评分={h['sustainability']['score']}, "
                  f"年收入≈{h['current_annual_income_est']:.1f}元")
    else:
        print(income_result)

    print()

    # 深度逻辑分析
    deep = DeepLogicEngine(holdings, summary)
    deep_results = deep.analyze_all_deep()

    print("--- DeepLogicEngine (五阶) ---")
    for r in deep_results[:2]:  # 只展示前2个
        print(f"\n[{r['ticker']}] {r['name']}")
        print(f"  SOTP: 加权PE={r['sotp_rerating'].get('weighted_pe', 'N/A')}x, "
              f"隐含价值={r['sotp_rerating'].get('implied_value_per_share', 'N/A')}, "
              f"上行={r['sotp_rerating'].get('upside_pct', 'N/A')}%")
        print(f"  隐含预期: {r['implied_expectation'].get('implied_growth', 'N/A')}, "
              f"脆弱度={r['implied_expectation'].get('fragility_score', 'N/A')}")
        opts = r['option_value'].get('embedded_options', [])
        print(f"  期权价值: {len(opts)} 个嵌入式期权, "
              f"总值={r['option_value'].get('total_option_value_cny', 0):.1f}元")
        game = r['game_theory_hedge']
        print(f"  博弈分析: {len(game.get('competitor_map', []))} 个竞争对手, "
              f"{len(game.get('hedge_opportunities', []))} 个对冲机会")
        tw = r['time_wall_terminal']
        print(f"  时间墙: {len(tw.get('time_walls', []))} 个关键事件, "
              f"终值={tw.get('terminal_value_est', {}).get('terminal_price', 'N/A')}, "
              f"均值回归风险={tw.get('reversion_risk', {}).get('level', 'N/A')}")

    print(f"\n{'='*70}")
    print("测试完成")
    print(f"{'='*70}")

    return deep_results

# ====================================================================
# Part 3: ThesisTracker + InvestmentChecklist + QualityScreen + NewsPulse + BerkshireAnalysis
# ====================================================================

class ThesisTracker:
    """投资论点追踪引擎：生成论点、检测漂移、红旗预警"""

    SECTOR_THESIS_TEMPLATES = {
        "银行/金融": {
            "buy_thesis": "银行龙头，零售模式领先，ROE高于行业平均，分红稳定。作为核心底仓配置，获取稳健分红收益和估值修复空间。",
            "hold_conditions": [
                "息差维持稳定或扩大",
                "不良率控制在低位",
                "零售银行业务持续增长",
                "分红率维持或提升",
            ],
            "sell_signals": [
                "不良率大幅上升超过行业平均",
                "息差持续收窄超过预期",
                "管理层出现重大诚信问题",
                "宏观经济恶化导致系统性风险",
            ],
            "timeframe": "中长期（1-3年）",
        },
        "消费/白酒": {
            "buy_thesis": "白酒行业是A股最佳商业模式之一，高毛利、低资本开支、强品牌粘性。行业处于周期底部，估值具备安全边际，等待行业拐点。",
            "hold_conditions": [
                "白酒行业库存逐步出清",
                "消费复苏趋势确认",
                "龙头品牌份额持续提升",
                "行业政策环境稳定",
            ],
            "sell_signals": [
                "消费持续降级，高端白酒需求大幅萎缩",
                "政策出台限制白酒消费",
                "行业库存不降反升",
                "年轻人饮酒习惯发生根本性变化",
            ],
            "timeframe": "中长期（1-2年）",
        },
        "ETF/全球指数": {
            "buy_thesis": "全球全市场ETF，覆盖发达+新兴市场，作为永久底仓配置。长期持有享受人类经济增长红利，无需择时。",
            "hold_conditions": [
                "全球经济长期增长趋势不变",
                "市场估值在合理范围内",
                "无极端系统性风险",
            ],
            "sell_signals": [
                "全球系统性金融危机爆发",
                "市场估值极端高估（如PE>30）",
                "投资目标或风险偏好发生变化",
            ],
            "timeframe": "永久底仓（10年以上）",
        },
        "ETF/道指": {
            "buy_thesis": "道指ETF追踪美国30家蓝筹股，核心永久底仓配置。美国经济长期增长+蓝筹股质量，适合长期持有。",
            "hold_conditions": [
                "美国经济持续增长",
                "蓝筹股盈利稳定",
                "无极端估值泡沫",
            ],
            "sell_signals": [
                "美国经济进入长期衰退",
                "指数估值极端高估",
                "美元信用体系受到挑战",
            ],
            "timeframe": "永久底仓（10年以上）",
        },
        "ETF/港股科技": {
            "buy_thesis": "港股科技板块估值处于历史低位，恒生科技指数成分股（小米、美团、腾讯等）基本面扎实。等待市场情绪修复和估值回归。",
            "hold_conditions": [
                "港股流动性保持稳定",
                "中美关系未进一步恶化",
                "科技龙头盈利未大幅下滑",
            ],
            "sell_signals": [
                "港股流动性持续枯竭",
                "中美脱钩导致科技公司业务受重大影响",
                "指数成分股基本面大幅恶化",
            ],
            "timeframe": "中期（6-12个月）",
        },
        "ETF/通信": {
            "buy_thesis": "通信行业是AI算力基础设施的一部分，长期需求确定。当前处于估值低位，等待行业催化。",
            "hold_conditions": [
                "AI算力需求持续增长",
                "5G/6G投资保持稳定",
                "行业估值处于低位",
            ],
            "sell_signals": [
                "AI资本开支大幅放缓",
                "通信技术路线发生根本变化",
                "行业竞争格局恶化",
            ],
            "timeframe": "中长期（1-2年）",
        },
        "ETF/科创板": {
            "buy_thesis": "科创板聚焦科技创新企业，半导体、AI等方向长期逻辑清晰。当前流动性偏紧导致估值承压，等待市场风格切换。",
            "hold_conditions": [
                "科创板流动性未进一步恶化",
                "科技创新政策支持持续",
                "半导体/AI行业景气度回升",
            ],
            "sell_signals": [
                "科创板流动性枯竭",
                "科技创新政策大幅转向",
                "指数大幅下跌超过50%",
            ],
            "timeframe": "中长期（1-3年）",
        },
        "制药": {
            "buy_thesis": "GLP-1赛道是全球制药行业最大的增长机会之一。LLY在GLP-1领域（Zepbound/Mounjaro）处于领先地位，8月财报前布局。",
            "hold_conditions": [
                "GLP-1药物销售持续增长",
                "新适应症获批进展顺利",
                "竞争对手未形成实质性威胁",
                "专利保护有效",
            ],
            "sell_signals": [
                "GLP-1药物安全性出现重大问题",
                "竞争对手（如诺和诺德）大幅领先",
                "新药审批被拒或延迟",
                "核心专利被挑战",
            ],
            "timeframe": "中短期（财报驱动，3-6个月）",
        },
        "工业/数据中心": {
            "buy_thesis": "AI基础设施建设的确定受益者，Vertiv在数据中心电力基础设施领域是细分龙头。EMEA区域订单节奏问题是短期扰动，不是需求问题。",
            "hold_conditions": [
                "AI资本开支保持高速增长",
                "Vertiv订单增长趋势持续",
                "EMEA区域改善趋势确认",
                "市场份额稳定或提升",
            ],
            "sell_signals": [
                "AI资本开支大幅放缓",
                "竞争对手侵蚀核心份额",
                "订单连续两个季度不及预期",
                "管理层指引大幅下调",
            ],
            "timeframe": "中长期（1-2年）",
        },
        "网络安全": {
            "buy_thesis": "身份安全需求刚性增长，Okta在身份管理领域有转换成本护城河。小仓位观察仓，关注增长和盈利改善进展。",
            "hold_conditions": [
                "网络安全需求持续增长",
                "Okta营收增长保持20%以上",
                "盈利改善趋势确认",
                "客户留存率稳定",
            ],
            "sell_signals": [
                "增长大幅放缓（低于15%）",
                "重大安全漏洞事件",
                "竞争格局恶化（微软等大厂挤压）",
                "管理层重大变动",
            ],
            "timeframe": "中期（6-12个月观察）",
        },
        "半导体": {
            "buy_thesis": "HBM（高带宽内存）是AI算力的瓶颈环节，SK海力士在HBM领域技术领先。ADR刚上市，波动较大，但长期AI需求逻辑清晰。",
            "hold_conditions": [
                "HBM需求持续增长",
                "SK海力士HBM技术领先地位维持",
                "存储芯片价格未进入下跌周期",
                "AI资本开支持续增长",
            ],
            "sell_signals": [
                "HBM技术路线被颠覆",
                "存储芯片进入长期价格下跌周期",
                "AI资本开支大幅放缓",
                "竞争对手在HBM领域超越",
            ],
            "timeframe": "中长期（1-2年）",
        },
        "另类投资": {
            "buy_thesis": "极小仓位试水创新基金，作为组合的另类配置。流动性有限，不抱过高期望。",
            "hold_conditions": [
                "基金资产质量未恶化",
                "无流动性危机",
            ],
            "sell_signals": [
                "基金资产大幅缩水",
                "流动性枯竭",
                "管理团队出现重大问题",
            ],
            "timeframe": "长期观察（3年以上）",
        },
        "互联网科技": {
            "buy_thesis": "小米集团兼具硬件制造和互联网服务，造车业务是潜在重大催化剂。当前深度套牢，等待电动车业务兑现和核心业务改善。",
            "hold_conditions": [
                "小米手机市场份额稳定",
                "造车业务按计划推进",
                "IoT业务持续增长",
                "公司持续回购",
            ],
            "sell_signals": [
                "造车业务烧钱超出预期且无进展",
                "手机份额大幅下滑",
                "核心管理层变动",
                "公司基本面持续恶化",
            ],
            "timeframe": "中长期（2-3年，等待造车兑现）",
        },
        "造纸": {
            "buy_thesis": "太阳纸业是造纸行业成本优势龙头，行业周期性底部，等待供需改善和估值修复。管理层激励计划体现信心。",
            "hold_conditions": [
                "纸价企稳回升",
                "原材料成本可控",
                "公司成本优势维持",
                "行业产能出清推进",
            ],
            "sell_signals": [
                "纸价持续下跌创新低",
                "原材料成本大幅上升侵蚀利润",
                "公司成本优势丧失",
                "行业需求持续萎缩",
            ],
            "timeframe": "中期（6-12个月，等待周期拐点）",
        },
    }

    SECTOR_METRICS = {
        "银行/金融": ["ROE>12%", "不良率<1.5%", "拨备覆盖率>200%", "净息差>2%", "分红率>30%"],
        "消费/白酒": ["毛利率>70%", "净利率>20%", "ROE>15%", "营收增速>10%", "经营现金流/净利润>1"],
        "ETF/全球指数": ["跟踪误差<0.5%", "费率<0.2%", "规模稳定", "流动性充足"],
        "ETF/道指": ["跟踪误差<0.5%", "费率<0.2%", "流动性充足"],
        "ETF/港股科技": ["跟踪误差<0.5%", "费率<0.5%", "规模稳定"],
        "ETF/通信": ["跟踪误差<0.5%", "费率<0.5%", "规模稳定"],
        "ETF/科创板": ["跟踪误差<0.5%", "费率<0.5%", "规模稳定"],
        "制药": ["营收增速>15%", "研发费用率>15%", "毛利率>75%", "核心产品专利到期>5年", "新药管线进度"],
        "工业/数据中心": ["营收增速>10%", "订单增速>15%", "毛利率>35%", "ROE>15%", "经营现金流为正"],
        "网络安全": ["营收增速>20%", "客户留存率>95%", "毛利率>70%", "净亏损收窄趋势", "DBNER>120%"],
        "半导体": ["营收增速>20%", "HBM市场份额>40%", "毛利率>40%", "资本开支效率", "研发费用率>10%"],
        "另类投资": ["资产净值稳定", "流动性充足", "管理费合理"],
        "互联网科技": ["手机份额稳定", "造车进度", "IoT收入增速>15%", "互联网服务毛利率>60%", "整体ROE>10%"],
        "造纸": ["毛利率>15%", "净利率>5%", "ROE>8%", "经营现金流/净利润>1", "资产负债率<60%"],
    }

    def create_thesis(self, holding: dict) -> dict:
        """生成结构化投资论点"""
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        ticker = holding.get("ticker", "")
        notes = holding.get("notes", "")
        pnl_pct = holding.get("pnl_pct", 0)
        days = holding.get("holding_days", 0)
        weight = holding.get("weight", 0)

        template = self.SECTOR_THESIS_TEMPLATES.get(sector, {})
        metrics = self.SECTOR_METRICS.get(sector, ["营收增长", "盈利能力", "估值水平", "现金流", "行业地位"])

        # 如果没有模板，生成通用论点
        if not template:
            buy_thesis = f"持有{name}（{ticker}），基于行业{sector}的分析，等待价值实现。"
            hold_conditions = ["基本面未恶化", "估值合理", "行业前景稳定"]
            sell_signals = ["基本面恶化", "估值过高", "更好机会出现"]
            timeframe = "中期"
        else:
            buy_thesis = template["buy_thesis"]
            hold_conditions = template["hold_conditions"]
            sell_signals = template["sell_signals"]
            timeframe = template["timeframe"]

        # 根据notes定制
        if notes:
            buy_thesis = f"{buy_thesis} 备注: {notes}"

        # 根据盈亏状态调整
        if pnl_pct <= -30:
            buy_thesis = f"{buy_thesis} 当前亏损{pnl_pct:.1f}%，处于深度套牢状态，需审视最初逻辑是否仍然成立。"
        elif pnl_pct <= -15:
            buy_thesis = f"{buy_thesis} 当前亏损{pnl_pct:.1f}%，需关注核心变量是否在恶化。"
        elif pnl_pct >= 20:
            buy_thesis = f"{buy_thesis} 当前盈利{pnl_pct:.1f}%，逻辑已被市场部分验证。"

        # 持仓时间评估
        time_status = "建仓初期"
        if days > 180:
            time_status = "长期持有"
        elif days > 60:
            time_status = "中期持有"
        elif days > 30:
            time_status = "持有观察期"
        else:
            time_status = "新建仓"

        return {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "buy_thesis": buy_thesis,
            "hold_conditions": hold_conditions,
            "sell_signals": sell_signals,
            "key_metrics_to_monitor": metrics,
            "timeframe": timeframe,
            "time_status": time_status,
            "holding_days": days,
            "current_pnl_pct": round(pnl_pct, 1),
            "weight": round(weight, 1),
        }

    def detect_thesis_drift(self, holding: dict, previous_thesis: Optional[dict] = None) -> dict:
        """检测投资论点是否发生漂移"""
        warnings = []
        unchanged = []
        drift_score = 0.0

        pnl_pct = holding.get("pnl_pct", 0)
        sector = holding.get("sector", "")
        days = holding.get("holding_days", 0)
        name = holding.get("name", "")
        ticker = holding.get("ticker", "")
        day_chg = holding.get("day_change_pct", 0)

        # 1. 检查盈亏是否触发漂移信号
        if pnl_pct <= -30:
            drift_score += 4.0
            warnings.append(f"深度亏损{pnl_pct:.1f}%，投资论点可能已被市场证伪，需重新审视")
        elif pnl_pct <= -20:
            drift_score += 2.0
            warnings.append(f"较大亏损{pnl_pct:.1f}%，需检查核心假设是否仍然成立")
        elif pnl_pct <= -10:
            drift_score += 1.0
            warnings.append(f"中等亏损{pnl_pct:.1f}%，建议关注基本面变化")
        else:
            unchanged.append("盈亏在可接受范围内，未触发漂移信号")

        # 2. 检查行业是否面临重大逆风
        sector_headwinds = {
            "消费/白酒": "消费复苏不及预期，行业库存压力仍在",
            "互联网科技": "电动车业务持续烧钱，盈利能力承压",
            "造纸": "需求疲软，原材料成本波动",
            "ETF/通信": "通信板块缺乏短期催化",
            "ETF/科创板": "科创板流动性偏紧，风险偏好降低",
            "ETF/港股科技": "港股流动性受地缘政治影响",
            "另类投资": "流动性有限，资产透明度低",
        }

        headwind = sector_headwinds.get(sector, "")
        if headwind:
            drift_score += 1.0
            warnings.append(f"行业逆风: {headwind}")

        # 3. 检查持仓时间 vs 预期时间框架
        template = self.SECTOR_THESIS_TEMPLATES.get(sector, {})
        expected_timeframe = template.get("timeframe", "中期") if template else "中期"

        timeframe_days_map = {
            "短期（1-3个月）": 90,
            "中短期（财报驱动，3-6个月）": 180,
            "中期（6-12个月）": 365,
            "中长期（1-2年）": 730,
            "中长期（1-3年）": 1095,
            "长期观察（3年以上）": 1095,
            "永久底仓（10年以上）": 3650,
            "中期（6-12个月观察）": 365,
            "中期（6-12个月，等待周期拐点）": 365,
            "中长期（2-3年，等待造车兑现）": 1095,
        }

        expected_days = timeframe_days_map.get(expected_timeframe, 365)
        if days > expected_days and pnl_pct <= -15:
            drift_score += 2.0
            warnings.append(f"已持有{days}天，超过预期时间框架({expected_timeframe})，但亏损仍在{pnl_pct:.1f}%，论点可能失效")
        elif days < 30:
            unchanged.append(f"建仓仅{days}天，时间太短不足以验证论点")
        else:
            unchanged.append(f"持有{days}天，在预期时间框架({expected_timeframe})内")

        # 4. 检查日内大幅波动
        if abs(day_chg) >= 5:
            drift_score += 1.0
            warnings.append(f"日内波动{day_chg:+.1f}%，可能存在未公开的重大信息")

        # 5. 如果之前有论点，检查是否仍然相关
        if previous_thesis:
            unchanged.append("基于已有论点继续跟踪")

        # 计算漂移阈值
        drift_detected = drift_score >= 5.0

        return {
            "ticker": ticker,
            "name": name,
            "drift_score": round(min(drift_score, 10.0), 1),
            "drift_detected": drift_detected,
            "warnings": warnings,
            "unchanged_elements": unchanged,
            "expected_timeframe": expected_timeframe,
            "days_elapsed": days,
            "days_remaining": max(0, expected_days - days) if expected_days > days else 0,
        }

    def generate_red_flags(self, holding: dict, summary: dict) -> list:
        """生成红旗预警信号"""
        flags = []
        pnl_pct = holding.get("pnl_pct", 0)
        weight = holding.get("weight", 0)
        sector = holding.get("sector", "")
        days = holding.get("holding_days", 0)
        day_chg = holding.get("day_change_pct", 0)
        ann_ret = holding.get("annualized_return", 0)
        name = holding.get("name", "")
        ticker = holding.get("ticker", "")

        # --- 技术面红旗 ---
        if pnl_pct <= -30:
            flags.append({
                "type": "technical",
                "severity": "high",
                "icon": "&#x1F534;",
                "text": f"过度回撤: 亏损{pnl_pct:.1f}%，超过30%的深度回撤阈值",
            })

        # 流动性检查（基于行业和规模）
        low_liquidity_sectors = ["另类投资", "ETF/科创板"]
        if sector in low_liquidity_sectors:
            flags.append({
                "type": "technical",
                "severity": "medium",
                "icon": "&#x26A0;",
                "text": f"流动性风险: {sector}品种流动性可能不足",
            })

        # 年化亏损
        if days > 60 and ann_ret < -20:
            flags.append({
                "type": "technical",
                "severity": "medium",
                "icon": "&#x26A0;",
                "text": f"年化亏损{ann_ret:.1f}%，持续亏损趋势需警惕",
            })

        # 日内暴跌
        if day_chg <= -5:
            flags.append({
                "type": "technical",
                "severity": "high",
                "icon": "&#x1F534;",
                "text": f"日内暴跌{abs(day_chg):.1f}%，可能存在重大利空",
            })

        # --- 基本面红旗 ---
        # 行业衰退检查
        declining_sectors = ["造纸", "ETF/通信"]
        if sector in declining_sectors:
            flags.append({
                "type": "fundamental",
                "severity": "medium",
                "icon": "&#x26A0;",
                "text": f"行业衰退风险: {sector}行业处于下行周期",
            })

        # 商业模式变化
        biz_change_sectors = {
            "互联网科技": "小米从手机制造商转型造车，商业模式正在变化，不确定性增加",
            "另类投资": "VCX是代币化创新基金，商业模式不透明",
        }
        if sector in biz_change_sectors:
            flags.append({
                "type": "fundamental",
                "severity": "medium",
                "icon": "&#x2139;",
                "text": f"商业模式变化: {biz_change_sectors[sector]}",
            })

        # --- 行为面红旗 ---
        # 沉没成本偏误
        if pnl_pct <= -20 and days > 60:
            flags.append({
                "type": "behavioral",
                "severity": "high",
                "icon": "&#x1F534;",
                "text": f"沉没成本偏误: 持有{days}天且亏损{pnl_pct:.1f}%，可能因为不愿承认错误而继续持有",
            })

        # 确认偏误
        if pnl_pct <= -15 and weight >= 10:
            flags.append({
                "type": "behavioral",
                "severity": "medium",
                "icon": "&#x26A0;",
                "text": f"确认偏误风险: 亏损{pnl_pct:.1f}%仍持有较大仓位({weight:.1f}%)，可能只关注利好信息",
            })

        # 处置效应（过早止盈）
        if pnl_pct >= 20 and days < 30:
            flags.append({
                "type": "behavioral",
                "severity": "low",
                "icon": "&#x2139;",
                "text": f"处置效应提醒: 短期盈利{pnl_pct:.1f}%，慎防过早卖出好公司",
            })

        # 过度自信
        if pnl_pct >= 50 and weight >= 20:
            flags.append({
                "type": "behavioral",
                "severity": "medium",
                "icon": "&#x26A0;",
                "text": f"过度自信风险: 大幅盈利{pnl_pct:.1f}%且重仓{weight:.1f}%，可能过度自信",
            })

        # 锚定效应
        if pnl_pct <= -20:
            flags.append({
                "type": "behavioral",
                "severity": "low",
                "icon": "&#x2139;",
                "text": f"锚定效应提醒: 成本价{holding.get('avg_cost', 0)}元，当前价{holding.get('current_price', 0)}元，不要被买入价锚定判断",
            })

        return flags


# ====================================================================
# InvestmentChecklist — 六门评估引擎
# ====================================================================

class InvestmentChecklist:
    """六门评估：理解业务、好生意、护城河、管理层、安全边际、仓位纪律"""

    # 行业理解难度评级
    SECTOR_UNDERSTANDABILITY = {
        "银行/金融": {"level": "medium", "reason": "银行业务模式相对清晰，但需理解信用风险、利率风险等专业概念"},
        "消费/白酒": {"level": "easy", "reason": "白酒商业模式简单易懂，品牌消费品的定价权和渠道逻辑清晰"},
        "ETF/全球指数": {"level": "easy", "reason": "被动指数基金，理解门槛极低"},
        "ETF/道指": {"level": "easy", "reason": "被动指数基金，理解门槛极低"},
        "ETF/港股科技": {"level": "easy", "reason": "被动指数基金，理解门槛极低"},
        "ETF/通信": {"level": "easy", "reason": "被动指数基金，理解门槛极低"},
        "ETF/科创板": {"level": "easy", "reason": "被动指数基金，理解门槛极低"},
        "制药": {"level": "hard", "reason": "需理解药物研发流程、临床试验、专利法规、FDA审批等专业知识"},
        "工业/数据中心": {"level": "medium", "reason": "数据中心基础设施业务模式清晰，但需理解电力、冷却等技术细节"},
        "网络安全": {"level": "medium", "reason": "身份安全概念相对清晰，但需理解技术架构和竞争格局"},
        "半导体": {"level": "hard", "reason": "需理解HBM技术、存储芯片周期、制造工艺等专业知识"},
        "另类投资": {"level": "hard", "reason": "代币化创新基金结构复杂，透明度低，难以充分理解"},
        "互联网科技": {"level": "medium", "reason": "硬件+互联网模式较复杂，需分别评估手机、IoT、造车等业务"},
        "造纸": {"level": "easy", "reason": "造纸业务模式传统且清晰，成本优势和规模效应容易理解"},
    }

    # 行业经济特征评级
    SECTOR_ECONOMICS = {
        "银行/金融": {"quality": "good", "reason": "高杠杆行业但招行零售模式优质，ROE领先，但受宏观经济影响大"},
        "消费/白酒": {"quality": "excellent", "reason": "高毛利+低资本开支+品牌粘性+定价权，A股最好的商业模式之一"},
        "ETF/全球指数": {"quality": "good", "reason": "低成本、高分散、长期收益确定，但弹性有限"},
        "ETF/道指": {"quality": "good", "reason": "追踪蓝筹股，质量可靠，长期收益稳定"},
        "ETF/港股科技": {"quality": "medium", "reason": "追踪科技指数，成长性好但波动大，受地缘政治影响"},
        "ETF/通信": {"quality": "medium", "reason": "通信行业需求稳定但增长弹性有限"},
        "ETF/科创板": {"quality": "medium", "reason": "科创企业成长性好但风险高，波动大"},
        "制药": {"quality": "good", "reason": "高毛利、专利壁垒高，但研发风险大、专利悬崖问题"},
        "工业/数据中心": {"quality": "good", "reason": "AI基础设施需求确定性强，但竞争激烈且资本开支大"},
        "网络安全": {"quality": "good", "reason": "需求刚性、转换成本高、经常性收入占比高"},
        "半导体": {"quality": "good", "reason": "技术壁垒高、资本壁垒高，但周期性明显"},
        "另类投资": {"quality": "poor", "reason": "流动性差、不透明、管理费高，商业模式不确定性高"},
        "互联网科技": {"quality": "medium", "reason": "硬件制造利润率低，互联网服务利润率高，但整体模式不如纯互联网"},
        "造纸": {"quality": "medium", "reason": "周期性行业、产品同质化、资本开支大，龙头有成本优势"},
    }

    # 护城河评估
    SECTOR_MOAT = {
        "银行/金融": {"moat": "strong", "reason": "零售银行品牌+规模+网络效应，招行在零售领域护城河深"},
        "消费/白酒": {"moat": "strong", "reason": "顶级白酒品牌几乎不可替代，品牌护城河极深"},
        "ETF/全球指数": {"moat": "n/a", "reason": "被动指数无护城河概念，但分散化本身就是保护"},
        "ETF/道指": {"moat": "n/a", "reason": "被动指数无护城河概念"},
        "ETF/港股科技": {"moat": "n/a", "reason": "被动指数无护城河概念"},
        "ETF/通信": {"moat": "n/a", "reason": "被动指数无护城河概念"},
        "ETF/科创板": {"moat": "n/a", "reason": "被动指数无护城河概念"},
        "制药": {"moat": "strong", "reason": "专利壁垒+研发壁垒+FDA审批壁垒，GLP-1赛道护城河深"},
        "工业/数据中心": {"moat": "strong", "reason": "技术+客户粘性+规模效应，Vertiv在电力基础设施领域领先"},
        "网络安全": {"moat": "strong", "reason": "转换成本极高，企业身份管理切换成本大，网络效应"},
        "半导体": {"moat": "strong", "reason": "HBM技术壁垒极高+资本壁垒极高，SK海力士领先"},
        "另类投资": {"moat": "weak", "reason": "无明显的护城河，产品容易被复制"},
        "互联网科技": {"moat": "medium", "reason": "品牌+生态有一定护城河，但远弱于腾讯阿里"},
        "造纸": {"moat": "medium", "reason": "成本优势+规模效应，太阳纸业是行业成本领先者"},
    }

    def gate1_can_i_understand(self, business_model: str) -> dict:
        """门1：我能理解这个业务吗？"""
        sector = business_model
        info = self.SECTOR_UNDERSTANDABILITY.get(sector, {"level": "medium", "reason": "行业理解程度待评估"})

        if info["level"] == "easy":
            passed = True
            score = 2
        elif info["level"] == "medium":
            passed = True
            score = 1
        else:
            passed = False
            score = 0

        return {
            "gate": "门1: 我能理解这个业务吗？",
            "passed": passed,
            "score": score,
            "max_score": 2,
            "detail": info["reason"],
            "level": info["level"],
        }

    def gate2_good_business(self, sector: str, financials: Optional[dict] = None) -> dict:
        """门2：这是好生意吗？"""
        info = self.SECTOR_ECONOMICS.get(sector, {"quality": "medium", "reason": "经济特征待评估"})

        if info["quality"] == "excellent":
            passed = True
            score = 3
        elif info["quality"] == "good":
            passed = True
            score = 2
        elif info["quality"] == "medium":
            passed = True
            score = 1
        else:
            passed = False
            score = 0

        return {
            "gate": "门2: 这是好生意吗？",
            "passed": passed,
            "score": score,
            "max_score": 3,
            "detail": info["reason"],
            "quality": info["quality"],
        }

    def gate3_moat(self, sector: str) -> dict:
        """门3：有护城河吗？"""
        info = self.SECTOR_MOAT.get(sector, {"moat": "medium", "reason": "护城河待评估"})

        if info["moat"] == "strong":
            passed = True
            score = 3
        elif info["moat"] == "medium":
            passed = True
            score = 2
        elif info["moat"] == "n/a":
            passed = True
            score = 1
        else:
            passed = False
            score = 0

        return {
            "gate": "门3: 有护城河吗？",
            "passed": passed,
            "score": score,
            "max_score": 3,
            "detail": info["reason"],
            "moat": info["moat"],
        }

    def gate4_management(self, notes: str) -> dict:
        """门4：管理层靠谱吗？"""
        # 基于notes推断管理层质量
        management_indicators = {
            "核心持仓": "notes提及核心持仓，表明对管理层有一定信任",
            "龙头": "notes提及龙头地位，管理层在行业内有竞争力",
            "深度套牢": "notes提及深度套牢，可能对管理层判断存在偏差",
            "观察仓": "notes提及观察仓，对管理层尚未建立充分信任",
            "小仓位观察": "notes提及小仓位观察，说明对管理层了解有限",
        }

        passed = True
        score = 1
        detail = "管理层信息有限，基于现有信息推断"

        for keyword, inference in management_indicators.items():
            if keyword in notes:
                detail = inference
                if keyword in ("深度套牢",):
                    score = 0
                    passed = False
                elif keyword in ("观察仓", "小仓位观察"):
                    score = 1
                    passed = True
                else:
                    score = 2
                    passed = True
                break

        return {
            "gate": "门4: 管理层靠谱吗？",
            "passed": passed,
            "score": score,
            "max_score": 2,
            "detail": detail,
        }

    def gate5_margin_of_safety(self, pnl_pct: float, sector: str) -> dict:
        """门5：有安全边际吗？"""
        # 安全边际评估：基于盈亏和行业
        # ETF类被动投资安全边际概念不同
        etf_sectors = [s for s in self.SECTOR_UNDERSTANDABILITY if s.startswith("ETF")]

        if sector in etf_sectors:
            passed = True
            score = 1
            detail = "被动指数投资，安全边际概念不直接适用，长期持有本身就是安全边际"
        elif pnl_pct <= -20:
            # 大幅下跌提供了安全边际（如果逻辑没变）
            passed = True
            score = 3
            detail = f"价格已下跌{pnl_pct:.1f}%，提供了显著的安全边际，前提是投资逻辑未变"
        elif pnl_pct <= -10:
            passed = True
            score = 2
            detail = f"价格下跌{pnl_pct:.1f}%，有一定的安全边际"
        elif pnl_pct <= 10:
            passed = True
            score = 1
            detail = f"价格在当前价格{pnl_pct:+.1f}%，安全边际中性"
        elif pnl_pct <= 30:
            passed = True
            score = 0
            detail = f"盈利{pnl_pct:.1f}%，安全边际缩小，但仍在合理范围"
        else:
            passed = False
            score = 0
            detail = f"大幅盈利{pnl_pct:.1f}%，安全边际已不足，需评估是否应部分止盈"

        return {
            "gate": "门5: 有安全边际吗？",
            "passed": passed,
            "score": score,
            "max_score": 3,
            "detail": detail,
        }

    def gate6_position_sizing(self, weight: float) -> dict:
        """门6：仓位是否合理？"""
        if weight >= 30:
            passed = False
            score = 0
            detail = f"仓位{weight:.1f}%过高，集中度风险大，需确保对该标的有足够深度理解"
        elif weight >= 20:
            passed = True
            score = 1
            detail = f"仓位{weight:.1f}%偏高，但仍在可接受范围，需持续跟踪"
        elif weight >= 10:
            passed = True
            score = 2
            detail = f"仓位{weight:.1f}%适中，仓位管理合理"
        elif weight >= 5:
            passed = True
            score = 2
            detail = f"仓位{weight:.1f}%正常，风险可控"
        else:
            passed = True
            score = 1
            detail = f"仓位{weight:.1f}%偏小，观察仓或试错仓位"

        return {
            "gate": "门6: 仓位合理吗？",
            "passed": passed,
            "score": score,
            "max_score": 2,
            "detail": detail,
        }

    def run_checklist(self, holding: dict) -> dict:
        """运行全部六门评估"""
        sector = holding.get("sector", "")
        pnl_pct = holding.get("pnl_pct", 0)
        weight = holding.get("weight", 0)
        notes = holding.get("notes", "")
        ticker = holding.get("ticker", "")
        name = holding.get("name", "")

        g1 = self.gate1_can_i_understand(sector)
        g2 = self.gate2_good_business(sector)
        g3 = self.gate3_moat(sector)
        g4 = self.gate4_management(notes)
        g5 = self.gate5_margin_of_safety(pnl_pct, sector)
        g6 = self.gate6_position_sizing(weight)

        gates = [g1, g2, g3, g4, g5, g6]
        total_score = sum(g["score"] for g in gates)
        max_score = sum(g["max_score"] for g in gates)
        passed_all = all(g["passed"] for g in gates)
        pass_rate = total_score / max_score * 100 if max_score > 0 else 0

        # 找出未通过的门
        failed_gates = [g["gate"] for g in gates if not g["passed"]]

        # 综合评估
        if pass_rate >= 80:
            verdict = "通过"
        elif pass_rate >= 60:
            verdict = "有条件通过"
        else:
            verdict = "未通过"

        return {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "verdict": verdict,
            "passed_all": passed_all,
            "total_score": total_score,
            "max_score": max_score,
            "pass_rate": round(pass_rate, 1),
            "gates": gates,
            "failed_gates": failed_gates,
            "summary": f"六门评估总分{total_score}/{max_score}（{pass_rate:.0f}%），{'全部通过' if passed_all else '未通过门: ' + ', '.join(failed_gates)}",
        }

    def quick_veto_list(self, holding: dict) -> list:
        """快速否决清单 - 8项否决条件"""
        veto_results = []
        pnl_pct = holding.get("pnl_pct", 0)
        weight = holding.get("weight", 0)
        sector = holding.get("sector", "")
        days = holding.get("holding_days", 0)
        day_chg = holding.get("day_change_pct", 0)
        ann_ret = holding.get("annualized_return", 0)
        name = holding.get("name", "")
        ticker = holding.get("ticker", "")

        # 1. 亏损超过40%
        veto_results.append({
            "condition": "亏损超过40%",
            "triggered": pnl_pct <= -40,
            "detail": f"当前亏损{pnl_pct:.1f}%" if pnl_pct <= -40 else f"当前亏损{pnl_pct:.1f}%，未触发",
        })

        # 2. 仓位超过35%
        veto_results.append({
            "condition": "单一仓位超过35%",
            "triggered": weight > 35,
            "detail": f"当前仓位{weight:.1f}%" if weight > 35 else f"当前仓位{weight:.1f}%，未触发",
        })

        # 3. 持有超过2年且亏损超过20%
        veto_results.append({
            "condition": "持有超过2年且亏损超过20%",
            "triggered": days > 730 and pnl_pct <= -20,
            "detail": f"持有{days}天，亏损{pnl_pct:.1f}%" if days > 730 and pnl_pct <= -20 else f"持有{days}天，亏损{pnl_pct:.1f}%，未触发",
        })

        # 4. 年化亏损超过30%
        veto_results.append({
            "condition": "年化亏损超过30%",
            "triggered": days > 30 and ann_ret < -30,
            "detail": f"年化收益{ann_ret:.1f}%" if days > 30 and ann_ret < -30 else f"年化收益{ann_ret:.1f}%，未触发",
        })

        # 5. 单日暴跌超过10%
        veto_results.append({
            "condition": "单日暴跌超过10%",
            "triggered": day_chg <= -10,
            "detail": f"日内跌幅{abs(day_chg):.1f}%" if day_chg <= -10 else f"日内{day_chg:+.1f}%，未触发",
        })

        # 6. 行业为另类投资且仓位超过10%
        veto_results.append({
            "condition": "另类投资仓位超过10%",
            "triggered": sector == "另类投资" and weight > 10,
            "detail": f"另类投资仓位{weight:.1f}%" if sector == "另类投资" and weight > 10 else "未触发",
        })

        # 7. 无法理解的业务（硬科技）且仓位超过20%
        hard_sectors = ["制药", "半导体", "另类投资"]
        veto_results.append({
            "condition": "硬科技/复杂业务仓位超过20%",
            "triggered": sector in hard_sectors and weight > 20,
            "detail": f"{sector}仓位{weight:.1f}%" if sector in hard_sectors and weight > 20 else "未触发",
        })

        # 8. 持有超过90天且从未盈利
        veto_results.append({
            "condition": "持有超过90天且从未盈利超过10%",
            "triggered": days > 90 and pnl_pct <= -10,
            "detail": f"持有{days}天，最大盈利未知，当前亏损{pnl_pct:.1f}%" if days > 90 and pnl_pct <= -10 else "未触发",
        })

        triggered = [v for v in veto_results if v["triggered"]]
        return {
            "ticker": ticker,
            "name": name,
            "veto_results": veto_results,
            "triggered_count": len(triggered),
            "triggered_items": [v["condition"] for v in triggered],
            "has_veto": len(triggered) > 0,
        }


# ====================================================================
# QualityScreen — 去劣筛选引擎
# ====================================================================

class QualityScreen:
    """七项去劣筛选：ROE、FCF、利息覆盖、毛利率、OCF/NI、净利率、股权稀释"""

    # 行业基准估计
    SECTOR_BENCHMARKS = {
        "银行/金融": {
            "roe": {"good": 12, "borderline": 8},
            "fcf_yield": {"good": 3, "borderline": 1},
            "interest_coverage": {"good": 8, "borderline": 5},
            "gross_margin": {"good": 60, "borderline": 40},
            "ocf_ni_ratio": {"good": 1.2, "borderline": 0.8},
            "net_margin": {"good": 25, "borderline": 15},
            "share_dilution": {"good": 0, "borderline": 2},
        },
        "消费/白酒": {
            "roe": {"good": 15, "borderline": 10},
            "fcf_yield": {"good": 4, "borderline": 2},
            "interest_coverage": {"good": 20, "borderline": 10},
            "gross_margin": {"good": 70, "borderline": 55},
            "ocf_ni_ratio": {"good": 1.2, "borderline": 0.8},
            "net_margin": {"good": 25, "borderline": 15},
            "share_dilution": {"good": 0, "borderline": 1},
        },
        "ETF/全球指数": {
            "roe": {"good": 8, "borderline": 5},
            "fcf_yield": {"good": 3, "borderline": 1},
            "interest_coverage": {"good": 5, "borderline": 3},
            "gross_margin": {"good": 50, "borderline": 30},
            "ocf_ni_ratio": {"good": 1.0, "borderline": 0.7},
            "net_margin": {"good": 15, "borderline": 8},
            "share_dilution": {"good": 0, "borderline": 1},
        },
        "ETF/道指": {
            "roe": {"good": 10, "borderline": 6},
            "fcf_yield": {"good": 3, "borderline": 1.5},
            "interest_coverage": {"good": 8, "borderline": 4},
            "gross_margin": {"good": 40, "borderline": 25},
            "ocf_ni_ratio": {"good": 1.0, "borderline": 0.7},
            "net_margin": {"good": 12, "borderline": 7},
            "share_dilution": {"good": 0, "borderline": 1},
        },
        "ETF/港股科技": {
            "roe": {"good": 10, "borderline": 5},
            "fcf_yield": {"good": 2, "borderline": 0.5},
            "interest_coverage": {"good": 8, "borderline": 4},
            "gross_margin": {"good": 40, "borderline": 25},
            "ocf_ni_ratio": {"good": 1.0, "borderline": 0.7},
            "net_margin": {"good": 15, "borderline": 8},
            "share_dilution": {"good": 0, "borderline": 1},
        },
        "ETF/通信": {
            "roe": {"good": 8, "borderline": 5},
            "fcf_yield": {"good": 3, "borderline": 1.5},
            "interest_coverage": {"good": 6, "borderline": 3},
            "gross_margin": {"good": 35, "borderline": 20},
            "ocf_ni_ratio": {"good": 1.0, "borderline": 0.7},
            "net_margin": {"good": 10, "borderline": 5},
            "share_dilution": {"good": 0, "borderline": 1},
        },
        "ETF/科创板": {
            "roe": {"good": 8, "borderline": 3},
            "fcf_yield": {"good": 1, "borderline": 0},
            "interest_coverage": {"good": 5, "borderline": 2},
            "gross_margin": {"good": 40, "borderline": 25},
            "ocf_ni_ratio": {"good": 0.8, "borderline": 0.5},
            "net_margin": {"good": 12, "borderline": 5},
            "share_dilution": {"good": 0, "borderline": 2},
        },
        "制药": {
            "roe": {"good": 20, "borderline": 12},
            "fcf_yield": {"good": 3, "borderline": 1.5},
            "interest_coverage": {"good": 15, "borderline": 8},
            "gross_margin": {"good": 75, "borderline": 60},
            "ocf_ni_ratio": {"good": 1.1, "borderline": 0.7},
            "net_margin": {"good": 20, "borderline": 10},
            "share_dilution": {"good": 0, "borderline": 1},
        },
        "工业/数据中心": {
            "roe": {"good": 18, "borderline": 12},
            "fcf_yield": {"good": 3, "borderline": 1},
            "interest_coverage": {"good": 10, "borderline": 5},
            "gross_margin": {"good": 38, "borderline": 28},
            "ocf_ni_ratio": {"good": 1.2, "borderline": 0.8},
            "net_margin": {"good": 12, "borderline": 7},
            "share_dilution": {"good": 0, "borderline": 1.5},
        },
        "网络安全": {
            "roe": {"good": 10, "borderline": 5},
            "fcf_yield": {"good": 2, "borderline": 0.5},
            "interest_coverage": {"good": 10, "borderline": 5},
            "gross_margin": {"good": 72, "borderline": 62},
            "ocf_ni_ratio": {"good": 1.0, "borderline": 0.6},
            "net_margin": {"good": 10, "borderline": 2},
            "share_dilution": {"good": 0, "borderline": 2},
        },
        "半导体": {
            "roe": {"good": 15, "borderline": 8},
            "fcf_yield": {"good": 2, "borderline": 0.5},
            "interest_coverage": {"good": 12, "borderline": 6},
            "gross_margin": {"good": 45, "borderline": 30},
            "ocf_ni_ratio": {"good": 1.1, "borderline": 0.7},
            "net_margin": {"good": 18, "borderline": 8},
            "share_dilution": {"good": 0, "borderline": 1},
        },
        "另类投资": {
            "roe": {"good": 5, "borderline": 0},
            "fcf_yield": {"good": 2, "borderline": 0},
            "interest_coverage": {"good": 3, "borderline": 1},
            "gross_margin": {"good": 30, "borderline": 15},
            "ocf_ni_ratio": {"good": 0.8, "borderline": 0.5},
            "net_margin": {"good": 8, "borderline": 0},
            "share_dilution": {"good": 0, "borderline": 3},
        },
        "互联网科技": {
            "roe": {"good": 12, "borderline": 6},
            "fcf_yield": {"good": 3, "borderline": 1},
            "interest_coverage": {"good": 10, "borderline": 5},
            "gross_margin": {"good": 25, "borderline": 15},
            "ocf_ni_ratio": {"good": 1.1, "borderline": 0.7},
            "net_margin": {"good": 8, "borderline": 3},
            "share_dilution": {"good": 0, "borderline": 2},
        },
        "造纸": {
            "roe": {"good": 10, "borderline": 6},
            "fcf_yield": {"good": 5, "borderline": 2},
            "interest_coverage": {"good": 8, "borderline": 4},
            "gross_margin": {"good": 20, "borderline": 12},
            "ocf_ni_ratio": {"good": 1.3, "borderline": 0.9},
            "net_margin": {"good": 8, "borderline": 4},
            "share_dilution": {"good": 0, "borderline": 1},
        },
    }

    def _estimate_metric(self, holding: dict, metric: str) -> dict:
        """基于持仓数据和行业基准估计单项指标"""
        sector = holding.get("sector", "")
        pnl_pct = holding.get("pnl_pct", 0)
        days = holding.get("holding_days", 0)

        benchmarks = self.SECTOR_BENCHMARKS.get(sector, self.SECTOR_BENCHMARKS.get("ETF/全球指数"))

        if metric not in benchmarks:
            return {"result": "unknown", "detail": "缺少行业基准"}

        bm = benchmarks[metric]
        good = bm["good"]
        borderline = bm["borderline"]

        # 根据盈亏和行业特征估算指标
        # 亏损程度作为基本面压力的代理变量
        if pnl_pct <= -30:
            pressure = "high"
        elif pnl_pct <= -15:
            pressure = "medium"
        elif pnl_pct <= -5:
            pressure = "low"
        else:
            pressure = "none"

        # 估算估计值范围
        if pressure == "high":
            estimated = borderline * 0.7
        elif pressure == "medium":
            estimated = borderline * 0.9
        elif pressure == "low":
            estimated = (borderline + good) / 2
        else:
            estimated = good * 1.1

        # 判断结果
        if estimated >= good:
            result = "pass"
        elif estimated >= borderline:
            result = "borderline"
        else:
            result = "fail"

        return {
            "result": result,
            "estimated": round(estimated, 1),
            "threshold_good": good,
            "threshold_borderline": borderline,
            "pressure": pressure,
        }

    def screen_holding(self, holding: dict) -> dict:
        """对单个持仓执行七项筛选"""
        sector = holding.get("sector", "")
        ticker = holding.get("ticker", "")
        name = holding.get("name", "")
        pnl_pct = holding.get("pnl_pct", 0)

        if sector == "现金":
            return {
                "ticker": ticker,
                "name": name,
                "sector": sector,
                "is_cash": True,
                "summary": "现金仓位，不适用质量筛选",
                "overall": "n/a",
                "criteria": [],
            }

        criteria_names = [
            ("roe", "ROE（净资产收益率）"),
            ("fcf_yield", "FCF收益率（自由现金流/市值）"),
            ("interest_coverage", "利息覆盖倍数"),
            ("gross_margin", "毛利率"),
            ("ocf_ni_ratio", "经营现金流/净利润比率"),
            ("net_margin", "净利率"),
            ("share_dilution", "股权稀释（年均%）"),
        ]

        results = []
        passed = 0
        failed = 0
        borderline = 0

        for key, label in criteria_names:
            est = self._estimate_metric(holding, key)
            results.append({
                "criterion": label,
                "key": key,
                "result": est["result"],
                "estimated_value": est["estimated"],
                "threshold_good": f">={est['threshold_good']}",
                "threshold_borderline": f">={est['threshold_borderline']}",
                "pressure_level": est["pressure"],
            })
            if est["result"] == "pass":
                passed += 1
            elif est["result"] == "fail":
                failed += 1
            else:
                borderline += 1

        # 综合评定
        total = len(criteria_names)
        if failed >= 3:
            overall = "fail"
            summary = f"七项筛选{passed}通过/{borderline}边缘/{failed}未通过，{failed}项未通过，质量堪忧"
        elif failed >= 1:
            overall = "borderline"
            summary = f"七项筛选{passed}通过/{borderline}边缘/{failed}未通过，存在{failed}项短板需关注"
        else:
            overall = "pass"
            summary = f"七项筛选全部通过或边缘，{passed}通过/{borderline}边缘，质量良好"

        return {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "overall": overall,
            "summary": summary,
            "passed": passed,
            "borderline": borderline,
            "failed": failed,
            "total": total,
            "criteria": results,
        }

    def screen_all(self, holdings: list) -> list:
        """筛选全部持仓"""
        results = []
        for h in holdings:
            if h.get("exchange") == "CASH":
                continue
            results.append(self.screen_holding(h))
        return results


# ====================================================================
# NewsPulse — 新闻情绪脉冲引擎
# ====================================================================

class NewsPulse:
    """新闻情绪脉冲引擎：检测价格异常、评估新闻影响"""

    # 行业敏感度配置
    SECTOR_SENSITIVITY = {
        "银行/金融": {"event_sensitivity": "medium", "common_triggers": ["利率政策", "经济数据", "监管政策"]},
        "消费/白酒": {"event_sensitivity": "medium", "common_triggers": ["消费数据", "政策调控", "行业库存"]},
        "ETF/全球指数": {"event_sensitivity": "low", "common_triggers": ["宏观数据", "地缘政治", "美联储政策"]},
        "ETF/道指": {"event_sensitivity": "low", "common_triggers": ["宏观数据", "美联储政策", "企业财报"]},
        "ETF/港股科技": {"event_sensitivity": "high", "common_triggers": ["中美关系", "科技政策", "港股流动性"]},
        "ETF/通信": {"event_sensitivity": "medium", "common_triggers": ["5G政策", "AI算力需求", "行业投资"]},
        "ETF/科创板": {"event_sensitivity": "high", "common_triggers": ["科创政策", "市场风险偏好", "流动性变化"]},
        "制药": {"event_sensitivity": "high", "common_triggers": ["新药审批", "临床试验数据", "财报数据", "专利诉讼"]},
        "工业/数据中心": {"event_sensitivity": "high", "common_triggers": ["AI资本开支", "订单数据", "财报", "竞争格局"]},
        "网络安全": {"event_sensitivity": "medium", "common_triggers": ["安全漏洞事件", "财报", "收购并购"]},
        "半导体": {"event_sensitivity": "high", "common_triggers": ["存储芯片价格", "AI需求", "财报", "技术突破"]},
        "另类投资": {"event_sensitivity": "low", "common_triggers": ["市场流动性", "基金报告"]},
        "互联网科技": {"event_sensitivity": "high", "common_triggers": ["电动车进展", "手机份额", "财报", "公司回购"]},
        "造纸": {"event_sensitivity": "low", "common_triggers": ["纸价走势", "原材料成本", "行业供需"]},
    }

    def detect_price_anomaly(self, holding: dict) -> dict:
        """检测价格是否异常波动"""
        ticker = holding.get("ticker", "")
        name = holding.get("name", "")
        day_chg = holding.get("day_change_pct", 0)
        pnl_pct = holding.get("pnl_pct", 0)
        sector = holding.get("sector", "")

        anomalies = []
        is_anomaly = False
        anomaly_type = None
        severity = "low"

        # 1. 检查单日涨跌幅
        if abs(day_chg) >= 10:
            is_anomaly = True
            anomaly_type = "extreme"
            severity = "high"
            anomalies.append(f"单日{'上涨' if day_chg > 0 else '下跌'}{abs(day_chg):.1f}%，属于极端异常波动")
        elif abs(day_chg) >= 7:
            is_anomaly = True
            anomaly_type = "major"
            severity = "high"
            anomalies.append(f"单日{'上涨' if day_chg > 0 else '下跌'}{abs(day_chg):.1f}%，属于重大异常波动")
        elif abs(day_chg) >= 5:
            is_anomaly = True
            anomaly_type = "significant"
            severity = "medium"
            anomalies.append(f"单日{'上涨' if day_chg > 0 else '下跌'}{abs(day_chg):.1f}%，属于显著异常波动")
        elif abs(day_chg) >= 3:
            anomalies.append(f"单日{'上涨' if day_chg > 0 else '下跌'}{abs(day_chg):.1f}%，波动较大但未达异常阈值")

        # 2. 检查累计盈亏变化
        if pnl_pct <= -30:
            if is_anomaly:
                anomalies.append(f"累计亏损{pnl_pct:.1f}%，叠加日内异常波动，需高度警惕")
            else:
                anomalies.append(f"累计亏损{pnl_pct:.1f}%，需关注是否持续恶化")

        # 3. 行业敏感度检查
        sensitivity = self.SECTOR_SENSITIVITY.get(sector, {}).get("event_sensitivity", "medium")
        if sensitivity == "high" and abs(day_chg) >= 3:
            anomalies.append(f"{sector}行业敏感度高，{abs(day_chg):.1f}%的波动可能对应重大行业事件")

        # 4. 连续异常检查（基于pnl_pct的剧烈变化）
        # 注意：这里没有历史数据，只能做单点检测
        if abs(day_chg) >= 5 and pnl_pct <= -20:
            anomalies.append("价格处于低位且日内大幅波动，可能存在恐慌性抛售或抄底资金涌入")

        return {
            "ticker": ticker,
            "name": name,
            "is_anomaly": is_anomaly,
            "anomaly_type": anomaly_type,
            "severity": severity,
            "day_change_pct": round(day_chg, 2),
            "anomalies": anomalies,
            "sector_sensitivity": sensitivity,
        }

    def quick_news_assessment(self, holding: dict) -> dict:
        """快速评估新闻影响"""
        ticker = holding.get("ticker", "")
        name = holding.get("name", "")
        day_chg = holding.get("day_change_pct", 0)
        sector = holding.get("sector", "")
        notes = holding.get("notes", "")
        pnl_pct = holding.get("pnl_pct", 0)

        # 基于价格变动和行业推断新闻影响
        sensitivity = self.SECTOR_SENSITIVITY.get(sector, {})
        common_triggers = sensitivity.get("common_triggers", ["行业新闻"])

        # 分类新闻影响类型
        if abs(day_chg) < 2:
            # 波动很小，无明显新闻影响
            category = "normal"
            impact = "neutral"
            detail = "价格波动正常，无明显新闻驱动"
            confidence = "high"
        elif day_chg >= 5:
            # 大涨
            if pnl_pct <= -20:
                category = "value_event"
                impact = "positive"
                detail = f"大涨{day_chg:.1f}%，可能是价值发现或超跌反弹，关注{', '.join(common_triggers[:2])}相关利好"
                confidence = "medium"
            else:
                category = "emotion_volatility"
                impact = "positive"
                detail = f"上涨{day_chg:.1f}%，可能是情绪驱动或行业催化，关注{', '.join(common_triggers[:2])}"
                confidence = "low"
        elif day_chg <= -5:
            # 大跌
            if pnl_pct <= -20:
                category = "emotion_volatility"
                impact = "negative"
                detail = f"大跌{abs(day_chg):.1f}%，深度套牢中进一步下跌，可能是恐慌性抛售或新利空"
                confidence = "medium"
            else:
                category = "value_event"
                impact = "negative"
                detail = f"大跌{abs(day_chg):.1f}%，可能是重大利空事件，需检查{', '.join(common_triggers[:2])}"
                confidence = "high"
        elif day_chg >= 3:
            category = "emotion_volatility"
            impact = "positive"
            detail = f"上涨{day_chg:.1f}%，温和上涨，可能是正面情绪或行业利好"
            confidence = "medium"
        elif day_chg <= -3:
            category = "emotion_volatility"
            impact = "negative"
            detail = f"下跌{abs(day_chg):.1f}%，温和下跌，可能是获利回吐或短期负面情绪"
            confidence = "medium"
        else:
            category = "unknown"
            impact = "neutral"
            detail = f"波动{day_chg:+.1f}%在正常范围，无明显新闻影响迹象"
            confidence = "high"

        # 根据notes补充
        news_keywords = {
            "财报": "临近财报期，波动可能加大",
            "收购": "存在收购事件，需要关注整合进展",
            "回购": "公司持续回购，体现管理层信心",
            "上市": "新股上市初期波动较大",
            "深度套牢": "持仓者情绪可能影响判断",
        }
        extra_notes = []
        for keyword, note in news_keywords.items():
            if keyword in notes:
                extra_notes.append(note)

        return {
            "ticker": ticker,
            "name": name,
            "category": category,
            "impact": impact,
            "confidence": confidence,
            "detail": detail,
            "extra_notes": extra_notes,
            "common_triggers": common_triggers,
            "day_change_pct": round(day_chg, 2),
        }


# ====================================================================
# DeepLogic — 深度分析引擎
# ====================================================================

class DeepLogicAnalysis:
    """深度逻辑分析：SOTP、隐含预期、期权价值、博弈论、时间壁垒"""

    def sotp_analysis(self, holding: dict) -> dict:
        """分部估值（SOTP）分析"""
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        pnl_pct = holding.get("pnl_pct", 0)
        weight = holding.get("weight", 0)

        # SOTP估算（基于行业特征）
        sotp_estimates = {
            "银行/金融": "零售银行估值+对公业务估值，招行零售业务占比高应享受估值溢价",
            "消费/白酒": "品牌价值+产能价值+渠道价值，高端白酒品牌价值是核心",
            "ETF/全球指数": "NAV（净资产价值）跟踪，无分部分析必要",
            "ETF/道指": "NAV跟踪，无分部分析必要",
            "ETF/港股科技": "NAV跟踪，无分部分析必要",
            "ETF/通信": "NAV跟踪，无分部分析必要",
            "ETF/科创板": "NAV跟踪，无分部分析必要",
            "制药": "核心产品估值（Zepbound/Mounjaro）+ 管线期权价值 + 现金",
            "工业/数据中心": "电力基础设施业务估值 + 服务收入估值，服务收入应享受更高估值",
            "网络安全": "订阅收入估值（ARR倍数）+ 专业服务估值",
            "半导体": "HBM业务估值 + 传统存储估值，HBM应享受高增长溢价",
            "另类投资": "NAV估值，但折价率较高",
            "互联网科技": "手机业务估值 + IoT业务估值 + 互联网服务估值 + 造车期权价值",
            "造纸": "造纸业务估值 + 浆纸一体化价值",
        }

        sotp = sotp_estimates.get(sector, "分部分析数据不足")
        return {
            "applicable": sector not in ("ETF/全球指数", "ETF/道指", "ETF/港股科技", "ETF/通信", "ETF/科创板"),
            "sotp_detail": sotp,
            "note": "基于行业特征估算，非精确计算",
        }

    def implied_expectation(self, holding: dict) -> dict:
        """隐含市场预期分析：当前价格反映了什么预期？"""
        sector = holding.get("sector", "")
        pnl_pct = holding.get("pnl_pct", 0)
        name = holding.get("name", "")

        if pnl_pct <= -30:
            expectation = "非常悲观"
            detail = f"价格已下跌{pnl_pct:.1f}%，市场已定价了极其悲观的前景，任何不差的实际数据都可能成为反弹催化剂"
        elif pnl_pct <= -15:
            expectation = "悲观"
            detail = f"价格下跌{pnl_pct:.1f}%，市场预期偏悲观，需要超预期才能推动上涨"
        elif pnl_pct <= -5:
            expectation = "谨慎"
            detail = f"小幅下跌{pnl_pct:.1f}%，市场情绪中性偏谨慎"
        elif pnl_pct <= 10:
            expectation = "中性"
            detail = f"价格在成本附近{pnl_pct:+.1f}%，市场预期中性"
        elif pnl_pct <= 30:
            expectation = "乐观"
            detail = f"盈利{pnl_pct:.1f}%，市场预期已偏乐观，需警惕预期差"
        else:
            expectation = "非常乐观"
            detail = f"大幅盈利{pnl_pct:.1f}%，市场已price in了大量利好，需警惕预期差风险"

        return {
            "expectation": expectation,
            "detail": detail,
            "pnl_pct": round(pnl_pct, 1),
        }

    def option_value(self, holding: dict) -> list:
        """期权价值分析：非对称性机会"""
        sector = holding.get("sector", "")
        name = holding.get("name", "")
        pnl_pct = holding.get("pnl_pct", 0)
        weight = holding.get("weight", 0)
        notes = holding.get("notes", "")

        options = []

        # 通用期权价值
        if pnl_pct <= -15:
            options.append({
                "type": "均值回归期权",
                "value": "高" if pnl_pct <= -30 else "中",
                "detail": f"价格已大幅下跌{pnl_pct:.1f}%，如果基本面未变，均值回归将带来可观回报",
            })

        # 行业特定期权价值
        sector_options = {
            "制药": {"type": "新药管线期权", "value": "高", "detail": "GLP-1新适应症获批、新药审批等都是潜在催化剂"},
            "工业/数据中心": {"type": "AI需求期权", "value": "高", "detail": "AI资本开支持续增长，Vertiv订单超预期是潜在上行催化剂"},
            "半导体": {"type": "HBM需求期权", "value": "高", "detail": "HBM是AI算力瓶颈，需求超预期可能带来戴维斯双击"},
            "互联网科技": {"type": "造车期权", "value": "中", "detail": "小米电动车如果成功，将打开千亿级新市场"},
            "消费/白酒": {"type": "周期反转期权", "value": "中", "detail": "白酒行业周期底部，一旦复苏将带来估值和盈利双升"},
        }

        if sector in sector_options:
            options.append(sector_options[sector])

        # 基于notes的期权
        if "财报" in notes:
            options.append({
                "type": "财报事件期权",
                "value": "高",
                "detail": "临近财报期，业绩超/不及预期将带来大幅波动",
            })

        if not options:
            options.append({
                "type": "持有期权",
                "value": "低",
                "detail": "当前未见明显的非对称性机会",
            })

        return options

    def game_theory(self, holding: dict) -> list:
        """博弈论分析：市场参与者的博弈格局"""
        sector = holding.get("sector", "")
        name = holding.get("name", "")

        games = []

        sector_games = {
            "银行/金融": [
                "多头逻辑: 经济复苏+息差企稳+高股息吸引价值投资者",
                "空头逻辑: 经济下行+息差收窄+地产风险暴露",
                "博弈焦点: 宏观经济数据和利率政策走向",
            ],
            "消费/白酒": [
                "多头逻辑: 库存出清+消费复苏+估值低位",
                "空头逻辑: 消费降级+年轻人不喝+库存压力",
                "博弈焦点: 中秋国庆旺季销售数据和库存水平",
            ],
            "制药": [
                "多头逻辑: GLP-1赛道高增长+新适应症获批+专利壁垒",
                "空头逻辑: 竞争加剧+安全性担忧+专利悬崖",
                "博弈焦点: 8/5财报的销售数据和管线进展",
            ],
            "工业/数据中心": [
                "多头逻辑: AI资本开支确定性高+Vertiv是细分龙头",
                "空头逻辑: 订单节奏问题+竞争加剧+AI资本开支放缓",
                "博弈焦点: EMEA订单改善趋势和AI资本开支指引",
            ],
            "网络安全": [
                "多头逻辑: 身份安全需求刚性+转换成本高+Okta领先",
                "空头逻辑: 微软等大厂挤压+增长放缓+盈利改善不及预期",
                "博弈焦点: 营收增长趋势和盈利改善进度",
            ],
            "半导体": [
                "多头逻辑: HBM持续受益AI需求+SK海力士技术领先",
                "空头逻辑: 存储芯片周期性+上市初期波动大",
                "博弈焦点: HBM订单和AI资本开支趋势",
            ],
            "互联网科技": [
                "多头逻辑: 手机份额稳定+造车进展+回购支撑",
                "空头逻辑: 造车持续烧钱+手机竞争加剧+港股流动性",
                "博弈焦点: 电动车SU7交付数据和手机市场份额变化",
            ],
            "造纸": [
                "多头逻辑: 成本优势+周期底部+管理层激励",
                "空头逻辑: 需求疲软+纸价低迷+产能过剩",
                "博弈焦点: 纸价走势和行业供需变化",
            ],
        }

        games = sector_games.get(sector, [
            "多头逻辑: 估值合理+长期趋势向好",
            "空头逻辑: 短期不确定性+市场情绪偏弱",
            "博弈焦点: 行业基本面变化",
        ])

        return games

    def time_wall(self, holding: dict) -> dict:
        """时间壁垒分析：时间是朋友还是敌人？"""
        sector = holding.get("sector", "")
        days = holding.get("holding_days", 0)
        pnl_pct = holding.get("pnl_pct", 0)
        name = holding.get("name", "")
        ann_ret = holding.get("annualized_return", 0)

        # 判断时间是朋友还是敌人
        time_friend_sectors = [
            "ETF/全球指数", "ETF/道指", "消费/白酒",
            "银行/金融", "工业/数据中心", "网络安全",
        ]
        time_enemy_sectors = [
            "互联网科技", "ETF/通信", "另类投资",
        ]

        if sector in time_friend_sectors:
            if pnl_pct >= 0:
                verdict = "时间在创造价值，继续持有"
                friend = True
            elif days > 180:
                verdict = "时间在验证逻辑，但需要更多耐心"
                friend = True
            else:
                verdict = "时间需要更多才能验证"
                friend = True
        elif sector in time_enemy_sectors:
            if pnl_pct <= -20 and days > 180:
                verdict = "时间在消耗价值，需考虑是否继续等待"
                friend = False
            else:
                verdict = "时间可能不是朋友，需关注催化剂"
                friend = False
        else:
            verdict = "时间中性，取决于催化剂何时出现"
            friend = None

        # 时间消耗成本
        if days > 0:
            daily_cost_pct = abs(pnl_pct) / days if pnl_pct < 0 else 0
            time_cost = f"每日亏损约{daily_cost_pct:.2f}%" if daily_cost_pct > 0 else "时间成本为零（盈利中）"
        else:
            time_cost = "持仓时间不足一天"

        return {
            "ticker": holding.get("ticker", ""),
            "name": name,
            "time_is_friend": friend,
            "verdict": verdict,
            "time_cost": time_cost,
            "holding_days": days,
            "annualized_return": round(ann_ret, 1),
        }


# ====================================================================
# IncomeAnalysis — 收益分析引擎
# ====================================================================

class IncomeAnalysis:
    """收益分析：分红可持续性、情景分析"""

    # 行业分红特征
    SECTOR_DIVIDEND_PROFILES = {
        "银行/金融": {"dividend_yield": 4.5, "payout_ratio": 30, "sustainability": "high", "trend": "稳定增长"},
        "消费/白酒": {"dividend_yield": 2.5, "payout_ratio": 50, "sustainability": "high", "trend": "稳定"},
        "ETF/全球指数": {"dividend_yield": 1.8, "payout_ratio": 40, "sustainability": "high", "trend": "跟随市场"},
        "ETF/道指": {"dividend_yield": 2.0, "payout_ratio": 35, "sustainability": "high", "trend": "稳定增长"},
        "ETF/港股科技": {"dividend_yield": 0.5, "payout_ratio": 20, "sustainability": "low", "trend": "低分红"},
        "ETF/通信": {"dividend_yield": 1.2, "payout_ratio": 30, "sustainability": "medium", "trend": "稳定"},
        "ETF/科创板": {"dividend_yield": 0.3, "payout_ratio": 15, "sustainability": "low", "trend": "低分红"},
        "制药": {"dividend_yield": 0.8, "payout_ratio": 35, "sustainability": "medium", "trend": "增长中"},
        "工业/数据中心": {"dividend_yield": 0.5, "payout_ratio": 15, "sustainability": "low", "trend": "低分红/再投资"},
        "网络安全": {"dividend_yield": 0.0, "payout_ratio": 0, "sustainability": "n/a", "trend": "无分红"},
        "半导体": {"dividend_yield": 1.0, "payout_ratio": 15, "sustainability": "medium", "trend": "周期性"},
        "另类投资": {"dividend_yield": 0.0, "payout_ratio": 0, "sustainability": "n/a", "trend": "无分红"},
        "互联网科技": {"dividend_yield": 0.0, "payout_ratio": 0, "sustainability": "n/a", "trend": "无分红"},
        "造纸": {"dividend_yield": 2.0, "payout_ratio": 30, "sustainability": "medium", "trend": "周期性波动"},
    }

    def analyze_dividend_sustainability(self, holding: dict) -> dict:
        """分析分红可持续性"""
        sector = holding.get("sector", "")
        pnl_pct = holding.get("pnl_pct", 0)
        name = holding.get("name", "")

        profile = self.SECTOR_DIVIDEND_PROFILES.get(sector, {})
        if not profile or profile["sustainability"] == "n/a":
            return {
                "has_dividend": False,
                "detail": f"{name}不分红或分红不适用",
                "sustainability": "n/a",
            }

        # 基于盈亏调整可持续性
        sustainability = profile["sustainability"]
        if pnl_pct <= -30:
            sustainability = "low"
            detail = f"价格大幅下跌{pnl_pct:.1f}%，可能影响分红能力，需关注财报现金流数据"
        elif pnl_pct <= -15:
            sustainability = "medium" if sustainability == "high" else sustainability
            detail = f"价格下跌{pnl_pct:.1f}%，分红可持续性需关注，但大概率不受影响"
        else:
            detail = f"分红可持续性强，{profile['trend']}，当前估算股息率约{profile['dividend_yield']}%"

        return {
            "has_dividend": True,
            "sustainability": sustainability,
            "estimated_yield": profile["dividend_yield"],
            "estimated_payout_ratio": profile["payout_ratio"],
            "trend": profile["trend"],
            "detail": detail,
        }

    def dividend_scenarios(self, holding: dict) -> list:
        """分红情景分析"""
        sector = holding.get("sector", "")
        pnl_pct = holding.get("pnl_pct", 0)
        name = holding.get("name", "")

        profile = self.SECTOR_DIVIDEND_PROFILES.get(sector, {})
        if not profile or profile["sustainability"] == "n/a":
            return [{"scenario": "不适用", "detail": f"{name}不分红"}]

        scenarios = [
            {
                "scenario": "基准情景",
                "detail": f"维持当前分红水平，股息率约{profile['dividend_yield']}%",
                "probability": "高",
            },
            {
                "scenario": "乐观情景",
                "detail": f"盈利改善带动分红增长，股息率提升至{profile['dividend_yield'] + 1:.1f}%",
                "probability": "中",
            },
        ]

        if pnl_pct <= -15:
            scenarios.append({
                "scenario": "悲观情景",
                "detail": "盈利下滑导致分红减少或取消",
                "probability": "低",
            })
        else:
            scenarios.append({
                "scenario": "悲观情景",
                "detail": f"盈利波动导致分红小幅调整，但大概率维持",
                "probability": "低",
            })

        return scenarios


# ====================================================================
# 主分析引擎（增强版）
# ====================================================================

class BerkshireAnalysis:
    """AI Berkshire 方法论集成分析引擎（增强版）
    集成四大师框架 + ThesisTracker + InvestmentChecklist + QualityScreen + NewsPulse + DeepLogic + IncomeAnalysis
    """

    def __init__(self, manager):
        self.manager = manager
        self.holdings = manager.get_holdings_table()
        self.summary = manager.get_summary_dict()
        self.thesis_tracker = ThesisTracker()
        self.checklist = InvestmentChecklist()
        self.quality_screen = QualityScreen()
        self.news_pulse = NewsPulse()
        self.deep_logic = DeepLogicAnalysis()
        self.income_analysis = IncomeAnalysis()

    def _build_data_snapshot(self, holding: dict) -> dict:
        """构建数据快照"""
        return {
            "pnl_pct": round(holding.get("pnl_pct", 0), 1),
            "pnl": round(holding.get("pnl", 0), 2),
            "weight": round(holding.get("weight", 0), 1),
            "weight_a": round(holding.get("weight_a", 0), 1),
            "weight_hk_us": round(holding.get("weight_hk_us", 0), 1),
            "holding_days": holding.get("holding_days", 0),
            "day_change_pct": round(holding.get("day_change_pct", 0), 2),
            "current_price": round(holding.get("current_price", 0), 2),
            "avg_cost": round(holding.get("avg_cost", 0), 2),
            "annualized_return": round(holding.get("annualized_return", 0), 1),
            "market": holding.get("market", ""),
        }

    def _build_signals(self, holding: dict, munger: dict) -> list:
        """构建数据驱动信号"""
        signals = []
        pnl_pct = holding.get("pnl_pct", 0)
        day_chg = holding.get("day_change_pct", 0)
        weight = holding.get("weight", 0)
        days = holding.get("holding_days", 0)
        ann_ret = holding.get("annualized_return", 0)

        # 盈亏信号
        if pnl_pct <= -30:
            signals.append({"type": "danger", "icon": "&#x26A0;", "text": f"亏损 {pnl_pct:.1f}%，已触发快速否决红线"})
        elif pnl_pct <= -15:
            signals.append({"type": "warning", "icon": "&#x26A0;", "text": f"亏损 {pnl_pct:.1f}%，需审视逻辑是否被证伪"})
        elif pnl_pct <= -5:
            signals.append({"type": "info", "icon": "&#x2193;", "text": f"小幅亏损 {pnl_pct:.1f}% 在正常波动范围"})
        elif pnl_pct >= 50:
            signals.append({"type": "success", "icon": "&#x2191;", "text": f"盈利 {pnl_pct:.1f}%，巴菲特：'好公司管住手不卖'"})
        elif pnl_pct >= 20:
            signals.append({"type": "success", "icon": "&#x2191;", "text": f"盈利 {pnl_pct:.1f}%，表现良好"})

        # 日涨跌信号
        if abs(day_chg) >= 5:
            signals.append({
                "type": "danger" if day_chg < 0 else "success",
                "icon": "&#x26A1;",
                "text": f"日内{'下跌' if day_chg < 0 else '上涨'}{abs(day_chg):.1f}%，芒格：'检查是否有新信息，不要被短期波动干扰'"
            })

        # 集中度信号
        if weight >= 30:
            signals.append({"type": "warning", "icon": "&#x26A0;", "text": f"仓位占比 {weight:.1f}%，巴菲特：'适度集中是好事，但必须深入理解'"})
        elif weight >= 20:
            signals.append({"type": "info", "icon": "&#x26A0;", "text": f"仓位占比 {weight:.1f}%"})

        # 持仓时间信号
        if days <= 5:
            signals.append({"type": "info", "icon": "&#x1F4C5;", "text": f"新建仓仅 {days} 天，段永平：'买股票就是买公司，需要时间验证'"})
        elif days >= 180:
            signals.append({"type": "info", "icon": "&#x23F1;", "text": f"已持有 {days} 天，李录：'长期持有是验证判断的唯一方式'"})

        # 年化收益信号
        if days > 30 and ann_ret < -20:
            signals.append({"type": "warning", "icon": "&#x26A0;", "text": f"年化 {ann_ret:.1f}%，芒格：'反过来想——如果年化亏20%，是不是应该考虑卖出？'"})

        # 芒格式逆向问题
        for q in munger.get("reverse_questions", []):
            signals.append({"type": "info", "icon": "&#x1F4AD;", "text": f"芒格追问: {q}"})

        return signals

    def analyze_holding(self, holding: dict) -> dict:
        """对单个持仓运行完整分析（四大师 + 深度分析 + 论点追踪 + 收益分析 + 清单 + 筛选 + 新闻脉冲）"""
        # 四大师评分
        buffett = buffett_score(holding, self.summary)
        munger = munger_score(holding, self.summary)
        duan = duan_score(holding, self.summary)
        li_lu = li_lu_score(holding, self.summary)
        verdict = generate_verdict(holding, buffett, munger, duan, li_lu)

        # 新引擎分析
        thesis = self.thesis_tracker.create_thesis(holding)
        drift = self.thesis_tracker.detect_thesis_drift(holding)
        red_flags = self.thesis_tracker.generate_red_flags(holding, self.summary)

        checklist_result = self.checklist.run_checklist(holding)
        veto_result = self.checklist.quick_veto_list(holding)

        quality = self.quality_screen.screen_holding(holding)

        anomaly = self.news_pulse.detect_price_anomaly(holding)
        news = self.news_pulse.quick_news_assessment(holding)

        deep = {
            "sotp": self.deep_logic.sotp_analysis(holding),
            "implied_expectation": self.deep_logic.implied_expectation(holding),
            "option_value": self.deep_logic.option_value(holding),
            "game_theory": self.deep_logic.game_theory(holding),
            "time_wall": self.deep_logic.time_wall(holding),
        }

        income = {
            "dividend_sustainability": self.income_analysis.analyze_dividend_sustainability(holding),
            "scenarios": self.income_analysis.dividend_scenarios(holding),
        }

        # 构建分析条目
        item = {
            "id": holding["id"],
            "ticker": holding["ticker"],
            "name": holding["name"],
            "market": holding["market"],
            "currency": holding["currency"],
            "sector": holding["sector"],
            "notes": holding.get("notes", ""),
            "analysis_text": "",
            "signals": self._build_signals(holding, munger),
            "risk_level": verdict["risk_level"],
            "verdict": verdict["verdict"],
            "data_snapshot": self._build_data_snapshot(holding),
            "berkshire": {
                "avg_score": verdict["avg_score"],
                "score_detail": verdict["score_detail"],
                "summary": verdict["summary"],
                "recommendations": verdict["recommendations"],
                "buffett": buffett,
                "munger": munger,
                "duan": duan,
                "li_lu": li_lu,
            },
            # 新增扩展分析
            "deep_logic": deep,
            "income_analysis": income,
            "thesis": {
                "thesis": thesis,
                "drift": drift,
                "red_flags": red_flags,
            },
            "checklist": {
                "six_gates": checklist_result,
                "veto": veto_result,
            },
            "quality_screen": quality,
            "news_pulse": {
                "anomaly": anomaly,
                "news_assessment": news,
            },
        }

        return item

    def _analyze_portfolio_review(self, review_report: dict = None) -> dict:
        """组合回顾分析：使用 PortfolioReviewEngine 结果 + 补充分析"""
        holdings = self.holdings
        summary = self.summary

        # 使用 PortfolioReviewEngine 的完整报告
        if review_report:
            return {
                "concentration": review_report.get("concentration", {}),
                "correlation": review_report.get("correlation", {}),
                "opportunity_cost": review_report.get("opportunity_cost", {}),
                "stress_test": review_report.get("stress_test", {}),
                "rebalancing": review_report.get("rebalancing", []),
            }

        # 降级：基础分析
        sorted_by_value = sorted(holdings, key=lambda h: h.get("market_value_cny", 0), reverse=True)
        top3 = sorted_by_value[:3]
        top3_weight = sum(h.get("weight", 0) for h in top3)
        concentration = {
            "top3_weight": round(top3_weight, 1),
            "num_holdings": summary.get("num_holdings", 0),
            "assessment": "适度集中" if top3_weight < 50 else "高度集中" if top3_weight < 70 else "极度集中",
        }
        sectors = {}
        for h in holdings:
            sec = h.get("sector", "其他")
            if sec not in sectors:
                sectors[sec] = {"count": 0, "weight": 0}
            sectors[sec]["count"] += 1
            sectors[sec]["weight"] += h.get("weight", 0)
        correlation = {
            "sector_count": len(sectors),
            "assessment": "分散良好" if len(sectors) >= 5 else "集中度偏高",
        }
        return {
            "concentration": concentration,
            "correlation": correlation,
            "opportunity_cost": {"total_loss": round(abs(summary.get("total_pnl", 0)), 2)},
            "stress_test": {"assessment": "基础压力测试"},
            "rebalancing": [{"ticker": "", "action": "无需调整", "reason": "基础分析模式"}],
        }

    def _analyze_anti_bias(self) -> list:
        """反偏见检查（芒格式逆向思考）"""
        signals = []
        pos_count = self.summary.get("num_positive", 0)
        neg_count = self.summary.get("num_negative", 0)
        total = pos_count + neg_count

        # 确认偏误
        if total > 0 and pos_count / total < 0.3:
            signals.append({
                "type": "warning", "icon": "&#x26A0;",
                "text": f"仅{pos_count}/{total}只持仓盈利，芒格：'反过来想，如果大部分持仓都在亏，是不是选股逻辑有问题？'"
            })

        # 处置效应
        for h in self.holdings:
            if h.get("pnl_pct", 0) >= 20 and h.get("holding_days", 0) < 30:
                signals.append({
                    "type": "info", "icon": "&#x1F4AD;",
                    "text": f"处置效应提醒: {h.get('ticker')}短期盈利{h.get('pnl_pct'):.1f}%，段永平：'好公司不卖，除非基本面变化'"
                })
                break

        # 现金仓位
        cash_holdings = [h for h in self.holdings if h.get("exchange") == "CASH"]
        cash_total = sum(h.get("market_value_cny", 0) for h in cash_holdings)
        total_value = self.summary.get("total_value_cny", 0)
        if total_value > 0:
            cash_pct = cash_total / total_value * 100
            if cash_pct > 20:
                signals.append({
                    "type": "info", "icon": "&#x1F4B0;",
                    "text": f"现金占比 {cash_pct:.1f}%，巴菲特：'现金是看跌期权，在市场恐慌时才有价值'"
                })

        # 快速否决
        for h in self.holdings:
            if h.get("pnl_pct", 0) <= -40:
                signals.append({
                    "type": "danger", "icon": "&#x274C;",
                    "text": f"快速否决: {h.get('ticker')}亏损{h.get('pnl_pct'):.1f}%，已触发一票否决红线"
                })

        return signals

    def _calculate_health_assessment(self, portfolio_review: dict, quality_results: list) -> dict:
        """计算组合健康评分"""
        score = 7.0  # 基准分
        penalties = []
        bonuses = []

        # 集中度扣分
        conc = portfolio_review.get("concentration", {})
        if conc.get("assessment") == "极度集中":
            score -= 2.0
            penalties.append("前3大持仓占比过高，集中度风险大")
        elif conc.get("assessment") == "高度集中":
            score -= 1.0
            penalties.append("集中度偏高")

        # 相关性扣分
        corr = portfolio_review.get("correlation", {})
        if corr.get("assessment") == "集中度偏高":
            score -= 1.0
            penalties.append(f"行业集中在{corr.get('dominant_sector')}，占比{corr.get('dominant_sector_weight')}%")

        # 质量筛选扣分
        failed_count = sum(1 for q in quality_results if q.get("overall") == "fail")
        borderline_count = sum(1 for q in quality_results if q.get("overall") == "borderline")
        if failed_count >= 3:
            score -= 2.0
            penalties.append(f"{failed_count}只持仓质量筛选未通过")
        elif failed_count >= 1:
            score -= 1.0
            penalties.append(f"{failed_count}只持仓质量筛选未通过")

        # 盈亏加分/扣分
        pos_count = self.summary.get("num_positive", 0)
        neg_count = self.summary.get("num_negative", 0)
        total_count = pos_count + neg_count
        if total_count > 0:
            win_rate = pos_count / total_count
            if win_rate >= 0.6:
                score += 1.0
                bonuses.append(f"胜率{win_rate:.0%}，表现良好")
            elif win_rate <= 0.3:
                score -= 1.0
                penalties.append(f"胜率仅{win_rate:.0%}，大部分持仓亏损")

        # 分散度加分
        if corr.get("sector_count", 0) >= 5:
            score += 1.0
            bonuses.append(f"覆盖{corr.get('sector_count')}个行业，分散化良好")

        # 现金仓位加分
        cash_holdings = [h for h in self.holdings if h.get("exchange") == "CASH"]
        cash_pct = sum(h.get("market_value_cny", 0) for h in cash_holdings) / max(self.summary.get("total_value_cny", 1), 1) * 100
        if 5 <= cash_pct <= 20:
            score += 0.5
            bonuses.append(f"现金仓位{cash_pct:.1f}%合理，留有缓冲")
        elif cash_pct > 30:
            score -= 0.5
            penalties.append(f"现金仓位{cash_pct:.1f}%过高，资金利用效率低")

        # 最终评分
        final_score = max(1, min(10, round(score, 1)))

        if final_score >= 8:
            level = "健康"
        elif final_score >= 6:
            level = "一般"
        elif final_score >= 4:
            level = "需关注"
        else:
            level = "风险较高"

        return {
            "score": final_score,
            "level": level,
            "penalties": penalties,
            "bonuses": bonuses,
            "summary": f"组合健康评分{final_score}/10 - {level}",
        }

    def analyze_all(self) -> List[Dict]:
        """分析所有持仓，返回完整分析数据"""
        alerts = []

        # 组合级分析
        portfolio_signals = []

        # 使用 PortfolioReviewEngine 进行集中度分析
        review_engine = PortfolioReviewEngine(self.holdings, self.summary)
        review_report = review_engine.full_review()
        for s in review_report.get("signals", []):
            portfolio_signals.append(s)

        # 反偏见检查
        bias_signals = self._analyze_anti_bias()
        portfolio_signals.extend(bias_signals)

        # 组合回顾分析
        portfolio_review = self._analyze_portfolio_review(review_report)
        portfolio_quality_results = self.quality_screen.screen_all(self.holdings)
        health = self._calculate_health_assessment(portfolio_review, portfolio_quality_results)

        # 组合级分析条目
        portfolio_entry = {
            "id": "portfolio_berkshire",
            "ticker": "",
            "name": "组合级分析",
            "market": "",
            "currency": "",
            "sector": "",
            "notes": "AI Berkshire 四大师框架 & 反偏见检查 & 深度分析引擎",
            "analysis_text": "基于巴菲特、芒格、段永平、李录四位大师方法论的综合分析，集成ThesisTracker、InvestmentChecklist、QualityScreen、NewsPulse引擎。",
            "signals": portfolio_signals,
            "risk_level": "info",
            "verdict": "组合级分析",
            "data_snapshot": {},
            "berkshire": None,
            "portfolio_review": portfolio_review,
            "portfolio_quality": {
                "results": portfolio_quality_results,
                "summary": f"质量筛选完成",
                "passed_count": sum(1 for q in portfolio_quality_results if q.get("overall") == "pass"),
                "borderline_count": sum(1 for q in portfolio_quality_results if q.get("overall") == "borderline"),
                "failed_count": sum(1 for q in portfolio_quality_results if q.get("overall") == "fail"),
            },
            "health_assessment": health,
        }

        alerts.append(portfolio_entry)

        # 分析每个持仓
        for h in self.holdings:
            if h.get("exchange") == "CASH":
                # 现金仓位简单处理
                alerts.append({
                    "id": h["id"],
                    "ticker": h["ticker"],
                    "name": h["name"],
                    "market": h["market"],
                    "currency": h["currency"],
                    "sector": h["sector"],
                    "notes": h.get("notes", ""),
                    "analysis_text": "现金仓位，不产生收益也不承担风险。提供流动性缓冲，在市场下跌时作为抄底弹药。",
                    "signals": [],
                    "risk_level": "normal",
                    "verdict": "现金",
                    "data_snapshot": {
                        "pnl_pct": 0, "pnl": 0, "weight": round(h["weight"], 1),
                        "weight_a": 0, "weight_hk_us": 0,
                        "holding_days": h["holding_days"], "day_change_pct": 0,
                        "current_price": round(h["avg_cost"], 2), "avg_cost": round(h["avg_cost"], 2),
                        "annualized_return": 0, "market": h.get("market", ""),
                    },
                    "berkshire": None,
                    "deep_logic": None,
                    "income_analysis": None,
                    "thesis": None,
                    "checklist": None,
                    "quality_screen": None,
                    "news_pulse": None,
                })
                continue

            item = self.analyze_holding(h)
            alerts.append(item)

        return alerts


# ====================================================================
# CLI 测试
# ====================================================================

def main():
    """测试运行"""
    from portfolio_core import PortfolioManager
    pm = PortfolioManager()
    ba = BerkshireAnalysis(pm)
    alerts = ba.analyze_all()

    print(f"\n{'='*70}")
    print("AI Berkshire 方法论 — 组合持仓分析结果（增强版）")
    print(f"{'='*70}\n")

    for a in alerts:
        if a.get("berkshire"):
            b = a["berkshire"]
            print(f"[{a['ticker']}] {a['name']} — {a['verdict']} (评分: {b['avg_score']})")
            print(f"  {b['score_detail']}")
            print(f"  {b['summary']}")
            if b["recommendations"]:
                for r in b["recommendations"]:
                    print(f"  {r}")

            # 打印论点追踪
            thesis_data = a.get("thesis", {})
            if thesis_data:
                t = thesis_data.get("thesis", {})
                print(f"  投资论点: {t.get('buy_thesis', '')[:80]}...")
                drift = thesis_data.get("drift", {})
                if drift.get("drift_detected"):
                    print(f"  论点漂移: 已检测到漂移 (评分: {drift.get('drift_score')})")
                else:
                    print(f"  论点漂移: 未检测到漂移 (评分: {drift.get('drift_score')})")

            # 打印质量筛选
            qs = a.get("quality_screen", {})
            if qs:
                print(f"  质量筛选: {qs.get('summary', '')}")

            # 打印新闻脉冲
            np = a.get("news_pulse", {})
            if np:
                anom = np.get("anomaly", {})
                if anom.get("is_anomaly"):
                    print(f"  价格异常: 检测到异常 ({anom.get('anomaly_type')})")

            print()

        elif a.get("ticker") == "":
            print(f"[组合级] {a['name']}")
            for s in a.get("signals", []):
                print(f"  [{s['type']}] {s['text']}")

            # 打印组合健康
            health = a.get("health_assessment", {})
            if health:
                print(f"  组合健康评分: {health.get('score')}/10 - {health.get('level')}")
                for p in health.get("penalties", []):
                    print(f"  扣分项: {p}")
                for b in health.get("bonuses", []):
                    print(f"  加分项: {b}")

            # 打印组合回顾
            pr = a.get("portfolio_review", {})
            if pr:
                print(f"  集中度: {pr.get('concentration', {}).get('assessment')}")
                print(f"  相关性: {pr.get('correlation', {}).get('assessment')}")

            print()

    return alerts


if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
