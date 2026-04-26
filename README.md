# 📊 매일 아침 시장 브리핑 봇 (v2)

매일 정해진 시간에 거시 경제·섹터 자금 흐름·SEC/DART 공시·기술적 지표·뉴스를 수집해서, Claude로 분석한 한국어 리포트를 이메일로 자동 발송합니다.

## 핵심 철학

> **"이미 대중에 노출된 정보는 이미 늦었다."**

CNBC·연합뉴스 헤드라인 시점이면 기관은 이미 진입 끝. 그래서 이 시스템은 데이터 우선순위를:

1. **공시 데이터** (SEC EDGAR Form 4·8-K / DART) — 임원 매매·중요사건. 뉴스 전 단계 신호.
2. **거시 지표** (FRED) — 발표 시점 정해진 객관 데이터.
3. **섹터 자금 흐름** — 11개 SPDR + KODEX 섹터 ETF 1일/5일/20일 비교.
4. **기술적 지표** — RSI, MA20/60/200, MACD, BB, ATR.
5. **뉴스** — 위 신호를 검증하는 보조 자료. 비중 작게.

---

## 📦 리포트 섹션

1. **오늘의 핵심** — 3줄 요약
2. **거시 환경** — Fed 금리, CPI, 실업률, 장단기 금리차
3. **섹터 로테이션** — 자금이 어디서 어디로
4. **🚨 공시 시그널** — 임원 매매·중요공시 (가장 비중 큼)
5. **관심 종목 동향 + 기술적 신호**
6. **주목 후보 + 포지션 가이드** — 300만원 가정한 분산 시뮬레이션
7. **뉴스 (확인용)**
8. **리스크 / 면책**

---

## 🚀 빠른 시작

### 1. 의존성 설치

```bash
cd stock_briefing
pip install -r requirements.txt
```

### 2. API 키 4개 발급

자세한 발급 절차는 [`API_KEYS_GUIDE.md`](./API_KEYS_GUIDE.md) 참조.

- **Anthropic API 키** (필수, 분석용) — https://console.anthropic.com/
- **Gmail 앱 비밀번호** (필수, 발송용)
- **FRED API 키** (권장, 거시 지표) — https://fred.stlouisfed.org/
- **DART API 키** (권장, 한국 공시) — https://opendart.fss.or.kr/

### 3. `.env` 파일 만들기

```bash
# Windows
copy .env.example .env
notepad .env

# macOS / Linux
cp .env.example .env
nano .env
```

각 키를 채워넣고 저장.

### 4. 관심 종목 / 기업 코드 수정

`config.py`:
- `WATCHLIST` — 본인 관심 종목 추가
- `US_TICKER_CIK` — 미국 종목 추가 시 CIK 매핑 추가
  - CIK 조회: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany
- `KR_TICKER_CORP_CODE` — 한국 종목 추가 시 DART corp_code 매핑 추가
  - corp_code 조회: https://opendart.fss.or.kr/disclosureinfo/company/main.do

### 5. 첫 실행

```bash
python main.py
```

수집 → 분석 → 발송까지 1~2분 정도. 본인 메일함에 리포트가 도착하면 성공.

---

## 📁 모듈 구조

```
stock_briefing/
├── main.py               # 진입점 — 전체 흐름 제어
├── config.py             # 설정 (관심종목, 모델, 임계값 등)
├── utils.py              # 재시도, 로깅, 환경변수 검증
│
├── data_fetcher.py       # yfinance — 시장지표/섹터/관심종목/뉴스
├── macro_fetcher.py      # FRED — 거시 경제 지표
├── filings_fetcher.py    # SEC EDGAR + DART — 공시
├── technicals.py         # 기술적 지표 (RSI, MA, MACD, BB, ATR)
│
├── analyzer.py           # Claude API → HTML 리포트
├── memory.py             # 시그널 archive + 다음 호출에 재주입
├── emailer.py            # Gmail SMTP + 텔레그램 fallback
│
├── archive/              # 매일 리포트 JSON 저장 (자동 생성)
├── .env                  # 본인 키들 (gitignore됨)
├── .env.example          # 템플릿
├── requirements.txt
├── API_KEYS_GUIDE.md     # 키 발급 단계별 가이드
└── README.md             # 이 파일
```

---

## ⏰ 자동 스케줄링

### 권장: GitHub Actions (PC 꺼져 있어도 동작)

이 프로젝트에는 `.github/workflows/briefing.yml` 가 포함되어 있습니다.

1. 이 폴더를 GitHub 저장소로 push (Private 권장)
2. 저장소 **Settings → Secrets and variables → Actions**
3. **New repository secret** 으로 다음 키들 등록:
   - `ANTHROPIC_API_KEY`
   - `SENDER_EMAIL`
   - `SENDER_APP_PASSWORD`
   - `RECIPIENT_EMAIL`
   - `FRED_API_KEY`
   - `DART_API_KEY`
4. 매일 평일 KST 오전 7:30 자동 실행됨
5. **Actions** 탭에서 수동 실행도 가능 (`workflow_dispatch`)

### 대안: Windows 작업 스케줄러 (PC가 항상 켜져 있어야 함)

1. 시작 → "작업 스케줄러"
2. **기본 작업 만들기** → 매일 오전 7:30
3. 실행: `python.exe`, 인수: `main.py`, 시작 위치: 프로젝트 절대경로

### 대안: cron (macOS / Linux)

```cron
30 7 * * 1-5 cd /path/to/stock_briefing && /usr/bin/python3 main.py >> briefing.log 2>&1
```

---

## 🛠 커스터마이징

| 원하는 것 | 수정할 곳 |
|---|---|
| 관심 종목 변경 | `config.py` → `WATCHLIST`, `US_TICKER_CIK`, `KR_TICKER_CORP_CODE` |
| 운용 자금 변경 | `config.py` → `TOTAL_CAPITAL_KRW`, `MAX_POSITIONS` |
| 추적 거시 지표 추가 | `config.py` → `FRED_SERIES` |
| 추적 섹터 변경 | `config.py` → `SECTOR_ETFS_US`, `SECTOR_ETFS_KR` |
| 모델 변경 (비용/품질) | `config.py` → `CLAUDE_MODEL` |
| 리포트 톤 / 형식 | `analyzer.py` → `SYSTEM_PROMPT` |
| 메모리 lookback 일수 | `config.py` → `MEMORY_LOOKBACK_DAYS` |
| RSI/MA 임계값 | `config.py` 의 기술 지표 섹션 |
| 이메일 디자인 | `emailer.py` → `EMAIL_TEMPLATE` |

---

## 💡 비용

- **Anthropic API**: 매일 1회 발송 기준 약 **$0.04~0.08/일** (월 $1~3)
- **FRED, DART, yfinance, RSS, Gmail**: 모두 무료
- 첫 실행 시 Anthropic 콘솔에서 최소 $5 충전 필요

---

## 🧠 메모리 / 학습 효과

매일 리포트 생성 시:
1. 그날의 핵심 시그널을 `archive/YYYY-MM-DD.json` 으로 저장
2. 그날의 종목 가격 스냅샷도 같이 저장
3. 다음 리포트 생성 시 지난 30일치 시그널 + 그동안의 가격 변화를 프롬프트에 주입

이렇게 하면 Claude가:
- "지난 주에 내가 X 종목에 매수 시그널 줬는데 주가는 -5% 빠짐 → 그 패턴은 보수적으로"
- "Y 패턴 신호 잘 맞았음 → 신뢰도 높여서 다룸"

진짜 fine-tuning은 아니지만 functional하게는 self-correcting.

---

## ⚠️ 면책 / 주의

- **이 시스템은 정보 정리 도구입니다. 투자 자문이 아닙니다.**
- 단기 가격은 누구도 신뢰성 있게 못 맞춥니다. Claude도 마찬가지.
- 모든 투자 판단과 결과의 책임은 본인에게 있습니다.
- "이 종목을 사세요"라고 말하지 않도록 설계됐고, 그렇게 말한다면 무시하세요.
- 손실 감내 가능한 자금만 사용. 빚으로 투자 X.

---

## 🔧 문제 해결

| 증상 | 해결 |
|---|---|
| `Authentication failed` (Gmail) | 앱 비밀번호 다시 확인. 일반 비밀번호 X. 2단계 인증 켜져 있어야 함. |
| yfinance 데이터 안 옴 | `pip install --upgrade yfinance`. 자주 차단됨. 다음날 다시 시도. |
| Claude API 401 | 키가 `sk-ant-` 로 시작하는지 확인. 콘솔에서 크레딧 잔액 확인. |
| FRED/DART 키 무시됨 | `.env` 파일이 프로젝트 루트에 있는지 + 따옴표 X 확인. |
| 리포트가 너무 짧음 | `config.py` 의 `MAX_OUTPUT_TOKENS` 늘리기. |
| SEC EDGAR 거부됨 | `filings_fetcher.py` 의 `SEC_HEADERS` User-Agent에 본인 이메일 넣기. |

---

## 🚧 향후 추가 가능한 모듈 (TODO)

- `screener.py` — 거래량 폭증·52주 신고가/신저가 종목 스크리닝
- `calendars.py` — 다음 주 어닝/경제 발표 일정 + 컨센서스
- `alt_signals.py` — CFTC COT, short interest, 풋콜 비율
- `position_sizer.py` — ATR 기반 손절·켈리 비율 계산기 (현재는 analyzer 프롬프트 안에서 시뮬레이션만)

필요해지면 추가로 만들 수 있습니다.
