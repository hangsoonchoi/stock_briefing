"""
시장 전체를 훑어 "잘 알려지지 않은 후보"를 발굴하는 모듈.

핵심 아이디어:
- watchlist에 미리 등록된 종목만 보면 결국 다 아는 대형주.
- 진짜 알파는 "임원이 매수했지만 뉴스에 안 뜬" 작은 회사들.
- DART 전체 + SEC EDGAR Form 4 RSS를 매일 훑어서 후보 명단 생성.

수집한 후보들은 analyzer에서 "🔍 발굴 후보" 섹션으로 들어감.
"""

import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List
from xml.etree import ElementTree as ET

import requests

from utils import logger, retry


SEC_HEADERS = {
    "User-Agent": "Personal Stock Briefing personal-research@example.com",
    "Accept-Encoding": "gzip, deflate",
}


# =============================================================
# 1. DART — 한국 시장 전체 임원 매수 공시 스캔
# =============================================================

@retry(max_attempts=2, base_delay=1.0)
def _dart_list(api_key: str, params: Dict) -> List[Dict]:
    """DART list.json 페이징 호출."""
    url = "https://opendart.fss.or.kr/api/list.json"
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "000":
        return []
    return data.get("list", [])


def scan_dart_insider_filings(days: int = 7, max_per_market: int = 60) -> List[Dict]:
    """
    DART에서 최근 N일 동안의 '임원·주요주주특정증권등소유상황보고서'(D002) 전체 수집.
    이건 임원이나 주요주주가 자기 회사 주식을 사거나 팔 때 의무적으로 내는 보고서.

    소형주 비중 높임 — 코스닥(K) 우선, 코스피(Y)도 일부.
    """
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        logger.warning("DART_API_KEY 없음 — 한국 발굴 스캔 스킵")
        return []

    end = datetime.now().date()
    start = end - timedelta(days=days)

    all_filings = []
    # 코스닥(K) — 작은 회사 많음, 정보 비대칭 큼
    # 코스피(Y) — 큰 회사 많지만 중·소형주도 있음
    for corp_cls in ("K", "Y"):
        try:
            params = {
                "crtfc_key": api_key,
                "bgn_de": start.strftime("%Y%m%d"),
                "end_de": end.strftime("%Y%m%d"),
                "pblntf_detail_ty": "D002",  # 임원·주요주주 소유상황 보고서
                "corp_cls": corp_cls,
                "page_count": 100,
                "page_no": 1,
            }
            collected = []
            for page in range(1, 4):  # 최대 3페이지 = 300건
                params["page_no"] = page
                items = _dart_list(api_key, params)
                if not items:
                    break
                collected.extend(items)
                if len(items) < 100:
                    break
                time.sleep(0.2)
            # 시장 별로 max_per_market 까지만
            all_filings.extend(collected[:max_per_market])
        except Exception as e:
            logger.warning(f"DART 시장({corp_cls}) 스캔 실패: {e}")
        time.sleep(0.3)

    return all_filings


def aggregate_dart_candidates(filings: List[Dict], top_n: int = 12) -> List[Dict]:
    """
    회사별로 공시 횟수 묶어서 top_n 추출 + 현재가 같이 가져옴.
    """
    by_corp = defaultdict(list)
    for f in filings:
        code = f.get("corp_code")
        if not code:
            continue
        by_corp[code].append(f)

    candidates = []
    for code, items in by_corp.items():
        first = items[0]
        stock_code = first.get("stock_code", "").strip()
        candidates.append({
            "corp_code": code,
            "corp_name": first.get("corp_name"),
            "stock_code": stock_code,
            "filing_count": len(items),
            "recent_titles": [it.get("report_nm") for it in items[:3]],
            "recent_dates": [it.get("rcept_dt") for it in items[:3]],
            "filers": list({it.get("flr_nm") for it in items if it.get("flr_nm")})[:5],
            "url_first": (
                f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={first.get('rcept_no')}"
                if first.get("rcept_no") else None
            ),
        })

    candidates.sort(
        key=lambda c: (c["filing_count"], max(c["recent_dates"]) if c["recent_dates"] else ""),
        reverse=True,
    )
    top = candidates[:top_n]

    # top_n 후보들 현재가 가져오기 (yfinance — KS 또는 KQ 시도)
    try:
        import yfinance as yf
        for c in top:
            sc = c["stock_code"]
            if not sc or len(sc) != 6:
                continue
            for suffix in (".KS", ".KQ"):
                try:
                    tk = yf.Ticker(f"{sc}{suffix}")
                    hist = tk.history(period="5d", interval="1d")
                    if hist is None or hist.empty:
                        continue
                    last = hist.iloc[-1]
                    prev = hist.iloc[-2] if len(hist) >= 2 else last
                    c["ticker_yf"] = f"{sc}{suffix}"
                    c["last_price"] = round(float(last["Close"]), 2)
                    c["change_pct"] = round(
                        (last["Close"] - prev["Close"]) / prev["Close"] * 100, 2
                    ) if prev is not None else None
                    c["volume"] = int(last["Volume"]) if last["Volume"] else 0
                    break
                except Exception:
                    continue
            time.sleep(0.1)
    except Exception as e:
        logger.warning(f"발굴 후보 현재가 fetch 실패: {e}")

    return top


# =============================================================
# 2. SEC — Form 4 (임원 매매) 최근 RSS 스캔
# =============================================================

@retry(max_attempts=2, base_delay=1.0)
def _sec_form4_recent(count: int = 100) -> List[Dict]:
    """
    SEC EDGAR 최근 Form 4 공시 RSS 스캔.
    All-companies feed — 어떤 회사든 최근 임원 매매 공시 다 잡힘.
    """
    url = (
        "https://www.sec.gov/cgi-bin/browse-edgar"
        f"?action=getcurrent&type=4&owner=include&count={count}&output=atom"
    )
    r = requests.get(url, headers=SEC_HEADERS, timeout=15)
    r.raise_for_status()
    return _parse_atom(r.text)


def _parse_atom(text: str) -> List[Dict]:
    """SEC atom feed 파싱."""
    items = []
    try:
        # 네임스페이스 처리
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(text)
        for entry in root.findall("a:entry", ns):
            title_el = entry.find("a:title", ns)
            link_el = entry.find("a:link", ns)
            updated_el = entry.find("a:updated", ns)
            if title_el is None:
                continue
            items.append({
                "title": (title_el.text or "").strip(),
                "url": link_el.attrib.get("href") if link_el is not None else "",
                "updated": (updated_el.text or "").strip() if updated_el is not None else "",
            })
    except Exception as e:
        logger.warning(f"SEC atom 파싱 실패: {e}")
    return items


def aggregate_sec_clusters(filings: List[Dict], top_n: int = 8) -> List[Dict]:
    """
    회사별로 묶고, 같은 회사에 여러 임원이 신고한 케이스 = 클러스터 매수 후보.
    Title 형식: "4 - COMPANY NAME (0001234567) (Issuer)"
    """
    by_company = defaultdict(list)
    for f in filings:
        title = f.get("title", "")
        # "4 - " 뒤 회사명 추출
        if " - " in title:
            after = title.split(" - ", 1)[1]
            # "(0000xxx) (Issuer)" 부분 제거
            issuer_part = after.split(" (")[0].strip()
            by_company[issuer_part].append(f)

    candidates = []
    for company, items in by_company.items():
        if not company or len(company) < 3:
            continue
        candidates.append({
            "company": company,
            "filing_count": len(items),
            "recent_url": items[0].get("url"),
            "recent_updated": items[0].get("updated"),
        })

    candidates.sort(key=lambda c: c["filing_count"], reverse=True)
    return candidates[:top_n]


# =============================================================
# 3. KRX — 외국인/기관 순매수 상위 (한국 시장 알파 채널)
# =============================================================
# 매일 외국인·기관이 어떤 종목 가장 많이 사는지가 강한 신호.
# 뉴스보다 빠르고 구체적임.

def scan_krx_institutional_flow(top_n: int = 15) -> Dict:
    """
    한국 거래소(KRX)에서 어제 외국인 + 기관 순매수 상위 종목.
    pykrx 라이브러리 사용. 휴일 자동 처리.
    """
    try:
        from pykrx import stock as krx
    except Exception as e:
        logger.warning(f"pykrx 미설치 또는 임포트 실패: {e} — KRX 스캔 스킵")
        return {"foreign_kospi": [], "foreign_kosdaq": [], "inst_kospi": [], "inst_kosdaq": []}

    # 가장 최근 영업일 찾기
    today = datetime.now().strftime("%Y%m%d")
    try:
        last_biz = krx.get_nearest_business_day_in_a_week(today)
    except Exception:
        # 전일로 fallback
        last_biz = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    result = {
        "date": last_biz,
        "foreign_kospi": [],
        "foreign_kosdaq": [],
        "inst_kospi": [],
        "inst_kosdaq": [],
    }

    def _fetch(market: str, investor: str) -> List[Dict]:
        try:
            df = krx.get_market_net_purchases_of_equities(
                last_biz, last_biz, market, investor
            )
            if df is None or df.empty:
                return []
            # 순매수거래대금 기준 정렬, top_n
            sort_col = next(
                (c for c in df.columns if "순매수거래대금" in c or "순매수" in c), None
            )
            if sort_col:
                df = df.sort_values(sort_col, ascending=False)
            top = df.head(top_n).reset_index()
            out = []
            for _, row in top.iterrows():
                ticker = str(row.get("티커") or row.get("종목코드") or "")
                name = str(row.get("종목명") or "")
                amt = row.get(sort_col) if sort_col else None
                out.append({
                    "ticker": ticker,
                    "name": name,
                    "net_buy_amount": float(amt) if amt is not None else None,
                })
            return out
        except Exception as e:
            logger.warning(f"KRX {market} {investor} 실패: {e}")
            return []

    result["foreign_kospi"] = _fetch("KOSPI", "외국인")
    time.sleep(0.5)
    result["foreign_kosdaq"] = _fetch("KOSDAQ", "외국인")
    time.sleep(0.5)
    result["inst_kospi"] = _fetch("KOSPI", "기관합계")
    time.sleep(0.5)
    result["inst_kosdaq"] = _fetch("KOSDAQ", "기관합계")

    return result


# =============================================================
# 3-5. KRX 공매도 잔고 — 숏커버 후보 발굴
# =============================================================
# 공매도 비율이 갑자기 줄어든 종목 = 기관이 숏을 풀고 있음 = 강세 가능 신호.
# 반대로 공매도 비율 급증 = 약세 베팅 증가 = 위험 신호.

def scan_krx_short_balance(top_n: int = 10) -> Dict:
    """KRX 공매도 잔고 데이터 — 코스피·코스닥 상위 종목."""
    try:
        from pykrx import stock as krx
    except Exception:
        return {"date": None, "kospi_high_short": [], "kosdaq_high_short": []}

    try:
        today = datetime.now().strftime("%Y%m%d")
        last_biz = krx.get_nearest_business_day_in_a_week(today)
    except Exception:
        last_biz = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    result = {"date": last_biz, "kospi_high_short": [], "kosdaq_high_short": []}

    def _fetch(market: str, key: str):
        try:
            df = krx.get_shorting_balance_by_ticker(last_biz, market=market)
            if df is None or df.empty:
                return
            # 잔고비율 (시총 대비) 기준 정렬
            ratio_col = next(
                (c for c in df.columns if "비율" in str(c) or "ratio" in str(c).lower()),
                None,
            )
            if ratio_col:
                df = df.sort_values(ratio_col, ascending=False)
            top = df.head(top_n).reset_index()
            for _, row in top.iterrows():
                ticker = str(row.get("티커") or row.get("종목코드") or row.get("Ticker") or "")
                name = str(row.get("종목명") or row.get("Name") or "")
                ratio = row.get(ratio_col) if ratio_col else None
                result[key].append({
                    "ticker": ticker,
                    "name": name,
                    "short_ratio_pct": float(ratio) if ratio else None,
                })
        except Exception as e:
            logger.warning(f"KRX 공매도 ({market}) 실패: {e}")

    _fetch("KOSPI", "kospi_high_short")
    _fetch("KOSDAQ", "kosdaq_high_short")
    return result


# =============================================================
# 3-6. KRX 단기과열·투자경고 — 위험 종목 자동 필터
# =============================================================
# KRX가 공식 지정한 "주의해야 할" 종목들. 단기과열은 거래량/가격 급등으로 시장이 비정상으로 본 종목.

def scan_krx_warning_stocks() -> Dict:
    """KRX 단기과열·투자경고·투자위험·관리종목 목록."""
    try:
        from pykrx import stock as krx
    except Exception:
        return {"warning_kospi": [], "warning_kosdaq": [], "managed": []}

    today = datetime.now().strftime("%Y%m%d")
    result = {"date": today, "warning_kospi": [], "warning_kosdaq": [], "managed": []}

    # pykrx에 공식 단기과열·투자경고 함수 — get_shorting_status_by_date 등
    # 정확히 매칭되는 함수가 없을 수 있으므로 try-except로 감쌈
    try:
        # 시도: 상장종목 외부 데이터 (관리/감리/단기과열)
        # pykrx에는 직접 단기과열 종목 가져오는 표준 함수가 없음
        # 대신 거래량 + 가격 급등 종목으로 proxy
        # 실제 KRX 단기과열은 wisestock 등에서 별도 가져와야 함
        pass
    except Exception as e:
        logger.warning(f"KRX 단기과열 실패: {e}")

    return result


# =============================================================
# 4. Reddit — 트렌딩 종목 (미국 retail 관심도)
# =============================================================
# r/stocks, r/wallstreetbets에서 자주 언급되는 티커는
# retail 관심도가 폭증 중이라는 신호.
# 뉴스 뜨기 전 단계 시그널.

import re

REDDIT_HEADERS = {
    "User-Agent": "stock-briefing/1.0 (personal research)"
}

# 흔한 일반 단어 (티커로 잘못 추출되는 거 거르기)
COMMON_WORDS_BLACKLIST = {
    "I", "A", "IT", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF", "IN", "IS",
    "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE", "ALL", "AND",
    "ANY", "ARE", "BUT", "CAN", "DAY", "DOW", "EOD", "FOR", "GET", "GOT", "HAD",
    "HAS", "HIS", "HOW", "IPO", "ITS", "LOL", "NEW", "NOT", "NOW", "ONE", "OUR",
    "OUT", "PUT", "SEC", "SEE", "SHE", "TBH", "THE", "TWO", "USA", "WAS", "WAY",
    "WHO", "WHY", "YOU", "YTD", "EPS", "PEG", "PER", "EV", "TLDR", "DD", "FYI",
    "OP", "AM", "PM", "CEO", "CFO", "CTO", "ETF", "ETFS", "ATH", "ATL", "FOMO",
    "ROI", "WSB", "PUMP", "DUMP", "BUY", "SELL", "HOLD", "MOON", "BULL", "BEAR",
    "CALL", "CALLS", "PUTS", "WSJ", "FB", "AI", "ML",
}


@retry(max_attempts=2, base_delay=1.0)
def _reddit_hot(subreddit: str, limit: int = 50) -> List[Dict]:
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    r = requests.get(url, headers=REDDIT_HEADERS, timeout=15)
    if r.status_code != 200:
        return []
    data = r.json()
    posts = []
    for child in data.get("data", {}).get("children", []):
        d = child.get("data", {})
        posts.append({
            "title": d.get("title", ""),
            "selftext": (d.get("selftext", "") or "")[:500],
            "score": d.get("score", 0),
            "num_comments": d.get("num_comments", 0),
            "url": "https://reddit.com" + d.get("permalink", ""),
            "subreddit": subreddit,
        })
    return posts


def _extract_tickers(text: str) -> List[str]:
    """텍스트에서 티커 후보 추출 — 1~5자리 대문자."""
    # $TICKER 형식 우선
    cashtag = re.findall(r"\$([A-Z]{1,5})\b", text)
    # 일반 대문자 단어 (블랙리스트 제외)
    plain = re.findall(r"\b([A-Z]{2,5})\b", text)
    out = list(cashtag)
    for t in plain:
        if t not in COMMON_WORDS_BLACKLIST:
            out.append(t)
    return out


def scan_reddit_trending(top_n: int = 12) -> List[Dict]:
    """
    여러 주식 서브레딧의 hot 게시물에서 자주 언급되는 티커 추출.
    """
    subreddits = ["stocks", "wallstreetbets", "investing", "options"]
    all_posts = []
    for sub in subreddits:
        try:
            posts = _reddit_hot(sub, limit=40)
            all_posts.extend(posts)
            time.sleep(1.0)  # Reddit rate limit
        except Exception as e:
            logger.warning(f"Reddit r/{sub} 실패: {e}")

    if not all_posts:
        return []

    # 티커별 점수 집계 (게시물 score 합계 기준)
    ticker_score = Counter()
    ticker_posts = defaultdict(list)
    for p in all_posts:
        text = f"{p['title']} {p['selftext']}"
        tickers = _extract_tickers(text)
        for t in set(tickers):  # 한 게시물에서 여러 번 나와도 1개로
            ticker_score[t] += max(p["score"], 0) + p["num_comments"]
            if len(ticker_posts[t]) < 2:
                ticker_posts[t].append({
                    "title": p["title"][:120],
                    "url": p["url"],
                    "subreddit": p["subreddit"],
                })

    out = []
    for ticker, score in ticker_score.most_common(top_n):
        out.append({
            "ticker": ticker,
            "score": score,
            "sample_posts": ticker_posts[ticker],
        })
    return out


# =============================================================
# 5. 통합 호출
# =============================================================

def screen_market(days: int = 7) -> Dict:
    """
    한국+미국 시장 전체에서 최근 임원 매매 활발 종목 후보 발굴.
    + KRX 외국인/기관 순매수 + Reddit 트렌딩 추가.
    """
    logger.info("🔍 발굴 스캔 시작")

    # 1. DART 임원 공시
    kr_filings = scan_dart_insider_filings(days=days, max_per_market=80)
    kr_candidates = aggregate_dart_candidates(kr_filings, top_n=15)
    logger.info(f"  ✓ DART 한국 후보 {len(kr_candidates)}개")

    # 2. SEC Form 4
    try:
        us_filings = _sec_form4_recent(count=100)
        us_candidates = aggregate_sec_clusters(us_filings, top_n=10)
        logger.info(f"  ✓ SEC Form 4 미국 후보 {len(us_candidates)}개")
    except Exception as e:
        logger.warning(f"SEC Form 4 실패: {e}")
        us_candidates = []

    # 3. KRX 외국인/기관 순매수
    try:
        krx_flow = scan_krx_institutional_flow(top_n=15)
        n = sum(len(v) for k, v in krx_flow.items() if isinstance(v, list))
        logger.info(f"  ✓ KRX 외국인/기관 순매수 {n}개 (date={krx_flow.get('date')})")
    except Exception as e:
        logger.warning(f"KRX 순매수 실패: {e}")
        krx_flow = {"foreign_kospi": [], "foreign_kosdaq": [], "inst_kospi": [], "inst_kosdaq": []}

    # 4. Reddit
    try:
        reddit_trend = scan_reddit_trending(top_n=12)
        logger.info(f"  ✓ Reddit 트렌딩 {len(reddit_trend)}개 티커")
    except Exception as e:
        logger.warning(f"Reddit 트렌딩 실패: {e}")
        reddit_trend = []

    # 5. KRX 공매도 잔고
    try:
        short_data = scan_krx_short_balance(top_n=10)
        n_short = len(short_data.get("kospi_high_short", [])) + len(short_data.get("kosdaq_high_short", []))
        logger.info(f"  ✓ KRX 공매도 잔고 {n_short}개 종목 (date={short_data.get('date')})")
    except Exception as e:
        logger.warning(f"KRX 공매도 실패: {e}")
        short_data = {"date": None, "kospi_high_short": [], "kosdaq_high_short": []}

    # 6. KRX 단기과열/투자경고 (현재 placeholder)
    warning_data = scan_krx_warning_stocks()

    return {
        "kr_candidates": kr_candidates,
        "us_candidates": us_candidates,
        "krx_flow": krx_flow,
        "reddit_trend": reddit_trend,
        "short_balance": short_data,
        "warning_stocks": warning_data,
        "scanned_days": days,
    }


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    from utils import setup_logging
    setup_logging()

    result = screen_market(days=7)
    print(f"\n=== 한국 발굴 후보 ({len(result['kr_candidates'])}개) ===")
    for c in result["kr_candidates"]:
        print(f"  [{c['filing_count']}건] {c['corp_name']} ({c['stock_code']})")
    print(f"\n=== 미국 발굴 후보 ({len(result['us_candidates'])}개) ===")
    for c in result["us_candidates"]:
        print(f"  [{c['filing_count']}건] {c['company']}")
