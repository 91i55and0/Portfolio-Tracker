"""
IBKR 白色风格专业组合持仓仪表盘生成器
包含持仓分析预警面板 — 集成 AI Berkshire 四大师框架
"""

import os
import json
from datetime import datetime
from typing import List, Dict

# 尝试导入 AI Berkshire 分析引擎
try:
    from portfolio_analysis import BerkshireAnalysis
    HAS_BERKSHIRE = True
except ImportError:
    HAS_BERKSHIRE = False
    import logging
    logging.warning("未找到 portfolio_analysis，使用基础分析模式")


def generate_analysis(holdings: List[Dict], summary: Dict, manager=None) -> List[Dict]:
    """使用 AI Berkshire 方法论生成分析（如有），否则使用基础分析"""
    if HAS_BERKSHIRE and manager:
        try:
            ba = BerkshireAnalysis(manager)
            alerts = ba.analyze_all()
            # 读取用户自定义分析文本
            analysis_map = {}
            for h in manager.data["holdings"]:
                if "analysis" in h:
                    analysis_map[h["id"]] = h["analysis"]
            for a in alerts:
                a["analysis_text"] = analysis_map.get(a["id"], a.get("analysis_text", ""))
            return alerts
        except Exception as e:
            import logging
            logging.warning(f"Berkshire 分析失败，回退基础模式: {e}")

    # ========== 回退：基础分析模式 ==========
    analysis_map = {}
    if manager:
        for h in manager.data["holdings"]:
            if "analysis" in h:
                analysis_map[h["id"]] = h["analysis"]

    alerts = []
    for h in holdings:
        item = {
            "id": h["id"],
            "ticker": h["ticker"],
            "name": h["name"],
            "market": h["market"],
            "currency": h["currency"],
            "sector": h["sector"],
            "notes": h.get("notes", ""),
            "analysis_text": analysis_map.get(h["id"], ""),
            "signals": [],
            "risk_level": "normal",
            "verdict": "",
            "data_snapshot": {},
        }
        item["data_snapshot"] = {
            "pnl_pct": round(h["pnl_pct"], 1),
            "pnl": round(h["pnl"], 2),
            "weight": round(h["weight"], 1),
            "weight_a": round(h.get("weight_a", 0), 1),
            "weight_hk_us": round(h.get("weight_hk_us", 0), 1),
            "holding_days": h["holding_days"],
            "day_change_pct": round(h["day_change_pct"], 2),
            "current_price": round(h["current_price"], 2),
            "avg_cost": round(h["avg_cost"], 2),
            "annualized_return": round(h["annualized_return"], 1),
            "market": h.get("market", ""),
        }
        pnl_pct = h["pnl_pct"]
        if pnl_pct <= -30:
            item["signals"].append({"type": "danger", "icon": "&#x26A0;", "text": f"亏损 {pnl_pct:.1f}%，深套严重"})
            item["risk_level"] = "danger"
        elif pnl_pct <= -15:
            item["signals"].append({"type": "warning", "icon": "&#x26A0;", "text": f"亏损 {pnl_pct:.1f}%"})
            if item["risk_level"] == "normal":
                item["risk_level"] = "warning"
        day_chg = h["day_change_pct"]
        if abs(day_chg) >= 5:
            item["signals"].append({"type": "danger" if day_chg < 0 else "success", "icon": "&#x26A1;", "text": f"日内{'下跌' if day_chg < 0 else '上涨'}{abs(day_chg):.1f}%"})
        weight = h["weight"]
        if weight >= 30:
            item["signals"].append({"type": "warning", "icon": "&#x26A0;", "text": f"仓位占比 {weight:.1f}%"})
            if item["risk_level"] == "normal":
                item["risk_level"] = "warning"
        if item["risk_level"] == "danger":
            item["verdict"] = "⚠ 需重点关注"
        elif item["risk_level"] == "warning":
            item["verdict"] = "⚡ 注意风险"
        elif item["risk_level"] == "info":
            item["verdict"] = "✓ 关注中"
        else:
            item["verdict"] = "● 正常"
        alerts.append(item)

    return alerts


def generate_dashboard(manager, output_path: str = None):
    if output_path is None:
        output_path = os.path.join(os.path.dirname(__file__), "dashboard.html")

    summary = manager.get_summary_dict()
    holdings = manager.get_holdings_table()
    sector_allocation = manager.get_sector_allocation()
    market_allocation = manager.get_market_allocation()
    price_history_dates = manager.get_price_history_dates()
    alerts = generate_analysis(holdings, summary, manager)

    hist_data = {}
    ph = manager.data.get("price_history", {})
    dates = sorted(ph.keys())
    for h in manager.holdings:
        key = f"{h.ticker}.{h.exchange}" if h.exchange != "US" else h.ticker
        values = []
        for d in dates:
            if d in ph and key in ph[d]:
                values.append(ph[d][key]["price"])
            else:
                values.append(None)
        if values:
            hist_data[key] = {"name": h.name, "ticker": h.ticker, "market": h.market, "dates": dates, "prices": values}

    holdings_json = json.dumps(holdings, ensure_ascii=False)
    summary_json = json.dumps(summary, ensure_ascii=False)
    sector_json = json.dumps(sector_allocation, ensure_ascii=False)
    market_json = json.dumps(market_allocation, ensure_ascii=False)
    hist_json = json.dumps(hist_data, ensure_ascii=False)
    dates_json = json.dumps(dates, ensure_ascii=False)
    alerts_json = json.dumps(alerts, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{summary['name']} - Portfolio Tracker</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
:root {{
    --bg-page: #f3f5f8;
    --bg-card: #ffffff;
    --bg-hover: #f0f2f5;
    --bg-header: #ffffff;
    --bg-sidebar: #ffffff;
    --text-primary: #1a1a2e;
    --text-secondary: #5a6070;
    --text-muted: #8a90a0;
    --border-color: #e0e4ea;
    --border-light: #eef0f4;
    --green: #16a34a;
    --green-bg: #ecfdf5;
    --green-border: #bbf7d0;
    --red: #dc2626;
    --red-bg: #fef2f2;
    --red-border: #fecaca;
    --blue: #2563eb;
    --blue-bg: #eff6ff;
    --blue-border: #bfdbfe;
    --orange: #ea580c;
    --orange-bg: #fff7ed;
    --orange-border: #fed7aa;
    --accent: #2563eb;
    --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
    --shadow-hover: 0 4px 12px rgba(0,0,0,0.08);
    --radius: 6px;
    --radius-lg: 10px;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'SF Pro Text', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
    background: var(--bg-page);
    color: var(--text-primary);
    font-size: 13px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
}}

/* Layout */
.app-layout {{
    display: flex;
    min-height: 100vh;
}}

/* Sidebar */
.sidebar {{
    width: 380px;
    min-width: 380px;
    background: var(--bg-sidebar);
    border-right: 1px solid var(--border-color);
    padding: 0;
    display: flex;
    flex-direction: column;
    height: 100vh;
    position: sticky;
    top: 0;
    overflow: hidden;
}}
.sidebar-header {{
    padding: 16px 18px 12px;
    border-bottom: 1px solid var(--border-color);
    flex-shrink: 0;
}}
.sidebar-title {{
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    display: flex;
    align-items: center;
    gap: 8px;
}}
.sidebar-title .badge {{
    font-size: 10px;
    background: var(--accent);
    color: #fff;
    padding: 1px 8px;
    border-radius: 8px;
    font-weight: 500;
    letter-spacing: 0;
}}
.sidebar-body {{
    flex: 1;
    overflow-y: auto;
    padding: 8px 12px 12px;
}}
.sidebar-body::-webkit-scrollbar {{ width: 4px; }}
.sidebar-body::-webkit-scrollbar-thumb {{ background: var(--border-color); border-radius: 2px; }}

/* Analysis Cards */
.analysis-card {{
    border: 1px solid var(--border-color);
    border-radius: var(--radius);
    margin-bottom: 10px;
    background: var(--bg-card);
    transition: all 0.15s;
    overflow: hidden;
}}
.analysis-card:hover {{
    border-color: #c0c6d0;
    box-shadow: var(--shadow);
}}
.analysis-card-header {{
    padding: 10px 14px 8px;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    cursor: pointer;
    user-select: none;
    border-bottom: 1px solid var(--border-light);
}}
.analysis-card-header:hover {{
    background: var(--bg-hover);
}}
.analysis-card-header-left {{
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
}}
.analysis-ticker {{
    font-weight: 700;
    font-size: 13px;
    color: var(--text-primary);
    letter-spacing: -0.2px;
}}
.analysis-name {{
    font-size: 11px;
    color: var(--text-muted);
    margin-left: 2px;
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}}
.analysis-market {{
    font-size: 9px;
    padding: 1px 5px;
    border-radius: 3px;
    background: #f3e8ff;
    color: #9333ea;
    font-weight: 500;
}}
.analysis-sector {{
    font-size: 9px;
    padding: 1px 5px;
    border-radius: 3px;
    background: var(--bg-hover);
    color: var(--text-muted);
}}
.analysis-verdict {{
    font-size: 10px;
    font-weight: 600;
    white-space: nowrap;
    padding: 2px 8px;
    border-radius: 4px;
}}
.verdict-normal {{
    color: var(--green);
    background: var(--green-bg);
}}
.verdict-info {{
    color: var(--blue);
    background: var(--blue-bg);
}}
.verdict-warning {{
    color: var(--orange);
    background: var(--orange-bg);
}}
.verdict-danger {{
    color: var(--red);
    background: var(--red-bg);
}}

.analysis-card-body {{
    padding: 10px 14px 12px;
}}

/* Narrative Analysis Text */
.analysis-narrative {{
    font-size: 12px;
    line-height: 1.65;
    color: var(--text-secondary);
    padding: 8px 10px;
    background: #f8f9fb;
    border-radius: 4px;
    border-left: 3px solid var(--accent);
    margin-bottom: 8px;
}}

/* Data Snapshot */
.data-snapshot {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 4px;
    margin-bottom: 6px;
}}
.data-item {{
    text-align: center;
    padding: 4px 2px;
    background: var(--bg-hover);
    border-radius: 3px;
}}
.data-item-label {{
    font-size: 9px;
    color: var(--text-muted);
    text-transform: uppercase;
}}
.data-item-value {{
    font-size: 12px;
    font-weight: 600;
    margin-top: 1px;
}}

/* Signals */
.signals-section {{
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1px dashed var(--border-light);
}}
.signals-header {{
    font-size: 10px;
    color: var(--text-muted);
    font-weight: 500;
    margin-bottom: 4px;
    cursor: pointer;
    user-select: none;
}}
.signals-header:hover {{ color: var(--text-secondary); }}
.signals-body {{
    display: flex;
    flex-direction: column;
    gap: 2px;
}}
.alert-signal {{
    display: flex;
    align-items: flex-start;
    gap: 5px;
    padding: 2px 0;
    font-size: 11px;
    line-height: 1.4;
    color: var(--text-secondary);
}}
.alert-signal .signal-icon {{ font-size: 11px; width: 14px; text-align: center; flex-shrink: 0; }}
.alert-signal .signal-text {{ flex: 1; }}
.signal-danger {{ color: var(--red); }}
.signal-warning {{ color: var(--orange); }}
.signal-success {{ color: var(--green); }}
.signal-info {{ color: var(--blue); }}

/* Notes Tag */
.analysis-notes {{
    display: inline-block;
    font-size: 10px;
    color: var(--text-muted);
    font-style: italic;
    margin-top: 4px;
}}

/* Main Content */
.main-content {{
    flex: 1;
    min-width: 0;
    padding: 20px 24px 20px 20px;
    max-width: calc(100% - 380px);
}}

/* Header */
.header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}}
.header-left {{
    display: flex;
    align-items: center;
    gap: 14px;
}}
.header-logo {{
    font-size: 18px;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: -0.3px;
    background: var(--blue-bg);
    padding: 6px 14px;
    border-radius: var(--radius);
}}
.header-title {{
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
}}
.header-badge {{
    background: var(--accent);
    color: #fff;
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 600;
}}
.header-right {{
    display: flex;
    align-items: center;
    gap: 14px;
    font-size: 11px;
    color: var(--text-muted);
}}
.header-right strong {{ color: var(--text-secondary); }}

/* Summary Cards */
.summary-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 10px;
    margin-bottom: 16px;
}}
.card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius);
    padding: 14px 16px;
    transition: all 0.2s;
    box-shadow: var(--shadow);
}}
.card:hover {{
    border-color: var(--accent);
    box-shadow: var(--shadow-hover);
}}
.card-label {{
    font-size: 10px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
    font-weight: 500;
}}
.card-value {{
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.3px;
    color: var(--text-primary);
}}
.card-sub {{
    font-size: 11px;
    margin-top: 3px;
}}
.positive {{ color: var(--green); }}
.negative {{ color: var(--red); }}
.neutral {{ color: var(--text-secondary); }}

/* Charts */
.charts-row {{
    display: grid;
    grid-template-columns: 2fr 1fr 1fr;
    gap: 12px;
    margin-bottom: 16px;
}}
.chart-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius);
    padding: 14px 16px;
    box-shadow: var(--shadow);
}}
.chart-title {{
    font-size: 11px;
    font-weight: 600;
    color: var(--text-muted);
    margin-bottom: 10px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
.chart-container {{
    position: relative;
    height: 200px;
}}

/* Table */
.table-section {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    overflow: hidden;
    box-shadow: var(--shadow);
}}
.table-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 18px;
    border-bottom: 1px solid var(--border-color);
    background: var(--bg-card);
}}
.table-title {{
    font-size: 11px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
.table-count {{
    font-size: 11px;
    color: var(--text-muted);
}}
.table-wrapper {{
    overflow-x: auto;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
}}
th {{
    text-align: right;
    padding: 8px 12px;
    font-size: 10px;
    color: var(--text-muted);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    border-bottom: 1px solid var(--border-color);
    white-space: nowrap;
    cursor: pointer;
    user-select: none;
    background: #fafbfc;
    position: sticky;
    top: 0;
}}
th:first-child {{ text-align: left; padding-left: 18px; }}
th:last-child {{ padding-right: 18px; }}
th:hover {{ color: var(--text-primary); }}
td {{
    padding: 8px 12px;
    text-align: right;
    border-bottom: 1px solid var(--border-light);
    white-space: nowrap;
}}
td:first-child {{ text-align: left; padding-left: 18px; }}
td:last-child {{ padding-right: 18px; }}
tr:hover {{ background: var(--bg-hover); }}
tr:last-child td {{ border-bottom: none; }}

.ticker-badge {{
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    margin-right: 4px;
}}
.ticker-SH, .ticker-SZ {{ background: #e8f4fd; color: #1d72b8; }}
.ticker-HK {{ background: #fff3e0; color: #e65100; }}
.ticker-US {{ background: #f3e8ff; color: #9333ea; }}

.progress-bar {{
    display: inline-block;
    width: 50px;
    height: 3px;
    background: var(--border-light);
    border-radius: 2px;
    vertical-align: middle;
    margin-right: 5px;
    overflow: hidden;
}}
.progress-fill {{
    height: 100%;
    border-radius: 2px;
    transition: width 0.3s;
}}

/* Footer */
.footer {{
    text-align: center;
    padding: 16px;
    color: var(--text-muted);
    font-size: 10px;
    border-top: 1px solid var(--border-color);
    margin-top: 16px;
}}

/* Responsive */
@media (max-width: 1200px) {{
    .app-layout {{ flex-direction: column; }}
    .sidebar {{ width: 100%; min-width: unset; height: auto; position: static; max-height: 500px; }}
    .sidebar-body {{ max-height: 400px; }}
    .main-content {{ max-width: 100%; padding: 16px; }}
    .charts-row {{ grid-template-columns: 1fr 1fr; }}
}}
@media (max-width: 768px) {{
    .summary-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .charts-row {{ grid-template-columns: 1fr; }}
    .header {{ flex-direction: column; gap: 8px; align-items: flex-start; }}
    .header-right {{ flex-wrap: wrap; }}
    .data-snapshot {{ grid-template-columns: repeat(2, 1fr); }}
}}
</style>
</head>
<body>

<div class="app-layout">
    <!-- ========== SIDEBAR ========== -->
    <div class="sidebar">
        <div class="sidebar-header">
            <div class="sidebar-title">
                &#x1F4DD; 持仓分析 <span class="badge">{len(alerts)} 只</span>
            </div>
        </div>
        <div class="sidebar-body" id="alertSidebar">
            <!-- Alerts rendered by JS -->
        </div>
        <div style="padding:8px 14px;border-top:1px solid var(--border-color);font-size:10px;color:var(--text-muted);text-align:center;flex-shrink:0;">
            AI Berkshire 四大师框架 &middot; 分析文本可在 portfolio.json 中编辑
        </div>
    </div>

    <!-- ========== MAIN CONTENT ========== -->
    <div class="main-content">
        <div class="header">
            <div class="header-left">
                <div class="header-logo">&#x25A0; IB</div>
                <div class="header-title">{summary['name']}</div>
                <span class="header-badge">{summary['num_holdings']} HOLDINGS</span>
            </div>
            <div class="header-right">
                <span>&#x23F0; {summary['last_updated']}</span>
                <span>|</span>
                <span>夏普 <strong>{summary['portfolio_sharpe']}</strong></span>
                <span>|</span>
                <span>年化 <strong class="{'positive' if summary['annualized_return'] >= 0 else 'negative'}">{summary['annualized_return']:+.2f}%</strong></span>
            </div>
        </div>

        <!-- Summary Cards -->
        <div class="summary-grid">
            <div class="card">
                <div class="card-label">组合总价值</div>
                <div class="card-value">&#xa5;{summary['total_value_cny']:,.2f}</div>
                <div class="card-sub neutral">含现金仓位</div>
            </div>
            <div class="card">
                <div class="card-label">总盈亏</div>
                <div class="card-value {'positive' if summary['total_pnl'] >= 0 else 'negative'}">{summary['total_pnl']:+,.2f}</div>
                <div class="card-sub {'positive' if summary['total_pnl_pct'] >= 0 else 'negative'}">{summary['total_pnl_pct']:+.2f}%</div>
            </div>
            <div class="card">
                <div class="card-label">当日盈亏</div>
                <div class="card-value {'positive' if summary['day_pnl'] >= 0 else 'negative'}">{summary['day_pnl']:+,.2f}</div>
                <div class="card-sub {'positive' if summary['day_pnl_pct'] >= 0 else 'negative'}">{summary['day_pnl_pct']:+.2f}%</div>
            </div>
            <div class="card">
                <div class="card-label">夏普比率</div>
                <div class="card-value {'positive' if summary['portfolio_sharpe'] >= 1 else 'neutral' if summary['portfolio_sharpe'] >= 0 else 'negative'}">{summary['portfolio_sharpe']}</div>
                <div class="card-sub neutral">无风险 {summary['risk_free_rate']*100:.1f}%</div>
            </div>
            <div class="card">
                <div class="card-label">年化收益率</div>
                <div class="card-value {'positive' if summary['annualized_return'] >= 0 else 'negative'}">{summary['annualized_return']:+.2f}%</div>
                <div class="card-sub neutral">加权持有 {summary['weighted_holding_days']:.0f} 天</div>
            </div>
            <div class="card">
                <div class="card-label">持仓</div>
                <div class="card-value">{summary['num_holdings']}</div>
                <div class="card-sub"><span class="positive">&#x25B2; {summary['num_positive']}</span> <span class="negative" style="margin-left:8px">&#x25BC; {summary['num_negative']}</span></div>
            </div>
            <div class="card">
                <div class="card-label">最大持仓</div>
                <div class="card-value" style="font-size:15px">{summary['top_holding']}</div>
                <div class="card-sub neutral">占比 {summary['top_holding_weight']:.1f}%</div>
            </div>
            <div class="card">
                <div class="card-label">最佳表现</div>
                <div class="card-value positive" style="font-size:15px">{summary['top_performer']}</div>
                <div class="card-sub positive">{summary['top_performer_pnl']:+,.2f}</div>
            </div>
        </div>

        <!-- Charts -->
        <div class="charts-row">
            <div class="chart-card">
                <div class="chart-title">组合净值走势</div>
                <div class="chart-container"><canvas id="valueChart"></canvas></div>
            </div>
            <div class="chart-card">
                <div class="chart-title">行业配置</div>
                <div class="chart-container"><canvas id="sectorChart"></canvas></div>
            </div>
            <div class="chart-card">
                <div class="chart-title">市场分布</div>
                <div class="chart-container"><canvas id="marketChart"></canvas></div>
            </div>
        </div>

        <!-- Holdings Table -->
        <div class="table-section">
            <div class="table-header">
                <div class="table-title">持仓明细</div>
                <div class="table-count">{summary['num_holdings']} 只标的 &middot; 点击表头排序</div>
            </div>
            <div class="table-wrapper">
                <table id="holdingsTable">
                    <thead>
                        <tr>
                            <th onclick="sortTable(0)">代码</th>
                            <th onclick="sortTable(1)">名称</th>
                            <th onclick="sortTable(2)">市场</th>
                            <th onclick="sortTable(3)">行业</th>
                            <th onclick="sortTable(4)">数量</th>
                            <th onclick="sortTable(5)">成本价</th>
                            <th onclick="sortTable(6)">现价</th>
                            <th onclick="sortTable(7)">市值(CNY)</th>
                            <th onclick="sortTable(8)">盈亏</th>
                            <th onclick="sortTable(9)">盈亏%</th>
                            <th onclick="sortTable(10)">日涨跌</th>
                            <th onclick="sortTable(11)">持仓天数</th>
                            <th onclick="sortTable(12)">总权重</th>
                            <th onclick="sortTable(13)">子权重</th>
                            <th onclick="sortTable(14)">年化收益</th>
                        </tr>
                    </thead>
                    <tbody id="holdingsBody"></tbody>
                </table>
            </div>
        </div>

        <div class="footer">
            PORTFOLIO TRACKER &mdash; 数据来源: Yahoo Finance &mdash; 更新于 {summary['last_updated']}
        </div>
    </div>
</div>

<script>
// ========== Data ==========
const holdingsData = {holdings_json};
const summaryData = {summary_json};
const sectorData = {sector_json};
const marketData = {market_json};
const histData = {hist_json};
const histDates = {dates_json};
const alertsData = {alerts_json};

// ========== Helpers ==========
function fmt(n, d) {{ return Number(n).toFixed(d||2); }}
function pct(n) {{ return (n >= 0 ? '+' : '') + fmt(n, 2) + '%'; }}
function money(n) {{ return '¥' + Number(n).toLocaleString('zh-CN', {{minimumFractionDigits:2, maximumFractionDigits:2}}); }}
function moneyUsd(n) {{ return '$' + Number(n).toLocaleString('en-US', {{minimumFractionDigits:2, maximumFractionDigits:2}}); }}
function moneyHkd(n) {{ return 'HK$' + Number(n).toLocaleString('zh-CN', {{minimumFractionDigits:2, maximumFractionDigits:2}}); }}
function fmtCurrency(n, c) {{ if(c==='USD') return moneyUsd(n); if(c==='HKD') return moneyHkd(n); return money(n); }}
function marketCls(h) {{ if(!h) return ''; if(h.market==='A股') return 'ticker-SH'; if(h.market==='港股') return 'ticker-HK'; return 'ticker-US'; }}

// ========== Render Alerts (Analysis Sidebar) ==========
function renderAlerts() {{
    const container = document.getElementById('alertSidebar');
    let html = '';
    alertsData.forEach(a => {{
        const vCls = 'verdict-' + a.risk_level;
        const hasAnalysis = a.analysis_text && a.analysis_text.length > 0;
        const ds = a.data_snapshot;

        html += `<div class="analysis-card">
            <div class="analysis-card-header">
                <div class="analysis-card-header-left">
                    <span class="analysis-ticker">${{a.ticker || 'PORTFOLIO'}}</span>
                    ${{a.name ? '<span class="analysis-name">'+a.name+'</span>' : ''}}
                    ${{a.market ? '<span class="analysis-market">'+a.market+'</span>' : ''}}
                    ${{a.sector ? '<span class="analysis-sector">'+a.sector+'</span>' : ''}}
                </div>
                <div class="analysis-verdict ${{vCls}}">${{a.verdict}}</div>
            </div>
            <div class="analysis-card-body">`;

        // Berkshire Score
        if (a.berkshire) {{
            const bs = a.berkshire;
            const scoreCls = bs.avg_score >= 3.5 ? 'positive' : bs.avg_score >= 2.5 ? 'neutral' : 'negative';
            html += `<div style="display:flex;align-items:center;gap:6px;padding:4px 0 6px;border-bottom:1px dashed var(--border-light);margin-bottom:6px;">
                <span style="font-size:10px;color:var(--text-muted);font-weight:600;">&#x1F3C6; 四大师评分</span>
                <span style="font-size:16px;font-weight:700;color:var(--text-primary);" class="${{scoreCls}}">${{bs.avg_score}}</span>
                <span style="font-size:9px;color:var(--text-muted);flex:1;">${{bs.score_detail}}</span>
            </div>
            <div style="font-size:11px;color:var(--text-secondary);padding:4px 6px;background:#f8f9fb;border-radius:3px;margin-bottom:6px;">
                ${{bs.summary}}
                ${{bs.recommendations && bs.recommendations.length ? '<br>' + bs.recommendations.map(r => '&#x2022; ' + r).join('<br>') : ''}}
            </div>`;
        }}

        // Narrative Analysis Text
        if (hasAnalysis) {{
            html += `<div class="analysis-narrative">${{a.analysis_text}}</div>`;
        }}

        // Data Snapshot
        if (ds && ds.pnl_pct !== undefined) {{
            const pnlCls = ds.pnl_pct >= 0 ? 'positive' : 'negative';
            const dayCls = ds.day_change_pct >= 0 ? 'positive' : 'negative';
            const annCls = ds.annualized_return >= 0 ? 'positive' : 'negative';
            const isA = ds.market === 'A股';
            const subW = isA && ds.weight_a ? ds.weight_a : ds.weight_hk_us;
            const subLabel = isA ? 'A股占比' : '港美股占比';
            html += `<div class="data-snapshot">
                <div class="data-item">
                    <div class="data-item-label">盈亏</div>
                    <div class="data-item-value ${{pnlCls}}">${{pct(ds.pnl_pct)}}</div>
                </div>
                <div class="data-item">
                    <div class="data-item-label">日涨跌</div>
                    <div class="data-item-value ${{dayCls}}">${{pct(ds.day_change_pct)}}</div>
                </div>
                <div class="data-item">
                    <div class="data-item-label">总权重</div>
                    <div class="data-item-value">${{ds.weight}}%</div>
                </div>
                <div class="data-item">
                    <div class="data-item-label">年化</div>
                    <div class="data-item-value ${{annCls}}">${{pct(ds.annualized_return)}}</div>
                </div>
            </div>
            <div class="data-snapshot" style="margin-top:2px;">
                <div class="data-item" style="grid-column:1/-1;">
                    <div class="data-item-label">${{subLabel}}</div>
                    <div class="data-item-value">${{subW.toFixed(1)}}%</div>
                </div>
            </div>`;
        }}

        // Notes
        if (a.notes) {{
            html += `<div class="analysis-notes">&#x1F4CB; ${{a.notes}}</div>`;
        }}

        // Signals
        if (a.signals && a.signals.length > 0) {{
            html += `<div class="signals-section">
                <div class="signals-header" onclick="toggleSignals(this)">&#x25BC; 数据信号 (${{a.signals.length}})</div>
                <div class="signals-body" style="display:none;">`;
            a.signals.forEach(s => {{
                const cls = 'signal-' + s.type;
                html += `<div class="alert-signal ${{cls}}">
                    <span class="signal-icon">${{s.icon}}</span>
                    <span class="signal-text">${{s.text}}</span>
                </div>`;
            }});
            html += `</div></div>`;
        }}

        html += `</div></div>`;
    }});
    if (!alertsData.length) {{
        html = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:12px;">暂无持仓数据</div>';
    }}
    container.innerHTML = html;
}}

function toggleSignals(el) {{
    const body = el.nextElementSibling;
    if (body) {{
        body.style.display = body.style.display === 'none' ? 'flex' : 'none';
        el.innerHTML = body.style.display === 'flex'
            ? '&#x25B2; 数据信号'
            : '&#x25BC; 数据信号';
    }}
}}

// ========== Holdings Table ==========
function renderTable() {{
    const tbody = document.getElementById('holdingsBody');
    let html = '';
    holdingsData.forEach(h => {{
        const pnlCls = h.pnl >= 0 ? 'positive' : 'negative';
        const dayCls = h.day_change_pct >= 0 ? 'positive' : 'negative';
        const annCls = h.annualized_return >= 0 ? 'positive' : 'negative';
        const wp = h.weight.toFixed(1);
        const sw = h.market === 'A股' ? (h.weight_a || 0).toFixed(1) : (h.weight_hk_us || 0).toFixed(1);
        html += `<tr>
            <td><span class="ticker-badge ${{marketCls(h)}}">${{h.ticker}}</span></td>
            <td style="text-align:left">${{h.name}}</td>
            <td>${{h.market}}</td>
            <td>${{h.sector}}</td>
            <td>${{h.shares.toLocaleString()}}</td>
            <td>${{fmtCurrency(h.avg_cost, h.currency)}}</td>
            <td>${{fmtCurrency(h.current_price, h.currency)}}</td>
            <td>${{money(h.market_value_cny)}}</td>
            <td class="${{pnlCls}}">${{fmtCurrency(h.pnl, h.currency)}}</td>
            <td class="${{pnlCls}}">${{pct(h.pnl_pct)}}</td>
            <td class="${{dayCls}}">${{pct(h.day_change_pct)}}</td>
            <td>${{h.holding_days}}d</td>
            <td><div class="progress-bar"><div class="progress-fill" style="width:${{wp}}%;background:${{h.pnl>=0?'var(--green)':'var(--red)'}}"></div></div>${{wp}}%</td>
            <td>${{sw}}%</td>
            <td class="${{annCls}}">${{pct(h.annualized_return)}}</td>
        </tr>`;
    }});
    tbody.innerHTML = html;
}}

let sortDir = {{}};
function sortTable(col) {{
    sortDir[col] = !(sortDir[col]||false);
    const d = sortDir[col] ? 1 : -1;
    const keys = ['ticker','name','market','sector','shares','avg_cost','current_price','market_value_cny','pnl','pnl_pct','day_change_pct','holding_days','weight','weight','annualized_return'];
    const k = keys[col]||'ticker';
    // 子权重列(13)使用自定义排序逻辑
    if (col === 13) {{
        holdingsData.sort((a,b) => {{
            const sa = a.market === 'A股' ? (a.weight_a||0) : (a.weight_hk_us||0);
            const sb = b.market === 'A股' ? (b.weight_a||0) : (b.weight_hk_us||0);
            return (sa - sb) * d;
        }});
        renderTable();
        return;
    }}
    holdingsData.sort((a,b) => {{ const va = a[k]||0, vb = b[k]||0; if(typeof va==='number') return (va-vb)*d; return String(va).localeCompare(String(vb))*d; }});
    renderTable();
}}

// ========== Charts ==========

// Sector
const sectorCtx = document.getElementById('sectorChart').getContext('2d');
const sectorColors = ['#2563eb','#16a34a','#ea580c','#dc2626','#9333ea','#0891b2','#ca8a04','#14b8a6'];
new Chart(sectorCtx, {{
    type: 'doughnut',
    data: {{
        labels: sectorData.map(s => s.sector + ' (' + s.weight.toFixed(1) + '%)'),
        datasets: [{{ data: sectorData.map(s => s.weight), backgroundColor: sectorColors.slice(0, sectorData.length), borderWidth: 0 }}]
    }},
    options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right', labels: {{ color: '#5a6070', font: {{ size: 10 }}, padding: 6, boxWidth: 10 }} }} }} }}
}});

// Market
const marketCtx = document.getElementById('marketChart').getContext('2d');
const mColors = {{'A股':'#2563eb','港股':'#ea580c','美股':'#9333ea'}};
new Chart(marketCtx, {{
    type: 'doughnut',
    data: {{
        labels: marketData.map(m => m.market + ' (' + m.weight.toFixed(1) + '%)'),
        datasets: [{{ data: marketData.map(m => m.weight), backgroundColor: marketData.map(m => mColors[m.market]||'#8a90a0'), borderWidth: 0 }}]
    }},
    options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right', labels: {{ color: '#5a6070', font: {{ size: 10 }}, padding: 6, boxWidth: 10 }} }} }} }}
}});

// Portfolio Value
if (histDates.length > 1 && Object.keys(histData).length > 0) {{
    const vCtx = document.getElementById('valueChart').getContext('2d');
    const totalValues = histDates.map((dt, idx) => {{
        let total = 0;
        for (const [k, d] of Object.entries(histData)) {{
            const p = d.prices[idx];
            if (p) {{ const h = holdingsData.find(hh => hh.ticker === d.ticker); if (h) total += p * h.shares; }}
        }}
        return total;
    }});
    let bi = 0; for (let i=0;i<totalValues.length;i++) {{ if(totalValues[i]>0){{ bi=i; break; }} }}
    const bv = totalValues[bi]||1;
    const nv = totalValues.map(v => (v/bv*100).toFixed(2));
    const lv = nv[nv.length-1];
    const lc = lv >= 100 ? '#16a34a' : '#dc2626';
    new Chart(vCtx, {{
        type: 'line',
        data: {{
            labels: histDates,
            datasets: [{{
                label: '组合净值',
                data: nv,
                borderColor: lc,
                backgroundColor: lv>=100?'rgba(22,163,74,0.06)':'rgba(220,38,38,0.06)',
                fill: true, tension: 0.3, pointRadius: 0, pointHitRadius: 10, borderWidth: 2
            }}]
        }},
        options: {{
            responsive: true, maintainAspectRatio: false,
            interaction: {{ intersect: false, mode: 'index' }},
            plugins: {{
                legend: {{ display: false }},
                tooltip: {{ backgroundColor: '#fff', titleColor: '#1a1a2e', bodyColor: '#5a6070', borderColor: '#e0e4ea', borderWidth: 1, callbacks: {{ label: ctx => '净值: ' + parseFloat(ctx.raw).toFixed(2) }} }}
            }},
            scales: {{
                x: {{ grid: {{ color: 'rgba(224,228,234,0.5)' }}, ticks: {{ color: '#8a90a0', maxTicksLimit: 8, font: {{ size: 10 }} }} }},
                y: {{ grid: {{ color: 'rgba(224,228,234,0.5)' }}, ticks: {{ color: '#8a90a0', font: {{ size: 10 }}, callback: v => v.toFixed(1) }} }}
            }}
        }}
    }});
}} else {{
    document.querySelector('.chart-card:first-child').innerHTML = '<div class="chart-title" style="padding:60px 0;text-align:center;color:var(--text-muted)">需要多次刷新累积数据后显示净值走势</div>';
}}

// ========== Init ==========
renderAlerts();
renderTable();
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


if __name__ == "__main__":
    from portfolio_core import PortfolioManager
    pm = PortfolioManager()
    generate_dashboard(pm)