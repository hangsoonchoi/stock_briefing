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

    # 1. 환경변수 검증
    # PUBLISH_MODE: "web"(기본 — docs/ 폴더에 HTML 저장) / "email"(Gmail SMTP 발송) / "both"
    publish_mode = os.environ.get("PUBLISH_MODE", "web").lower()

    required = ["ANTHROPIC_API_KEY"]
    if publish_mode in ("email", "both"):
        required += ["SENDER_EMAIL", "SENDER_APP_PASSWORD", "RECIPIENT_EMAIL"]

    validate_env(
        required_keys=required,
        optional_keys=["FRED_API_KEY", "DART_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
    )
    logger.info(f"PUBLISH_MODE = {publish_mode}")

    # 2. 데이터 수집 (모듈별 격리)
    from data_fetcher import fetch_all_data
    from macro_fetcher import fetch_macro_indicators
    from filings_fetcher import fetch_all_filings
    from screener import screen_market

    data = safe_run("시장 데이터", fetch_all_data) or {
        "collected_at": datetime.now().isoformat(),
        "indicators": [], "sectors": [], "watchlist": [], "news": [],
    }
    data["macro"] = safe_run("거시 지표", fetch_macro_indicators) or []
    data["filings"] = safe_run("공시", fetch_all_filings) or {"sec": {}, "dart": {}}
    data["screener"] = safe_run("발굴 스캔", screen_market, days=7) or {
        "kr_candidates": [], "us_candidates": [], "scanned_days": 7,
    }

    n_ind = len(data.get("indicators", []))
    n_sec = len(data.get("sectors", []))
    n_stk = len(data.get("watchlist", []))
    n_news = len(data.get("news", []))
    n_macro = len(data.get("macro", []))
    n_sec_filings = len(data.get("filings", {}).get("sec", {}))
    n_dart = len(data.get("filings", {}).get("dart", {}))
    n_kr_scan = len(data.get("screener", {}).get("kr_candidates", []))
    n_us_scan = len(data.get("screener", {}).get("us_candidates", []))
    logger.info(
        f"\n수집 요약 — 지표 {n_ind} / 섹터 {n_sec} / 종목 {n_stk} / "
        f"뉴스 {n_news} / 거시 {n_macro} / SEC {n_sec_filings} / DART {n_dart} / "
        f"발굴(KR {n_kr_scan} / US {n_us_scan})"
    )

    # 데이터가 너무 빈약하면 중단
    if n_ind == 0 and n_stk == 0 and n_macro == 0:
        logger.error("핵심 데이터 거의 0 — 중단")
        return 1

    # 3. Claude 분석 → HTML
    try:
        from analyzer import generate_briefing
        html_body = generate_briefing(data)
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

    # 5. 메모리 저장
    try:
        import memory
        signals = memory.extract_signals_from_html(html_body)
        memory.save_today({
            "generated_at": datetime.now().isoformat(),
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
        logger.warning(f"메모리 저장 실패 (리포트는 발송됨): {e}")

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"\n✅ 전체 완료 ({elapsed:.1f}초 소요)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
