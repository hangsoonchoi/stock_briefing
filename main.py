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
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from utils import setup_logging, validate_env, logger


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
    start = datetime.now()
    logger.info("=" * 60)
    logger.info(f"📊 시장 브리핑 시작 — {start.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

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

    # 2. 데이터 수집 (모드별 분기)
    from data_fetcher import fetch_all_data
    from intraday_fetcher import fetch_quick_data

    is_quick = (brief_mode == "quick")
    data = safe_run("시장 데이터", fetch_all_data, quick=is_quick) or {
        "collected_at": datetime.now().isoformat(),
        "indicators": [], "sectors": [], "watchlist": [], "news": [],
    }

    if brief_mode == "full":
        # 풀 모드: 거시·공시·발굴까지 다 수집
        from macro_fetcher import fetch_macro_indicators
        from filings_fetcher import fetch_all_filings
        from screener import screen_market

        data["macro"] = safe_run("거시 지표", fetch_macro_indicators) or []
        data["filings"] = safe_run("공시", fetch_all_filings) or {"sec": {}, "dart": {}}
        data["screener"] = safe_run("발굴 스캔", screen_market, days=7) or {
            "kr_candidates": [], "us_candidates": [], "scanned_days": 7,
        }
    else:
        # 단타 모드: 빠른 데이터 + 아침 추천 포지션 평가
        from position_tracker import evaluate_positions

        quick = safe_run("단타 데이터", fetch_quick_data) or {
            "intraday_watchlist": [], "top_movers": {},
        }
        data["intraday"] = quick

        # 🚨 핵심: 아침에 추천된 포지션들 현재 상태 평가
        evaluated = safe_run("포지션 평가", evaluate_positions) or []
        data["evaluated_positions"] = evaluated
        logger.info(f"  📌 추적 중인 아침 추천 포지션 {len(evaluated)}개")

        # 빈 자리 채움 (analyzer가 안전하게 작동하도록)
        data["macro"] = []
        data["filings"] = {"sec": {}, "dart": {}}
        data["screener"] = {"kr_candidates": [], "us_candidates": [], "scanned_days": 0}

    n_ind = len(data.get("indicators", []))
    n_sec = len(data.get("sectors", []))
    n_stk = len(data.get("watchlist", []))
    n_news = len(data.get("news", []))
    if brief_mode == "full":
        n_macro = len(data.get("macro", []))
        n_dart = len(data.get("filings", {}).get("dart", {}))
        logger.info(
            f"\n[FULL] 수집 — 지표 {n_ind} / 섹터 {n_sec} / 종목 {n_stk} / "
            f"뉴스 {n_news} / 거시 {n_macro} / DART {n_dart}"
        )
    else:
        intra = data.get("intraday", {})
        movers = intra.get("top_movers", {})
        logger.info(
            f"\n[QUICK] 수집 — 지표 {n_ind} / 종목 {n_stk} (5분봉) / "
            f"뉴스 {n_news} / 톱무버: KR↑{len(movers.get('kr_gainers',[]))} "
            f"KR↓{len(movers.get('kr_losers',[]))} "
            f"US↑{len(movers.get('us_gainers',[]))} US↓{len(movers.get('us_losers',[]))}"
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

    # 6. 풀 모드 한정 — 추천 포지션 추출/저장 (단타 모드가 매시간 추적할 데이터)
    if brief_mode == "full":
        try:
            from position_tracker import extract_positions_from_html, save_today_positions
            positions = extract_positions_from_html(html_body)
            if positions:
                save_today_positions(positions)
                logger.info(f"📌 아침 추천 {len(positions)}개 포지션 저장 — 단타 모드가 추적 시작")
            else:
                logger.warning("HTML에서 포지션 추출 0개 — Claude 출력에 data 속성 누락 의심")
        except Exception as e:
            logger.warning(f"포지션 저장 실패: {e}")

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"\n✅ 전체 완료 ({elapsed:.1f}초 소요)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
