# Round 3 Walk-forward — Agent W 진행 로그

목적: Round 2 (KR/US) 의 OOS Sharpe 가 IS 보다 높은 현상이 강세장 의존인지
6개 1년 sliding window 로 regime-fair 하게 검증.

Round 2 권장 룰 (출발점):
- KR trend_pullback 1d, th=60, hold=252d, trail=25%, TP=40%
- KR trend_pullback 1w, th=75, hold=78w, trail=20%, TP=40%
- KR trend_chase    1d, th=60, hold=365d, trail=25%, TP=40%
- US trend_pullback 1d, th=70, hold=252d, trail=20%, TP=30%
- US trend_pullback 1w, th=70, hold=52w,  trail=20%, TP=30%
- US trend_chase    1d, th=60, hold=252d, trail=20%, TP=30%

Windows:
- W1 2020-05~2021-05
- W2 2021-05~2022-05
- W3 2022-05~2023-05
- W4 2023-05~2024-05
- W5 2024-05~2025-05
- W6 2025-05~2026-05-18

- [2026-05-17 18:29:06] [cache] US build trend_pullback/1d top=300
- [2026-05-17 18:29:22] [cache] US trend_pullback/1d -> 295 symbols (15.5s)
- [2026-05-17 18:29:38] === Agent W start: task1 ===
- [2026-05-17 18:29:38] task1 start — 6 sliding windows × 6 recommendations
- [2026-05-17 18:29:38]   evaluating kr_trend_pullback_1d (th=60, hold=252, trail=0.25, TP=0.4)
- [2026-05-17 18:29:38] [cache] KR build trend_pullback/1d top=800
- [2026-05-17 18:29:53] [cache] KR trend_pullback/1d -> 799 symbols (14.7s)
- [2026-05-17 18:29:59] [indices] fetched KOSPI (2053,) NASDAQ (2104,)
- [2026-05-17 18:30:05]   evaluating kr_trend_pullback_1w (th=75, hold=78, trail=0.2, TP=0.4)
- [2026-05-17 18:30:05] [cache] KR build trend_pullback/1w top=800
- [2026-05-17 18:30:26] [cache] KR trend_pullback/1w -> 797 symbols (21.0s)
- [2026-05-17 18:30:28]   evaluating kr_trend_chase_1d (th=60, hold=365, trail=0.25, TP=0.4)
- [2026-05-17 18:30:28] [cache] KR build trend_chase/1d top=800
- [2026-05-17 18:30:39] [cache] KR trend_chase/1d -> 799 symbols (11.4s)
- [2026-05-17 18:30:43]   evaluating us_trend_pullback_1d (th=70, hold=252, trail=0.2, TP=0.3)
- [2026-05-17 18:30:43] [cache] US build trend_pullback/1d top=300
- [2026-05-17 18:30:58] [cache] US trend_pullback/1d -> 295 symbols (14.2s)
- [2026-05-17 18:31:34] === Agent W start: task1 ===
- [2026-05-17 18:31:34] task1 start — 6 sliding windows × 6 recommendations
- [2026-05-17 18:31:34]   evaluating kr_trend_pullback_1d (th=60, hold=252, trail=0.25, TP=0.4)
- [2026-05-17 18:31:34] [cache] KR build trend_pullback/1d top=800
- [2026-05-17 18:31:48] [cache] KR trend_pullback/1d -> 799 symbols (14.1s)
- [2026-05-17 18:31:59]   evaluating kr_trend_pullback_1w (th=75, hold=78, trail=0.2, TP=0.4)
- [2026-05-17 18:31:59] [cache] KR build trend_pullback/1w top=800
- [2026-05-17 18:32:20] [cache] KR trend_pullback/1w -> 797 symbols (20.7s)
- [2026-05-17 18:32:21]   evaluating kr_trend_chase_1d (th=60, hold=365, trail=0.25, TP=0.4)
- [2026-05-17 18:32:21] [cache] KR build trend_chase/1d top=800
- [2026-05-17 18:32:32] [cache] KR trend_chase/1d -> 799 symbols (11.2s)
- [2026-05-17 18:32:36]   evaluating us_trend_pullback_1d (th=70, hold=252, trail=0.2, TP=0.3)
- [2026-05-17 18:32:36] [cache] US build trend_pullback/1d top=300
- [2026-05-17 18:32:51] [cache] US trend_pullback/1d -> 295 symbols (14.4s)
- [2026-05-17 18:33:02]   evaluating us_trend_pullback_1w (th=70, hold=52, trail=0.2, TP=0.3)
- [2026-05-17 18:33:02] [cache] US build trend_pullback/1w top=300
- [2026-05-17 18:33:14] [cache] US trend_pullback/1w -> 288 symbols (12.1s)
- [2026-05-17 18:33:17]   evaluating us_trend_chase_1d (th=60, hold=252, trail=0.2, TP=0.3)
- [2026-05-17 18:33:17] [cache] US build trend_chase/1d top=300
- [2026-05-17 18:33:32] [cache] US trend_chase/1d -> 295 symbols (15.0s)
- [2026-05-17 18:33:41] task1 done
- [2026-05-17 18:33:41] === Agent W done (126.7s) ===
- [2026-05-17 18:33:54] === Agent W start: task2 ===
- [2026-05-17 18:33:54] task2 start — regime tag per window
- [2026-05-17 18:33:54] task2 done
- [2026-05-17 18:33:54] === Agent W done (0.2s) ===
- [2026-05-17 18:34:04] === Agent W start: task3 ===
- [2026-05-17 18:34:04] task3 start — anchored walk-forward
- [2026-05-17 18:34:04]   anchored kr_trend_pullback_1d
- [2026-05-17 18:34:04] [cache] KR build trend_pullback/1d top=800
- [2026-05-17 18:34:17] [cache] KR trend_pullback/1d -> 799 symbols (12.4s)
- [2026-05-17 18:34:49]   anchored kr_trend_pullback_1w
- [2026-05-17 18:34:49] [cache] KR build trend_pullback/1w top=800
- [2026-05-17 18:35:09] [cache] KR trend_pullback/1w -> 797 symbols (20.5s)
- [2026-05-17 18:35:13]   anchored kr_trend_chase_1d
- [2026-05-17 18:35:13] [cache] KR build trend_chase/1d top=800
- [2026-05-17 18:35:24] [cache] KR trend_chase/1d -> 799 symbols (11.0s)
- [2026-05-17 18:35:36]   anchored us_trend_pullback_1d
- [2026-05-17 18:35:36] [cache] US build trend_pullback/1d top=300
- [2026-05-17 18:35:50] [cache] US trend_pullback/1d -> 295 symbols (13.7s)
- [2026-05-17 18:36:11]   anchored us_trend_pullback_1w
- [2026-05-17 18:36:11] [cache] US build trend_pullback/1w top=300
- [2026-05-17 18:36:23] [cache] US trend_pullback/1w -> 288 symbols (11.5s)
- [2026-05-17 18:36:27]   anchored us_trend_chase_1d
- [2026-05-17 18:36:27] [cache] US build trend_chase/1d top=300
- [2026-05-17 18:36:41] [cache] US trend_chase/1d -> 295 symbols (13.5s)
- [2026-05-17 18:36:53] task3 done
- [2026-05-17 18:36:53] === Agent W done (168.4s) ===
- [2026-05-17 18:37:05] === Agent W start: task4 ===
- [2026-05-17 18:37:05] task4 start — macro gate (index EMA200 / 6m ROC)
- [2026-05-17 18:37:05]   macro-gate kr_trend_pullback_1d
- [2026-05-17 18:37:05] [cache] KR build trend_pullback/1d top=800
- [2026-05-17 18:37:17] [cache] KR trend_pullback/1d -> 799 symbols (12.4s)
- [2026-05-17 18:37:43]   macro-gate kr_trend_pullback_1w
- [2026-05-17 18:37:43] [cache] KR build trend_pullback/1w top=800
- [2026-05-17 18:38:02] [cache] KR trend_pullback/1w -> 797 symbols (20.0s)
- [2026-05-17 18:38:05]   macro-gate kr_trend_chase_1d
- [2026-05-17 18:38:05] [cache] KR build trend_chase/1d top=800
- [2026-05-17 18:38:16] [cache] KR trend_chase/1d -> 799 symbols (11.6s)
- [2026-05-17 18:38:25]   macro-gate us_trend_pullback_1d
- [2026-05-17 18:38:25] [cache] US build trend_pullback/1d top=300
- [2026-05-17 18:38:39] [cache] US trend_pullback/1d -> 295 symbols (13.6s)
- [2026-05-17 18:38:52]   macro-gate us_trend_pullback_1w
- [2026-05-17 18:38:52] [cache] US build trend_pullback/1w top=300
- [2026-05-17 18:39:04] [cache] US trend_pullback/1w -> 288 symbols (11.6s)
- [2026-05-17 18:39:06]   macro-gate us_trend_chase_1d
- [2026-05-17 18:39:06] [cache] US build trend_chase/1d top=300
- [2026-05-17 18:39:19] [cache] US trend_chase/1d -> 295 symbols (13.3s)
- [2026-05-17 18:39:25] task4 done
- [2026-05-17 18:39:25] === Agent W done (140.0s) ===

## Final summary (Agent W)

Tasks 1-4 complete in ~8 minutes. Outputs:
- task1_all.csv / task1_sharpe_matrix.csv / task1_{asset}_{strategy}_{iv}.csv
- task2_regime.csv / task2_regime_x_sharpe.csv / task2_corr.csv
- task3_anchored.csv / task3_oos_sharpe_pivot.csv
- task4_macro_gate.csv
- _indices.parquet (KOSPI/NASDAQ daily close cache)
- task1.log / task2.log / task3.log / task4.log

Sharpe matrix (Task1):
| asset/strat/iv  | W1     | W2     | W3    | W4    | W5    | W6    | mean  | std   | pos% |
| KR pullback 1d  |  90.03 | -24.59 | -0.32 |  0.89 | 11.50 | 41.39 | 19.82 | 36.97 | 67%  |
| KR pullback 1w  |  25.47 | -17.70 |  1.18 | 10.55 | 27.75 | 27.60 | 12.47 | 16.70 | 83%  |
| KR chase    1d  |  35.91 | -15.50 | -0.57 |  6.32 | 17.82 | 11.26 |  9.21 | 15.84 | 67%  |
| US pullback 1d  |  45.40 |  -5.86 | 11.77 | 18.31 | 10.39 | 31.45 | 18.58 | 16.31 | 83%  |
| US pullback 1w  |  25.48 |  -6.67 | 10.36 | 16.19 |  7.10 | 12.94 | 10.90 |  9.73 | 83%  |
| US chase    1d  |  11.86 |  -5.52 |  5.01 | 10.99 |  7.94 |  5.27 |  5.92 |  5.73 | 83%  |

Regime (Task2):
W1 bull(+66/+62), W2 bear(-14/-11), W3 side(-7/-3), W4 side/bull(+7/+28),
W5 side/bull(-5/+12), W6 bull(+193/+48).

corr(index ret%, Sharpe):
US pullback 1d 0.96  (강한 regime 추수)
US pullback 1w 0.85
US chase    1d 0.70
KR pullback 1d 0.58
KR pullback 1w 0.57
KR chase    1d 0.36

Macro gate (Task4, full 6y):
- KR pullback 1d: none 23.69 → ema200 26.57 (+2.88, mean% +30%)  ← 의미있는 개선
- 나머지: Sharpe 거의 무차별, mean%/PF 는 일관되게 향상, 거래수 25-35% 감소

Anchored OOS Sharpe (Task3) - IS_size↑ 와 OOS Sharpe 의 monotone 관계 없음
→ stability 가 아니라 regime contribution 이 dominant.

판정: Round 2 의 높은 OOS Sharpe 는 2024-05~2026-05 강세장 contribution이 dominant.
모든 전략이 W2 약세장에서 음수 Sharpe. KR pullback 1d 가 가장 regime-dependent
(std 36.97), US pullback 1w / US chase 1d 가 가장 robust (std 9.73 / 5.73).
