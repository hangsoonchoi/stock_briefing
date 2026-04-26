# 🔑 API 키 발급 가이드

이 시스템은 4개의 무료 API 키가 필요합니다. 모두 무료이고 발급은 5~15분 안에 끝납니다.

---

## 1️⃣ Anthropic API 키 (분석용, 필수)

### 발급 절차

1. https://console.anthropic.com/ 접속
2. 구글 계정 또는 이메일로 회원가입
3. 좌측 메뉴 → **API Keys** → **Create Key**
4. 이름 칸에 `stock-briefing` 입력 → **Create**
5. `sk-ant-...` 으로 시작하는 키가 화면에 표시됨
6. ⚠️ **즉시 복사** — 창을 닫으면 다시 볼 수 없음

### 비용
- 신규 가입 시 약간의 무료 크레딧 ($5 정도) 제공
- Claude Sonnet 4.6 기준, 매일 1회 발송 = 월 $1 ~ $3
- 무료 크레딧 다 쓰면 결제 카드 등록 필요

### .env 에 입력
```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## 2️⃣ Gmail 앱 비밀번호 (메일 발송용, 필수)

본인 Gmail의 일반 비밀번호로는 SMTP 로그인이 안 됩니다. 16자리 "앱 비밀번호"를 따로 받아야 합니다.

### 사전 준비
- **2단계 인증이 반드시 켜져 있어야 합니다.**
- 확인: https://myaccount.google.com/security → "2단계 인증" 항목

### 발급 절차

1. https://myaccount.google.com/apppasswords 접속
2. "앱 이름" 칸에 `stock briefing` 입력
3. **만들기** 클릭
4. 16자리 비밀번호 표시됨 (예: `abcd efgh ijkl mnop`)
5. ⚠️ **즉시 복사** — 창을 닫으면 다시 볼 수 없음

### .env 에 입력
```
SENDER_EMAIL=your.email@gmail.com
SENDER_APP_PASSWORD=abcd efgh ijkl mnop
RECIPIENT_EMAIL=your.email@gmail.com
```
- 띄어쓰기 포함해도 되고 빼도 됨 (코드에서 알아서 처리)
- `SENDER_EMAIL` 과 `RECIPIENT_EMAIL` 같은 주소 써도 됨 (자기 자신에게 보내기)

---

## 3️⃣ FRED API 키 (거시지표용, 권장)

미국 연방준비제도(St. Louis Fed)의 경제 데이터 API. Fed 금리, CPI, 실업률, 장단기 금리차 같은 핵심 거시 지표를 가져옵니다.

### 발급 절차

1. https://fredaccount.stlouisfed.org/login/secure/ 접속
2. 우측 **"Create New Account"** 클릭
3. 이메일 / 이름 / 비밀번호 입력 → 가입
4. 이메일로 인증 메일이 오니 링크 클릭하여 인증
5. 로그인 후 상단 **"My Account"** → 좌측 **"API Keys"**
6. **"Request API Key"** 버튼 클릭
7. 입력 양식:
   - Application Name: `personal stock briefing`
   - Description: `personal investment research, daily macro indicator pulls`
   - 약관 체크 → **Request API Key**
8. 즉시 32자리 키 발급됨

### .env 에 입력
```
FRED_API_KEY=abc123def456...
```

### 비용
- 완전 무료, 발급 제한 없음
- 일일 호출 제한도 매우 넉넉함 (개인 사용 시 절대 초과 안 됨)

---

## 4️⃣ DART API 키 (한국 공시용, 권장)

금융감독원 전자공시(DART) API. 한국 종목의 임원 매매·중요 공시를 즉시 추적합니다.

### 발급 절차

1. https://opendart.fss.or.kr/ 접속
2. 우측 상단 **"회원가입"** 클릭
3. 이메일 / 이름 / 비밀번호 입력 → 이메일 인증
4. 로그인 후 상단 **"인증키 신청·관리"** → **"인증키 신청"**
5. 입력 양식:
   - 활용목적: `개인 투자 정보 분석`
   - 약관 동의 → 신청
6. 승인 대기:
   - 보통 자동 승인 (1~2분 안에 됨)
   - 가끔 영업일 1일 걸림
7. 승인되면 **"인증키 관리"** 메뉴에서 40자리 키 확인 및 복사

### .env 에 입력
```
DART_API_KEY=abc123def456...
```

### 비용
- 완전 무료
- 일일 20,000회 호출 제한 (개인 사용 시 절대 초과 안 됨)

---

## ✅ 발급 완료 체크리스트

- [ ] Anthropic API 키 — `sk-ant-`로 시작하는 키 받음
- [ ] Gmail 2단계 인증 켜짐 + 앱 비밀번호 16자리 받음
- [ ] FRED API 키 — 32자리 받음
- [ ] DART API 키 — 40자리 받음 (승인 대기 중일 수 있음)

---

## 🔧 .env 파일 만들기

1. 작업 폴더의 `.env.example` 파일을 복사
2. 파일명을 `.env` 로 변경 (점으로 시작하는 파일)
3. 각 키 자리에 발급받은 값 붙여넣기
4. 저장

```bash
# Windows PowerShell
Copy-Item .env.example .env
notepad .env

# macOS / Linux
cp .env.example .env
nano .env
```

⚠️ **`.env` 파일은 절대 GitHub에 올리지 마세요.** `.gitignore`에 이미 포함되어 있습니다.

---

## 🆘 문제 생기면

- **Gmail 앱 비밀번호 메뉴가 안 보임** → 2단계 인증을 먼저 켜야 합니다.
- **FRED 가입 시 이메일 인증 메일이 안 옴** → 스팸 폴더 확인.
- **DART 인증키 승인이 1일 넘게 안 됨** → DART 고객센터(02-3145-7800)로 문의 가능.
- **Anthropic 무료 크레딧이 없음** → "Plans & Billing"에서 카드 등록하면 종량제로 쓸 수 있음.
