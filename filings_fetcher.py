"""
공시 / Filings 수집
- SEC EDGAR (미국): Form 4 (임원 매매), 8-K (중요사건)
- DART (한국): 임원·주요주주 보유주식보고, 주요사항보고서

여기가 진짜 알파의 원천. 뉴스보다 훨씬 빨리 신호가 잡힘.
임원이 대량으로 자기회사 주식 매수하면 뉴스 나오기 전에
이미 시그널.
"""

import os
import time
from datetime import datetime, timedelta
from typing import Dict, List

import requests

from config import US_TICKER_CIK, KR_TICKER_CORP_CODE
from utils import logger, retry


# SEC EDGAR는 User-Agent 헤더 필수 (사용자 식별)
SEC_HEADERS = {
    "User-Agent": "Personal Stock Briefing personal-research@example.com",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov",
}


@retry(max_attempts=2, base_delay=1.0)
def _fetch_sec_recent(cik: str, form_type: str = None, days: int = 14) -> List[Dict]:
    """SEC EDGAR submissions API — 최근 공시 목록."""
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    r = requests.get(url, headers=SEC_HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    cutoff = (datetime.now() - timedelta(days=days)).date()
    out = []
    for i, form in enumerate(forms):
        try:
            fdate = datetime.strptime(dates[i], "%Y-%m-%d").date()
            if fdate < cutoff:
                continue
            if form_type and form_type != form:
                continue
            acc = accessions[i].replace("-", "")
            doc = primary_docs[i] if i < len(primary_docs) else ""
            url_filing = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
                if doc else
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}"
            )
            out.append({
                "form": form,
                "date": dates[i],
                "url": url_filing,
            })
        except Exception:
            continue
    return out


def fetch_sec_filings(days: int = 14) -> Dict[str, Dict]:
    """미국 watchlist의 SEC EDGAR 공시 수집."""
    results = {}
    for ticker, cik in US_TICKER_CIK.items():
        try:
            all_recent = _fetch_sec_recent(cik, form_type=None, days=days)
            form4 = [f for f in all_recent if f["form"] == "4"]  # 임원 매매
            form8k = [f for f in all_recent if f["form"] == "8-K"]  # 중요사건
            form13 = [f for f in all_recent if f["form"].startswith("SC 13")]  # 13D/G

            results[ticker] = {
                "form4_count": len(form4),
                "form4_recent": form4[:5],
                "form8k_count": len(form8k),
                "form8k_recent": form8k[:3],
                "form13_count": len(form13),
                "form13_recent": form13[:2],
            }
        except Exception as e:
            logger.warning(f"SEC {ticker} 수집 실패: {e}")
        time.sleep(0.15)  # SEC rate limit: 10 req/sec
    return results


@retry(max_attempts=2, base_delay=1.0)
def _fetch_dart_filings(corp_code: str, days: int = 14) -> List[Dict]:
    """DART 공시 목록 API."""
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        return []

    end = datetime.now().date()
    start = end - timedelta(days=days)

    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": start.strftime("%Y%m%d"),
        "end_de": end.strftime("%Y%m%d"),
        "page_count": 30,
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "000":
        return []

    out = []
    for item in data.get("list", []):
        out.append({
            "report_nm": item.get("report_nm"),     # 공시 제목
            "rcept_dt": item.get("rcept_dt"),       # 접수일자
            "flr_nm": item.get("flr_nm"),           # 제출인
            "rcept_no": item.get("rcept_no"),       # 접수번호
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no')}",
        })
    return out


def fetch_dart_filings(days: int = 14) -> Dict[str, List[Dict]]:
    """한국 watchlist의 DART 공시 수집."""
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        logger.warning("DART_API_KEY 없음 — 한국 공시 스킵")
        return {}

    results = {}
    for ticker_short, corp_code in KR_TICKER_CORP_CODE.items():
        try:
            filings = _fetch_dart_filings(corp_code, days=days)

            # 중요 공시만 필터: 임원·주요주주, 주요사항보고서, 분기/사업보고서
            important_keywords = [
                "임원", "주요주주", "보유주식", "최대주주",
                "주요사항", "유상증자", "전환사채", "신주", "자기주식",
                "분기보고서", "반기보고서", "사업보고서",
                "수주", "단일판매", "공급계약",
            ]
            important = [
                f for f in filings
                if any(kw in (f["report_nm"] or "") for kw in important_keywords)
            ]

            results[ticker_short] = {
                "all_count": len(filings),
                "important_count": len(important),
                "important_recent": important[:8],
            }
        except Exception as e:
            logger.warning(f"DART {ticker_short} 수집 실패: {e}")
        time.sleep(0.2)
    return results


def fetch_all_filings(days: int = 14) -> Dict:
    """SEC + DART 통합."""
    logger.info("📋 SEC EDGAR 공시 수집 중...")
    sec = fetch_sec_filings(days=days)
    logger.info("📋 DART 공시 수집 중...")
    dart = fetch_dart_filings(days=days)
    return {"sec": sec, "dart": dart}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    from utils import setup_logging
    setup_logging()

    data = fetch_all_filings(days=14)
    print(f"\nSEC: {len(data['sec'])} 종목")
    for t, d in data["sec"].items():
        print(f"  {t}: Form4 {d['form4_count']}건, 8-K {d['form8k_count']}건")
    print(f"\nDART: {len(data['dart'])} 종목")
    for t, d in data["dart"].items():
        print(f"  {t}: 중요공시 {d['important_count']}건 / 전체 {d['all_count']}건")
