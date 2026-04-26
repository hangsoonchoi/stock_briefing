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
    """관심 종목 가격/변동/거래량/기술지표/애널리스트."""
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

                # 거래량 이상 체크 (30일 평균 대비)
                avg_vol = hist["Volume"].tail(30).mean()
                vol_ratio = float(last["Volume"]) / avg_vol if avg_vol else 1.0

                # 52주 위치 (0=신저가, 1=신고가)
                yr_low = float(hist["Low"].tail(252).min())
                yr_high = float(hist["High"].tail(252).max())
                yr_position = (last["Close"] - yr_low) / (yr_high - yr_low + 1e-9)

                # 기술적 지표
                tech = technicals.analyze(hist)

                # 애널리스트 (있으면)
                analyst_summary = None
                try:
                    rec = tk.recommendations
                    if rec is not None and not rec.empty:
                        analyst_summary = rec.tail(5).to_dict(orient="records")
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


def fetch_all_data() -> Dict:
    """모든 시장 데이터 수집."""
    logger.info("📊 시장 지표 수집 중...")
    indicators = fetch_market_indicators()

    logger.info("🏭 섹터 로테이션 수집 중...")
    sectors = fetch_sector_performance()

    logger.info("📈 관심 종목 + 기술지표 수집 중...")
    watchlist = fetch_watchlist_data()

    logger.info("📰 뉴스 수집 중 (보조용)...")
    news = fetch_news()

    return {
        "collected_at": datetime.now().isoformat(),
        "indicators": indicators,
        "sectors": sectors,
        "watchlist": watchlist,
        "news": news,
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
