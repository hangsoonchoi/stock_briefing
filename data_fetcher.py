"""
시장 데이터 수집 모듈
- yfinance: 시장 지표, 종목 가격/거래량/히스토리, 애널리스트 의견
- RSS: 뉴스 (보조용 — 재시도 + dedup)
- technicals: 종목별 기술적 지표

이전 버전 대비 개선:
- 모든 외부 호출에 retry
- 뉴스 dedup (제목 유사도)
- 환경변수/데이터 freshness 검증
- 한국/미국 종목 구분해서 history 길이 다르게
- print 대신 logger
"""

import re
import time
from datetime import datetime, timedelta
from typing import Dict, List

import feedparser
import pandas as pd
import yfinance as yf

from config import (
    MARKET_INDICATORS,
    NEWS_FEEDS,
    MAX_ARTICLES_PER_FEED,
    WATCHLIST,
    SECTOR_ETFS_US,
    SECTOR_ETFS_KR,
)
from utils import logger, retry
import technicals


@retry(max_attempts=2, base_delay=0.8)
def _yf_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    return yf.Ticker(ticker).history(period=period, interval=interval)


def fetch_market_indicators() -> List[Dict]:
    """주요 시장 지표 — 어제(또는 최근 거래일) 종가/변동률."""
    results = []
    for ticker, name in MARKET_INDICATORS.items():
        try:
            hist = _yf_history(ticker, period="10d", interval="1d")
            if hist.empty or len(hist) < 2:
                continue
            last, prev = hist.iloc[-1], hist.iloc[-2]
            change_pct = (last["Close"] - prev["Close"]) / prev["Close"] * 100

            # freshness 체크 — 7일 이상 묵으면 경고
            stale_days = (datetime.now().date() - last.name.date()).days
            if stale_days > 7:
                logger.warning(f"{ticker} 데이터 {stale_days}일 묵음 — yfinance 차단 가능성")

            results.append({
                "ticker": ticker,
                "name": name,
                "close": round(float(last["Close"]), 2),
                "change_pct": round(float(change_pct), 2),
                "date": str(last.name.date()),
                "stale_days": stale_days,
            })
        except Exception as e:
            logger.warning(f"지표 {ticker} 수집 실패: {e}")
        time.sleep(0.15)
    return results


def fetch_sector_performance() -> List[Dict]:
    """섹터 ETF 1일/5일/20일 수익률 — 자금 흐름 추적."""
    results = []
    all_etfs = {**SECTOR_ETFS_US, **SECTOR_ETFS_KR}
    for ticker, name in all_etfs.items():
        try:
            hist = _yf_history(ticker, period="3mo", interval="1d")
            if hist.empty or len(hist) < 25:
                continue
            close = hist["Close"]
            last = float(close.iloc[-1])
            r1d = (close.iloc[-1] / close.iloc[-2] - 1) * 100 if len(close) >= 2 else None
            r5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) >= 6 else None
            r20d = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) >= 21 else None
            results.append({
                "ticker": ticker,
                "name": name,
                "close": round(last, 2),
                "ret_1d": round(r1d, 2) if r1d is not None else None,
                "ret_5d": round(r5d, 2) if r5d is not None else None,
                "ret_20d": round(r20d, 2) if r20d is not None else None,
            })
        except Exception as e:
            logger.warning(f"섹터 {ticker} 수집 실패: {e}")
        time.sleep(0.15)

    # 1일 수익률 기준 정렬
    results.sort(key=lambda x: (x.get("ret_1d") or -999), reverse=True)
    return results


def fetch_watchlist_data() -> List[Dict]:
    """관심 종목 가격/변동/거래량/기술지표/애널리스트/펀더멘털/어닝."""
    results = []
    for market, stocks in WATCHLIST.items():
        for ticker, name in stocks.items():
            try:
                tk = yf.Ticker(ticker)
                hist = _yf_history(ticker, period="1y", interval="1d")
                if hist.empty or len(hist) < 5:
                    continue

                last, prev = hist.iloc[-1], hist.iloc[-2]
                change_pct = (last["Close"] - prev["Close"]) / prev["Close"] * 100

                avg_vol = hist["Volume"].tail(30).mean()
                vol_ratio = float(last["Volume"]) / avg_vol if avg_vol else 1.0

                yr_low = float(hist["Low"].tail(252).min())
                yr_high = float(hist["High"].tail(252).max())
                yr_position = (last["Close"] - yr_low) / (yr_high - yr_low + 1e-9)

                tech = technicals.analyze(hist)

                # 애널리스트
                analyst_summary = None
                try:
                    rec = tk.recommendations
                    if rec is not None and not rec.empty:
                        analyst_summary = rec.tail(5).to_dict(orient="records")
                except Exception:
                    pass

                # 펀더멘털 (yfinance.info)
                fundamentals = {}
                try:
                    info = tk.info or {}
                    fundamentals = {
                        "market_cap": info.get("marketCap"),
                        "trailing_pe": info.get("trailingPE"),  # PER
                        "forward_pe": info.get("forwardPE"),
                        "price_to_book": info.get("priceToBook"),  # PBR
                        "return_on_equity": info.get("returnOnEquity"),  # ROE
                        "debt_to_equity": info.get("debtToEquity"),
                        "profit_margins": info.get("profitMargins"),
                        "revenue_growth": info.get("revenueGrowth"),
                        "earnings_growth": info.get("earningsGrowth"),
                        "dividend_yield": info.get("dividendYield"),
                        "beta": info.get("beta"),
                        "short_ratio": info.get("shortRatio"),
                        "short_percent_of_float": info.get("shortPercentOfFloat"),
                    }
                except Exception:
                    pass

                # 어닝 캘린더
                earnings_date = None
                try:
                    cal = tk.calendar
                    if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
                        if isinstance(cal, dict):
                            ed = cal.get("Earnings Date")
                            if ed and isinstance(ed, list) and len(ed) > 0:
                                earnings_date = str(ed[0])
                        elif hasattr(cal, 'iloc'):
                            try:
                                earnings_date = str(cal.iloc[0, 0])
                            except Exception:
                                pass
                except Exception:
                    pass

                results.append({
                    "market": market,
                    "ticker": ticker,
                    "name": name,
                    "close": round(float(last["Close"]), 2),
                    "change_pct": round(float(change_pct), 2),
                    "volume": int(last["Volume"]),
                    "vol_vs_avg": round(vol_ratio, 2),
                    "year_position": round(float(yr_position), 2),
                    "year_high": round(yr_high, 2),
                    "year_low": round(yr_low, 2),
                    "technicals": tech,
                    "analyst": analyst_summary,
                    "fundamentals": fundamentals,
                    "next_earnings": earnings_date,
                })
            except Exception as e:
                logger.warning(f"종목 {ticker} ({name}) 수집 실패: {e}")
            time.sleep(0.2)
    return results


def _normalize_title(t: str) -> str:
    """뉴스 제목 정규화 — dedup용 (공백·기호 제거, 소문자)."""
    t = re.sub(r"[^\w가-힣\s]", "", t.lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fetch_news() -> List[Dict]:
    """RSS 뉴스 — 24시간 이내 + dedup."""
    cutoff = datetime.now() - timedelta(hours=24)
    seen_titles = set()
    all_articles = []

    for source_name, url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if count >= MAX_ARTICLES_PER_FEED:
                    break
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if published:
                    pub_dt = datetime(*published[:6])
                    if pub_dt < cutoff:
                        continue
                title = entry.get("title", "").strip()
                if not title:
                    continue

                # dedup
                norm = _normalize_title(title)
                if norm in seen_titles:
                    continue
                seen_titles.add(norm)

                summary = entry.get("summary", "").strip()
                if "<" in summary:
                    summary = re.sub(r"<[^>]+>", "", summary)
                summary = summary[:300]

                all_articles.append({
                    "source": source_name,
                    "title": title,
                    "summary": summary,
                    "link": entry.get("link", ""),
                })
                count += 1
        except Exception as e:
            logger.warning(f"뉴스 피드 {source_name} 수집 실패: {e}")

    return all_articles


def _gnews_search(query: str, hl: str = "en", gl: str = "US", limit: int = 6,
                  hours_back: int = 72) -> List[Dict]:
    """Google News RSS 검색 헬퍼. 출처 분리해서 정리."""
    from urllib.parse import quote
    cutoff = datetime.now() - timedelta(hours=hours_back)
    # 검색어에 공백/한글 등 들어갈 수 있으니 URL 인코딩 필수
    q_enc = quote(query)
    url = f"https://news.google.com/rss/search?q={q_enc}&hl={hl}&gl={gl}&ceid={gl}:{hl}"
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        logger.warning(f"GNews 실패 {query}: {e}")
        return []

    out = []
    for entry in feed.entries[:limit * 2]:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            pub_dt = datetime(*published[:6])
            if pub_dt < cutoff:
                continue
        title = (entry.get("title", "") or "").strip()
        if not title:
            continue
        src = ""
        if " - " in title:
            parts = title.rsplit(" - ", 1)
            title = parts[0].strip()
            src = parts[1].strip()
        out.append({
            "title": title,
            "source": src or "Google News",
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
        })
        if len(out) >= limit:
            break
    return out


def fetch_korean_stock_news_per_ticker() -> Dict[str, Dict]:
    """한국 watchlist 종목별 한국어 뉴스 (노동/정치/사회 이슈 포함)."""
    results = {}
    kr_stocks = WATCHLIST.get("한국", {})
    for ticker, name in kr_stocks.items():
        try:
            articles = _gnews_search(name, hl="ko", gl="KR", limit=5, hours_back=72)
            if articles:
                results[ticker] = {"name": name, "articles": articles}
        except Exception as e:
            logger.warning(f"종목별 뉴스(KR) {name} 실패: {e}")
        time.sleep(0.3)
    return results


def fetch_us_stock_news_per_ticker() -> Dict[str, Dict]:
    """미국 watchlist 종목별 영어 뉴스."""
    results = {}
    us_stocks = WATCHLIST.get("미국", {})
    for ticker, name in us_stocks.items():
        try:
            # 회사명으로 검색 (티커는 공통 단어 많음)
            articles = _gnews_search(name, hl="en", gl="US", limit=5, hours_back=72)
            if articles:
                results[ticker] = {"name": name, "articles": articles}
        except Exception as e:
            logger.warning(f"종목별 뉴스(US) {name} 실패: {e}")
        time.sleep(0.3)
    return results


def fetch_global_theme_news() -> List[Dict]:
    """거시·테마·지정학 이슈 키워드 검색."""
    try:
        from config import GLOBAL_NEWS_QUERIES
    except ImportError:
        return []

    out = []
    for query, hl, gl in GLOBAL_NEWS_QUERIES:
        try:
            articles = _gnews_search(query, hl=hl, gl=gl, limit=3, hours_back=48)
            for a in articles:
                a["theme"] = query
                out.append(a)
        except Exception as e:
            logger.warning(f"테마 뉴스 {query} 실패: {e}")
        time.sleep(0.3)
    return out


def fetch_all_data(quick: bool = False) -> Dict:
    """
    모든 시장 데이터 수집.
    quick=True: 단타 모드 — 빠른 핵심만 (15초 내). 종목별 뉴스/테마 뉴스 SKIP.
    quick=False: 풀 모드 — 전부.
    """
    logger.info("📊 시장 지표 수집 중...")
    indicators = fetch_market_indicators()

    sectors = []
    if not quick:
        logger.info("🏭 섹터 로테이션 수집 중...")
        sectors = fetch_sector_performance()

    logger.info("📈 관심 종목 + 기술지표 수집 중...")
    watchlist = fetch_watchlist_data()

    logger.info("📰 일반 RSS 뉴스 수집 중...")
    news = fetch_news()

    kr_stock_news = {}
    us_stock_news = {}
    theme_news = []

    if not quick:
        logger.info("🇰🇷 한국 종목별 뉴스 (노조·정치 이슈 포함)...")
        kr_stock_news = fetch_korean_stock_news_per_ticker()
        logger.info(f"  → {len(kr_stock_news)}종목 수집")

        logger.info("🇺🇸 미국 종목별 뉴스...")
        us_stock_news = fetch_us_stock_news_per_ticker()
        logger.info(f"  → {len(us_stock_news)}종목 수집")

        logger.info("🌍 세계 거시·테마 뉴스 (Fed, 중국, 지정학, AI, EV 등)...")
        theme_news = fetch_global_theme_news()
        logger.info(f"  → {len(theme_news)}건 수집")
    else:
        logger.info("⚡ 단타 모드: 종목별 뉴스/테마 뉴스 SKIP")

    return {
        "collected_at": datetime.now().isoformat(),
        "indicators": indicators,
        "sectors": sectors,
        "watchlist": watchlist,
        "news": news,
        "kr_stock_news": kr_stock_news,
        "us_stock_news": us_stock_news,
        "theme_news": theme_news,
    }


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    from utils import setup_logging
    setup_logging()
    data = fetch_all_data()
    logger.info(
        f"수집 완료 — 지표 {len(data['indicators'])} / 섹터 {len(data['sectors'])} / "
        f"종목 {len(data['watchlist'])} / 뉴스 {len(data['news'])}"
    )
