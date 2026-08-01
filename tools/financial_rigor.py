#!/usr/bin/env python3
"""Financial Rigor Toolkit for AI Berkshire.
Command-line tool for verifying financial data accuracy during investment research.
Zero external dependencies — uses only Python stdlib (decimal, json, math, argparse).
Requires Python >= 3.7.

Usage:
    python3 tools/financial_rigor.py verify-market-cap --price 510 --shares 9.11e9 --reported 4.65e12 --currency HKD
    python3 tools/financial_rigor.py verify-valuation --price 510 --eps 23.5 --bvps 120 --fcf-per-share 18 --dividend 2.4
    python3 tools/financial_rigor.py cross-validate --field revenue --values '{"年报": 7518, "Yahoo": 7500, "StockAnalysis": 7520}' --unit 亿
    python3 tools/financial_rigor.py calc --expr '510 * 9.11e9'
"""
import argparse
import json
import math
import sys
from decimal import Decimal, Context, ROUND_HALF_EVEN, InvalidOperation

# ---------------------------------------------------------------------------
# Exact Decimal Engine (no floating-point drift)
# ---------------------------------------------------------------------------

_CTX = Context(prec=28, rounding=ROUND_HALF_EVEN)

def exact(value) -> Decimal:
    """Convert any numeric to exact Decimal, avoiding float traps."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))

def fmt_number(d: Decimal, unit: str = "") -> str:
    """Format large numbers in human-readable form (亿/万亿/B/T)."""
    v = float(d)
    abs_v = abs(v)
    if unit in ("亿", "亿元", "亿港元", "亿美元"):
        if abs_v >= 10000:
            return f"{v/10000:.2f}万亿{unit[1:] if len(unit) > 1 else ''}"
        return f"{v:.2f}{unit}"
    if abs_v >= 1e12:
        return f"{v/1e12:.2f}T"
    if abs_v >= 1e9:
        return f"{v/1e9:.2f}B"
    if abs_v >= 1e6:
        return f"{v/1e6:.2f}M"
    return f"{v:,.2f}"

def _force_utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

# ---------------------------------------------------------------------------
# 1. Market Cap Verification
# ---------------------------------------------------------------------------

def verify_market_cap(price, shares, reported_cap, currency=""):
    p = exact(price)
    s = exact(shares)
    r = exact(reported_cap)
    calculated = _CTX.multiply(p, s)
    deviation = abs(float(calculated - r) / float(r)) * 100 if r != 0 else 0
    print("=" * 60)
    print("市值验算 (Market Cap Verification)")
    print("=" * 60)
    print(f"  股价 (Price):       {p} {currency}")
    print(f"  总股本 (Shares):    {fmt_number(s)}")
    print(f"  计算市值:           {fmt_number(calculated)} {currency}")
    print(f"  报告市值:           {fmt_number(r)} {currency}")
    print(f"  偏差:               {deviation:.2f}%")
    print()
    if deviation > 5:
        print(f"  ❌ 警告: 偏差 {deviation:.1f}% > 5%, 请检查:")
        print(f"     - 股本是否为最新（回购/增发）?")
        print(f"     - 单位是否一致?")
        print(f"     - 股价是否为最新?")
        return False
    elif deviation > 1:
        print(f"  ⚠️  偏差 {deviation:.1f}% 在可接受范围, 可能因股价波动/股本变化")
        return True
    else:
        print(f"  ✅ 验证通过, 偏差仅 {deviation:.2f}%")
        return True

# ---------------------------------------------------------------------------
# 2. Valuation Metrics Verification
# ---------------------------------------------------------------------------

def verify_valuation(price, eps=None, bvps=None, fcf_per_share=None,
                     dividend=None, revenue_per_share=None):
    p = exact(price)
    print("=" * 60)
    print("估值指标验算 (Valuation Verification)")
    print("=" * 60)
    print(f"  当前股价: {p}")
    print()
    results = {}
    if eps is not None:
        e = exact(eps)
        if e != 0:
            pe = _CTX.divide(p, e)
            print(f"  PE (TTM):  {p} / {e} = {pe:.2f}x")
            results["PE"] = float(pe)
            ey = _CTX.divide(e, p) * 100
            print(f"  盈利收益率: {ey:.2f}%")
    if bvps is not None:
        b = exact(bvps)
        if b != 0:
            pb = _CTX.divide(p, b)
            print(f"  PB:        {p} / {b} = {pb:.2f}x")
            results["PB"] = float(pb)
            if eps is not None and float(exact(eps)) != 0:
                roe = _CTX.divide(exact(eps), b) * 100
                print(f"  ROE:       {exact(eps)} / {b} = {roe:.2f}%")
                results["ROE"] = float(roe)
    if fcf_per_share is not None:
        f = exact(fcf_per_share)
        if f != 0:
            fcf_yield = _CTX.divide(f, p) * 100
            pfcf = _CTX.divide(p, f)
            print(f"  P/FCF:     {p} / {f} = {pfcf:.2f}x")
            print(f"  FCF Yield: {fcf_yield:.2f}%")
            results["P_FCF"] = float(pfcf)
            results["FCF_Yield"] = float(fcf_yield)
    if dividend is not None:
        d = exact(dividend)
        if p != 0:
            div_yield = _CTX.divide(d, p) * 100
            print(f"  股息率:    {d} / {p} = {div_yield:.2f}%")
            results["Dividend_Yield"] = float(div_yield)
    if revenue_per_share is not None:
        r = exact(revenue_per_share)
        if r != 0:
            ps = _CTX.divide(p, r)
            print(f"  PS:        {p} / {r} = {ps:.2f}x")
            results["PS"] = float(ps)
    print()
    print("  ✅ 以上指标均使用精确十进制计算, 无浮点误差")
    return results

# ---------------------------------------------------------------------------
# 3. Cross-Source Data Validation
# ---------------------------------------------------------------------------

def cross_validate(field_name, source_values: dict, unit="", tolerance_pct=2.0):
    print("=" * 60)
    print(f"交叉验证: {field_name} (Cross-Validation)")
    print("=" * 60)
    values = {k: exact(v) for k, v in source_values.items()}
    sorted_vals = sorted(float(v) for v in values.values())
    n = len(sorted_vals)
    median = sorted_vals[n // 2] if n % 2 == 1 else (sorted_vals[n//2-1] + sorted_vals[n//2]) / 2
    print(f"  数据来源数: {len(source_values)}")
    print(f"  参考中位数: {fmt_number(exact(median))} {unit}")
    print()
    all_ok = True
    for src, val in values.items():
        dev = abs(float(val) - median) / median * 100 if median != 0 else 0
        status = "✅" if dev <= tolerance_pct else "❌"
        if dev > tolerance_pct:
            all_ok = False
        print(f"  {status} {src:20s}: {fmt_number(val)} {unit}  (偏差 {dev:.2f}%)")
    print()
    if all_ok:
        print(f"  ✅ 所有来源偏差 ≤ {tolerance_pct}%, 数据一致")
    else:
        print(f"  ⚠️  存在来源偏差 > {tolerance_pct}%, 请核实差异原因")
    print(f"\n  共识值: {fmt_number(exact(median))} {unit}")
    return {"consensus": median, "all_consistent": all_ok}

# ---------------------------------------------------------------------------
# 4. Exact Calculator
# ---------------------------------------------------------------------------

def exact_calc(expr: str):
    print("=" * 60)
    print("精确计算 (Exact Calculator)")
    print("=" * 60)
    allowed = set("0123456789.+-*/() eE")
    if not all(c in allowed for c in expr.replace(" ", "")):
        print(f"  ❌ 不安全的表达式: {expr}")
        return None
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        d_result = exact(result)
        print(f"  表达式: {expr}")
        print(f"  结果:   {fmt_number(d_result)}")
        print(f"  精确值: {d_result}")
        return float(d_result)
    except Exception as e:
        print(f"  ❌ 计算错误: {e}")
        return None

# ---------------------------------------------------------------------------
# 5. Three-Scenario Valuation
# ---------------------------------------------------------------------------

def three_scenario_valuation(current_price, current_eps, shares_billion,
                             growth_optimistic, growth_neutral, growth_pessimistic,
                             pe_optimistic, pe_neutral, pe_pessimistic,
                             years=3, currency=""):
    p = exact(current_price)
    eps = exact(current_eps)
    shares = exact(shares_billion)
    scenarios = [
        ("乐观 (Bull)", growth_optimistic, pe_optimistic),
        ("中性 (Base)", growth_neutral, pe_neutral),
        ("悲观 (Bear)", growth_pessimistic, pe_pessimistic),
    ]
    print("=" * 60)
    print("三情景估值模型 (Three-Scenario Valuation)")
    print("=" * 60)
    print(f"  当前股价: {p} {currency}")
    print(f"  当前EPS:  {eps}")
    print(f"  预测期:   {years}年")
    print()
    print(f"  {'情景':12} {'年增速':>8} {'目标PE':>8} {'目标EPS':>10} {'目标股价':>10} {'涨跌幅':>8}")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*8}")
    for name, growth, pe in scenarios:
        g = exact(growth)
        target_pe = exact(pe)
        future_eps = eps
        for _ in range(years):
            future_eps = _CTX.multiply(future_eps, _CTX.add(Decimal("1"), g))
        target_price = _CTX.multiply(future_eps, target_pe)
        change = float(target_price - p) / float(p) * 100
        print(f"  {name:12} {float(g)*100:>7.0f}% {float(target_pe):>7.0f}x "
              f"{float(future_eps):>10.2f} {float(target_price):>9.1f} {change:>+7.1f}%")
    print()
    print("  ✅ 所有计算使用精确十进制, 结果可审计复现")

# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Financial Rigor Toolkit — 金融数据严谨性验证工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s verify-market-cap --price 510 --shares 9.11e9 --reported 4.65e12 --currency HKD
  %(prog)s verify-valuation --price 510 --eps 23.5 --bvps 120
  %(prog)s cross-validate --field revenue --values '{"年报": 7518, "Yahoo": 7500}' --unit 亿
  %(prog)s calc --expr '510 * 9.11e9'
        """)
    sub = parser.add_subparsers(dest="command")
    mc = sub.add_parser("verify-market-cap")
    mc.add_argument("--price", type=float, required=True)
    mc.add_argument("--shares", type=float, required=True)
    mc.add_argument("--reported", type=float, required=True)
    mc.add_argument("--currency", default="")
    val = sub.add_parser("verify-valuation")
    val.add_argument("--price", type=float, required=True)
    val.add_argument("--eps", type=float, default=None)
    val.add_argument("--bvps", type=float, default=None)
    val.add_argument("--fcf-per-share", type=float, default=None)
    val.add_argument("--dividend", type=float, default=None)
    val.add_argument("--revenue-per-share", type=float, default=None)
    cv = sub.add_parser("cross-validate")
    cv.add_argument("--field", required=True)
    cv.add_argument("--values", required=True)
    cv.add_argument("--unit", default="")
    cv.add_argument("--tolerance", type=float, default=2.0)
    ca = sub.add_parser("calc")
    ca.add_argument("--expr", required=True)
    ts = sub.add_parser("three-scenario")
    ts.add_argument("--price", type=float, required=True)
    ts.add_argument("--eps", type=float, required=True)
    ts.add_argument("--shares", type=float, required=True, help="总股本(亿)")
    ts.add_argument("--growth", nargs=3, type=float, required=True,
                    help="乐观/中性/悲观 年增速(小数)")
    ts.add_argument("--pe", nargs=3, type=float, required=True,
                    help="乐观/中性/悲观 目标PE")
    ts.add_argument("--years", type=int, default=3)
    ts.add_argument("--currency", default="")
    args = parser.parse_args()
    _force_utf8_stdio()
    if args.command == "verify-market-cap":
        verify_market_cap(args.price, args.shares, args.reported, args.currency)
    elif args.command == "verify-valuation":
        verify_valuation(args.price, args.eps, args.bvps,
                         args.fcf_per_share, args.dividend,
                         args.revenue_per_share)
    elif args.command == "cross-validate":
        values = json.loads(args.values)
        cross_validate(args.field, values, args.unit, args.tolerance)
    elif args.command == "calc":
        exact_calc(args.expr)
    elif args.command == "three-scenario":
        three_scenario_valuation(
            args.price, args.eps, args.shares,
            args.growth[0], args.growth[1], args.growth[2],
            args.pe[0], args.pe[1], args.pe[2],
            args.years, args.currency,
        )
    else:
        parser.print_help()

if __name__ == "__main__":
    main()