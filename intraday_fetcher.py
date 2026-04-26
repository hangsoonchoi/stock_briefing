"""
단타 모드용 — 빠르게 변하는 데이터 위주
- 관심종목 5분봉 (최근 1시간 흐름)
- 거래량 폭증 종목
- 장중 급등/급락 종목 (top movers)
- 한국 외국인 순매수 (장중 갱신)
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd
import yfinance as yf

from config import WATCHLIST
from utils import logger, retry


@retry(max_attempts=2, base_delay=0.5)
def _yf_intraday(ticker: str, period: str = "1d", interval: str = "5m") -> pd.DataFrame:
    return yf.Ticker(ticker).history(period=period, interval=interval)


def fetch_watchlist_intraday() -> List[Dict]:
    """관심종목 — 오늘 5분봉 흐름. 최근 1시간 변동, 거래량 비율, 장중 위치."""
    out = []
    for market, stocks in WATCHLIST.items():
        for ticker, name in stocks.items():
            try:
                hist = _yf_intraday(ticker, period="1d", interval="5m")
                if hist is None or hist.empty or len(hist) < 6:
                    # 5분봉 안 잡히면 일봉으로 fallback
                    daily = _yf_intraday(ticker, period="2d", interval="1d")
                    if daily is None or daily.empty:
                        continue
                    last = daily.iloc[-1]
                    out.append({
                        "market": market, "ticker": ticker, "name": name,
                        "last_price": round(float(last["Close"]), 2),
                        "intraday_pct": None,
                        "hour_pct": None,
                        "volume": int(last["Volume"]),
                        "note": "5분봉 안 잡힘 (장 휴장이거나 데이터 지연)",
                    })
                    continue

                first_close = float(hist["Close"].iloc[0])
                last_close = float(hist["Close"].iloc[-1])
                intraday_pct = (last_close - first_close) / first_close * 100

                # 최근 1시간 (12개 봉)
                hour_ago_idx = max(0, len(hist) - 12)
                hour_ago_close = float(hist["Close"].iloc[hour_ago_idx])
                hour_pct = (last_close - hour_ago_close) / hour_ago_close * 100

                # 오늘 누적 거래량 vs 평균(20일)
                today_vol = int(hist["Volume"].sum())
                try:
                    daily = _yf_intraday(ticker, period="1mo", interval="1d")
                    avg_vol = float(daily["Volume"].tail(20).mean()) if not daily.empty else 0
                except Exception:
                    avg_vol = 0
                vol_ratio = today_vol / avg_vol if avg_vol > 0 else None

                out.append({
                    "market": market, "ticker": ticker, "name": name,
                    "last_price": round(last_close, 2),
                    "intraday_pct": round(intraday_pct, 2),
                    "hour_pct": round(hour_pct, 2),
                    "volume": today_vol,
                    "vol_vs_avg": round(vol_ratio, 2) if vol_ratio else None,
                    "high_today": round(float(hist["High"].max()), 2),
                    "low_today": round(float(hist["Low"].min()), 2),
                })
            except Exception as e:
                logger.warning(f"intraday {ticker} 실패: {e}")
            time.sleep(0.15)
    return out


# 기본 모니터링 종목군 — 한국 시총 상위 + 미국 거래량 많은 거
# (단타 후보 발굴용 — watchlist 외)
DAY_TRADE_UNIVERSE_KR = [
    "005930.KS",  # 삼성전자
    "000660.KS",  # SK하이닉스
    "373220.KS",  # LG에너지솔루션
    "207940.KS",  # 삼성바이오로직스
    "005490.KS",  # POSCO홀딩스
    "035420.KS",  # NAVER
    "035720.KS",  # 카카오
    "051910.KS",  # LG화학
    "068270.KS",  # 셀트리온
    "323410.KS",  # 카카오뱅크
    "005380.KS",  # 현대차
    "012330.KS",  # 현대모비스
    "028260.KS",  # 삼성물산
    "066570.KS",  # LG전자
    "003670.KS",  # 포스코퓨처엠
    # 코스닥 활발
    "247540.KQ",  # 에코프로비엠
    "086520.KQ",  # 에코프로
    "091990.KQ",  # 셀트리온헬스케어
    "196170.KQ",  # 알테오젠
    "112040.KQ",  # 위메이드
    "418550.KQ",  # 제이오
    "058470.KQ",  # 리노공업
    "041510.KQ",  # SM
    "078340.KQ",  # 컴투스
    "035900.KQ",  # JYP Ent.
    "263750.KQ",  # 펄어비스
]

DAY_TRADE_UNIVERSE_US = [
    "NVDA", "TSLA", "AAPL", "MSFT", "META", "AMZN", "GOOGL", "AMD",
    "AVGO", "NFLX", "PLTR", "SOFI", "RIVN", "LCID", "COIN", "MSTR",
    "MARA", "RIOT", "ARM", "SMCI", "CRWD", "SNOW", "CRWV", "DELL",
    "AAL", "BAC", "WFC", "JPM", "GS", "BA",
]


def fetch_top_movers(min_change_pct: float = 3.0, top_n: int = 15) -> Dict:
    """
    거래량 폭증 + 장중 급등/급락 종목 발굴.
    한국 시총 상위 + 코스닥 활발 + 미국 거래량 상위 대상으로 스캔.
    """
    movers = {"kr_gainers": [], "kr_losers": [], "us_gainers": [], "us_losers": [],
              "kr_volume_spike": [], "us_volume_spike": []}

    def _scan(tickers: List[str], market_key: str):
        for tk in tickers:
            try:
                # 5분봉 1일치 + 일봉 1달치 (거래량 평균용)
                intra = _yf_intraday(tk, period="1d", interval="5m")
                if intra is None or intra.empty or len(intra) < 6:
                    continue
                first_close = float(intra["Close"].iloc[0])
                last_close = float(intra["Close"].iloc[-1])
                pct = (last_close - first_close) / first_close * 100
                today_vol = int(intra["Volume"].sum())

                daily = _yf_intraday(tk, period="1mo", interval="1d")
                avg_vol = float(daily["Volume"].tail(20).mean()) if not daily.empty else 0
                vol_ratio = today_vol / avg_vol if avg_vol > 0 else None

                rec = {
                    "ticker": tk,
                    "last_price": round(last_close, 2),
                    "intraday_pct": round(pct, 2),
                    "vol_vs_avg": round(vol_ratio, 2) if vol_ratio else None,
                    "today_volume": today_vol,
                }

                # 분류
                if pct >= min_change_pct:
                    movers[f"{market_key}_gainers"].append(rec)
                elif pct <= -min_change_pct:
                    movers[f"{market_key}_losers"].append(rec)
                if vol_ratio and vol_ratio >= 3.0:
                    movers[f"{market_key}_volume_spike"].append(rec)
            except Exception as e:
                logger.debug(f"top_movers {tk}: {e}")
            time.sleep(0.1)

    logger.info("  단타 발굴: 한국 종목 스캔 중...")
    _scan(DAY_TRADE_UNIVERSE_KR, "kr")
    logger.info("  단타 발굴: 미국 종목 스캔 중...")
    _scan(DAY_TRADE_UNIVERSE_US, "us")

    # 정렬
    for k in ("kr_gainers", "us_gainers"):
        movers[k].sort(key=lambda x: x["intraday_pct"], reverse=True)
        movers[k] = movers[k][:top_n]
    for k in ("kr_losers", "us_losers"):
        movers[k].sort(key=lambda x: x["intraday_pct"])
        movers[k] = movers[k][:top_n]
    for k in ("kr_volume_spike", "us_volume_spike"):
        movers[k].sort(key=lambda x: (x["vol_vs_avg"] or 0), reverse=True)
        movers[k] = movers[k][:top_n]

    return movers


def fetch_quick_data() -> Dict:
    """단타 모드 데이터 수집 — 빠른 것만."""
    logger.info("⚡ 단타 모드 데이터 수집 시작")

    intraday_watchlist = fetch_watchlist_intraday()
    logger.info(f"  ✓ 관심종목 5분봉: {len(intraday_watchlist)}개")

    movers = fetch_top_movers()
    logger.info(
        f"  ✓ 톱 무버: 한국 상승 {len(movers['kr_gainers'])} / 하락 {len(movers['kr_losers'])} / "
        f"거래량 폭증 {len(movers['kr_volume_spike'])}, 미국 상승 {len(movers['us_gainers'])} / "
        f"하락 {len(movers['us_losers'])} / 거래량 폭증 {len(movers['us_volume_spike'])}"
    )

    return {
        "collected_at": datetime.now().isoformat(),
        "intraday_watchlist": intraday_watchlist,
        "top_movers": movers,
    }


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    from utils import setup_logging
    setup_logging()
    data = fetch_quick_data()
    import json
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str)[:3000])
