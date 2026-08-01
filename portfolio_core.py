"""
组合持仓核心模块 - 管理持仓数据、计算分析指标
支持 A股、港股、美股
"""

import json
import os
import math
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict
from dataclasses import dataclass, field, asdict
from copy import deepcopy

logger = logging.getLogger(__name__)

# ========== 数据模型 ==========

@dataclass
class Holding:
    """单只持仓"""
    id: str
    ticker: str
    exchange: str          # SH / SZ / HK / US
    name: str
    market: str            # A股 / 港股 / 美股
    sector: str
    shares: float
    avg_cost: float
    currency: str          # CNY / HKD / USD
    add_date: str          # YYYY-MM-DD
    notes: str = ""

    # 动态字段（由系统计算填充）
    current_price: float = 0.0
    day_change_pct: float = 0.0
    market_value: float = 0.0
    cost_total: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    holding_days: int = 0
    weight: float = 0.0          # 总组合占比
    weight_a: float = 0.0        # A股子组合占比
    weight_hk_us: float = 0.0    # 港股+美股子组合占比
    daily_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    annualized_return: float = 0.0
    volatility: float = 0.0
    beta: float = 0.0

    @property
    def cost_total_calc(self) -> float:
        return self.shares * self.avg_cost

    @property
    def market_value_calc(self) -> float:
        return self.shares * self.current_price

    @property
    def pnl_calc(self) -> float:
        return self.market_value_calc - self.cost_total_calc

    @property
    def pnl_pct_calc(self) -> float:
        if self.cost_total_calc == 0:
            return 0.0
        return (self.pnl_calc / self.cost_total_calc) * 100

    @property
    def holding_days_calc(self) -> int:
        try:
            add = datetime.strptime(self.add_date, "%Y-%m-%d")
            return (datetime.now() - add).days
        except:
            return 0


@dataclass
class PortfolioSummary:
    """组合汇总"""
    total_market_value: float = 0.0
    total_cost: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    total_cash_cny: float = 0.0
    total_cash_hkd: float = 0.0
    total_cash_usd: float = 0.0
    total_cash_cny_equiv: float = 0.0
    total_market_value_cny: float = 0.0
    total_value_cny: float = 0.0
    day_pnl: float = 0.0
    day_pnl_pct: float = 0.0
    portfolio_sharpe: float = 0.0
    portfolio_volatility: float = 0.0
    portfolio_beta: float = 0.0
    portfolio_max_drawdown: float = 0.0
    num_holdings: int = 0
    num_positive: int = 0
    num_negative: int = 0
    top_holding: str = ""
    top_holding_weight: float = 0.0
    top_performer: str = ""
    top_performer_pnl: float = 0.0
    worst_performer: str = ""
    worst_performer_pnl: float = 0.0
    weighted_holding_days: float = 0.0
    annualized_return: float = 0.0


# ========== 汇率配置 ==========

FX_RATES = {
    "USDCNY": 7.25,    # 1 USD = 7.25 CNY
    "HKDCNY": 0.93,    # 1 HKD = 0.93 CNY
}


def update_fx_rates(usd_cny: float = None, hkd_cny: float = None):
    """更新汇率"""
    if usd_cny is not None:
        FX_RATES["USDCNY"] = usd_cny
    if hkd_cny is not None:
        FX_RATES["HKDCNY"] = hkd_cny


def to_cny(amount: float, currency: str) -> float:
    """转换到人民币"""
    if currency == "CNY":
        return amount
    elif currency == "HKD":
        return amount * FX_RATES["HKDCNY"]
    elif currency == "USD":
        return amount * FX_RATES["USDCNY"]
    return amount


# ========== 组合管理 ==========

class PortfolioManager:
    """组合持仓管理器"""

    def __init__(self, filepath: str = None):
        if filepath is None:
            filepath = os.path.join(os.path.dirname(__file__), "portfolio.json")
        self.filepath = filepath
        self.data = self._load()
        self.holdings: List[Holding] = []
        self.summary = PortfolioSummary()
        self._load_holdings()

    def _load(self) -> dict:
        """加载JSON数据"""
        if not os.path.exists(self.filepath):
            raise FileNotFoundError(f"组合数据文件不存在: {self.filepath}")
        with open(self.filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self):
        """保存到JSON文件"""
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def _load_holdings(self):
        """从data加载持仓列表"""
        self.holdings = []
        for h in self.data["holdings"]:
            holding = Holding(
                id=h["id"],
                ticker=h["ticker"],
                exchange=h["exchange"],
                name=h["name"],
                market=h["market"],
                sector=h["sector"],
                shares=h["shares"],
                avg_cost=h["avg_cost"],
                currency=h["currency"],
                add_date=h["add_date"],
                notes=h.get("notes", ""),
            )
            holding.cost_total = holding.cost_total_calc
            self.holdings.append(holding)

    def get_holding(self, holding_id: str) -> Optional[Holding]:
        """按ID获取持仓"""
        for h in self.holdings:
            if h.id == holding_id:
                return h
        return None

    def get_holding_by_ticker(self, ticker: str, exchange: str = None) -> Optional[Holding]:
        """按代码获取持仓"""
        for h in self.holdings:
            if h.ticker == ticker:
                if exchange is None or h.exchange == exchange:
                    return h
        return None

    def get_ticker_symbols(self) -> List[Dict]:
        """获取所有持仓代码列表（用于数据获取，排除现金）"""
        symbols = []
        for h in self.holdings:
            if h.exchange == "CASH":
                continue  # 现金仓位不需要获取行情
            if h.exchange == "SH":
                symbols.append({"ticker": f"{h.ticker}.SH", "market": "A股", "code": h.ticker, "exchange": "SH"})
            elif h.exchange == "SZ":
                symbols.append({"ticker": f"{h.ticker}.SZ", "market": "A股", "code": h.ticker, "exchange": "SZ"})
            elif h.exchange == "HK":
                symbols.append({"ticker": f"{h.ticker}.HK", "market": "港股", "code": h.ticker, "exchange": "HK"})
            elif h.exchange == "US":
                symbols.append({"ticker": h.ticker, "market": "美股", "code": h.ticker, "exchange": "US"})
        return symbols

    # ---------- 持仓更新 ----------

    def add_holding(self, ticker: str, exchange: str, name: str, market: str, sector: str,
                    shares: float, avg_cost: float, currency: str, add_date: str = None,
                    notes: str = "") -> Holding:
        """添加新持仓"""
        if add_date is None:
            add_date = datetime.now().strftime("%Y-%m-%d")
        new_id = f"h{len(self.data['holdings']) + 1:03d}"
        holding_data = {
            "id": new_id,
            "ticker": ticker,
            "exchange": exchange,
            "name": name,
            "market": market,
            "sector": sector,
            "shares": shares,
            "avg_cost": avg_cost,
            "currency": currency,
            "add_date": add_date,
            "notes": notes,
        }
        self.data["holdings"].append(holding_data)
        self.save()
        self._load_holdings()
        return self.holdings[-1]

    def update_holding(self, holding_id: str, **kwargs) -> Optional[Holding]:
        """更新持仓信息（支持部分更新）"""
        for h in self.data["holdings"]:
            if h["id"] == holding_id:
                for key, value in kwargs.items():
                    if key in h:
                        h[key] = value
                self.save()
                self._load_holdings()
                return self.get_holding(holding_id)
        return None

    def remove_holding(self, holding_id: str) -> bool:
        """删除持仓"""
        for i, h in enumerate(self.data["holdings"]):
            if h["id"] == holding_id:
                self.data["holdings"].pop(i)
                self.save()
                self._load_holdings()
                return True
        return False

    def _get_last_known_prices(self) -> Dict[str, Dict]:
        """从价格历史中获取最近一次已知价格"""
        last_prices = {}
        ph = self.data.get("price_history", {})
        dates = sorted(ph.keys())
        if not dates:
            return last_prices
        # 从最近一天往前找
        for d in reversed(dates):
            day_data = ph[d]
            for key, val in day_data.items():
                if key not in last_prices and val.get("price", 0) > 0:
                    last_prices[key] = val
            if len(last_prices) >= len(self.holdings):
                break
        return last_prices

    def update_prices(self, price_data: Dict[str, Dict]):
        """更新价格数据并计算指标"""
        # 获取上次已知价格作为回退
        last_prices = self._get_last_known_prices()

        for h in self.holdings:
            # 现金仓位：价格 = 成本，无波动
            if h.exchange == "CASH":
                h.current_price = h.avg_cost
                h.day_change_pct = 0.0
                h.cost_total = h.cost_total_calc
                h.market_value = h.market_value_calc
                h.pnl = 0.0
                h.pnl_pct = 0.0
                h.holding_days = h.holding_days_calc
                h.annualized_return = 0.0
                continue

            key = f"{h.ticker}.{h.exchange}" if h.exchange != "US" else h.ticker
            if key in price_data:
                pd = price_data[key]
                h.current_price = pd.get("price", 0)
                h.day_change_pct = pd.get("change_pct", 0)
            elif key in last_prices:
                # 使用上次已知价格
                h.current_price = last_prices[key]["price"]
                h.day_change_pct = 0
                logger.debug(f"使用上次价格: {key} = {h.current_price}")

            h.cost_total = h.cost_total_calc
            h.market_value = h.market_value_calc
            h.pnl = h.pnl_calc
            h.pnl_pct = h.pnl_pct_calc
            h.holding_days = h.holding_days_calc

            # 计算年化收益率
            if h.holding_days > 0 and h.cost_total > 0:
                total_return = h.pnl / h.cost_total
                h.annualized_return = ((1 + total_return) ** (365 / h.holding_days) - 1) * 100
            else:
                h.annualized_return = 0.0

        # 计算权重（基于人民币等值）
        total_cny = 0
        for h in self.holdings:
            total_cny += to_cny(h.market_value, h.currency)

        # 计算子组合市值
        total_a_cny = sum(to_cny(h.market_value, h.currency) for h in self.holdings if h.market == "A股")
        total_hk_us_cny = sum(to_cny(h.market_value, h.currency) for h in self.holdings if h.market in ("港股", "美股"))

        for h in self.holdings:
            if total_cny > 0:
                h.weight = (to_cny(h.market_value, h.currency) / total_cny) * 100
            else:
                h.weight = 0.0

            # A股内部占比
            if h.market == "A股" and total_a_cny > 0:
                h.weight_a = (to_cny(h.market_value, h.currency) / total_a_cny) * 100
            else:
                h.weight_a = 0.0

            # 港股+美股内部占比
            if h.market in ("港股", "美股") and total_hk_us_cny > 0:
                h.weight_hk_us = (to_cny(h.market_value, h.currency) / total_hk_us_cny) * 100
            else:
                h.weight_hk_us = 0.0

        self._calc_summary(total_cny)

    def _calc_summary(self, total_market_value_cny: float):
        """计算组合汇总"""
        s = self.summary
        s.num_holdings = len(self.holdings)
        s.total_market_value = sum(h.market_value for h in self.holdings)
        s.total_cost = sum(h.cost_total for h in self.holdings)

        total_pnl_cny = sum(to_cny(h.pnl, h.currency) for h in self.holdings)
        total_cost_cny = sum(to_cny(h.cost_total, h.currency) for h in self.holdings)
        s.total_pnl = total_pnl_cny
        s.total_pnl_pct = (total_pnl_cny / total_cost_cny * 100) if total_cost_cny > 0 else 0

        s.total_market_value_cny = total_market_value_cny
        # 现金已纳入持仓计算，不再单独加回
        s.total_cash_cny = 0
        s.total_cash_hkd = 0
        s.total_cash_usd = 0
        s.total_cash_cny_equiv = 0
        s.total_value_cny = total_market_value_cny

        # 每日盈亏
        day_pnl_cny = sum(to_cny(h.market_value * h.day_change_pct / 100, h.currency) for h in self.holdings)
        s.day_pnl = day_pnl_cny
        s.day_pnl_pct = (day_pnl_cny / (total_market_value_cny - day_pnl_cny) * 100) if total_market_value_cny > 0 else 0

        # 盈亏统计
        s.num_positive = sum(1 for h in self.holdings if h.pnl > 0)
        s.num_negative = sum(1 for h in self.holdings if h.pnl < 0)

        # 最大持仓
        if self.holdings:
            top = max(self.holdings, key=lambda h: to_cny(h.market_value, h.currency))
            s.top_holding = f"{top.name}({top.ticker})"
            s.top_holding_weight = top.weight

            # 最佳/最差表现
            best = max(self.holdings, key=lambda h: to_cny(h.pnl, h.currency))
            worst = min(self.holdings, key=lambda h: to_cny(h.pnl, h.currency))
            s.top_performer = f"{best.name}({best.ticker})"
            s.top_performer_pnl = to_cny(best.pnl, best.currency)
            s.worst_performer = f"{worst.name}({worst.ticker})"
            s.worst_performer_pnl = to_cny(worst.pnl, worst.currency)

        # 加权平均持仓天数
        if total_market_value_cny > 0:
            s.weighted_holding_days = sum(
                h.holding_days * to_cny(h.market_value, h.currency) / total_market_value_cny
                for h in self.holdings
            )

        # 总年化回报
        if total_cost_cny > 0 and s.weighted_holding_days > 0:
            total_return = total_pnl_cny / total_cost_cny
            s.annualized_return = ((1 + total_return) ** (365 / s.weighted_holding_days) - 1) * 100

        s.portfolio_sharpe = self._calc_sharpe_ratio()
        self.data["portfolio"]["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.save()

    def _calc_sharpe_ratio(self) -> float:
        """计算组合夏普比率（基于价格历史模拟）"""
        risk_free = self.data["portfolio"]["risk_free_rate"]
        has_price_history = len(self.data.get("price_history", {})) > 0

        if not has_price_history or not self.holdings:
            # 无历史数据时，使用现有持仓数据估算
            returns = []
            for h in self.holdings:
                if h.cost_total > 0:
                    r = h.pnl / h.cost_total
                    if h.holding_days > 0:
                        annual_r = (1 + r) ** (365 / h.holding_days) - 1
                        returns.append(annual_r)

            if len(returns) < 2:
                return 0.0

            avg_return = sum(returns) / len(returns)
            variance = sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)
            std = math.sqrt(variance) if variance > 0 else 1.0

            if std == 0:
                return 0.0
            return (avg_return - risk_free) / std

        # 如果有价格历史，基于日收益率计算
        price_history = self.data["price_history"]
        daily_returns = []
        dates = sorted(price_history.keys())
        for i in range(1, len(dates)):
            prev_total = 0
            curr_total = 0
            for h in self.holdings:
                key = f"{h.ticker}.{h.exchange}" if h.exchange != "US" else h.ticker
                prev_prices = price_history[dates[i - 1]].get(key, {})
                curr_prices = price_history[dates[i]].get(key, {})
                prev_p = prev_prices.get("price", 0)
                curr_p = curr_prices.get("price", 0)
                if prev_p > 0:
                    prev_total += prev_p * h.shares
                    curr_total += curr_p * h.shares
            if prev_total > 0:
                daily_returns.append((curr_total - prev_total) / prev_total)

        if len(daily_returns) < 5:
            return 0.0

        avg_daily_return = sum(daily_returns) / len(daily_returns)
        variance = sum((r - avg_daily_return) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        daily_std = math.sqrt(variance) if variance > 0 else 1e-6

        # 年化
        annual_return = avg_daily_return * 252
        annual_std = daily_std * math.sqrt(252)
        if annual_std == 0:
            return 0.0
        return (annual_return - risk_free) / annual_std

    # ---------- 导出数据 ----------

    def get_holdings_table(self) -> List[Dict]:
        """获取持仓表格数据（用于仪表盘）"""
        table = []
        for h in self.holdings:
            table.append({
                "id": h.id,
                "ticker": h.ticker,
                "exchange": h.exchange,
                "name": h.name,
                "market": h.market,
                "sector": h.sector,
                "shares": h.shares,
                "avg_cost": h.avg_cost,
                "current_price": h.current_price,
                "currency": h.currency,
                "cost_total": h.cost_total,
                "market_value": h.market_value,
                "market_value_cny": to_cny(h.market_value, h.currency),
                "pnl": h.pnl,
                "pnl_pct": h.pnl_pct,
                "day_change_pct": h.day_change_pct,
                "holding_days": h.holding_days,
                "weight": h.weight,
                "weight_a": h.weight_a,
                "weight_hk_us": h.weight_hk_us,
                "annualized_return": h.annualized_return,
                "sharpe_ratio": h.sharpe_ratio,
                "max_drawdown": h.max_drawdown,
                "notes": h.notes,
                "add_date": h.add_date,
            })
        return table

    def get_summary_dict(self) -> Dict:
        """获取汇总数据字典"""
        s = self.summary
        return {
            "total_market_value": round(s.total_market_value, 2),
            "total_cost": round(s.total_cost, 2),
            "total_pnl": round(s.total_pnl, 2),
            "total_pnl_pct": round(s.total_pnl_pct, 2),
            "total_cash_cny": s.total_cash_cny,
            "total_cash_hkd": s.total_cash_hkd,
            "total_cash_usd": s.total_cash_usd,
            "total_cash_cny_equiv": round(s.total_cash_cny_equiv, 2),
            "total_market_value_cny": round(s.total_market_value_cny, 2),
            "total_value_cny": round(s.total_value_cny, 2),
            "day_pnl": round(s.day_pnl, 2),
            "day_pnl_pct": round(s.day_pnl_pct, 2),
            "portfolio_sharpe": round(s.portfolio_sharpe, 2),
            "portfolio_volatility": round(s.portfolio_volatility, 2),
            "portfolio_beta": round(s.portfolio_beta, 2),
            "portfolio_max_drawdown": round(s.portfolio_max_drawdown, 2),
            "num_holdings": s.num_holdings,
            "num_positive": s.num_positive,
            "num_negative": s.num_negative,
            "top_holding": s.top_holding,
            "top_holding_weight": round(s.top_holding_weight, 1),
            "top_performer": s.top_performer,
            "top_performer_pnl": round(s.top_performer_pnl, 2),
            "worst_performer": s.worst_performer,
            "worst_performer_pnl": round(s.worst_performer_pnl, 2),
            "weighted_holding_days": round(s.weighted_holding_days, 1),
            "annualized_return": round(s.annualized_return, 2),
            "name": self.data["portfolio"]["name"],
            "last_updated": self.data["portfolio"]["last_updated"] or "尚未更新",
            "risk_free_rate": self.data["portfolio"]["risk_free_rate"],
            "total_a_cny": round(sum(to_cny(h.market_value, h.currency) for h in self.holdings if h.market == "A股"), 2),
            "total_hk_us_cny": round(sum(to_cny(h.market_value, h.currency) for h in self.holdings if h.market in ("港股", "美股")), 2),
        }

    def get_sector_allocation(self) -> List[Dict]:
        """获取行业配置"""
        sector_map = {}
        total_cny = sum(to_cny(h.market_value, h.currency) for h in self.holdings)
        for h in self.holdings:
            val = to_cny(h.market_value, h.currency)
            if h.sector not in sector_map:
                sector_map[h.sector] = {"sector": h.sector, "value": 0, "count": 0}
            sector_map[h.sector]["value"] += val
            sector_map[h.sector]["count"] += 1
        for s in sector_map.values():
            s["weight"] = round((s["value"] / total_cny * 100) if total_cny > 0 else 0, 1)
            s["value"] = round(s["value"], 2)
        return sorted(sector_map.values(), key=lambda x: x["weight"], reverse=True)

    def get_market_allocation(self) -> List[Dict]:
        """获取市场配置"""
        market_map = {}
        total_cny = sum(to_cny(h.market_value, h.currency) for h in self.holdings)
        for h in self.holdings:
            if h.market not in market_map:
                market_map[h.market] = {"market": h.market, "value": 0, "count": 0}
            val = to_cny(h.market_value, h.currency)
            market_map[h.market]["value"] += val
            market_map[h.market]["count"] += 1
        for m in market_map.values():
            m["weight"] = round((m["value"] / total_cny * 100) if total_cny > 0 else 0, 1)
            m["value"] = round(m["value"], 2)
        return sorted(market_map.values(), key=lambda x: x["weight"], reverse=True)

    def get_price_history_dates(self) -> List[str]:
        """获取价格历史日期列表"""
        return sorted(self.data.get("price_history", {}).keys())


# ========== CLI 交互 ==========

def print_holdings(manager: PortfolioManager):
    """打印持仓表格"""
    print(f"\n{'='*120}")
    print(f"  {manager.data['portfolio']['name']}")
    print(f"  最后更新: {manager.data['portfolio']['last_updated'] or 'N/A'}")
    print(f"{'='*120}")
    print(f"{'代码':<10} {'名称':<12} {'市场':<6} {'数量':<10} {'成本价':<10} {'现价':<10} "
          f"{'市值':<12} {'盈亏':<10} {'盈亏%':<8} {'天数':<6} {'权重':<6}")
    print(f"{'-'*120}")
    for h in manager.holdings:
        pnl_str = f"+{h.pnl:.2f}" if h.pnl >= 0 else f"{h.pnl:.2f}"
        print(f"{h.ticker:<10} {h.name:<12} {h.market:<6} {h.shares:<10.2f} {h.avg_cost:<10.2f} "
              f"{h.current_price:<10.2f} {h.market_value:<12.2f} {pnl_str:<10} {h.pnl_pct:<8.2f} "
              f"{h.holding_days:<6} {h.weight:<6.1f}")
    s = manager.summary
    print(f"{'-'*120}")
    print(f" 总市值: {s.total_market_value:.2f} | 总盈亏: {s.total_pnl:+.2f} ({s.total_pnl_pct:+.2f}%)")
    print(f" 当日盈亏: {s.day_pnl:+.2f} ({s.day_pnl_pct:+.2f}%)")
    print(f" 持仓数: {s.num_holdings} (盈利: {s.num_positive}, 亏损: {s.num_negative})")
    print(f" 夏普率: {s.portfolio_sharpe:.2f}")
    print(f"{'='*120}\n")


if __name__ == "__main__":
    pm = PortfolioManager()
    print_holdings(pm)