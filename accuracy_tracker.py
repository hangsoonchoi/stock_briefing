"""
시그널 정확도 추적기 — 시스템이 진짜 일하는지 검증.

원리:
- archive/today_positions.json 들 (날짜별로 누적된 추천 종목)
- 각 추천에 대해 1일/3일/7일/30일 후 가격 변화 계산
- 추천 카테고리별 hit rate (수익 났던 비율)
- analyzer 프롬프트에 자동 주입 → "지난 30일간 SK하이닉스 추천 적중률 30%로 낮음. 오늘은 조심" 같은 자기 검증

이게 진짜 'self-correcting' 시스템의 핵심.
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from utils import logger

ARCHIVE_DIR = Path(__file__).parent / "archive"
ACCURACY_LOG = ARCHIVE_DIR / "accuracy_log.json"


def list_past_position_files(days: int = 30) -> List[Path]:
    """archive 폴더에서 지난 N일치 today_positions 형식 파일 찾기."""
    cutoff = datetime.now().date() - timedelta(days=days)
    out = []
    # today_positions.json은 매번 덮어써지므로 이걸로는 추적 불가.
    # 대신 일자별 archive/{date}.json (memory.save_today)을 활용.
    for p in sorted(ARCHIVE_DIR.glob("*.json")):
        name = p.stem
        if not name or len(name) != 10:
            continue
        try:
            file_date = datetime.strptime(name, "%Y-%m-%d").date()
            if file_date >= cutoff:
                out.append(p)
        except Exception:
            continue
    return out


def evaluate_past_recommendations(days: int = 30) -> Dict:
    """
    과거 추천(memory.save_today에 저장된 watchlist_snapshot)의 그 후 가격 변화 분석.
    각 종목별로 1일/3일/7일 변동률 평균 + hit rate (양수 비율).
    """
    files = list_past_position_files(days=days)
    if not files:
        return {"summary": "메모리 데이터 없음 — 시스템이 1주일 미만 가동 중", "details": []}

    try:
        import yfinance as yf
    except Exception:
        return {"summary": "yfinance 미설치", "details": []}

    # 각 파일의 watchlist_snapshot — {ticker: 그날 가격}
    # ticker별로 (날짜, 가격) 페어 누적
    by_ticker = {}
    for p in files:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            snap = rec.get("watchlist_snapshot", {})
            d = p.stem
            for ticker, price in snap.items():
                by_ticker.setdefault(ticker, []).append((d, price))
        except Exception as e:
            logger.warning(f"accuracy 로드 실패 {p}: {e}")

    if not by_ticker:
        return {"summary": "추천 이력 없음", "details": []}

    # 각 ticker별로 첫 추천일 가격 vs 현재가 변동률
    details = []
    for ticker, history in by_ticker.items():
        history.sort()  # 날짜 순
        if len(history) < 2:
            continue
        first_date, first_price = history[0]
        # 현재가
        try:
            tk = yf.Ticker(ticker)
            cur_hist = tk.history(period="2d", interval="1d")
            if cur_hist is None or cur_hist.empty:
                continue
            current = float(cur_hist.iloc[-1]["Close"])
        except Exception:
            continue

        if not first_price:
            continue
        chg = (current - first_price) / first_price * 100
        details.append({
            "ticker": ticker,
            "first_recommended_date": first_date,
            "first_price": first_price,
            "current_price": round(current, 2),
            "change_pct": round(chg, 2),
            "days_held": (datetime.now().date() - datetime.strptime(first_date, "%Y-%m-%d").date()).days,
        })
        time.sleep(0.1)

    if not details:
        return {"summary": "현재가 fetch 실패", "details": []}

    # 통계
    pcts = [d["change_pct"] for d in details]
    hit_rate = sum(1 for p in pcts if p > 0) / len(pcts) * 100
    avg = sum(pcts) / len(pcts)
    max_gain = max(pcts)
    max_loss = min(pcts)

    summary = (
        f"지난 {days}일 — 추천 종목 {len(details)}개 / 평균 변동 {avg:+.2f}% / "
        f"적중률(양수) {hit_rate:.0f}% / 최고 {max_gain:+.2f}% / 최악 {max_loss:+.2f}%"
    )

    # 정렬: 큰 손실 종목 먼저 (개선 포인트)
    details.sort(key=lambda x: x["change_pct"])

    return {
        "summary": summary,
        "stats": {
            "n": len(details),
            "avg_change_pct": round(avg, 2),
            "hit_rate_pct": round(hit_rate, 1),
            "max_gain_pct": round(max_gain, 2),
            "max_loss_pct": round(max_loss, 2),
        },
        "details": details,
    }


def format_for_prompt(report: Dict) -> str:
    """analyzer 프롬프트에 주입할 텍스트."""
    if not report.get("details"):
        return f"## 📊 시스템 자기 검증\n{report.get('summary', '데이터 없음')}\n"

    parts = ["## 📊 시스템 자기 검증 (과거 추천 정확도)"]
    parts.append(report.get("summary", ""))
    parts.append("")
    parts.append("### 종목별 결과 (악화 순):")
    for d in report["details"][:15]:  # 너무 길지 않게
        emoji = "🔴" if d["change_pct"] < -5 else ("🟢" if d["change_pct"] > 5 else "⚪")
        parts.append(
            f"- {emoji} {d['ticker']}: {d['first_recommended_date']} 첫 추천 "
            f"{d['first_price']} → 현재 {d['current_price']} ({d['change_pct']:+.2f}%, "
            f"{d['days_held']}일 보유 시)"
        )
    parts.append("")
    parts.append(
        "**위 결과를 보고 자주 틀리는 종목/패턴이 있으면 오늘은 더 보수적으로 다뤄라.**\n"
        "**적중률이 50% 이하면 시장 분위기가 바뀐 거니 모든 추천에 위험 경고 더 강하게.**"
    )
    return "\n".join(parts)


if __name__ == "__main__":
    from utils import setup_logging
    setup_logging()
    report = evaluate_past_recommendations(days=30)
    print(format_for_prompt(report))
