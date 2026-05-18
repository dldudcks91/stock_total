# 전략 DEFAULT_PARAMS 갱신 — PR 후보 (선택, 주의 필요)

## 권장 변경 3건

| 파일 | 키 | Before | After | 효과 (Cycle 3 OAT) |
|---|---|---|---|---|
| `backtest/strategies/trend_chase.py:61` | `fresh_big_th` | 0.05 | **0.08** | KR OOS Sharpe 12.32→**15.96** (+30%), US 6.79→**10.09** (+49%), n 2.2x |
| `backtest/strategies/quiet_bottom.py:63` | `dd_avg_max` | -0.45 | **-0.40** | KR OOS Sharpe 4.41→**6.83** (+55%), US 4.96→**6.43** (+30%), n 1.5x |
| `backtest/strategies/trend_pullback.py:61` | `rally_lookback` | 60 | **60 유지** | KR 만 90 이 dominant (+18%), US 는 60 best. **KR-only override 권장** |

---

## ⚠ 주의 — DEFAULT 변경의 부작용

`backtest/strategies/*.py` 의 `DEFAULT_PARAMS` 변경은 **모든 자산·인터벌의 호출에 영향**.

- `_STRATEGY_SPECS_STOCK` / `_STRATEGY_SPECS_CRYPTO` 의 빈 dict `{}` 행이 DEFAULT 를 그대로 사용 → 자동 변경됨
- spec 에서 명시 override 한 행은 영향 없음

### 영향 표

| spec 행 | trend_chase fresh_big_th | trend_pullback rally_lookback | quiet_bottom dd_avg_max |
|---|---|---|---|
| stock chase 1d `{}` | **영향 받음** | - | - |
| stock chase 1w `{base_lookback,...}` | override (영향 X) | - | - |
| stock pullback 1d `{}` | - | **영향 받음 (60→60 유지면 무변)** | - |
| stock pullback 1w `{rally_lookback:26}` | - | override | - |
| stock pullback 1m `{rally_lookback:12, ...}` | - | override | - |
| stock quiet 1w `{}` | - | - | **영향 받음** |
| crypto chase 1h/4h/1d/1w | override (모두 명시) | - | - |
| crypto pullback 1h/4h `{rally_lookback,...}` | - | override | - |
| crypto pullback 1d `{}` | - | **영향 받음 (60→60 유지면 무변)** | - |
| crypto quiet 1w `{}` | - | - | **영향 받음** |

→ `trend_chase.py` 의 `fresh_big_th 0.05→0.08` 은 **stock chase 1d** spec 만 영향 (1w 는 override). 안전.
→ `quiet_bottom.py` 의 `dd_avg_max -0.45→-0.40` 은 **stock quiet 1w + crypto quiet 1w** 영향. Crypto quiet 는 `STRATEGY_SPECS_patch.md` 에서 제거 예정이므로 사실상 stock 만.
→ `trend_pullback.py` 의 `rally_lookback` 은 KR/US 양쪽이 같은 default 를 공유 — US 는 60 best, KR 만 90 best. **DEFAULT 변경 금지**, spec override 가 안전.

---

## 권장 적용 방식 (안전 순)

### 방식 A — spec override (안전, 권장)

`dashboards/_recommendation.py` 의 `_STRATEGY_SPECS_STOCK` 만 수정. DEFAULT_PARAMS 는 그대로.

```python
_STRATEGY_SPECS_STOCK: list[tuple[str, str, str, object, int, str, dict]] = [
    # 추격 — Cycle 3: fresh_big_th 0.08 이 KR/US 양 자산 dominant (+30~49% OOS Sharpe)
    ("추격", "chase",    "1d", trend_chase,    70,  "score",  {"fresh_big_th": 0.08}),
    ("추격", "chase",    "1w", trend_chase,    30,  "score",  {"base_lookback": 26, "fresh_big_th": 0.10, "max_prior_extension": 0.60}),
    # 수렴 — KR 만 rally_lookback=90 이 dominant (+18%). US 는 60 best → asset-specific 가 이상적
    # 임시 절충: KR/US 공통은 60 유지. KR 만 따로 분리하려면 asset 인자 추가 필요 (별도 PR)
    ("수렴", "pullback", "1d", trend_pullback, 70,  "score",  {}),
    ("수렴", "pullback", "1w", trend_pullback, 30,  "score",  {"rally_lookback": 26}),
    ("수렴", "pullback", "1m", trend_pullback, 24,  "score",  {"rally_lookback": 12, "depth_lookback": 12, "react_volume_ma": 12}),
    # 바닥 — Cycle 3: dd_avg_max=-0.40 이 KR/US 양 자산 dominant (+30~55% OOS Sharpe)
    ("바닥", "quiet",    "1w", quiet_bottom,   120, "binary", {"dd_avg_max": -0.40}),
]
```

장점: 자산·전략별 fine-grained 통제. backtest 베이스라인 (DEFAULT_PARAMS) 보존.
단점: spec 행이 길어짐.

### 방식 B — DEFAULT_PARAMS 직접 갱신 (간결, 위험)

- `trend_chase.py:61` `"fresh_big_th": 0.05,` → `"fresh_big_th": 0.08,`
- `quiet_bottom.py:63` `"dd_avg_max": -0.45,` → `"dd_avg_max": -0.40,`
- `trend_pullback.py:61` **변경 금지** (US 영향)

장점: 코드 minimal, backtest CLI / batch_runner 도 자동 혜택.
단점: 모든 호출자에 영향. backtest reproducibility (이전 결과 재현) 깨짐. PR description 에 명시 필수.

### 방식 C — KR 자산 specific rally_lookback (asset-aware)

KR 만 `rally_lookback=90` 적용하려면 `compute_recommendations()` 에 asset 정보를 spec 단계에서 분기 필요. 현 구조 (`_STRATEGY_SPECS_STOCK` 가 KR/US 공유) 로는 불가능.

가장 가벼운 변경: `_STRATEGY_SPECS_STOCK` 을 `_STRATEGY_SPECS_KR` / `_STRATEGY_SPECS_US` 로 분리. 또는 `compute_recommendations(asset=...)` 에서 asset 별 dict override 주입.

→ **별도 PR 권장** (구조 변경 동반).

---

## 적용 후 검증 (어떤 방식이든)

```powershell
# precompute 강제 재실행 (recs.parquet 무효화)
.venv/Scripts/python.exe -m dashboards._precompute --asset kr --force
.venv/Scripts/python.exe -m dashboards._precompute --asset us --force

# 알림 dry-run 으로 빈도 / 라벨 변화 확인
.venv/Scripts/python.exe -m alerts.scan --asset kr --no-persist
.venv/Scripts/python.exe -m alerts.scan --asset us --no-persist
```

기대: 같은 종목 풀에서 trend_chase 신호 개수 증가 (fresh_big_th 0.08 → 더 큰 양봉만 ★ 강한 게이트지만 score 분포 자체는 변동), quiet_bottom 신호 개수 증가 (-0.40 → 덜 깊은 바닥도 통과).

---

## Rollback

방식 A — spec 의 override dict 만 비우면 원복.
방식 B — 숫자만 되돌리면 원복.
어느 쪽이든 git revert 1 커밋으로 충분.

---

## 권장 (요약)

- **방식 A** 가 가장 안전. 본 미션 산출물의 1차 추천.
- **방식 B** 는 backtest 베이스라인을 명시적으로 갱신하고 싶을 때만 (PR 본문에 "DEFAULT_PARAMS 갱신: Cycle 3 OAT 검증 결과 반영" 명시 + 기존 cycle_1/2 결과 재현 불가 안내).
- **rally_lookback=90 (KR-only)** 은 구조 변경이 필요하므로 cycle 6 또는 별도 PR 로 미루는 게 합리적.
