# Round 2 KR — 진행 로그

Round 1 출발점 (Sharpe ranks):
- trend_pullback 1d, th=60: Sharpe 18.40, n=18143
- trend_pullback 1w, th=75: Sharpe 11.93, n=5550
- trend_chase 1d, th=60: Sharpe 7.23, n=4011
- trend_chase 1w, th=60: Sharpe 2.42, n=81

- [2026-05-17 17:47:17] task1 start: trend_pullback/1d threshold=60 universe_top=300
- [2026-05-17 17:47:19] task1 start: trend_pullback/1w threshold=75 universe_top=300
- [2026-05-17 17:47:22] task1 start: trend_chase/1d threshold=60 universe_top=300
- [2026-05-17 17:47:24] task1 start: trend_chase/1w threshold=60 universe_top=300
- [2026-05-17 17:47:54] task1 done: trend_chase/1w best_sharpe=3.26 rule=h78_tr25_TP40_SLx_cutN elapsed=15.1s
- [2026-05-17 17:50:24] task1 done: trend_pullback/1w best_sharpe=12.82 rule=h78_tr20_TP40_SLx_cutN elapsed=163.1s
- [2026-05-17 17:57:47] task1 done: trend_chase/1d best_sharpe=8.49 rule=h365_tr25_TP40_SLx_cutN elapsed=611.9s
- [2026-05-17 18:15:05] task1 done: trend_pullback/1d best_sharpe=22.35 rule=h252_tr25_TP40_SLx_cutN elapsed=1658.7s
- [2026-05-17 18:15:35] task2 start: trend_pullback/1d threshold=60 IS=2020-05-01~2024-05-01 OOS=2024-05-01~2026-05-18 use_task1_topk=True
- [2026-05-17 18:15:40] task2 start: trend_pullback/1w threshold=75 IS=2020-05-01~2024-05-01 OOS=2024-05-01~2026-05-18 use_task1_topk=True
- [2026-05-17 18:15:44] task2 start: trend_chase/1d threshold=60 IS=2020-05-01~2024-05-01 OOS=2024-05-01~2026-05-18 use_task1_topk=True
- [2026-05-17 18:15:45] task2 start: trend_chase/1w threshold=60 IS=2020-05-01~2024-05-01 OOS=2024-05-01~2026-05-18 use_task1_topk=True
- [2026-05-17 18:15:47] task3 start: trend_pullback/1d threshold=60 sizes=[100, 300, 500, 1000] rule=h252_tr20_TP30
- [2026-05-17 18:16:10] task2 done: trend_chase/1w IS_best_sharpe=2.24 OOS_sharpe_at_IS_best=6.0 robust=267.9% elapsed=6.0s
- [2026-05-17 18:16:24] task2 done: trend_pullback/1w IS_best_sharpe=5.66 OOS_sharpe_at_IS_best=23.22 robust=410.2% elapsed=27.6s
- [2026-05-17 18:16:38] task3 done: trend_pullback/1d elapsed=50.3s
- [2026-05-17 18:16:58] task2 done: trend_chase/1d IS_best_sharpe=5.15 OOS_sharpe_at_IS_best=12.67 robust=246.0% elapsed=60.7s
- [2026-05-17 18:18:06] task2 done: trend_pullback/1d IS_best_sharpe=17.46 OOS_sharpe_at_IS_best=30.93 robust=177.1% elapsed=143.3s
- [2026-05-17 18:18:31] task3 start: trend_pullback/1d threshold=60 sizes=[100, 300, 500, 800, -1] rule=h252_tr20_TP30
- [2026-05-17 18:18:36] task3 start: trend_pullback/1w threshold=75 sizes=[100, 300, 500, 800, -1] rule=h52w_tr20_TP30
- [2026-05-17 18:18:37] task3 start: trend_chase/1d threshold=60 sizes=[100, 300, 500, 800, -1] rule=h252_tr20_TP30
- [2026-05-17 18:19:15] task4 start: trend_pullback/1d threshold=60 rule=h252_tr25_TP40
- [2026-05-17 18:19:47] task4 done: trend_pullback/1d elapsed=22.8s
- [2026-05-17 18:19:59] task3 done: trend_chase/1d elapsed=82.6s
- [2026-05-17 18:20:28] task3 done: trend_pullback/1d elapsed=116.8s
- [2026-05-17 18:20:34] task3 done: trend_pullback/1w elapsed=118.0s
