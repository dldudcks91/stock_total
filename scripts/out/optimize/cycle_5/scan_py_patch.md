# `alerts/scan.py` — 자산별 score_threshold 분리 패치

## 배경

현재 `DEFAULT_SCORE_THRESHOLD = 80.0` 단일값이 KR/US/Crypto 모두에 적용됨.
Cycle 1+4 결과는 자산별 최적이 다름을 보임:

| 자산 | 권장 th | 근거 |
|---|---|---|
| kr | **60** | Cyc1 OOS Sharpe 24.83 @ th=60 (24.86 @ th=70 거의 동등, but n +5%) |
| us | **70** | Cyc1 OOS Sharpe 22.08 @ th=70 (peak; 60: 19.88, 80: 18.97) |
| crypto | **75** | Cyc4 trend_pullback 1h Sharpe 8.23 @ th=75 (plateau peak) |

기본값 80 은 KR/US 에서 너무 보수 (alert 빈도 ↓ + Sharpe ~10% 손실), Crypto 에서는 1h 와 1d 가 다른 임계가 필요한데 단일값으로 불가.

---

## 패치 (구체 diff)

`alerts/scan.py` line 27 ~ 35:

```python
# ── BEFORE ─────────────────────────────────────────────────────────────
DEFAULT_SCORE_THRESHOLD = 80.0


def scan_new(
    asset: str,
    *,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    persist: bool = True,
) -> List[dict]:
```

```python
# ── AFTER ──────────────────────────────────────────────────────────────
# 자산별 권장 threshold (Cycle 1+4 OOS 검증 결과).
# - kr: trend_pullback 1d, Cyc1 OOS Sharpe 24.83 @ th=60
# - us: trend_pullback 1d, Cyc1 OOS Sharpe 22.08 @ th=70 (peak)
# - crypto: trend_pullback 1h, Cyc4 Sharpe 8.23 @ th=75 (plateau peak)
RECOMMENDED_THRESHOLD: dict[str, float] = {
    "kr": 60.0,
    "us": 70.0,
    "crypto": 75.0,
}
DEFAULT_SCORE_THRESHOLD = 80.0  # fallback (자산 미지정 시)


def scan_new(
    asset: str,
    *,
    score_threshold: Optional[float] = None,
    persist: bool = True,
) -> List[dict]:
    if score_threshold is None:
        score_threshold = RECOMMENDED_THRESHOLD.get(asset, DEFAULT_SCORE_THRESHOLD)
```

함수 본문 (`cur = recs[recs["rec_score"] >= score_threshold].copy()` 이하) 그대로 유지.

---

## CLI 변경 (line 110 ~ 117)

`--threshold` 의 default 를 None 으로 바꿔 명시적 override 의도를 살림:

```python
# ── BEFORE ─────────────────────────────────────────────────────────────
ap.add_argument("--threshold", type=float, default=DEFAULT_SCORE_THRESHOLD)
...
items = scan_new(args.asset, score_threshold=args.threshold, persist=not args.no_persist)
```

```python
# ── AFTER ──────────────────────────────────────────────────────────────
ap.add_argument(
    "--threshold",
    type=float,
    default=None,
    help=(
        "score_threshold override. 미지정 시 자산별 권장값 사용 "
        f"(kr:{RECOMMENDED_THRESHOLD['kr']}, us:{RECOMMENDED_THRESHOLD['us']}, "
        f"crypto:{RECOMMENDED_THRESHOLD['crypto']})"
    ),
)
...
items = scan_new(args.asset, score_threshold=args.threshold, persist=not args.no_persist)
```

`scan_new` 가 `None` 을 받으면 `RECOMMENDED_THRESHOLD[asset]` 로 떨어지므로 CLI 호출 변경 없음.

---

## 호환성

- 외부에서 `scan_new(asset, score_threshold=80.0)` 처럼 명시 호출하는 코드는 영향 없음.
- 기존 default 동작 (`scan_new("kr")` → th=80) 은 **변경됨** (`th=60`). 의도된 변경 — Cyc1 결과 반영.
- `alerts/run.py` 가 `scan_new(asset)` 만 호출한다면 자동으로 새 권장값 사용.

## 적용 후 검증

```powershell
# 자산별 dry-run (state 갱신 X)
.venv/Scripts/python.exe -m alerts.scan --asset kr --no-persist
.venv/Scripts/python.exe -m alerts.scan --asset us --no-persist
.venv/Scripts/python.exe -m alerts.scan --asset crypto --no-persist
```

기대: KR/US 알림 종목 수가 기존 (th=80) 대비 1.3~1.5x 증가, Crypto 는 비슷하거나 약간 증가.
