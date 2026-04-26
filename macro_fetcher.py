"""
거시 경제 지표 수집 (FRED API)
Fed 금리, CPI, 실업률, 장단기 금리차 등.

뉴스보다 훨씬 빠른 시그널 — 발표 시점이 정해져 있고
대부분 retail은 의미를 놓침.
"""

import os
from datetime import datetime
from typing import Dict, List

from config import FRED_SERIES
from utils import logger, retry


@retry(max_attempts=3, base_delay=1.0)
def _fetch_one(fred, series_id: str):
    """한 시리즈의 최근 2개 값 + 발표일을 가져옴."""
    s = fred.get_series(series_id, observation_start="2024-01-01")
    s = s.dropna()
    if len(s) == 0:
        return None
    last_val = float(s.iloc[-1])
    last_date = s.index[-1].date().isoformat()
    prev_val = float(s.iloc[-2]) if len(s) >= 2 else None
    change = (last_val - prev_val) if prev_val is not None else None
    change_pct = ((last_val - prev_val) / prev_val * 100) if prev_val not in (None, 0) else None

    # 가장 최근 5개 추세
    trend = [float(v) for v in s.iloc[-5:].tolist()]

    return {
        "series_id": series_id,
        "last_value": round(last_val, 4),
        "last_date": last_date,
        "prev_value": round(prev_val, 4) if prev_val is not None else None,
        "change": round(change, 4) if change is not None else None,
        "change_pct": round(change_pct, 4) if change_pct is not None else None,
        "recent_trend": [round(v, 4) for v in trend],
    }


def fetch_macro_indicators() -> List[Dict]:
    """FRED에서 주요 거시 지표 수집. 키 없으면 빈 리스트."""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        logger.warning("FRED_API_KEY 없음 — 거시 지표 스킵")
        return []

    try:
        from fredapi import Fred
    except ImportError:
        logger.warning("fredapi 미설치 — pip install fredapi")
        return []

    fred = Fred(api_key=api_key)
    results = []

    for sid, name in FRED_SERIES.items():
        try:
            data = _fetch_one(fred, sid)
            if data is None:
                continue
            data["name"] = name
            results.append(data)
        except Exception as e:
            logger.warning(f"FRED {sid} ({name}) 수집 실패: {e}")

    logger.info(f"거시 지표 {len(results)}개 수집됨")
    return results


def get_yield_curve_status(macro: List[Dict]) -> Dict:
    """장단기 금리차 상태 — 침체 시그널 체크."""
    t10y2y = next((m for m in macro if m["series_id"] == "T10Y2Y"), None)
    t10y3m = next((m for m in macro if m["series_id"] == "T10Y3M"), None)

    status = {"signal": "정상", "detail": ""}
    if t10y2y:
        v = t10y2y["last_value"]
        if v < 0:
            status["signal"] = "역전 (10Y-2Y)"
            status["detail"] = f"10Y-2Y = {v:+.2f}%p (음수 = 침체 선행 시그널)"
        elif v < 0.3:
            status["signal"] = "축소"
            status["detail"] = f"10Y-2Y = {v:+.2f}%p (정상화 진행 중일 수 있음)"
        else:
            status["detail"] = f"10Y-2Y = {v:+.2f}%p"
    return status


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    from utils import setup_logging
    setup_logging()

    data = fetch_macro_indicators()
    for d in data:
        print(f"{d['name']:35} {d['last_value']:>10}  ({d['last_date']})")
    print("\n금리차 상태:", get_yield_curve_status(data))
