"""
진짜 메모리·패턴 학습 시스템.

기존 accuracy_tracker.py 한계:
- watchlist 전체 가격 변화만 추적 (실제 추천 종목 분리 X)
- 30일 단위 통계만 — 단기(1~3일) 성과는 안 봄
- 패턴별 분석 없음 (RSI 60-70 추천 적중률 vs RSI 70+ 적중률 같은 거)

이 모듈의 역할:
- 매번 추천 종목을 'archive/recommendations_log.jsonl' 에 누적 (덮어쓰기 X)
- 각 추천: ticker, 추천 시 가격, 카테고리, RSI, 52주 위치, 뉴스 수, 섹터, 시총
- 1일/3일/7일/30일 후 가격 자동 비교 → 수익률 계산
- 패턴별 그룹화 → RSI bucket / 시총 bucket / 카테고리 / 섹터별 적중률
- Claude 프롬프트에 주입: "RSI 60-70 추천 평균 +2.3%, RSI 70+ 평균 -4.5%"
"""

import json
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils import logger


ARCHIVE_DIR = Path(__file__).parent / "archive"
ARCHIVE_DIR.mkdir(exist_ok=True)
LOG_PATH = ARCHIVE_DIR / "recommendations_log.jsonl"


# =============================================================
# 1. 추천 시점 기록
# =============================================================

def log_recommendation(rec: Dict) -> None:
    """
    한 추천을 누적 로그에 append.

    rec 필수 필드:
    - date (str ISO)
    - ticker
    - name
    - price_at_rec (float)
    - category ("priority-1"/"priority-2"/"priority-3"/"intraday"/"discovery"/"avoid"/...)

    선택 필드:
    - rsi, year_position, news_count, reddit_score, sector, market_cap, change_pct, vol_vs_avg
    """
    if not rec.get("ticker") or not rec.get("price_at_rec"):
        return
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"recommendation 로그 실패: {e}")


def log_recommendations_batch(positions: List[Dict], rec_date: Optional[str] = None) -> int:
    """today_positions 형식 리스트 → 로그에 한꺼번에 기록."""
    if rec_date is None:
        rec_date = datetime.now().date().isoformat()

    written = 0
    seen = set()  # 같은 날짜+ticker 중복 방지

    # 기존 로그에서 이미 있는 (date, ticker) 수집
    if LOG_PATH.exists():
        try:
            for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                    seen.add((e.get("date"), e.get("ticker"), e.get("category")))
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"로그 사전 검색 실패: {e}")

    for p in positions:
        ticker = p.get("ticker")
        if not ticker:
            continue
        category = p.get("section") or p.get("category") or "unknown"
        if (rec_date, ticker, category) in seen:
            continue  # 중복

        rec = {
            "date": rec_date,
            "ticker": ticker,
            "name": p.get("name", ""),
            "price_at_rec": p.get("recommended_at") or p.get("price"),
            "category": category,
            "rsi": p.get("rsi"),
            "year_position": p.get("year_position"),
            "news_count": p.get("news_count"),
            "reddit_score": p.get("reddit_score"),
            "sector": p.get("sector"),
            "market_cap": p.get("market_cap"),
            "change_pct": p.get("change_pct"),
            "vol_vs_avg": p.get("vol_vs_avg"),
        }
        log_recommendation(rec)
        written += 1

    if written:
        logger.info(f"📊 추천 로그 누적: +{written}건 (총 {LOG_PATH.stat().st_size if LOG_PATH.exists() else 0} bytes)")
    return written


# =============================================================
# 2. 추천 종목 N일 후 가격 비교
# =============================================================

def _fetch_price_now(ticker: str) -> Optional[float]:
    """yfinance로 현재가 가져오기. 캐시 무시 (실시간)."""
    try:
        import yfinance as yf
    except Exception:
        return None
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d", interval="1d")
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def _bucket_rsi(rsi: Optional[float]) -> str:
    if rsi is None:
        return "unknown"
    if rsi < 40:
        return "RSI <40 (과매도)"
    if rsi < 60:
        return "RSI 40-60 (중립)"
    if rsi < 70:
        return "RSI 60-70 (강세)"
    return "RSI 70+ (과매수)"


def _bucket_year_pos(yp: Optional[float]) -> str:
    if yp is None:
        return "unknown"
    if yp < 0.3:
        return "52주 저점 (<30%)"
    if yp < 0.7:
        return "52주 중간 (30-70%)"
    if yp < 0.9:
        return "52주 고점 근처 (70-90%)"
    return "52주 ATH 근처 (≥90%)"


def _bucket_market_cap(mc: Optional[float]) -> str:
    if mc is None:
        return "unknown"
    if mc < 1e12:  # 1조원 미만
        return "소형주 (<1조)"
    if mc < 5e12:
        return "중형주 (1-5조)"
    if mc < 30e12:
        return "대형주 (5-30조)"
    return "초대형주 (≥30조)"


def evaluate_log(max_age_days: int = 60) -> Dict:
    """
    로그에 있는 모든 추천에 대해 현재가 비교 → 패턴별 통계.

    반환: {
        "by_age": {"1day": [...], "3day": [...], ...},
        "by_rsi": {"RSI <40": {hit_rate: X, avg_pct: Y, n: Z}, ...},
        "by_year_pos": {...},
        "by_category": {...},
        "by_market_cap": {...},
        "samples": [최근 추천들의 현황]
    }
    """
    if not LOG_PATH.exists():
        return {"summary": "추천 로그 없음 — 첫 실행", "stats": {}}

    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        logger.warning(f"recommendations_log 읽기 실패: {e}")
        return {"summary": f"로그 읽기 실패: {e}", "stats": {}}

    today = date.today()
    cutoff = today - timedelta(days=max_age_days)

    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        d_str = e.get("date")
        if not d_str:
            continue
        try:
            d = datetime.strptime(d_str[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        if d < cutoff:
            continue
        e["_date_obj"] = d
        e["_age_days"] = (today - d).days
        entries.append(e)

    if not entries:
        return {"summary": "최근 추천 없음", "stats": {}}

    # 현재가 fetch (ticker별로 한 번만)
    unique_tickers = list({e["ticker"] for e in entries if e.get("ticker")})
    prices_now: Dict[str, Optional[float]] = {}
    for t in unique_tickers:
        prices_now[t] = _fetch_price_now(t)

    # 각 entry 별로 수익률 계산
    enriched = []
    for e in entries:
        t = e.get("ticker")
        p_then = e.get("price_at_rec")
        p_now = prices_now.get(t)
        if not (isinstance(p_then, (int, float)) and isinstance(p_now, (int, float)) and p_then > 0):
            continue
        ret_pct = (p_now - p_then) / p_then * 100
        e["return_pct"] = round(ret_pct, 2)
        e["price_now"] = round(p_now, 2)
        enriched.append(e)

    if not enriched:
        return {"summary": "수익률 계산 가능한 추천 없음", "stats": {}}

    # 패턴별 그룹화
    def group_stats(group_fn):
        groups: Dict[str, List[float]] = {}
        for e in enriched:
            key = group_fn(e)
            groups.setdefault(key, []).append(e["return_pct"])
        out = {}
        for k, vals in groups.items():
            n = len(vals)
            wins = sum(1 for v in vals if v > 0)
            out[k] = {
                "n": n,
                "hit_rate_pct": round(wins / n * 100, 1) if n else 0,
                "avg_pct": round(sum(vals) / n, 2) if n else 0,
                "best_pct": round(max(vals), 2) if vals else 0,
                "worst_pct": round(min(vals), 2) if vals else 0,
            }
        return out

    return {
        "total_recommendations": len(enriched),
        "lookback_days": max_age_days,
        "by_age": group_stats(lambda e: f"{e['_age_days']}일 경과"),
        "by_rsi": group_stats(lambda e: _bucket_rsi(e.get("rsi"))),
        "by_year_pos": group_stats(lambda e: _bucket_year_pos(e.get("year_position"))),
        "by_category": group_stats(lambda e: e.get("category", "unknown")),
        "by_market_cap": group_stats(lambda e: _bucket_market_cap(e.get("market_cap"))),
        "samples": sorted(enriched, key=lambda e: e["_age_days"])[:10],
    }


# =============================================================
# 3. Claude 프롬프트 주입용 포맷
# =============================================================

def format_for_prompt(report: Dict) -> str:
    """Claude 프롬프트에 주입할 패턴별 적중률 요약."""
    if not report or not report.get("total_recommendations"):
        return ""

    parts = [
        "## 📊 추천 성과 누적 분석 (지난 %d일)" % report.get("lookback_days", 60),
        "총 누적 추천 %d건. 패턴별 평균 수익률·적중률 — **이걸 보고 자기 패턴 보완하라.**" % report["total_recommendations"],
        "",
    ]

    def render_section(title: str, group: Dict, key_label: str = "패턴"):
        if not group:
            return
        parts.append(f"### {title}")
        # n 큰 순으로 정렬
        sorted_items = sorted(
            group.items(), key=lambda kv: kv[1].get("n", 0), reverse=True
        )
        for k, st in sorted_items[:6]:
            parts.append(
                "- **%s**: 평균 %+.2f%% / 적중률 %.0f%% (n=%d) / 최고 %+.2f%% / 최악 %+.2f%%"
                % (k, st["avg_pct"], st["hit_rate_pct"], st["n"], st["best_pct"], st["worst_pct"])
            )
        parts.append("")

    render_section("RSI 구간별 (단기 고점 추격 함정 검증)", report.get("by_rsi", {}))
    render_section("52주 위치별", report.get("by_year_pos", {}))
    render_section("시총별 (사용자 요구: 발굴 후보 우선)", report.get("by_market_cap", {}))
    render_section("추천 카테고리별", report.get("by_category", {}))

    samples = report.get("samples") or []
    if samples:
        parts.append("### 최근 개별 추천 결과 샘플")
        for s in samples[:8]:
            parts.append(
                "- [%s] %s (%s, %s 카테고리): %+.2f%% (현재 %s)"
                % (
                    s.get("date", "?"),
                    s.get("name", s.get("ticker", "?")),
                    s.get("ticker", "?"),
                    s.get("category", "?"),
                    s.get("return_pct", 0),
                    s.get("price_now", "?"),
                )
            )

    parts.extend([
        "",
        "**⛔ 위 통계 강제 활용:**",
        "- 적중률 50% 미만 패턴(예: RSI 70+, 52주 ATH 근처) 의 종목은 추천 카드에서 제외하라.",
        "- 적중률 70%+ 패턴(예: 소형주 + RSI 50-60) 우선 추천하라.",
        "- '평균 -X% 떨어진 패턴' 을 또 추천하면 사용자 반복 손해. 이건 시스템 신뢰도 자살.",
    ])

    return "\n".join(parts)
