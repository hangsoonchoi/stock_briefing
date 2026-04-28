"""
메인 스크립트 — 매일 한 번 실행 (스케줄러에서)

흐름:
1. 환경변수 검증
2. 데이터 수집 (시장, 거시, 공시, 뉴스) — 각각 try/except로 격리
3. Claude로 분석 → HTML 리포트
4. 이메일 발송
5. 메모리 archive 저장 (다음번 self-correct용)

실행: python main.py
"""

import os
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from utils import setup_logging, validate_env, logger


# === KST 타임존 (Asia/Seoul = UTC+9) ===
# zoneinfo가 환경에 따라 없을 수도 있어 fallback으로 fixed offset 사용
try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except ImportError:
    KST = timezone(timedelta(hours=9))


# === 30분 중복 방지 락 ===
# GitHub Actions 무료 cron 은 같은 슬롯에 백업 cron 여러 개 필요 →
# 같은 30분 안에 두 번 돌면 두 번째는 그냥 종료 (API 비용 낭비 차단)
LOCK_FILE = Path(__file__).parent / "archive" / "last_run.txt"


def _check_lock(now: datetime) -> bool:
    """True 면 너무 최근에 돈 거 — 즉시 종료해야 함."""
    if not LOCK_FILE.exists():
        return False
    try:
        last_iso = LOCK_FILE.read_text(encoding="utf-8").strip()
        last = datetime.fromisoformat(last_iso)
        # 둘 다 aware/naive 통일
        if last.tzinfo is None:
            last = last.replace(tzinfo=KST)
        if now.tzinfo is None:
            now = now.replace(tzinfo=KST)
        delta_min = (now - last).total_seconds() / 60
        return 0 <= delta_min < 30
    except Exception as e:
        logger.warning(f"락 파일 파싱 실패 — 무시: {e}")
        return False


def _write_lock(now: datetime) -> None:
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(now.isoformat(), encoding="utf-8")
    except Exception as e:
        logger.warning(f"락 파일 쓰기 실패 — 무시: {e}")


def safe_run(fn_name: str, fn, *args, **kwargs):
    """모듈 하나 실패해도 전체 죽지 않게 격리."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.error(f"{fn_name} 실패: {e}")
        logger.debug(traceback.format_exc())
        return None


def main() -> int:
    setup_logging("INFO")
    # 모든 시간은 KST 기준
    start = datetime.now(KST)
    logger.info("=" * 60)
    logger.info(f"📊 시장 브리핑 시작 — {start.strftime('%Y-%m-%d %H:%M:%S KST')}")
    logger.info("=" * 60)

    # 30분 중복 방지 락 — 백업 cron 들 줄줄이 동시 트리거 막기
    # 사용자가 수동 강제 실행하고 싶으면 환경변수 FORCE_RUN=1
    if os.environ.get("FORCE_RUN") != "1" and _check_lock(start):
        logger.info("⏭️  30분 안에 이미 실행됨 — 중복 차단 (FORCE_RUN=1 로 강제 실행 가능)")
        return 0
    _write_lock(start)

    # 1. 환경변수 + 모드 검증
    # PUBLISH_MODE: "web"(기본 — docs/ 폴더에 HTML 저장) / "email" / "both"
    # BRIEF_MODE: "full"(아침 풀 분석) / "quick"(매시간 단타 모드)
    publish_mode = os.environ.get("PUBLISH_MODE", "web").lower()
    brief_mode = os.environ.get("BRIEF_MODE", "full").lower()

    required = ["ANTHROPIC_API_KEY"]
    if publish_mode in ("email", "both"):
        required += ["SENDER_EMAIL", "SENDER_APP_PASSWORD", "RECIPIENT_EMAIL"]

    validate_env(
        required_keys=required,
        optional_keys=["FRED_API_KEY", "DART_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
    )
    logger.info(f"PUBLISH_MODE = {publish_mode} | BRIEF_MODE = {brief_mode}")

    # 2. 데이터 수집 — 통합 모드 (매시간 모든 정보 + 단타 데이터 같이)
    # 변하지 않는 데이터(거시·공시·발굴·종목별 뉴스)는 캐시(2~6시간)
    # 빠른 데이터(가격·5분봉·톱무버·포지션)는 매번 fresh
    from data_fetcher import (
        fetch_all_data,
        fetch_korean_stock_news_per_ticker,
        fetch_us_stock_news_per_ticker,
        fetch_global_theme_news,
    )
    from intraday_fetcher import fetch_quick_data
    from macro_fetcher import fetch_macro_indicators
    from filings_fetcher import fetch_all_filings
    from screener import screen_market
    from position_tracker import evaluate_positions
    from cache import fetch_with_cache

    # 빠르게 변하는 시장 데이터 (캐시 X) — 항상 fresh
    data = safe_run("시장 데이터", fetch_all_data, quick=True) or {
        "collected_at": datetime.now().isoformat(),
        "indicators": [], "sectors": [], "watchlist": [], "news": [],
    }

    # 거시 지표: 6시간 캐시 (FRED는 자주 안 바뀜)
    data["macro"] = safe_run(
        "거시 지표(캐시)", fetch_with_cache, "macro", fetch_macro_indicators, 21600
    ) or []

    # 공시: 4시간 캐시
    data["filings"] = safe_run(
        "공시(캐시)", fetch_with_cache, "filings", fetch_all_filings, 14400
    ) or {"sec": {}, "dart": {}}

    # 발굴: 3시간 캐시
    data["screener"] = safe_run(
        "발굴 스캔(캐시)", fetch_with_cache, "screener", screen_market, 10800, days=7
    ) or {"kr_candidates": [], "us_candidates": [], "scanned_days": 7}

    # 종목별 뉴스: 2시간 캐시
    data["kr_stock_news"] = safe_run(
        "한국 종목별 뉴스(캐시)", fetch_with_cache, "kr_stock_news",
        fetch_korean_stock_news_per_ticker, 7200
    ) or {}
    data["us_stock_news"] = safe_run(
        "미국 종목별 뉴스(캐시)", fetch_with_cache, "us_stock_news",
        fetch_us_stock_news_per_ticker, 7200
    ) or {}
    data["theme_news"] = safe_run(
        "테마 뉴스(캐시)", fetch_with_cache, "theme_news",
        fetch_global_theme_news, 7200
    ) or []

    # 섹터: 1시간 캐시 (장중에는 의미 있게 변함)
    from data_fetcher import fetch_sector_performance
    data["sectors"] = safe_run(
        "섹터(캐시)", fetch_with_cache, "sectors", fetch_sector_performance, 3600
    ) or []

    # 단타 데이터 (5분봉, 톱무버) — 매번 fresh
    quick = safe_run("단타 데이터", fetch_quick_data) or {
        "intraday_watchlist": [], "top_movers": {},
    }
    data["intraday"] = quick

    # 아침 추천 포지션 평가 — 매번 fresh (현재가 비교)
    evaluated = safe_run("포지션 평가", evaluate_positions) or []
    data["evaluated_positions"] = evaluated
    logger.info(f"  📌 추적 중인 아침 추천 포지션 {len(evaluated)}개")

    # 🎯 사용자 실제 보유 종목 평가 — user_holdings.json 기반
    from position_tracker import evaluate_user_holdings
    user_holdings = safe_run("사용자 보유 종목 평가", evaluate_user_holdings) or []
    data["user_holdings"] = user_holdings
    if user_holdings:
        total_pnl = sum(h.get("pnl") or 0 for h in user_holdings)
        logger.info(f"  🎯 사용자 보유 {len(user_holdings)}종목 / 총 평가손익 {total_pnl:+,}원")

    # 시스템 자기 검증 — 과거 30일 추천 정확도 (Claude가 self-correct하도록)
    from accuracy_tracker import evaluate_past_recommendations
    accuracy = safe_run(
        "정확도 평가", fetch_with_cache, "accuracy_30d",
        evaluate_past_recommendations, 21600, days=30
    ) or {"summary": "데이터 없음", "details": []}
    data["accuracy_report"] = accuracy
    logger.info(f"  📊 자기검증: {accuracy.get('summary', 'N/A')}")

    n_ind = len(data.get("indicators", []))
    n_sec = len(data.get("sectors", []))
    n_stk = len(data.get("watchlist", []))
    n_news = len(data.get("news", []))
    n_macro = len(data.get("macro", []))
    n_dart = len(data.get("filings", {}).get("dart", {}))
    n_kr_disc = len(data.get("screener", {}).get("kr_candidates", []))
    intra = data.get("intraday", {})
    movers = intra.get("top_movers", {})
    logger.info(
        f"\n[수집 요약] 지표 {n_ind} / 섹터 {n_sec} / 종목 {n_stk} / 뉴스 {n_news} / "
        f"거시 {n_macro} / DART {n_dart} / 발굴 {n_kr_disc} / "
        f"단타무버: KR↑{len(movers.get('kr_gainers',[]))} KR↓{len(movers.get('kr_losers',[]))} "
        f"US↑{len(movers.get('us_gainers',[]))} US↓{len(movers.get('us_losers',[]))} / "
        f"포지션 {len(evaluated)}"
    )

    # 데이터가 너무 빈약하면 중단
    if n_ind == 0 and n_stk == 0 and n_macro == 0:
        logger.error("핵심 데이터 거의 0 — 중단")
        return 1

    # 3. Claude 분석 → HTML
    try:
        from analyzer import generate_briefing
        html_body = generate_briefing(data, mode=brief_mode)
    except Exception as e:
        logger.error(f"Claude 분석 실패: {e}")
        logger.debug(traceback.format_exc())
        return 1

    # 4. 발행 (웹 / 이메일 / 둘다)
    if publish_mode in ("web", "both"):
        try:
            from publisher import publish
            published_path = publish(html_body)
            logger.info(f"🌐 웹페이지 저장 완료 — {published_path}")
        except Exception as e:
            logger.error(f"웹페이지 저장 실패: {e}")
            logger.debug(traceback.format_exc())
            if publish_mode == "web":
                return 1

    if publish_mode in ("email", "both"):
        try:
            from emailer import send_email
            send_email(html_body)
        except Exception as e:
            logger.error(f"이메일 발송 실패: {e}")
            return 1

    # 5. 메모리 저장 (모든 모드)
    try:
        import memory
        signals = memory.extract_signals_from_html(html_body)
        memory.save_today({
            "generated_at": datetime.now().isoformat(),
            "mode": brief_mode,
            "signals": signals,
            "watchlist_snapshot": {
                s["ticker"]: s["close"] for s in data.get("watchlist", [])
            },
            "macro_summary": {
                m["series_id"]: m["last_value"] for m in data.get("macro", [])
            },
            "indicators_summary": {
                i["ticker"]: i["close"] for i in data.get("indicators", [])
            },
        })
    except Exception as e:
        logger.warning(f"메모리 저장 실패: {e}")

    # 6. 추천 포지션 추출 + 누적 로그 (모든 run 마다)
    try:
        from position_tracker import extract_positions_from_html, save_today_positions
        from performance_tracker import log_recommendations_batch
        positions = extract_positions_from_html(html_body)
        if positions:
            if brief_mode == "full":
                save_today_positions(positions)
                logger.info(f"📌 아침 추천 {len(positions)}개 포지션 저장")

            # 모든 run 에서 추천 로그 누적 (패턴 학습용)
            wl_meta = {
                s["ticker"]: {
                    "rsi": (s.get("technicals") or {}).get("rsi"),
                    "year_position": s.get("year_position"),
                    "news_count": s.get("_news_count"),
                    "reddit_score": s.get("_reddit_score"),
                    "market_cap": (s.get("fundamentals") or {}).get("market_cap"),
                    "sector": (s.get("fundamentals") or {}).get("sector"),
                    "change_pct": s.get("change_pct"),
                    "vol_vs_avg": s.get("vol_vs_avg"),
                }
                for s in data.get("watchlist", [])
            }
            for p in positions:
                meta = wl_meta.get(p.get("ticker"))
                if meta:
                    p.update(meta)
            log_recommendations_batch(positions)
        else:
            logger.warning("HTML에서 포지션 추출 0개 — Claude 출력에 data 속성 누락 의심")
    except Exception as e:
        logger.warning(f"포지션 저장 실패: {e}")

    elapsed = (datetime.now(KST) - start).total_seconds()
    logger.info(f"\n✅ 전체 완료 ({elapsed:.1f}초 소요)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
