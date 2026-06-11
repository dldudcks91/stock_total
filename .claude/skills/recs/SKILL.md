---
name: recs
description: 오늘 기준 ma_touch 통과 종목을 표로 보여준다. 사용자가 "추천 종목", "ma_touch 통과", "오늘 통과 종목", "/recs"라고 할 때 발동. 자산별 분리 표 (KR / NASDAQ / Crypto). 컬럼 = 종목명·코드·시총·거래량·현재가·일/주/월봉 MA10·20 거리·통과TF·큰흐름정합도.
---

# `/recs` — ma_touch 추천 종목 표

`data/cache/{asset}/_ma_touch.parquet` 의 평가 결과를 사용자 지정 표 형식으로 출력. 추천 종목 단순 조회용.

## 호출

```powershell
.venv/Scripts/python.exe -m scripts._common.build_recs_table [--asset kr|us|crypto|all] [--tf any|1D|1W|1M|1Q|1Y] [--kind full|partial|both] [--sort marcap|ticker|tf|count_signal] [--top N]
```

기본값: `--asset kr --tf any --kind both --sort marcap`.

## 인자

| 인자 | 기본 | 의미 |
|---|---|---|
| `--asset` | `kr` | 어느 자산 (`all` = KR + NASDAQ + Crypto 세 표 동시 출력) |
| `--tf` | `any` | 특정 TF 통과만 (`1D` / `1W` / `1M` / `1Q` / `1Y`), `any` = 모두 |
| `--kind` | `both` | `full` (안정 종목) / `partial` (신생주) / `both` |
| `--sort` | `marcap` | 시총·코드·통과TF·시그널 카운트 순 |
| `--top` | (전체) | 상위 N |

## 출력 표 컬럼 (자산 공통)

| 컬럼 | 단위 | 의미 |
|---|---|---|
| 종목명 | str | KR=한글 / US=영문 / Crypto=Bitget 심볼 |
| 코드 | str | 종목 코드/티커/심볼 |
| 시총 | 조 (KR) / B$ (US) / — (Crypto) | 시가총액 |
| 거래량 | 만주 (주식) / 코인 (Crypto) | 마지막 일봉 거래량 |
| 현재가 | 원/USD/USDT | 마지막 일봉 종가 |
| vs일봉MA10(%) / vs일봉MA20(%) | % | (close/MA−1) × 100, 일봉 |
| vs주봉MA10(%) / vs주봉MA20(%) | % | 주봉 |
| vs월봉MA10(%) / vs월봉MA20(%) | % | 월봉 |
| 통과TF | str | 시그널 잡힌 TF (예: `"1W,1M"`) |
| 큰흐름정합도 | `N/5` | 5 TF 중 MA20 각도 양수인 TF 수 — 클수록 큰 흐름 다 상승추세 |

## 전제 조건

- `data/cache/{asset}/_ma_touch.parquet` 가 존재해야 함. 없으면 메시지 출력 후 종료.
- 새로 생성하려면 `scripts.{kr,crypto,nasdaq}.ma_touch.recommend` 먼저 실행.

## 의도

- 사용자가 차트 열기 전 한눈에 "오늘 통과 종목 + 어디 위치인지" 확인용
- `통과TF` + `큰흐름정합도` 조합으로 신호 강도 판단:
  - 1M 통과 + 5/5 = 모든 TF 상승 = 가장 강한 자리
  - 1D 통과 + 1/5 = 단기 자리 + 큰 흐름 약함 = 검증 필요
