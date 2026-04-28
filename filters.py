"""
추천 정확도 강화 — 단기 고점 추격 차단 + 반(反)합의 필터 + 숨은 가치주 발견.
"""

from datetime import datetime, date
from typing import Dict, List, Optional, Tuple


# === 단기 고점 추격 컷오프 ===
RSI_OVERHEATED = 70.0
YEAR_POS_OVERHEATED = 0.90
VOLUME_PUMP_RATIO = 3.0
PRICE_PUMP_PCT = 10.0
EARNINGS_DAYS_BLOCK = 3

# === 적중률 보수화 트리거 ===
ACCURACY_CONSERVATIVE_THRESHOLD = 60.0
ACCURACY_HALT_THRESHOLD = 40.0

# === 반(反)합의 필터 ===
CONSENSUS_NEWS_COUNT = 4
CONSENSUS_REDDIT_SCORE = 800

# === 숨은 가치주 ===
HIDDEN_GEM_NEWS_MAX = 1
HIDDEN_GEM_REDDIT_MAX = 100
HIDDEN_GEM_PER_MAX = 15.0
HIDDEN_GEM_ROE_MIN = 0.15
HIDDEN_GEM_MARGIN_MIN = 0.10


def _days_until(date_str):
    if not date_str:
        return None
    try:
        target = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
        return (target - date.today()).days
    except Exception:
        return None


def is_buy_blocked(stock):
    reasons = []
    tech = stock.get("technicals") or {}
    rsi = tech.get("rsi")
    if isinstance(rsi, (int, float)) and rsi >= RSI_OVERHEATED:
        reasons.append("RSI %.0f (과매수 ≥%.0f)" % (rsi, RSI_OVERHEATED))
    year_pos = stock.get("year_position")
    if isinstance(year_pos, (int, float)) and year_pos >= YEAR_POS_OVERHEATED:
        reasons.append("52주 위치 %.0f%% (고점 근처 ≥%.0f%%)" % (year_pos*100, YEAR_POS_OVERHEATED*100))
    change_pct = stock.get("change_pct")
    vol_vs_avg = stock.get("vol_vs_avg")
    if (isinstance(change_pct, (int, float)) and isinstance(vol_vs_avg, (int, float))
            and change_pct >= PRICE_PUMP_PCT and vol_vs_avg >= VOLUME_PUMP_RATIO):
        reasons.append("거래량 %.1fx + 당일 %+.1f%% (추격매수 광기)" % (vol_vs_avg, change_pct))
    earnings = stock.get("next_earnings")
    days_to_earn = _days_until(earnings)
    if days_to_earn is not None and 0 <= days_to_earn <= EARNINGS_DAYS_BLOCK:
        reasons.append("어닝 D-%d (결과 복불복 도박)" % days_to_earn)
    return (bool(reasons), reasons)


def annotate_buy_blocks(watchlist):
    blocked = 0
    for s in watchlist:
        is_blocked, reasons = is_buy_blocked(s)
        if is_blocked:
            s["_buy_block_reason"] = " / ".join(reasons)
            blocked += 1
        else:
            s["_buy_block_reason"] = None
    return {"total": len(watchlist), "blocked": blocked, "buy_eligible": len(watchlist) - blocked}


def _get_news_count(ticker, kr_stock_news, us_stock_news):
    for source in (kr_stock_news or {}, us_stock_news or {}):
        if ticker in source:
            articles = source[ticker].get("articles") or []
            return len(articles)
    return 0


def _get_reddit_score(ticker, reddit_trending):
    if not reddit_trending:
        return 0
    short = ticker.split(".")[0] if "." in ticker else ticker
    best = 0
    for r in reddit_trending:
        rt = r.get("ticker", "")
        if rt == ticker or rt == short:
            best = max(best, r.get("score", 0))
    return best


def is_consensus_overheated(stock, news_count, reddit_score):
    reasons = []
    if news_count >= CONSENSUS_NEWS_COUNT:
        reasons.append("뉴스 %d건 ≥%d (시장에 다 퍼진 정보)" % (news_count, CONSENSUS_NEWS_COUNT))
    if reddit_score >= CONSENSUS_REDDIT_SCORE:
        reasons.append("Reddit 점수 %d ≥%d (개인 몰림 = 꼭지)" % (reddit_score, CONSENSUS_REDDIT_SCORE))
    return (bool(reasons), reasons)


def is_hidden_gem(stock, news_count, reddit_score):
    quiet_news = news_count <= HIDDEN_GEM_NEWS_MAX
    quiet_reddit = reddit_score <= HIDDEN_GEM_REDDIT_MAX
    if not (quiet_news and quiet_reddit):
        return (False, [])
    f = stock.get("fundamentals") or {}
    per = f.get("trailing_pe")
    roe = f.get("return_on_equity")
    margin = f.get("profit_margins")
    quality = []
    if isinstance(per, (int, float)) and 0 < per <= HIDDEN_GEM_PER_MAX:
        quality.append("PER %.1f (저평가)" % per)
    if isinstance(roe, (int, float)) and roe >= HIDDEN_GEM_ROE_MIN:
        quality.append("ROE %.1f%% (수익성↑)" % (roe*100))
    if isinstance(margin, (int, float)) and margin >= HIDDEN_GEM_MARGIN_MIN:
        quality.append("영업이익률 %.1f%% (수익성↑)" % (margin*100))
    if len(quality) >= 2:
        return (True, quality + ["뉴스 %d건 + Reddit %d점 (남이 안 봄)" % (news_count, reddit_score)])
    return (False, [])


def annotate_consensus_and_gems(watchlist, kr_stock_news=None, us_stock_news=None, reddit_trending=None):
    consensus_blocked = 0
    gems = 0
    for s in watchlist:
        ticker = s.get("ticker", "")
        news_count = _get_news_count(ticker, kr_stock_news or {}, us_stock_news or {})
        reddit_score = _get_reddit_score(ticker, reddit_trending or [])
        is_consensus, c_reasons = is_consensus_overheated(s, news_count, reddit_score)
        if is_consensus:
            existing = s.get("_buy_block_reason")
            extra = " / ".join(c_reasons)
            s["_buy_block_reason"] = (existing + " / " + extra) if existing else extra
            consensus_blocked += 1
        is_gem, g_reasons = is_hidden_gem(s, news_count, reddit_score)
        if is_gem:
            s["_hidden_gem_reason"] = " / ".join(g_reasons)
            gems += 1
        else:
            s["_hidden_gem_reason"] = None
        s["_news_count"] = news_count
        s["_reddit_score"] = reddit_score
    return {"consensus_blocked": consensus_blocked, "hidden_gems": gems}


def filter_discovery_candidates(candidates):
    passed = []
    blocked = []
    for c in candidates:
        is_blocked, reasons = is_buy_blocked(c)
        if is_blocked:
            cc = dict(c)
            cc["_buy_block_reason"] = " / ".join(reasons)
            blocked.append(cc)
        else:
            passed.append(c)
    return passed, blocked


def get_accuracy_mode(accuracy_report):
    if not accuracy_report:
        return "no_data"
    stats = accuracy_report.get("stats") or {}
    hit_rate = stats.get("hit_rate_pct")
    if hit_rate is None:
        return "no_data"
    if hit_rate < ACCURACY_HALT_THRESHOLD:
        return "halt"
    if hit_rate < ACCURACY_CONSERVATIVE_THRESHOLD:
        return "conservative"
    return "normal"


def build_filter_summary(stats, mode, consensus_stats=None):
    mode_msg = {
        "halt": "🚨 적중률 < 40% — 매수 추천 절대 보류 모드. 오늘은 '사지 말 것 / 손절' 만 출력하라.",
        "conservative": "⚠️ 적중률 < 60% — 보수화 모드. 매수 후보 최대 3개. RSI 60 이하만 매수 권고.",
        "normal": "✅ 적중률 정상 (≥60%) — 일반 모드.",
        "no_data": "ℹ️ 적중률 데이터 부족 — 일반 모드로 진행.",
    }.get(mode, "")
    parts = [
        "## 🛡️ 추천 안전 필터 상태",
        "- 모드: **%s** — %s" % (mode, mode_msg),
        "- 관심종목 %d개 중 **%d개**가 단기 고점 추격 + 합의 과열로 BUY 차단" % (stats.get("total", 0), stats.get("blocked", 0)),
        "- 매수 추천 가능: %d개" % stats.get("buy_eligible", 0),
    ]
    if consensus_stats:
        cb = consensus_stats.get("consensus_blocked", 0)
        gems = consensus_stats.get("hidden_gems", 0)
        parts.append("- 합의 과열(뉴스 4건+ 또는 Reddit 800점+): **%d개** 추가 차단" % cb)
        parts.append("- 💎 숨은 가치주 (뉴스 적음 + 펀더멘털 우수): **%d개** 발견" % gems)
    parts.extend([
        "",
        "**⛔ 강제 규칙 — 이거 안 지키면 사용자가 또 손해 봐서 시스템 폐기됨:**",
        "1. `_buy_block_reason` 가 있는 종목 → 절대 '🏆 TOP 3' / '매수 검토' / '발굴 후보' / '단타' 추천 카드에 넣지 마라.",
        "   해당 종목은 '🚫 사지 말 것' 카드에만 등장 (그것도 차단 사유 그대로 인용).",
        "2. 매수 추천 모든 종목: RSI < 70 + 52주 위치 < 90% + 어닝 D-3 이상 떨어짐 + 뉴스 4건 미만 + Reddit 800점 미만.",
        "3. **🏆 TOP 3 우선순위 구성 강제:**",
        "   - 3개 중 **2개 이상**: 발굴 후보(small/mid cap, 시총 5조 이하) 또는 _hidden_gem_reason 있는 종목.",
        "   - **대형주(삼성/SK하이닉스/NVDA/TSLA/AAPL/MSFT/현대차 등) 최대 1개**.",
        "   - 자리 채우려고 'TOP 1만 출력' 하지 마라. 발굴 후보 데이터 적어도 '추가 조사 필요' 라벨로 채워라.",
        "4. **단타 후보 1~3 도 같음**: 3개 중 2개 이상은 단타 톱무버 또는 발굴 후보(시총 1조원 미만 우선). RSI 87 같은 차단 종목 단타로도 추천 금지.",
        "5. **💎 _hidden_gem_reason 있는 종목은 무조건 발굴 후보 카드에 우선 배치하라.** 사용자가 가장 원하는 것: '남이 안 본 진짜 가치 발견'.",
        "6. **'다 아는 종목' (뉴스 많음 + Reddit 트렌딩) 은 절대 신규 매수 추천 X.** 이미 가격에 반영됨 = 추격매수 함정.",
    ])
    return "\n".join(parts)
