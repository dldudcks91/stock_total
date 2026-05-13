# scripts/

일회성 / 분석 / 운영용 스크립트. 모듈로 import 가능 (실행은 `python -m scripts.<group>.<name>`).

## quiet_bottom/

`backtest/strategies/quiet_bottom` 전략 관련 분석·검증·플롯. 13 개 파일이 서로 import 하므로 한 묶음으로 유지.

| 파일 | 역할 |
|---|---|
| `count_slope_turn_signals.py` | 시그널 개수 집계 + 자산별 weekly 로더 (라이브러리 역할 겸함) |
| `forward_returns_top200.py` | KR/US Top200 진입 후 +1w~+8w 수익률 (라이브러리 겸함) |
| `forward_returns_2m_all.py` | 전 종목 2개월 포워드 리턴 |
| `forward_returns_2m_crypto.py` | 크립토 한정 2개월 포워드 |
| `forward_returns_longh.py` | 장기 보유 시 수익률 |
| `forward_returns_slope_turn.py` | slope turn 시점 기준 포워드 |
| `exit_rule_grid.py` | 청산룰 그리드 시뮬레이터 (라이브러리 겸함) |
| `ablation_crypto.py` | 조건별 ablation (크립토) |
| `compare_curl.py` | curl(slope·R²·dd) 임계값 비교 |
| `plot_curl_examples.py` | curl 시각화 |
| `plot_r2_intuition.py` | R² 의미 시각화 |
| `plot_signal_check.py` | 종목별 차트 + 박치기 카운트 |
| `validate_quiet_bottom.py` | KR/US 검증 (시기별/Outlier/종목분할/IS-OOS) |

## spring/

박스권 → 변동성 압축 → 돌파 ("spring") 탐색. 실험적.

| 파일 | 역할 |
|---|---|
| `spring_scan.py` | 단발 스캔 |
| `spring_sweep.py` | 파라미터 스윕 |

## misc/

데이터 수집·마이그레이션·스모크·벤치 등 잡다 단발 스크립트.

| 파일 | 역할 |
|---|---|
| `smoke_bitget.py` | Bitget fetch 스모크 테스트 |
| `bench_bitget_table.py` | Bitget 페이지 표 렌더 벤치 |
| `fetch_us_top200.py` | NASDAQ Top200 일괄 수집 |
| `migrate_crypto_cache_layout.py` | 옛 캐시 레이아웃 → 신 레이아웃 마이그레이션 |
| `run_matrix.py` | 다중 전략 × 다중 인터벌 행렬 백테스트 |
| `compute_baseline.py` | 그룹별 B&H 베이스라인 계산 |

## out/

스크립트 결과물 (CSV·PNG·log) 저장 위치. git tracked — 분석 맥락 보존 용도.

## 실행 예

```bash
.venv/Scripts/python.exe -m scripts.quiet_bottom.validate_quiet_bottom
.venv/Scripts/python.exe -m scripts.spring.spring_scan
```
