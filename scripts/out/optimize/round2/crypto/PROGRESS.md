# Round 2 — Crypto Progress

Started: 2026-05-17

## Plan

| Task | Status | Notes |
|---|---|---|
| 1. 1h grid (trend_chase + pullback) | DONE | best: chase th=60 hold168h_trail20 S=4.05, pullback th=75 hold336h_trail20_cut5h S=8.23 |
| 2. Classification group split | DONE | trend=297 follower=6 whale=20 junk=228 (단순분류). pullback 1d 트렌드 그룹은 th=80 권장 |
| 3. BTC trend filter | DONE | chase EMA200 위에서 mean ↑, pullback EMA200 아래에서 Sharpe ↑ |
| 4. OOS validation | DONE | 모든 Round 1 best 가 OOS Sharpe 음수 (-1.07 ~ -7.67) |
| 5. (optional) Cluster concurrency cap | skip | 시간 한도 |

## Pre-flight

- `data/cache/crypto/classification.parquet` 가 **없음** — `crypto-classify` 미실행 상태. Task 2 는 별도 분류 생성 필요.
- 1h 캐시 553 종목, 1d 캐시 553 종목.
- 1h 그리드 가벼운 구성: top100 × th{60,70,75,80,85,90} × rules ~6개 ≈ 3.6k cell summarize.

## Log
