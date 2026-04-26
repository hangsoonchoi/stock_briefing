"""
사용자 설정 파일
관심 종목, 뉴스 소스, 모델 등 자유롭게 수정하세요.
"""

# ============================================================
# 운용 자금 (포지션 사이징 계산용)
# ============================================================
TOTAL_CAPITAL_KRW = 3_000_000  # 300만원

# 최대 보유 종목 수 (분산 정도)
MAX_POSITIONS = 6

# 종목당 최대 비중 (%)
MAX_POSITION_PCT = 25  # 한 종목 최대 25%

# 손절 기준 (단순 ATR 기반)
STOP_LOSS_ATR_MULTIPLIER = 2.0

# ============================================================
# 관심 종목 (이 종목들의 개별 동향이 리포트에 포함됩니다)
# ============================================================
# 한국 종목: "종목코드.KS" (코스피) 또는 "종목코드.KQ" (코스닥)
# 미국 종목: 그냥 티커 (예: "AAPL", "NVDA")
WATCHLIST = {
    "한국": {
        "005930.KS": "삼성전자",
        "000660.KS": "SK하이닉스",
        "373220.KS": "LG에너지솔루션",
        # 원하는 종목 추가 / 삭제하세요
    },
    "미국": {
        "AAPL": "Apple",
        "NVDA": "NVIDIA",
        "TSLA": "Tesla",
        "MSFT": "Microsoft",
        # 원하는 종목 추가 / 삭제하세요
    },
}

# SEC EDGAR Form 4 (임원 매매) 추적용 — 미국 watchlist의 CIK
# CIK 조회: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=apple&type=&dateb=&owner=include&count=40
US_TICKER_CIK = {
    "AAPL": "0000320193",
    "NVDA": "0001045810",
    "TSLA": "0001318605",
    "MSFT": "0000789019",
}

# DART 한국 종목 corp_code 매핑 (종목코드 → DART corp_code)
# corp_code 조회: https://opendart.fss.or.kr/disclosureinfo/company/main.do
KR_TICKER_CORP_CODE = {
    "005930": "00126380",  # 삼성전자
    "000660": "00164779",  # SK하이닉스
    "373220": "01515323",  # LG에너지솔루션
}

# ============================================================
# 시장 지표 (지수, 환율, 원자재)
# ============================================================
MARKET_INDICATORS = {
    # 미국 지수
    "^GSPC": "S&P 500",
    "^IXIC": "나스닥",
    "^DJI": "다우존스",
    "^VIX": "VIX (변동성 지수)",
    "^RUT": "Russell 2000 (소형주)",
    # 한국 지수
    "^KS11": "KOSPI",
    "^KQ11": "KOSDAQ",
    # 환율 / 원자재 / 채권
    "KRW=X": "USD/KRW",
    "JPY=X": "USD/JPY",
    "CNY=X": "USD/CNY",
    "DX-Y.NYB": "달러인덱스(DXY)",
    "CL=F": "WTI 원유",
    "BZ=F": "브렌트유",
    "GC=F": "금",
    "SI=F": "은",
    "HG=F": "구리",
    "^TNX": "美 10년물 국채금리",
    "^FVX": "美 5년물 국채금리",
    "^TYX": "美 30년물 국채금리",
    "BTC-USD": "비트코인",
}

# ============================================================
# 섹터 로테이션 추적용 ETF
# ============================================================
SECTOR_ETFS_US = {
    "XLK": "Tech",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLP": "Consumer Staples",
    "XLY": "Consumer Discretionary",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication",
    # 스타일
    "IWM": "Russell 2000 (소형)",
    "QQQ": "Nasdaq 100 (대형 성장)",
    "IWD": "Russell 1000 Value",
    "IWF": "Russell 1000 Growth",
}

SECTOR_ETFS_KR = {
    "091160.KS": "KODEX 반도체",
    "091170.KS": "KODEX 은행",
    "098560.KS": "KODEX 미디어&엔터",
    "139220.KS": "KODEX 건설",
    "117700.KS": "KODEX 철강",
    "266390.KS": "KODEX 자동차",
    "228790.KS": "KODEX 화장품",
    "117460.KS": "KODEX 에너지화학",
}

# ============================================================
# FRED 거시 지표
# ============================================================
# 시리즈 ID — https://fred.stlouisfed.org/
FRED_SERIES = {
    "DFF": "美 연방기금금리(EFFR)",
    "DGS10": "美 10년 국채금리",
    "DGS2": "美 2년 국채금리",
    "T10Y2Y": "美 10년-2년 금리차 (경기 시그널)",
    "T10Y3M": "美 10년-3개월 금리차 (경기 시그널)",
    "CPIAUCSL": "美 CPI (전월)",
    "CPILFESL": "美 Core CPI (전월)",
    "UNRATE": "美 실업률",
    "PAYEMS": "美 비농업 고용",
    "ICSA": "美 신규 실업수당 청구 (주간)",
    "UMCSENT": "미시간 소비자심리",
    "DEXKOUS": "USD/KRW (FRED)",
    "VIXCLS": "VIX (FRED 일간)",
    "WTISPLC": "WTI 원유",
}

# ============================================================
# 뉴스 RSS 피드 (보조 — 거시 이벤트 캐치용으로만)
# ============================================================
# 주의: 뉴스는 "확인용"이지 "원천 시그널"이 아님.
# 진짜 시그널은 SEC, DART, FRED, CFTC 데이터에서 나옴.
NEWS_FEEDS = [
    # 글로벌 시장·경제
    ("Reuters Business", "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best"),
    ("CNBC Markets", "https://www.cnbc.com/id/15839069/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Bloomberg Markets (top news)", "https://feeds.bloomberg.com/markets/news.rss"),
    ("Yahoo Finance Headlines", "https://finance.yahoo.com/news/rssindex"),
    # 글로벌 지정학·세계 흐름 (전쟁·선거·정상회담·제재 등)
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Reuters World", "https://www.reutersagency.com/feed/?best-topics=world&post_type=best"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("AP World", "https://feeds.apnews.com/rss/apf-topnews"),
    # 중국·아시아
    ("SCMP China Economy", "https://www.scmp.com/rss/318198/feed"),
    ("Nikkei Asia", "https://asia.nikkei.com/rss/feed/nar"),
    # 테크·AI 산업
    ("TechCrunch", "https://techcrunch.com/feed/"),
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    # 에너지·원자재
    ("OilPrice", "https://oilprice.com/rss/main"),
    # 한국 — 일반·경제·사회 (노동·정치 이슈 포함)
    ("한경 마켓", "https://www.hankyung.com/feed/finance"),
    ("한경 산업", "https://www.hankyung.com/feed/industry"),
    ("연합뉴스 경제", "https://www.yonhapnewstv.co.kr/category/news/economy/feed/"),
    ("연합뉴스 사회", "https://www.yonhapnewstv.co.kr/category/news/society/feed/"),
    ("매일경제 증권", "https://www.mk.co.kr/rss/50200011/"),
    ("매일경제 산업", "https://www.mk.co.kr/rss/50100032/"),
    ("머니투데이", "https://rss.mt.co.kr/mt_rss.xml"),
    ("이데일리 경제", "https://rss.edaily.co.kr/economy_news.xml"),
]

MAX_ARTICLES_PER_FEED = 4  # 피드 늘어났으니 피드당 갯수는 줄임 (총량 비슷하게)

# Google News 키워드 검색 — 종목 외 거시·테마 이슈 포착용
# 검색어 / 언어 / 국가
GLOBAL_NEWS_QUERIES = [
    ("AI semiconductor", "en", "US"),
    ("Federal Reserve interest rate", "en", "US"),
    ("China economy stimulus", "en", "US"),
    ("Geopolitical risk Middle East", "en", "US"),
    ("EV battery industry", "en", "US"),
    ("Bitcoin cryptocurrency regulation", "en", "US"),
    ("미국 관세 무역", "ko", "KR"),  # 미국발 한국 영향
    ("반도체 보조금", "ko", "KR"),
    ("원/달러 환율", "ko", "KR"),
]

# 종목별 네이버 뉴스 — Korean watchlist 종목 코드(6자리) 매핑
# 005930 → 삼성전자 / 000660 → SK하이닉스 / 373220 → LG에너지솔루션
NAVER_STOCK_CODES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "373220": "LG에너지솔루션",
}

# ============================================================
# 기술적 지표 설정
# ============================================================
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

MA_SHORT = 20  # 단기 이동평균
MA_MID = 60    # 중기
MA_LONG = 200  # 장기 (추세 판정)

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

BB_PERIOD = 20
BB_STD = 2

ATR_PERIOD = 14

# ============================================================
# 스크리너 설정
# ============================================================
# 거래량 이상치: 평균 대비 N배 이상
VOLUME_SPIKE_THRESHOLD = 3.0
# 신고/신저가 lookback
HIGH_LOW_LOOKBACK_DAYS = 252  # 약 1년

# ============================================================
# 메모리 / 학습 시스템
# ============================================================
# 매일 리포트 + 시그널을 archive/ 폴더에 저장
# 다음 리포트 생성 시 지난 N일치 시그널 + 결과를 프롬프트에 주입
MEMORY_LOOKBACK_DAYS = 30

# ============================================================
# Claude 모델 설정
# ============================================================
# 더 깊은 분석을 원하면 "claude-opus-4-7" (비싸지만 똑똑함)
# 빠르고 저렴: "claude-sonnet-4-6" (이게 일상용으로 베스트)
# 매우 저렴: "claude-haiku-4-5"
CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 32000  # 16개 섹션 모두 디테일 유지 (팔것/사지말것/TOP3 추가)

# ============================================================
# 리포트 발송 시각 (스케줄러에서 참고용 - 한국 시간 기준 권장)
# ============================================================
# 미국 장 마감 후 + 한국 장 시작 전이 가장 적절
# 추천: 평일 오전 7:30 KST
