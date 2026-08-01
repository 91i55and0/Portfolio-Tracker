"""
AI Berkshire 方法论集成 — 组合持仓分析引擎
集成四大师框架（巴菲特/芒格/段永平/李录）+ 反偏见机制 + 精确计算

用法：
    from portfolio_analysis import BerkshireAnalysis
    ba = BerkshireAnalysis(manager)
    analysis = ba.analyze_all()
"""
import os
import sys
import math
import json
import logging
from datetime import datetime
from decimal import Decimal, Context, ROUND_HALF_EVEN
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# 精确十进制引擎
_CTX = Context(prec=28, rounding=ROUND_HALF_EVEN)

def _exact(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))

# ====================================================================
# 四大师评分框架
# ====================================================================

# 巴菲特 — 护城河 + 财务质量 + 合理估值
def buffett_score(holding: dict, summary: dict) -> dict:
    """巴菲特视角评分：护城河、财务质量、安全边际"""
    s = {"score": 3.0, "details": [], "color": "neutral"}
    pnl_pct = holding.get("pnl_pct", 0)
    weight = holding.get("weight", 0)
    sector = holding.get("sector", "")
    name = holding.get("name", "")
    ann_ret = holding.get("annualized_return", 0)

    # 护城河评估（基于行业和持仓特征）
    moat_indicators = {
        "银行/金融": "品牌+规模护城河，招行零售银行优势明显",
        "消费/白酒": "品牌护城河，白酒行业定价权强",
        "ETF/全球指数": "无个股护城河，但分散化本身就是保护",
        "ETF/道指": "被动指数，护城河不适用",
        "ETF/港股科技": "被动指数，护城河不适用",
        "ETF/通信": "被动指数，护城河不适用",
        "ETF/科创板": "被动指数，护城河不适用",
        "制药": "专利+研发护城河，GLP-1赛道壁垒高",
        "工业/数据中心": "技术+客户粘性护城河，Vertiv在电力基础设施领域领先",
        "网络安全": "转换成本护城河，Okta在身份管理领域有网络效应",
        "半导体": "技术+资本护城河，HBM高带宽内存技术壁垒高",
        "另类投资": "非传统资产，护城河不清晰",
        "互联网科技": "生态+网络效应护城河，但小米护城河弱于腾讯阿里",
        "造纸": "成本+规模护城河，太阳纸业在造纸行业有成本优势",
    }
    moat = moat_indicators.get(sector, "")
    if moat:
        s["details"].append(f"护城河: {moat}")

    # 财务质量
    if pnl_pct >= -5:
        s["score"] += 0.5
        s["details"].append("财务质量: 盈亏接近平衡，基本面尚可")
    elif pnl_pct >= -15:
        s["score"] += 0.0
        s["details"].append(f"财务质量: 亏损{pnl_pct:.1f}%，需关注基本面变化")
    else:
        s["score"] -= 0.5
        s["details"].append(f"财务质量: 亏损{pnl_pct:.1f}%，深度套牢需审视逻辑")

    # 安全边际
    if pnl_pct <= -15:
        s["score"] += 0.5  # 越跌安全边际越大（如果逻辑没变）
        s["details"].append("安全边际: 价格大幅低于成本，若逻辑未变则是加仓机会")
    elif pnl_pct >= 20:
        s["score"] -= 0.3
        s["details"].append("安全边际: 已大幅盈利，安全边际缩小")

    # 集中度
    if weight >= 30:
        s["score"] -= 0.5
        s["details"].append(f"集中度: 仓位{weight:.1f}%偏高，巴菲特认为适度集中但需能力圈")
    elif weight >= 20:
        s["score"] -= 0.2
        s["details"].append(f"集中度: 仓位{weight:.1f}%偏高")

    s["color"] = "positive" if s["score"] >= 3.5 else "neutral" if s["score"] >= 2.5 else "negative"
    return s


# 芒格 — 逆向思考 + 避免愚蠢 + 认知偏误检查
def munger_score(holding: dict, summary: dict) -> dict:
    """芒格视角评分：逆向思考、认知偏误、失败场景"""
    s = {"score": 3.0, "details": [], "color": "neutral", "reverse_questions": []}
    pnl_pct = holding.get("pnl_pct", 0)
    day_chg = holding.get("day_change_pct", 0)
    sector = holding.get("sector", "")
    name = holding.get("name", "")
    ann_ret = holding.get("annualized_return", 0)
    days = holding.get("holding_days", 0)
    weight = holding.get("weight", 0)

    # 逆向思考：什么情况下这个持仓会失败？
    failure_scenarios = {
        "银行/金融": "息差持续收窄、不良率大幅上升、经济深度衰退",
        "消费/白酒": "消费降级加速、年轻人不喝白酒、政策打压",
        "ETF/全球指数": "全球系统性金融危机、地缘政治分裂",
        "ETF/道指": "美国经济长期衰退",
        "ETF/港股科技": "中美脱钩加剧、港股流动性枯竭",
        "ETF/通信": "AI算力需求不及预期、5G投资回报率低",
        "ETF/科创板": "科创板流动性枯竭、政策转向",
        "制药": "GLP-1药物安全性问题曝光、竞争对手追赶、集采扩大",
        "工业/数据中心": "AI资本开支放缓、竞争对手侵蚀份额",
        "网络安全": "增长放缓、竞争加剧、收购整合不及预期",
        "半导体": "HBM产能过剩、存储芯片价格下跌周期",
        "另类投资": "流动性危机、估值大幅缩水",
        "互联网科技": "电动车业务持续烧钱、手机份额下滑、核心业务被侵蚀",
        "造纸": "需求持续萎缩、原材料成本上升、环保政策加码",
    }
    fs = failure_scenarios.get(sector, "行业风险")
    s["reverse_questions"].append(f"什么情况下{sector}会失效？→ {fs}")

    if pnl_pct <= -30:
        s["reverse_questions"].append(f"已亏损{pnl_pct:.1f}%，是否已经被市场证伪？")
        s["score"] -= 1.0
    elif pnl_pct <= -15:
        s["reverse_questions"].append(f"亏损{pnl_pct:.1f}%，是暂时的还是永久性的？")
        s["score"] -= 0.5

    # 反共识检查
    if day_chg >= 5:
        s["reverse_questions"].append(f"单日大涨{day_chg:.1f}%，聪明人是否在卖出？")
        s["score"] -= 0.2
    elif day_chg <= -5:
        s["reverse_questions"].append(f"单日大跌{abs(day_chg):.1f}%，是错杀还是逻辑变化？")
        s["score"] -= 0.2

    # 认知偏误检查
    if pnl_pct <= -20 and days > 60:
        s["details"].append("⚠️ 沉没成本偏误: 持有已久且深度亏损，可能不愿承认错误")
        s["score"] -= 0.5
    if pnl_pct >= 20 and days < 30:
        s["details"].append("⚠️ 近期盈利偏误: 短期盈利可能让人过度自信")
        s["score"] -= 0.3
    if weight < 5 and pnl_pct <= -20:
        s["details"].append("✅ 仓位控制合理: 小仓位试错，亏损影响有限")

    s["color"] = "positive" if s["score"] >= 3.5 else "neutral" if s["score"] >= 2.5 else "negative"
    return s


# 段永平 — 商业模式 + 企业文化 + 好价格
def duan_score(holding: dict, summary: dict) -> dict:
    """段永平视角评分：商业模式、企业文化、价格合理性"""
    s = {"score": 3.0, "details": [], "color": "neutral"}
    sector = holding.get("sector", "")
    pnl_pct = holding.get("pnl_pct", 0)
    name = holding.get("name", "")

    # 商业模式评估（段永平核心：好生意、好管理、好价格）
    biz_models = {
        "银行/金融": "好生意但高杠杆，招行是银行中最好的零售模式，ROE领先",
        "消费/白酒": "好生意，白酒是A股最好的商业模式之一，高毛利、低资本开支、品牌粘性强",
        "ETF/全球指数": "被动投资工具，不需要评估商业模式",
        "ETF/道指": "被动投资工具",
        "ETF/港股科技": "被动投资工具",
        "ETF/通信": "被动投资工具",
        "ETF/科创板": "被动投资工具",
        "制药": "好生意，但专利悬崖风险需要持续跟踪",
        "工业/数据中心": "好生意，AI基础设施需求确定性强，Vertiv是细分龙头",
        "网络安全": "好生意，身份安全需求刚性，但竞争激烈",
        "半导体": "好生意，HBM是AI算力的瓶颈环节，但周期性较强",
        "另类投资": "非传统模式，流动性差，段永平大概率不会碰",
        "互联网科技": "一般生意，小米本质是硬件制造+互联网服务，模式不如纯互联网",
        "造纸": "一般生意，周期性行业，资本开支大，产品同质化",
    }
    biz = biz_models.get(sector, "商业模式待评估")
    s["details"].append(f"商业模式: {biz}")

    # 好价格判断
    if pnl_pct <= -20:
        s["details"].append("价格: 大幅低于成本，段永平认为'好生意+好价格'值得买入")
        s["score"] += 0.5
    elif pnl_pct >= 30:
        s["details"].append("价格: 已大幅盈利，段永平认为'好生意+好价格'后应长期持有")
        s["score"] += 0.0
    else:
        s["details"].append("价格: 当前价格在合理区间")

    # 管理层判断
    mgmt_notes = {
        "小米集团": "雷军是优秀企业家，但造车烧钱是长期考验",
        "招商银行": "招行管理层在零售银行领域能力突出",
    }
    for k, v in mgmt_notes.items():
        if k in name:
            s["details"].append(f"管理层: {v}")
            break

    # 段永平核心原则：如果不想持有10年，就不要持有10分钟
    s["details"].append("段永平原则: 如果跌到0也不慌，才是真理解")

    s["color"] = "positive" if s["score"] >= 3.5 else "neutral" if s["score"] >= 2.5 else "negative"
    return s


# 李录 — 长期确定性 + 文明视角 + 能力圈
def li_lu_score(holding: dict, summary: dict) -> dict:
    """李录视角评分：长期确定性、文明视角、能力圈"""
    s = {"score": 3.0, "details": [], "color": "neutral"}
    sector = holding.get("sector", "")
    days = holding.get("holding_days", 0)
    pnl_pct = holding.get("pnl_pct", 0)
    name = holding.get("name", "")

    # 长期确定性（李录的核心：买入确定的长期增长）
    certainty = {
        "银行/金融": "招商银行零售银行护城河深，但金融行业本质是周期性的，10年确定性中等",
        "消费/白酒": "白酒行业10年确定性高，茅台五粮液等顶级品牌几乎不可替代",
        "ETF/全球指数": "人类经济长期增长，10年确定性很高",
        "ETF/道指": "美国经济长期增长，10年确定性高",
        "ETF/港股科技": "港股科技长期趋势向上，但受地缘政治影响大",
        "ETF/通信": "通信行业长期需求增长，但确定性强于增长弹性",
        "ETF/科创板": "科创长期方向确定，但个体公司不确定性高",
        "制药": "LLY在GLP-1赛道领先，但10年后的竞争格局不确定",
        "工业/数据中心": "AI长期趋势确定，Vertiv受益确定性高",
        "网络安全": "网络安全需求长期增长，但竞争格局变化快",
        "半导体": "HBM受益AI长期趋势，但存储芯片的周期性无法回避",
        "另类投资": "流动性差、透明度低，长期确定性低",
        "互联网科技": "小米10年确定性中等，取决于造车能否成功",
        "造纸": "造纸行业长期需求稳定但增速低，周期性明显",
    }
    cert = certainty.get(sector, "长期确定性待评估")
    s["details"].append(f"长期确定性: {cert}")

    # 文明视角（李录强调现代化和文明演进）
    if sector in ("ETF/全球指数", "ETF/道指"):
        s["details"].append("文明视角: 持有全球/美国指数就是做多人类文明进步，李录认同")
        s["score"] += 0.5
    elif "AI" in sector or "半导体" in sector:
        s["details"].append("文明视角: AI是新一轮技术革命，半导体是基础，受益于文明进步")
        s["score"] += 0.3
    elif sector == "消费/白酒":
        s["details"].append("文明视角: 白酒文化是中国文明的一部分，但年轻人消费习惯变化值得关注")
        s["score"] += 0.0

    # 能力圈
    if sector in ("ETF/全球指数", "ETF/道指", "银行/金融"):
        s["details"].append("能力圈: 指数和银行业属于能力圈范围内")
    elif sector in ("另类投资",):
        s["details"].append("能力圈: VCX这类产品透明度低，超出了大多数人的能力圈")
        s["score"] -= 0.5

    # 时间维度
    if days > 180:
        s["details"].append(f"时间验证: 已持有{days}天，李录认为长期持有是验证判断的唯一方式")
        s["score"] += 0.3
    elif days < 30:
        s["details"].append(f"时间验证: 仅持有{days}天，时间太短无法验证判断")
        s["score"] -= 0.2

    s["color"] = "positive" if s["score"] >= 3.5 else "neutral" if s["score"] >= 2.5 else "negative"
    return s


# ====================================================================
# 组合级别分析
# ====================================================================

def portfolio_concentration_analysis(holdings: list, summary: dict) -> list:
    """组合集中度分析（芒格式逆向思考）"""
    signals = []
    total = summary.get("total_value_cny", 0)

    # 前3大持仓占比
    sorted_by_value = sorted(holdings, key=lambda h: h.get("market_value_cny", 0), reverse=True)
    top3 = sorted_by_value[:3]
    top3_weight = sum(h.get("weight", 0) for h in top3)

    if top3_weight > 60:
        signals.append({
            "type": "warning",
            "icon": "&#x26A0;",
            "text": f"前3大持仓占比 {top3_weight:.1f}%，集中度极高，芒格：'如果去掉最好的3个投资就没收益，说明你太集中了'"
        })
    elif top3_weight > 40:
        signals.append({
            "type": "info",
            "icon": "&#x26A0;",
            "text": f"前3大持仓占比 {top3_weight:.1f}%，适度集中，巴菲特认为集中投资需要深度研究"
        })

    # VT+DIA 核心底仓占比
    core_etfs = [h for h in holdings if h.get("ticker") in ("VT", "DIA")]
    core_weight = sum(h.get("weight", 0) for h in core_etfs)
    if core_weight > 0:
        signals.append({
            "type": "success",
            "icon": "&#x2705;",
            "text": f"核心底仓(VT+DIA)占比 {core_weight:.1f}%，李录建议永久底仓配置"
        })

    return signals


def portfolio_anti_bias_checks(holdings: list, summary: dict) -> list:
    """组合级别的反偏见检查"""
    signals = []

    # 1. 确认偏误检查
    pos_count = summary.get("num_positive", 0)
    neg_count = summary.get("num_negative", 0)
    total = pos_count + neg_count

    if total > 0 and pos_count / total < 0.3:
        signals.append({
            "type": "warning",
            "icon": "&#x26A0;",
            "text": f"仅{pos_count}/{total}只持仓盈利，芒格：'反过来想，如果大部分持仓都在亏，是不是选股逻辑有问题？'"
        })

    # 2. 处置效应检查（过早卖出盈利、死守亏损）
    for h in holdings:
        pnl = h.get("pnl_pct", 0)
        days = h.get("holding_days", 0)
        if pnl >= 20 and days < 30:
            signals.append({
                "type": "info",
                "icon": "&#x1F4AD;",
                "text": f"处置效应提醒: {h.get('ticker')}短期盈利{pnl:.1f}%，段永平：'好公司不卖，除非基本面变化'"
            })
            break

    # 3. 现金仓位检查
    cash_holdings = [h for h in holdings if h.get("exchange") == "CASH"]
    cash_total = sum(h.get("market_value_cny", 0) for h in cash_holdings)
    total_value = summary.get("total_value_cny", 0)
    if total_value > 0:
        cash_pct = cash_total / total_value * 100
        if cash_pct > 20:
            signals.append({
                "type": "info",
                "icon": "&#x1F4B0;",
                "text": f"现金占比 {cash_pct:.1f}%，巴菲特：'现金是看跌期权，在市场恐慌时才有价值'"
            })

    # 4. 快速否决清单
    for h in holdings:
        if h.get("pnl_pct", 0) <= -40:
            signals.append({
                "type": "danger",
                "icon": "&#x274C;",
                "text": f"快速否决: {h.get('ticker')}亏损{h.get('pnl_pct'):.1f}%，已触发一票否决红线"
            })

    return signals


# ====================================================================
# 综合判决
# ====================================================================

def generate_verdict(holding: dict, buffett: dict, munger: dict, duan: dict, li_lu: dict) -> dict:
    """综合四大师视角生成最终判决"""
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
    if avg_score >= 3.5:
        verdict = "✓ 通过"
        risk_level = "normal"
        summary_text = "四大师视角综合评分优秀，逻辑一致，继续持有"
    elif avg_score >= 2.5:
        verdict = "○ 观察"
        risk_level = "info"
        summary_text = "四大师视角存在分歧，需持续跟踪关键变量"
    elif avg_score >= 1.5:
        verdict = "⚡ 注意风险"
        risk_level = "warning"
        summary_text = "四大师视角评分偏低，建议审视持仓逻辑"
    else:
        verdict = "⚠ 需重点关注"
        risk_level = "danger"
        summary_text = "四大师视角评分极低，强烈建议重新评估"

    # 得分详情
    score_detail = " | ".join([f"{k}: {v:.1f}" for k, v in scores.items()])

    # 综合建议
    recommendations = []
    if pnl_pct <= -30:
        recommendations.append("建议: 深度亏损，需判断是否被证伪，否则考虑止损")
    elif pnl_pct <= -15:
        recommendations.append("建议: 关注逻辑是否变化，若核心逻辑未变可持有观察")
    elif pnl_pct >= 50:
        recommendations.append("建议: 大幅盈利，可考虑分批止盈")
    elif pnl_pct >= 20:
        recommendations.append("建议: 盈利良好，趋势未变可继续持有")
    else:
        recommendations.append("建议: 当前价格区间保持持有")

    if weight >= 30:
        recommendations.append("注意: 仓位过重，需确保对该标的有足够深度理解")

    return {
        "verdict": verdict,
        "risk_level": risk_level,
        "avg_score": round(avg_score, 1),
        "score_detail": score_detail,
        "summary": summary_text,
        "recommendations": recommendations,
    }


# ====================================================================
# 主分析引擎
# ====================================================================

class BerkshireAnalysis:
    """AI Berkshire 方法论集成分析引擎"""

    def __init__(self, manager):
        self.manager = manager
        self.holdings = manager.get_holdings_table()
        self.summary = manager.get_summary_dict()

    def analyze_holding(self, holding: dict) -> dict:
        """对单个持仓运行四大师分析"""
        buffett = buffett_score(holding, self.summary)
        munger = munger_score(holding, self.summary)
        duan = duan_score(holding, self.summary)
        li_lu = li_lu_score(holding, self.summary)

        verdict = generate_verdict(holding, buffett, munger, duan, li_lu)

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
            "signals": [],
            "risk_level": verdict["risk_level"],
            "verdict": verdict["verdict"],
            "data_snapshot": {
                "pnl_pct": round(holding["pnl_pct"], 1),
                "pnl": round(holding["pnl"], 2),
                "weight": round(holding["weight"], 1),
                "weight_a": round(holding.get("weight_a", 0), 1),
                "weight_hk_us": round(holding.get("weight_hk_us", 0), 1),
                "holding_days": holding["holding_days"],
                "day_change_pct": round(holding["day_change_pct"], 2),
                "current_price": round(holding["current_price"], 2),
                "avg_cost": round(holding["avg_cost"], 2),
                "annualized_return": round(holding["annualized_return"], 1),
                "market": holding.get("market", ""),
            },
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
        }

        # 添加数据驱动信号
        pnl_pct = holding["pnl_pct"]
        day_chg = holding["day_change_pct"]
        weight = holding["weight"]
        days = holding["holding_days"]
        ann_ret = holding["annualized_return"]

        # 盈亏信号
        if pnl_pct <= -30:
            item["signals"].append({"type": "danger", "icon": "&#x26A0;", "text": f"亏损 {pnl_pct:.1f}%，已触发快速否决红线"})
        elif pnl_pct <= -15:
            item["signals"].append({"type": "warning", "icon": "&#x26A0;", "text": f"亏损 {pnl_pct:.1f}%，需审视逻辑是否被证伪"})
        elif pnl_pct <= -5:
            item["signals"].append({"type": "info", "icon": "&#x2193;", "text": f"小幅亏损 {pnl_pct:.1f}% 在正常波动范围"})
        elif pnl_pct >= 50:
            item["signals"].append({"type": "success", "icon": "&#x2191;", "text": f"盈利 {pnl_pct:.1f}%，巴菲特：'好公司管住手不卖'"})
        elif pnl_pct >= 20:
            item["signals"].append({"type": "success", "icon": "&#x2191;", "text": f"盈利 {pnl_pct:.1f}%，表现良好"})

        # 日涨跌信号
        if abs(day_chg) >= 5:
            item["signals"].append({
                "type": "danger" if day_chg < 0 else "success",
                "icon": "&#x26A1;",
                "text": f"日内{'下跌' if day_chg < 0 else '上涨'}{abs(day_chg):.1f}%，芒格：'检查是否有新信息，不要被短期波动干扰'"
            })

        # 集中度信号
        if weight >= 30:
            item["signals"].append({"type": "warning", "icon": "&#x26A0;", "text": f"仓位占比 {weight:.1f}%，巴菲特：'适度集中是好事，但必须深入理解'"})
        elif weight >= 20:
            item["signals"].append({"type": "info", "icon": "&#x26A0;", "text": f"仓位占比 {weight:.1f}%"})

        # 持仓时间信号
        if days <= 5:
            item["signals"].append({"type": "info", "icon": "&#x1F4C5;", "text": f"新建仓仅 {days} 天，段永平：'买股票就是买公司，需要时间验证'"})
        elif days >= 180:
            item["signals"].append({"type": "info", "icon": "&#x23F1;", "text": f"已持有 {days} 天，李录：'长期持有是验证判断的唯一方式'"})

        # 年化收益信号
        if days > 30 and ann_ret < -20:
            item["signals"].append({"type": "warning", "icon": "&#x26A0;", "text": f"年化 {ann_ret:.1f}%，芒格：'反过来想——如果年化亏20%，是不是应该考虑卖出？'"})

        # 芒格式逆向问题
        for q in munger.get("reverse_questions", []):
            item["signals"].append({"type": "info", "icon": "&#x1F4AD;", "text": f"芒格追问: {q}"})

        return item

    def analyze_all(self) -> List[Dict]:
        """分析所有持仓，返回完整分析数据"""
        alerts = []

        # 组合级分析
        portfolio_signals = []

        # 集中度
        conc_signals = portfolio_concentration_analysis(self.holdings, self.summary)
        portfolio_signals.extend(conc_signals)

        # 反偏见
        bias_signals = portfolio_anti_bias_checks(self.holdings, self.summary)
        portfolio_signals.extend(bias_signals)

        if portfolio_signals:
            alerts.append({
                "id": "portfolio_berkshire",
                "ticker": "",
                "name": "组合级分析",
                "market": "",
                "currency": "",
                "sector": "",
                "notes": "AI Berkshire 四大师框架 & 反偏见检查",
                "analysis_text": "基于巴菲特、芒格、段永平、李录四位大师方法论的综合分析。",
                "signals": portfolio_signals,
                "risk_level": "info",
                "verdict": "组合级分析",
                "data_snapshot": {},
                "berkshire": None,
            })

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
                    "verdict": "● 现金",
                    "data_snapshot": {
                        "pnl_pct": 0, "pnl": 0, "weight": round(h["weight"], 1),
                        "weight_a": 0, "weight_hk_us": 0,
                        "holding_days": h["holding_days"], "day_change_pct": 0,
                        "current_price": round(h["avg_cost"], 2), "avg_cost": round(h["avg_cost"], 2),
                        "annualized_return": 0, "market": h.get("market", ""),
                    },
                    "berkshire": None,
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
    print("AI Berkshire 方法论 — 组合持仓分析结果")
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
            print()
        elif a.get("ticker") == "":
            print(f"[组合级] {a['name']}")
            for s in a.get("signals", []):
                print(f"  [{s['type']}] {s['text']}")
            print()

    return alerts


if __name__ == "__main__":
    main()