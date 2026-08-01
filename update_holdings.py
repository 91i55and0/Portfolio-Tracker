"""
持仓修改工具 - 支持通过命令行或函数调用修改持仓
用户可以直接编辑 portfolio.json，也可以通过此工具交互式修改
"""

import os
import sys
import json
import argparse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from portfolio_core import PortfolioManager


def list_holdings():
    """列出所有持仓"""
    pm = PortfolioManager()
    print(f"\n{'='*80}")
    print(f"  {pm.data['portfolio']['name']} - 当前持仓")
    print(f"{'='*80}")
    print(f"{'ID':<6} {'代码':<10} {'名称':<14} {'市场':<6} {'行业':<12} {'数量':<10} {'成本价':<10} {'币种':<6} {'建仓日':<12}")
    print(f"{'-'*80}")
    for h in pm.holdings:
        print(f"{h.id:<6} {h.ticker:<10} {h.name:<14} {h.market:<6} {h.sector:<12} "
              f"{h.shares:<10.2f} {h.avg_cost:<10.2f} {h.currency:<6} {h.add_date:<12}")
    print(f"{'='*80}")
    print(f"总计: {len(pm.holdings)} 只持仓\n")
    return pm.holdings


def add_holding(ticker, exchange, name, market, sector, shares, avg_cost, currency,
                add_date=None, notes=""):
    """添加新持仓"""
    pm = PortfolioManager()
    h = pm.add_holding(ticker, exchange, name, market, sector, shares, avg_cost,
                       currency, add_date, notes)
    print(f"✅ 已添加: {name} ({ticker}) - {shares}股 @ {avg_cost} {currency}")
    return h


def update_holding(holding_id, **kwargs):
    """更新持仓"""
    pm = PortfolioManager()
    h = pm.update_holding(holding_id, **kwargs)
    if h:
        print(f"✅ 已更新 {holding_id}: ", end="")
        changed = []
        for k, v in kwargs.items():
            changed.append(f"{k}={v}")
        print(", ".join(changed))
    else:
        print(f"❌ 未找到持仓: {holding_id}")
    return h


def remove_holding(holding_id):
    """删除持仓"""
    pm = PortfolioManager()
    h = pm.get_holding(holding_id)
    if h:
        name = h.name
        pm.remove_holding(holding_id)
        print(f"✅ 已删除持仓: {name} ({holding_id})")
    else:
        print(f"❌ 未找到持仓: {holding_id}")


def update_cash(cny=None, hkd=None, usd=None):
    """更新现金余额"""
    pm = PortfolioManager()
    if cny is not None:
        pm.data["portfolio"]["cash_cny"] = cny
    if hkd is not None:
        pm.data["portfolio"]["cash_hkd"] = hkd
    if usd is not None:
        pm.data["portfolio"]["cash_usd"] = usd
    pm.save()
    print(f"✅ 现金已更新: CNY={pm.data['portfolio']['cash_cny']}, "
          f"HKD={pm.data['portfolio']['cash_hkd']}, USD={pm.data['portfolio']['cash_usd']}")


def rename_portfolio(name):
    """重命名组合"""
    pm = PortfolioManager()
    old = pm.data["portfolio"]["name"]
    pm.data["portfolio"]["name"] = name
    pm.save()
    print(f"✅ 组合已重命名: '{old}' → '{name}'")


# ========== 便捷函数（供AI调用） ==========

def add_stock(ticker, exchange, name, market, sector, shares, avg_cost, currency,
              add_date=None, notes=""):
    """添加股票持仓"""
    return add_holding(ticker, exchange, name, market, sector, shares, avg_cost,
                       currency, add_date, notes)


def modify_holding(holding_id, **kwargs):
    """修改持仓字段（支持部分更新）"""
    return update_holding(holding_id, **kwargs)


def delete_holding(holding_id):
    """删除持仓"""
    return remove_holding(holding_id)


def show_summary():
    """显示组合摘要"""
    pm = PortfolioManager()
    from portfolio_core import print_holdings
    print_holdings(pm)
    return pm.summary


# ========== CLI ==========

def main():
    parser = argparse.ArgumentParser(description="组合持仓管理工具")
    parser.add_argument("action", nargs="?", default="list",
                        choices=["list", "add", "update", "remove", "cash", "rename"],
                        help="操作类型")

    parser.add_argument("--id", help="持仓ID")
    parser.add_argument("--ticker", help="股票代码")
    parser.add_argument("--exchange", help="交易所 (SH/SZ/HK/US)")
    parser.add_argument("--name", help="股票名称")
    parser.add_argument("--market", help="市场 (A股/港股/美股)")
    parser.add_argument("--sector", help="行业")
    parser.add_argument("--shares", type=float, help="持仓数量")
    parser.add_argument("--avg_cost", type=float, help="平均成本")
    parser.add_argument("--currency", help="币种 (CNY/HKD/USD)")
    parser.add_argument("--add_date", help="建仓日期 (YYYY-MM-DD)")
    parser.add_argument("--notes", help="备注")
    parser.add_argument("--cny", type=float, help="人民币现金")
    parser.add_argument("--hkd", type=float, help="港币现金")
    parser.add_argument("--usd", type=float, help="美元现金")
    parser.add_argument("--name2", help="新组合名称")

    args = parser.parse_args()

    if args.action == "list":
        list_holdings()
    elif args.action == "add":
        add_holding(
            args.ticker, args.exchange, args.name, args.market, args.sector,
            args.shares, args.avg_cost, args.currency, args.add_date, args.notes or ""
        )
    elif args.action == "update":
        kwargs = {}
        for k in ["ticker", "exchange", "name", "market", "sector", "shares",
                   "avg_cost", "currency", "add_date", "notes"]:
            v = getattr(args, k, None)
            if v is not None:
                kwargs[k] = v
        update_holding(args.id, **kwargs)
    elif args.action == "remove":
        remove_holding(args.id)
    elif args.action == "cash":
        update_cash(args.cny, args.hkd, args.usd)
    elif args.action == "rename":
        rename_portfolio(args.name2)


if __name__ == "__main__":
    main()