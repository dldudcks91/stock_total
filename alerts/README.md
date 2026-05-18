# alerts/ — 롱 진입 추천 카카오 알림

`dashboards/_precompute.py` 가 만든 `_recs.parquet` (KR/US/Crypto) 에서
**score ≥ 80 신규 종목** 만 골라 카카오톡 "나에게 보내기" 로 푸시.

## 파이프라인

```
alerts.run --asset {kr|us|crypto}
   │
   ├─ 1) fetch       : data.sources.{stocks|bitget} 증분 다운로드
   ├─ 2) precompute  : dashboards._precompute 가 _refs/_recs 갱신
   ├─ 3) scan        : _recs.parquet 의 score≥80 종목 ← last_seen_{asset}.json 차집합
   └─ 4) kakao       : 신규만 카카오 텍스트 1건 (alerts.kakao.get_sender)
```

각 단계는 옵션으로 끌 수 있음 (`--no-fetch`, `--no-precompute`, `--dry-run`).

## 신규 감지 정책

- 비교 키: `symbol` 만 (라벨 변경은 무시)
- 어제 last_seen 에 **없던 종목** 만 알림
- 추천에서 빠진 종목 (어제 있었는데 오늘 없음) → 알림 X
- 임계치: `rec_score >= 80` (CLI `--threshold` 로 조정)

state 파일: `data/alerts/last_seen_{asset}.json` (gitignore).
파일이 없으면 cold start — 그 시점의 **모든 추천이 신규로 잡힘** (첫 실행 시 주의).

## 최초 세팅 (로컬 또는 AWS)

### 1) 환경변수 — `.env`

프로젝트 루트의 `.env` (gitignore) 에 다음 추가:

```
KAKAO_REST_API_KEY=<카카오 개발자 콘솔의 REST API 키>
KAKAO_CLIENT_SECRET=<선택 — 보안 강화 사용 시>
KAKAO_REDIRECT_URI=http://localhost:8080
```

> 참고: `upbit_project/bithumb/kakao_message_sender.py` 의 하드코딩된 키가
> 원본. `.env` 로 옮긴 뒤 원본 파일에서 키를 지워 git 노출 위험 제거 권장.

### 2) OAuth 토큰 발급 (1회만)

```bash
.venv/Scripts/python.exe -m alerts.kakao --setup
```

- 출력된 URL 을 브라우저에서 열고 카카오 로그인
- 리다이렉트된 주소의 `?code=` 뒤 문자열을 복사
- 터미널에 붙여넣으면 `data/alerts/kakao_token.json` 자동 저장
- 이후 access_token 은 만료 10분 전 자동 refresh

### 3) 전송 테스트

```bash
.venv/Scripts/python.exe -m alerts.kakao --test "테스트"
```

### 4) baseline 만들기 (선택, 권장)

첫 실행 시 score≥80 종목 전부 (KR 74 / US 285 / Crypto 184건) 가 신규로 잡히면
카톡 메시지가 너무 김. 사전에 baseline 만 채우려면:

```bash
.venv/Scripts/python.exe -m alerts.scan --asset kr
.venv/Scripts/python.exe -m alerts.scan --asset us
.venv/Scripts/python.exe -m alerts.scan --asset crypto
```

(scan CLI 는 카카오 전송 없이 state 만 갱신)

## AWS 배포

### 가정
- Ubuntu 22.04 EC2, SSH 접근 가능
- `git`, `python3-venv`, `cron` 설치됨

### 1) 리포 클론 + venv

```bash
ssh ubuntu@<EC2_IP>
git clone <repo_url> ~/stock_total
cd ~/stock_total
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2) 시크릿 파일 업로드 (로컬에서)

```bash
# 로컬
scp .env ubuntu@<EC2_IP>:~/stock_total/.env
scp data/alerts/kakao_token.json ubuntu@<EC2_IP>:~/stock_total/data/alerts/kakao_token.json
```

또는 EC2 에서 `python -m alerts.kakao --setup` 으로 새로 발급.

### 3) baseline (선택)

```bash
.venv/bin/python -m alerts.scan --asset kr
.venv/bin/python -m alerts.scan --asset us
.venv/bin/python -m alerts.scan --asset crypto
```

### 4) crontab 등록

`crontab -e` 후 추가 — 분은 일부러 :33 / :07 등으로 흩어 트래픽 분산:

```cron
# 환경
HOME=/home/ubuntu
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
TZ=Asia/Seoul

# KR: 평일 장마감 33분 후
33 16 * * 1-5  cd ~/stock_total && .venv/bin/python -m alerts.run --asset kr     >> logs/kr.log 2>&1

# US: 매일 KST 06:33 (US 마감 직후)
33  6 * * 2-6  cd ~/stock_total && .venv/bin/python -m alerts.run --asset us     >> logs/us.log 2>&1

# Crypto: 매시 7분
 7  * * * *    cd ~/stock_total && .venv/bin/python -m alerts.run --asset crypto >> logs/crypto.log 2>&1
```

로그 디렉터리 미리 생성: `mkdir -p ~/stock_total/logs`

### 5) 동작 확인

```bash
# 즉시 1회 실행 (카톡 전송 X)
.venv/bin/python -m alerts.run --asset crypto --dry-run

# 카톡 포함 전체 실행
.venv/bin/python -m alerts.run --asset crypto
```

## 운영 메모

- **카카오 token refresh**: access_token 6h / refresh_token 60일. 60일 지나면
  `python -m alerts.kakao --setup` 재실행 필요. 토큰 만료가 가까워지면
  `data/alerts/kakao_token.json` 의 `token_expiry` 확인.
- **fetch 실패해도 알림 시도 계속**: 네트워크 일시 오류 → 캐시 기준으로 scan.
  precompute 실패 시는 신규 판정 불가 → 알림 skip.
- **메시지 길이**: 카톡 본문 ~1000자 한도. 신규가 20건 넘으면 본문에 20건만,
  나머지는 `... 외 N건` 으로 요약.
- **자산별 시그널**: KR/US 는 일/주/월봉 추격·수렴·바닥. Crypto 는 1h/4h/1d/1w
  추격·수렴 + 주봉 바닥. 라벨 접미사가 인터벌 (`d`, `w`, `m`, `h`, `4h`).
