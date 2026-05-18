# Cycle 2 — 청산 룰 정밀 그리드 (Stage A 결과)

**완료**: 2026-05-17 18:08 KST
**대상**: Cycle 1 OOS 생존 6 조합
**그리드**: trail {15,20,25}% × TP {20,30,None} × hold (1d: {60,120,252}; 1w: {26,52,104}) = 27셀/조합

## 자산·전략별 Best 청산 룰

| asset | strategy | itv | score_th | best (trail/TP/hold) | Sharpe_full | Sharpe_oos | mean% | win% | n |
|---|---|---|---|---|---|---|---|---|---|
| **KR** | **trend_pullback** | 1d | 60 | **25 / 30 / 252** | **21.53** | **17.72** | +10.75 | 57.0 | 18143 |
| **US** | **trend_pullback** | 1d | 70 | **25 / 30 / 252** | **22.01** | 13.90 | +10.32 | 58.0 | 19038 |
| KR | trend_chase | 1d | 60 | 25 / 30 / 252 | 7.98 | **9.12** | +7.94 | 53.0 | 4011 |
| US | trend_chase | 1d | 60 | 15 / 30 / 252 | 5.35 | 3.82 | +5.57 | 47.3 | 2202 |
| KR | quiet_bottom | 1w | binary | 25 / 30 / 104w | 6.24 | 3.38 | +18.63 | 65.4 | 607 |
| US | quiet_bottom | 1w | binary | 25 / 20 / 104w | 4.78 | 3.36 | +15.47 | 73.3 | 404 |

## 검증된 룰 (hold_252d+trail20+TP30 / hold_52w+trail20+TP30) 대비 개선폭

| 조합 | 검증 Sharpe_full | Cycle2 Sharpe_full | 개선 | OOS 개선 |
|---|---|---|---|---|
| KR trend_pullback 1d | 18.40 | **21.53** | +17% | +24% (14.83→17.72) |
| US trend_pullback 1d | 19.76 | **22.01** | +11% | -30% (19.71→13.90) ⚠ |
| KR trend_chase 1d | 7.23 | 7.98 | +10% | -25% (12.17→9.12) ⚠ |
| US trend_chase 1d | 5.74 | 5.35 | -7% | -41% (6.46→3.82) ⚠ |
| KR quiet_bottom 1w | 5.70 (52w) | 6.24 (104w) | +9% | -23% (4.36→3.38) |
| US quiet_bottom 1w | 4.01 (52w) | 4.78 (104w) | +19% | -33% (5.01→3.36) |

**핵심 발견**:
- **trail 25%** 가 모든 stock 조합에서 dominant (US trend_chase 만 예외 — trail 15% 가 OOS 안정성 우위).
- **hold 252d (≈ 12개월)** 이 1d 전략 모두에서 최적. 짧게(60d) 잡으면 trend 자르고, 길게 가도 252d 가 plateau 상단.
- **TP 30%** 이 거의 모든 조합에서 우위. TP 20% 는 너무 짧게 익절 → mean%↓. TP None 은 변동성↑ Sharpe↓.
- quiet_bottom 1w 에서 **hold 104w (2년)** 가 52w 대비 mean% +20% 개선 — bottoming 후 본격 상승까지 더 길게 줘야 함.
- **OOS 악화 경고**: 청산 룰 정밀 튜닝이 full Sharpe 는 개선했지만 OOS 가 떨어진 조합 다수. **Overfit risk** — 청산 룰 fine-tuning 은 신중. 검증된 trail20/TP30 가 더 안전할 가능성.

## Plateau 영역 (KR trend_pullback 1d, 27셀 heatmap 요약)

| trail \ TP | TP20 | TP30 | TPNone |
|---|---|---|---|
| 15% / hold 60 | 12.4 | 12.9 | 10.7 |
| 15% / hold 252 | 14.0 | 15.5 | 14.0 |
| 20% / hold 252 | 18.5 | 19.5 | 17.5 |
| **25% / hold 252** | **20.5** | **21.5** | 18.5 |

→ **trail 20~25 × TP 30 × hold 120~252** 가 안정적 plateau (Sharpe 18~22). 이 영역 내에서 fine-tuning 의미 작음.

## Cycle 3 에 넘길 권장 청산 룰 (보조 게이트 그리드 baseline)

| asset | strategy | itv | exit rule | 비고 |
|---|---|---|---|---|
| KR | trend_pullback | 1d | **trail25 + TP30 + hold252** | OOS 17.72 — 검증룰 대비 진짜 개선 |
| US | trend_pullback | 1d | **trail20 + TP30 + hold252** (보수) | Cycle2 best 는 trail25 지만 OOS decay 큼. trail20 fallback. |
| KR | trend_chase | 1d | **trail20 + TP30 + hold252** (보수) | 검증룰 유지 |
| US | trend_chase | 1d | **trail15 + TP30 + hold252** | OOS 안정 |
| KR | quiet_bottom | 1w | **trail20 + TP30 + hold52w** (보수) | 104w 도 OK 지만 검증치 보존 |
| US | quiet_bottom | 1w | **trail20 + TP30 + hold52w** | 동일 |

## OOS overfit 가설

Stage B (fine grid trail±5/TP±5/hold±60) 는 **돌리지 않음**. 이유:
- Stage A 가 이미 27셀 × 6조합 = 162 셀. fine grid 는 162 × 6 = 972 셀 추가.
- Stage A 결과가 plateau 형태 → fine grid 는 노이즈 잡을 가능성 큼.
- OOS decay 패턴이 이미 overfit 경고 → 더 짜내면 OOS 안정성 더 떨어질 위험.
- **Cycle 3 (entry gate)** + **Cycle 4 (universe sensitivity)** 가 더 가치 있음.

## 다음 (Cycle 3)
- KR/US trend_pullback 1d 의 rally_lookback / depth_lookback 변형
- KR/US trend_chase 1d 의 amount_lookback / fresh_big_th 변형
- 주봉 SMA 필터 (KR/US 1d 에 추가) — long-term trend filter 로 OOS robustness 개선 가능성 큼
