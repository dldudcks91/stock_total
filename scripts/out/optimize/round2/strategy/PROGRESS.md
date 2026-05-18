# Agent S — Strategy Deep-Tune (Round 2)

Round 1 은 score_threshold 만 튜닝 → 이번 라운드는 **score 를 만드는 파라미터 자체**.

## 진행

- [start] PROGRESS.md 생성. 인프라 검토 — `scripts/optimize/threshold_grid.py` 의 `collect_entries` / `run_grid` 재사용 가능.
  - threshold_grid.py 가 base_params 를 인자로 받게 되어 있어 그리드 러너에서 strategy params 만 override 하면 됨.
  - 단 collect_entries 는 params 1세트로 score 시계열을 1번 계산. 따라서 새 그리드 러너는 "(asset, strategy, interval, params)" 별로 collect_entries 를 새로 호출.

## Tasks

- [ ] Task 1 — trend_pullback 진입 파라미터 그리드 (KR/US 1d)
- [ ] Task 2 — trend_chase 진입 파라미터 그리드 (KR/US 1d)
- [ ] Task 3 — quiet_bottom_v2 보강 지표 (KR/US 1w)
- [ ] Task 4 (옵션) — Ensemble composite_score (chase+pullback)
