# `dashboards/_recommendation.py` — `_STRATEGY_SPECS_CRYPTO` 패치

## 배경 (Cycle 1+4 결과)

| 조합 | Cyc1 OOS Sharpe | Cyc4 결과 | 결정 |
|---|---|---|---|
| Crypto chase **1h** | (Cyc4 only) | 4.05 (th=60) → 2.06 (OOS 3yr) | 유지 (보조) |
| Crypto chase **4h** | — | (Cyc1 phase3) Sharpe 0.62 | **제거** |
| Crypto chase 1d | 1.48 → 0.34 (decay) | — | 유지 (한계는 인지) |
| Crypto chase 1w | — | n=1 무용 | **제거** |
| Crypto pullback **1h** | (Cyc4 only) | **8.23** (th=75) — 최고 | **신규 추가, th 권장 75** |
| Crypto pullback **4h** | — | Sharpe -0.31 | **제거** |
| Crypto pullback **1d** | -0.32 (th=60), 1.77 (th=80) | — | **제거** (OOS 붕괴) |
| Crypto pullback 1w | — | Sharpe 2.01 | 유지 (한계는 인지) |
| Crypto quiet_bottom 1w | — | Sharpe 0.27 | **제거** |
| (참고: 4h quiet_bottom -1.14, 1d quiet_bottom 0.61 — 무용) | | | |

목표:
1. **제거**: 4h 전체, quiet_bottom 1w, trend_pullback 1d
2. **추가**: trend_pullback 1h
3. **유지**: chase 1h/1d/1w, pullback 1w

> 1h 는 _STRATEGY_SPECS_CRYPTO 에 이미 chase/pullback 모두 정의돼 있음. 본 패치는 4h/1d (pullback)/quiet_bottom 만 제거.

---

## 패치 (line 51 ~ 105)

`_STRATEGY_SPECS_CRYPTO` 리스트 전체 재정의. 제거 항목은 주석으로 남김.

```python
# ── BEFORE (요약) ──────────────────────────────────────────────────────
_STRATEGY_SPECS_CRYPTO: list[...] = [
    ("추격", "chase", "1h", trend_chase, 280, "score", {...}),
    ("추격", "chase", "4h", trend_chase,  90, "score", {...}),   # 제거
    ("추격", "chase", "1d", trend_chase,  70, "score", {...}),
    ("추격", "chase", "1w", trend_chase,  30, "score", {...}),
    ("수렴", "pullback", "1h", trend_pullback, 280, "score", {...}),
    ("수렴", "pullback", "4h", trend_pullback,  90, "score", {...}),  # 제거
    ("수렴", "pullback", "1d", trend_pullback,  70, "score", {...}),  # 제거
    ("수렴", "pullback", "1w", trend_pullback,  30, "score", {...}),
    ("바닥", "quiet",    "1w", quiet_bottom,   120, "binary", {}),    # 제거
]
```

```python
# ── AFTER ──────────────────────────────────────────────────────────────
# Cycle 1+4 OOS 검증 결과 반영:
#   제거: chase 4h (Sharpe 0.62), pullback 4h (-0.31), pullback 1d (OOS -0.32 ~ 1.77 무너짐),
#         quiet_bottom 1w (Sharpe 0.27)
#   최우선: pullback 1h (Cyc4 Sharpe 8.23 @ th=75, plateau peak) — 알림 임계는 75 권장.
_STRATEGY_SPECS_CRYPTO: list[tuple[str, str, str, object, int, str, dict]] = [
    # ── 추격 (chase) — 1h 보조, 1d/1w 유지하되 신뢰도 한계 인지 ────────
    ("추격", "chase", "1h", trend_chase, 280, "score", {
        "ret_th":  [0.010, 0.015, 0.020, 0.030],
        "ret_pts": [15, 10, 10, 5],
        "base_lookback": 240,        # 10 일
        "fresh_big_th": 0.015,
        "max_prior_extension": 0.20,
        "amount_lookback": 720,      # 30 일치 분위
    }),
    # (제거) ("추격", "chase", "4h", ...): Cyc1 Sharpe 0.62, 인터벌 어중간
    ("추격", "chase", "1d", trend_chase, 70, "score", {
        "ret_th":  [0.04, 0.06, 0.09, 0.13],
        "ret_pts": [15, 10, 10, 5],
        "base_lookback": 60,
        "fresh_big_th": 0.06,
        "max_prior_extension": 0.40,
    }),
    ("추격", "chase", "1w", trend_chase, 30, "score", {
        "ret_th":  [0.08, 0.12, 0.17, 0.25],
        "ret_pts": [15, 10, 10, 5],
        "base_lookback": 26,
        "fresh_big_th": 0.13,
        "max_prior_extension": 0.80,
        "amount_lookback": 100,
    }),
    # ── 수렴 (pullback) — 1h 가 자산군 통틀어 최고 시그널 (Cyc4) ────────
    ("수렴", "pullback", "1h", trend_pullback, 280, "score", {
        "rally_lookback": 168,       # 7 일
        "rally_min_gain": 0.10,
        "depth_lookback": 48,        # 2 일
    }),
    # (제거) ("수렴", "pullback", "4h", ...): Cyc1 Sharpe -0.31
    # (제거) ("수렴", "pullback", "1d", ...): Cyc1 OOS Sharpe -0.32 ~ 1.77 (붕괴)
    ("수렴", "pullback", "1w", trend_pullback, 30, "score", {
        "rally_lookback": 26,
        "rally_min_gain": 0.60,
    }),
    # (제거) ("바닥", "quiet", "1w", ...): Cyc1 Sharpe 0.27 (자산 부적합)
]
```

`_STRATEGY_SPECS_STOCK` 은 변경 없음 (Cyc1+2+3 모두 기존 spec OK).

---

## 부수 영향

- 대시보드 Crypto 표의 "rec_label" 후보가 줄어듦 — 종목당 candidates 가 4h/1d-pullback/quiet 제거로 평균 3 개 감소.
- `pages/3_Bitget.py` 의 추천 필터링 (예: "수렴1h" 우선 표시) 로직 영향 없음 (라벨 자체는 그대로).
- `data/cache/crypto/_recs.parquet` 재계산 필요 — 다음 precompute 실행 시 자동 갱신.

## 적용 후 검증

```powershell
# 재계산
.venv/Scripts/python.exe -m dashboards._precompute --asset crypto --force

# scan 결과 변화 확인 (제거된 라벨이 나오지 않아야 함)
.venv/Scripts/python.exe -m alerts.scan --asset crypto --no-persist
```

기대: "수렴4h", "수렴d", "바닥w" 라벨이 사라지고 "수렴h" / "추격h" / "추격d" / "수렴w" / "추격w" 만 표시.
