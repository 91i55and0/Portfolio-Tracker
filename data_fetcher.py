"""
数据获取模块 - 获取 A股、港股、美股实时行情
使用 akshare (A股) + yfinance (港股/美股) + 新浪财经 多源数据
含自动重试和回退机制
"""

import time
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, List

# 设置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 导入数据源
try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False
    logger.warning("akshare 未安装，A股数据将不可用")

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False
    logger.warning("yfinance 未安装，港股/美股数据将不可用")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# 请求间隔控制
YFINANCE_DELAY = 3.0  # yfinance 请求间隔（秒）


# ========== A股 数据获取 ==========

def fetch_a_share_price_batch(codes: List[Dict]) -> Dict[str, Dict]:
    """批量获取A股行情 - 优先使用akshare，回退到新浪财经"""
    results = {}
    a_stocks = [c for c in codes if c["market"] == "A股"]
    if not a_stocks:
        return results

    # 方案1: akshare 批量获取
    if HAS_AKSHARE:
        try:
            df = ak.stock_zh_a_spot_em()
            code_col = "代码"
            name_col = "名称"
            price_col = "最新价"
            change_col = "涨跌幅"

            for c in a_stocks:
                full_code = f"{c['code']}.{c['exchange']}"
                key = full_code
                match = df[df[code_col] == full_code]
                if match.empty:
                    match = df[df[code_col] == c["code"]]
                if not match.empty:
                    row = match.iloc[0]
                    price = float(row[price_col]) if price_col in row else 0
                    change_pct = float(row[change_col]) if change_col in row else 0
                    name = str(row[name_col]) if name_col in row else c["code"]
                    results[key] = {
                        "ticker": c["code"],
                        "exchange": c["exchange"],
                        "name": name,
                        "price": price,
                        "change_pct": change_pct,
                        "source": "akshare",
                        "time": datetime.now().strftime("%H:%M:%S"),
                    }
            if results:
                logger.info(f"akshare 获取A股成功: {len(results)} 只")
                return results
        except Exception as e:
            logger.warning(f"akshare 批量获取失败: {e}")

    # 方案2: 逐个使用新浪财经
    for c in a_stocks:
        key = f"{c['code']}.{c['exchange']}"
        try:
            sina_code = f"{'sh' if c['exchange'] == 'SH' else 'sz'}{c['code']}"
            url = f"https://hq.sinajs.cn/list={sina_code}"
            headers = {
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=5)
            resp.encoding = "gbk"
            if resp.text and '"' in resp.text:
                data = resp.text.split('"')[1]
                parts = data.split(",")
                if len(parts) >= 30:
                    name = parts[0]
                    last_close = float(parts[2]) if parts[2] else 0
                    current_price = float(parts[3]) if parts[3] else 0
                    change_pct = ((current_price - last_close) / last_close * 100) if last_close > 0 else 0
                    results[key] = {
                        "ticker": c["code"],
                        "exchange": c["exchange"],
                        "name": name,
                        "price": current_price,
                        "change_pct": round(change_pct, 2),
                        "source": "sina",
                        "time": datetime.now().strftime("%H:%M:%S"),
                    }
        except Exception as e:
            logger.debug(f"新浪获取A股 {c['code']} 失败: {e}")

    if results:
        logger.info(f"新浪财经获取A股成功: {len(results)} 只")
        return results

    # 方案3: yfinance 回退（适用于 GitHub Actions 海外环境）
    if HAS_YFINANCE:
        for c in a_stocks:
            if c["code"] in results:
                continue
            key = f"{c['code']}.{c['exchange']}"
            yf_ticker = f"{c['code']}.{'SS' if c['exchange'] == 'SH' else 'SZ'}"
            try:
                time.sleep(2)
                t = yf.Ticker(yf_ticker)
                hist = t.history(period="2d")
                if not hist.empty:
                    latest = hist.iloc[-1]
                    price = float(latest["Close"])
                    prev_close = float(hist.iloc[-2]["Close"]) if len(hist) > 1 else price
                    change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                    name = ""
                    try:
                        name = t.info.get("shortName") or t.info.get("longName") or ""
                    except:
                        pass
                    results[key] = {
                        "ticker": c["code"],
                        "exchange": c["exchange"],
                        "name": name,
                        "price": round(price, 2),
                        "change_pct": round(change_pct, 2),
                        "source": "yfinance",
                        "time": datetime.now().strftime("%H:%M:%S"),
                    }
            except Exception as e:
                logger.debug(f"yfinance A股 {yf_ticker} 失败: {e}")

        if results:
            logger.info(f"yfinance 获取A股成功: {len(results)} 只")

    return results


# ========== 港股 / 美股 数据获取 ==========

def fetch_yfinance_with_retry(ticker_str: str, max_retries: int = 2) -> Optional[Dict]:
    """
    通过 yfinance 获取股票行情，含重试机制
    ticker_str: yfinance 格式代码 (如 "0700.HK", "AAPL")
    """
    for attempt in range(max_retries + 1):
        try:
            time.sleep(YFINANCE_DELAY)  # 先等待，避免限流
            t = yf.Ticker(ticker_str)

            # 优先使用 history 获取最新价格（更稳定）
            hist = t.history(period="2d")
            if not hist.empty:
                latest = hist.iloc[-1]
                price = float(latest["Close"])
                prev_close = float(hist.iloc[-2]["Close"]) if len(hist) > 1 else price
                change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                name = ""
                try:
                    name = t.info.get("shortName") or t.info.get("longName") or ""
                except:
                    pass
                return {
                    "price": round(price, 2),
                    "change_pct": round(change_pct, 2),
                    "name": name,
                    "source": "yfinance_hist",
                    "time": datetime.now().strftime("%H:%M:%S"),
                }

            # 回退到 info
            try:
                info = t.info
                price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0)
                prev_close = info.get("previousClose", 0) or info.get("regularMarketPreviousClose", 0)
                name = info.get("shortName") or info.get("longName") or ""
                change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                return {
                    "price": price,
                    "change_pct": round(change_pct, 2),
                    "name": name,
                    "source": "yfinance_info",
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
            except Exception as e2:
                if attempt < max_retries:
                    logger.debug(f"yfinance {ticker_str} info 失败(第{attempt+1}次): {e2}, 重试...")
                    time.sleep(YFINANCE_DELAY * 2)
                else:
                    logger.warning(f"yfinance {ticker_str} 最终失败: {e2}")

        except Exception as e:
            if attempt < max_retries:
                logger.debug(f"yfinance {ticker_str} 失败(第{attempt+1}次): {e}, 重试...")
                time.sleep(YFINANCE_DELAY * 2)
            else:
                logger.warning(f"yfinance {ticker_str} 最终失败: {e}")

    return None


def _hk_code_to_sina(code: str) -> str:
    """港股代码转新浪格式（5位补零）"""
    code = code.strip()
    if len(code) <= 5:
        return f"hk{code.zfill(5)}"
    return f"hk{code}"


def fetch_hk_stock_price_sina(code: str) -> Optional[Dict]:
    """通过新浪财经获取港股行情"""
    try:
        sina_code = _hk_code_to_sina(code)
        url = f"https://hq.sinajs.cn/list={sina_code}"
        headers = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=5)
        resp.encoding = "gbk"
        if resp.text and '"' in resp.text:
            data = resp.text.split('"')[1]
            parts = data.split(",")
            if len(parts) >= 9 and parts[1]:
                name = parts[1]  # 中文名
                prev_close = float(parts[3]) if parts[3] else 0
                current_price = float(parts[6]) if parts[6] else 0
                change_pct = float(parts[8]) if parts[8] else 0
                return {
                    "price": current_price,
                    "change_pct": round(change_pct, 2),
                    "name": name,
                    "source": "sina_hk",
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
    except Exception as e:
        logger.debug(f"新浪港股获取 {code} 失败: {e}")
    return None


def fetch_us_stock_price_sina(ticker: str) -> Optional[Dict]:
    """通过新浪财经获取美股行情"""
    try:
        sina_code = f"gb_{ticker.lower()}"
        url = f"https://hq.sinajs.cn/list={sina_code}"
        headers = {
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=5)
        resp.encoding = "gbk"
        if resp.text and '"' in resp.text:
            data = resp.text.split('"')[1]
            parts = data.split(",")
            if len(parts) >= 5 and parts[1]:
                name = parts[0]
                current_price = float(parts[1]) if parts[1] else 0
                change_pct = float(parts[2]) if parts[2] else 0
                return {
                    "price": current_price,
                    "change_pct": round(change_pct, 2),
                    "name": name,
                    "source": "sina_us",
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
    except Exception as e:
        logger.debug(f"新浪美股获取 {ticker} 失败: {e}")
    return None


def fetch_hk_stock_price_batch(codes: List[Dict]) -> Dict[str, Dict]:
    """批量获取港股行情 - 优先新浪财经（更稳定），回退yfinance"""
    results = {}
    hk_stocks = [c for c in codes if c["market"] == "港股"]

    for c in hk_stocks:
        key = f"{c['code']}.HK"
        result = None

        # 优先新浪财经（国内用户更快更稳定）
        if HAS_REQUESTS:
            result = fetch_hk_stock_price_sina(c["code"])

        # 回退 yfinance
        if not result and HAS_YFINANCE:
            result = fetch_yfinance_with_retry(f"{c['code']}.HK")

        if result:
            results[key] = {
                "ticker": c["code"],
                "exchange": "HK",
                "name": result.get("name", c["code"]),
                "price": result["price"],
                "change_pct": result["change_pct"],
                "source": result["source"],
                "time": result["time"],
            }

    return results


def fetch_us_stock_price_direct(ticker: str) -> Optional[Dict]:
    """通过 Yahoo Finance 直连API获取美股行情（绕开yfinance库的限流）"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=2d&interval=1d"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            chart = data.get("chart", {}).get("result", [])
            if chart:
                result = chart[0]
                meta = result.get("meta", {})
                price = meta.get("regularMarketPrice", 0)
                prev_close = meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0)
                quotes = result.get("indicators", {}).get("quote", [{}])[0]
                if price == 0 and quotes.get("close"):
                    closes = [c for c in quotes["close"] if c]
                    price = closes[-1] if closes else 0
                change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                return {
                    "price": round(price, 2),
                    "change_pct": round(change_pct, 2),
                    "name": ticker,
                    "source": "yahoo_direct",
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
    except Exception as e:
        logger.debug(f"Yahoo直连获取 {ticker} 失败: {e}")
    return None


def fetch_us_stock_price_batch(codes: List[Dict]) -> Dict[str, Dict]:
    """批量获取美股行情 - 优先新浪财经，回退Yahoo直连/yfinance"""
    results = {}
    us_stocks = [c for c in codes if c["market"] == "美股"]

    for c in us_stocks:
        result = None

        # 方案1: 新浪财经美股（国内可用）
        if HAS_REQUESTS:
            result = fetch_us_stock_price_sina(c["code"])
            time.sleep(0.3)

        # 方案2: Yahoo直连API
        if not result and HAS_REQUESTS:
            result = fetch_us_stock_price_direct(c["code"])
            time.sleep(1)

        # 方案3: yfinance
        if not result and HAS_YFINANCE:
            result = fetch_yfinance_with_retry(c["code"])

        if result:
            results[c["code"]] = {
                "ticker": c["code"],
                "exchange": "US",
                "name": result.get("name", c["code"]),
                "price": result["price"],
                "change_pct": result["change_pct"],
                "source": result["source"],
                "time": result["time"],
            }

    return results


# ========== 统一入口 ==========

def fetch_all_prices(codes: List[Dict]) -> Dict[str, Dict]:
    """
    统一获取所有持仓的实时行情
    """
    results = {}
    logger.info(f"开始获取 {len(codes)} 只股票行情...")

    # A股 - 批量获取
    a_results = fetch_a_share_price_batch(codes)
    results.update(a_results)
    logger.info(f"A股获取完成: {len(a_results)} 只")

    # 港股 - 逐个获取
    hk_results = fetch_hk_stock_price_batch(codes)
    results.update(hk_results)
    logger.info(f"港股获取完成: {len(hk_results)} 只")

    # 美股 - 逐个获取
    us_results = fetch_us_stock_price_batch(codes)
    results.update(us_results)
    logger.info(f"美股获取完成: {len(us_results)} 只")

    logger.info(f"总计获取: {len(results)}/{len(codes)} 只")
    return results


# ========== 汇率获取 ==========

def fetch_fx_rates() -> Dict[str, float]:
    """获取最新汇率，含多源回退"""
    rates = {"USDCNY": 7.25, "HKDCNY": 0.93}

    # 新浪财经 USD/CNY
    if HAS_REQUESTS:
        try:
            url = "https://hq.sinajs.cn/list=fx_susdcny"
            headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.text and '"' in resp.text:
                data = resp.text.split('"')[1]
                parts = data.split(",")
                if len(parts) > 1 and parts[1]:
                    rates["USDCNY"] = float(parts[1])
        except:
            pass

        try:
            url = "https://hq.sinajs.cn/list=fx_shkdcny"
            headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.text and '"' in resp.text:
                data = resp.text.split('"')[1]
                parts = data.split(",")
                if len(parts) > 1 and parts[1]:
                    rates["HKDCNY"] = float(parts[1])
        except:
            pass

    logger.info(f"汇率: USD/CNY={rates['USDCNY']}, HKD/CNY={rates['HKDCNY']}")
    return rates


# ========== 历史数据获取 ==========

def fetch_hist_price(ticker: str, exchange: str, days: int = 60) -> List[Dict]:
    """获取历史日线数据"""
    results = []

    if exchange in ("US", "HK"):
        yf_ticker = ticker if exchange == "US" else f"{ticker}.HK"
        if HAS_YFINANCE:
            try:
                time.sleep(2)
                t = yf.Ticker(yf_ticker)
                hist = t.history(period=f"{days}d")
                for date_idx, row in hist.iterrows():
                    results.append({
                        "date": date_idx.strftime("%Y-%m-%d"),
                        "price": round(float(row["Close"]), 2),
                        "open": round(float(row["Open"]), 2),
                        "high": round(float(row["High"]), 2),
                        "low": round(float(row["Low"]), 2),
                        "volume": int(row["Volume"]),
                    })
            except Exception as e:
                logger.warning(f"获取 {yf_ticker} 历史数据失败: {e}")
    else:
        if HAS_AKSHARE:
            try:
                end_date = datetime.now().strftime("%Y%m%d")
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
                df = ak.stock_zh_a_hist(symbol=ticker, period="daily",
                                        start_date=start_date, end_date=end_date, adjust="qfq")
                if not df.empty:
                    for _, row in df.iterrows():
                        results.append({
                            "date": str(row["日期"]),
                            "price": round(float(row["收盘"]), 2),
                            "open": round(float(row["开盘"]), 2),
                            "high": round(float(row["最高"]), 2),
                            "low": round(float(row["最低"]), 2),
                            "volume": int(row["成交量"]),
                        })
            except Exception as e:
                logger.warning(f"获取A股 {ticker} 历史数据失败: {e}")

    return results


def fetch_all_hist_prices(manager, days: int = 60) -> Dict[str, List[Dict]]:
    """批量获取所有持仓历史数据"""
    results = {}
    for h in manager.holdings:
        hist = fetch_hist_price(h.ticker, h.exchange, days)
        if hist:
            key = f"{h.ticker}.{h.exchange}" if h.exchange != "US" else h.ticker
            results[key] = hist
        time.sleep(1)
    return results


# ========== 测试 ==========

if __name__ == "__main__":
    test_codes = [
        {"ticker": "000858.SZ", "market": "A股", "code": "000858", "exchange": "SZ"},
        {"ticker": "600519.SH", "market": "A股", "code": "600519", "exchange": "SH"},
        {"ticker": "0700.HK", "market": "港股", "code": "0700", "exchange": "HK"},
        {"ticker": "AAPL", "market": "美股", "code": "AAPL", "exchange": "US"},
    ]
    prices = fetch_all_prices(test_codes)
    print(json.dumps(prices, ensure_ascii=False, indent=2))
    rates = fetch_fx_rates()
    print(f"汇率: {rates}")