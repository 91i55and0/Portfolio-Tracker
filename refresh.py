"""
组合持仓刷新脚本 - 获取最新行情、计算指标、生成仪表盘
可定时运行实现每日自动刷新
"""

import os
import sys
import json
import logging
from datetime import datetime

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "refresh.log"), encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# 确保在正确的目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

from portfolio_core import PortfolioManager, update_fx_rates
from data_fetcher import fetch_all_prices, fetch_fx_rates, fetch_all_hist_prices


def refresh_all(save_history: bool = True):
    """
    完整刷新流程
    1. 加载持仓
    2. 获取汇率
    3. 获取实时行情
    4. 更新指标
    5. 保存价格历史
    6. 生成仪表盘
    """
    logger.info("=" * 60)
    logger.info("开始组合持仓刷新...")
    logger.info(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 加载持仓
    pm = PortfolioManager()
    logger.info(f"已加载 {len(pm.holdings)} 只持仓")

    # 2. 获取汇率
    try:
        rates = fetch_fx_rates()
        update_fx_rates(rates["USDCNY"], rates["HKDCNY"])
        logger.info(f"汇率: USD/CNY={rates['USDCNY']}, HKD/CNY={rates['HKDCNY']}")
    except Exception as e:
        logger.warning(f"获取汇率失败，使用默认值: {e}")

    # 3. 获取实时行情
    symbols = pm.get_ticker_symbols()
    logger.info(f"准备获取 {len(symbols)} 个标的行情...")

    prices = fetch_all_prices(symbols)
    logger.info(f"成功获取 {len(prices)} 个标的行情")

    # 4. 更新指标
    pm.update_prices(prices)
    logger.info("指标计算完成")

    # 打印概要
    s = pm.summary
    logger.info(f"组合市值: {s.total_market_value_cny:.2f} CNY (等值)")
    logger.info(f"总盈亏: {s.total_pnl:+.2f} CNY ({s.total_pnl_pct:+.2f}%)")
    logger.info(f"当日盈亏: {s.day_pnl:+.2f} CNY ({s.day_pnl_pct:+.2f}%)")
    logger.info(f"夏普率: {s.portfolio_sharpe:.2f}")

    # 5. 保存价格历史
    if save_history:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            history_entry = {}
            for key, data in prices.items():
                history_entry[key] = {
                    "price": data["price"],
                    "change_pct": data["change_pct"],
                }
            pm.data.setdefault("price_history", {})
            pm.data["price_history"][today] = history_entry
            pm.save()
            logger.info("价格历史已保存")
        except Exception as e:
            logger.warning(f"保存价格历史失败: {e}")

    # 6. 生成仪表盘
    try:
        from dashboard_generator import generate_dashboard
        output_path = os.path.join(SCRIPT_DIR, "dashboard.html")
        generate_dashboard(pm, output_path)
        logger.info(f"仪表盘已生成: {output_path}")
    except Exception as e:
        logger.error(f"生成仪表盘失败: {e}")
        import traceback
        traceback.print_exc()

    # 7. 运行 AI Berkshire 分析
    try:
        from portfolio_analysis import BerkshireAnalysis
        ba = BerkshireAnalysis(pm)
        alerts = ba.analyze_all()
        logger.info(f"Berkshire 分析完成: {len(alerts)} 条分析条目")
        # 记录关键发现
        for a in alerts:
            if a.get("berkshire") and a["berkshire"]["avg_score"] < 2.0:
                logger.warning(f"  ⚠ {a['ticker']} {a['name']}: 四大师评分 {a['berkshire']['avg_score']} - {a['berkshire']['summary']}")
    except Exception as e:
        logger.warning(f"Berkshire 分析跳过: {e}")

    logger.info("刷新完成!")
    logger.info("=" * 60)

    return pm


def refresh_quick():
    """快速刷新（仅获取行情和生成仪表盘，不保存历史）"""
    return refresh_all(save_history=False)


if __name__ == "__main__":
    refresh_all()