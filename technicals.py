"""
기술적 지표 계산
- RSI: 과매수/과매도
- 이동평균선: 골든/데드 크로스
- MACD: 추세 전환
- 볼린저밴드: 변동성 / 평균 회귀
- ATR: 손절 폭 산정용

대단한 알파는 아니지만, 매수 타이밍의 기본 가드레일.
"""

from typing import Dict, Optional

import numpy as np
import pandas as pd

from config import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    MA_SHORT, MA_MID, MA_LONG,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD,
    ATR_PERIOD,
)


def rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series) -> pd.DataFrame:
    ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger(close: pd.Series) -> pd.DataFrame:
    mid = close.rolling(BB_PERIOD).mean()
    std = close.rolling(BB_PERIOD).std()
    return pd.DataFrame({
        "mid": mid,
        "upper": mid + BB_STD * std,
        "lower": mid - BB_STD * std,
    })


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = ATR_PERIOD) -> pd.Series:
    prev_close = close.shift()
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def analyze(history: pd.DataFrame) -> Optional[Dict]:
    """
    history: yfinance hist (Open/High/Low/Close/Volume)
    반환: 현재 기술적 상태 + 라벨 + 매수 가드레일
    """
    if history is None or history.empty or len(history) < MA_LONG + 5:
        # 200일선이 안 잡히면 핵심 라벨이 비어버림. 짧은 데이터는 스킵.
        return None

    close = history["Close"]
    high = history["High"]
    low = history["Low"]

    last_close = float(close.iloc[-1])
    rsi_val = float(rsi(close).iloc[-1])
    ma20 = float(close.rolling(MA_SHORT).mean().iloc[-1])
    ma60 = float(close.rolling(MA_MID).mean().iloc[-1])
    ma200 = float(close.rolling(MA_LONG).mean().iloc[-1])

    macd_df = macd(close)
    macd_last = float(macd_df["macd"].iloc[-1])
    macd_sig = float(macd_df["signal"].iloc[-1])
    macd_hist_now = float(macd_df["hist"].iloc[-1])
    macd_hist_prev = float(macd_df["hist"].iloc[-2])

    bb = bollinger(close)
    bb_pos = (last_close - float(bb["lower"].iloc[-1])) / (
        float(bb["upper"].iloc[-1]) - float(bb["lower"].iloc[-1]) + 1e-9
    )  # 0=하단, 1=상단

    atr_val = float(atr(high, low, close).iloc[-1])

    # 라벨링
    labels = []
    if rsi_val >= RSI_OVERBOUGHT:
        labels.append(f"과매수 (RSI {rsi_val:.0f})")
    elif rsi_val <= RSI_OVERSOLD:
        labels.append(f"과매도 (RSI {rsi_val:.0f})")

    # 추세 (200일선 대비)
    if last_close > ma200:
        labels.append("장기 상승 추세")
    else:
        labels.append("장기 하락 추세")

    # 단기/중기 크로스
    ma20_prev = float(close.rolling(MA_SHORT).mean().iloc[-2])
    ma60_prev = float(close.rolling(MA_MID).mean().iloc[-2])
    if ma20_prev < ma60_prev and ma20 > ma60:
        labels.append("골든크로스 (20>60일선 돌파)")
    elif ma20_prev > ma60_prev and ma20 < ma60:
        labels.append("데드크로스 (20<60일선 하향)")

    # MACD 전환
    if macd_hist_prev < 0 < macd_hist_now:
        labels.append("MACD 매수 전환")
    elif macd_hist_prev > 0 > macd_hist_now:
        labels.append("MACD 매도 전환")

    # 볼린저
    if bb_pos > 1.0:
        labels.append("볼린저 상단 돌파")
    elif bb_pos < 0.0:
        labels.append("볼린저 하단 이탈")

    return {
        "last_close": last_close,
        "rsi": round(rsi_val, 1),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "ma200": round(ma200, 2),
        "macd": round(macd_last, 4),
        "macd_signal": round(macd_sig, 4),
        "macd_hist": round(macd_hist_now, 4),
        "bb_position": round(bb_pos, 2),
        "atr": round(atr_val, 2),
        "atr_pct_of_price": round(atr_val / last_close * 100, 2),
        "labels": labels,
    }
