"""``_recs.parquet`` → 신규 진입 추천 종목 감지.

규칙:
  - ``rec_score >= score_threshold`` (기본 80) 인 종목만 후보
  - 직전 ``last_seen_{asset}.json`` 에 **없던 symbol** 만 신규로 보고
  - 라벨이 바뀐 종목은 제외 (= 같은 symbol 이 어제도 추천이었으면 알림 X)
  - 부수효과로 state 파일 갱신 — 다음 실행의 baseline

KR/US: rec_score 컷 (이미 dashboards 의 SCORE_THRESHOLD=80 과 같은 값).
Crypto: 같은 규칙이지만 종목 수가 많아 노이즈가 높을 수 있음 — 필요시 임계치 상향.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from alerts.state import load_last_seen, save_last_seen
from dashboards._precompute import load_recs, precompute_status

DEFAULT_SCORE_THRESHOLD = 80.0


def scan_new(
    asset: str,
    *,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    persist: bool = True,
) -> List[dict]:
    """현재 _recs 와 last_seen 을 비교해 신규 추천 종목 리스트 반환.

    Args:
      asset            : "kr" / "us" / "crypto".
      score_threshold  : rec_score 컷오프 (>= 만 알림).
      persist          : True 면 state 파일을 현재 종목 set 으로 갱신.

    Returns:
      [{"symbol", "rec_label", "rec_score", "rec_detail"} ...] — 신규 종목만.
      _recs.parquet 가 없으면 빈 리스트.
    """
    recs = load_recs(asset)
    if recs is None or recs.empty:
        return []
    if "rec_score" not in recs.columns:
        return []

    # 현재 추천 (score 컷). NaN 은 자동 제외 (>= 비교).
    cur = recs[recs["rec_score"] >= score_threshold].copy()
    cur["symbol"] = cur["symbol"].astype(str)
    cur["rec_label"] = cur["rec_label"].astype(str)

    current_map = dict(zip(cur["symbol"], cur["rec_label"]))

    last = load_last_seen(asset)
    new_symbols = [s for s in current_map.keys() if s not in last]

    new_items: List[dict] = []
    if new_symbols:
        rows = cur[cur["symbol"].isin(new_symbols)]
        for r in rows.itertuples(index=False):
            new_items.append({
                "symbol": str(r.symbol),
                "rec_label": str(r.rec_label),
                "rec_score": float(r.rec_score),
                "rec_detail": (str(r.rec_detail) if pd.notna(r.rec_detail) else ""),
            })
        # 점수 내림차순으로 보기 좋게
        new_items.sort(key=lambda x: x["rec_score"], reverse=True)

    if persist:
        status = precompute_status(asset)
        anchor = None  # precompute_status 는 anchor 노출 안함 — None 으로 둠
        save_last_seen(asset, current_map, anchor_ms=anchor)
        _ = status  # 향후 메시지 헤더에 mtime 쓸 자리

    return new_items


def format_message(asset: str, items: List[dict], *, now: Optional[pd.Timestamp] = None) -> str:
    """카카오톡 본문 (≤1000자 권장). items 가 비면 빈 문자열."""
    if not items:
        return ""
    if now is None:
        now = pd.Timestamp.now()
    ts = now.strftime("%Y-%m-%d %H:%M")
    asset_name = {"kr": "KOSPI", "us": "NASDAQ", "crypto": "Crypto"}.get(asset, asset.upper())

    head = f"[{ts} {asset_name}] 신규 롱 후보 {len(items)}건"
    lines = [head, ""]
    # 카톡 본문 길이 제한 (실측 ~1000자) — 최대 20개까지만 본문 표시
    MAX = 20
    for it in items[:MAX]:
        score = int(round(it["rec_score"]))
        lines.append(f"★ {it['symbol']:<10} {it['rec_label']:<6} {score}점")
    if len(items) > MAX:
        lines.append(f"... 외 {len(items) - MAX}건")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────
def _cli() -> int:
    import argparse
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="신규 추천 종목 감지 (state 갱신 + 메시지 출력)")
    ap.add_argument("--asset", required=True, choices=["kr", "us", "crypto"])
    ap.add_argument("--threshold", type=float, default=DEFAULT_SCORE_THRESHOLD)
    ap.add_argument("--no-persist", action="store_true",
                    help="state 파일 갱신 X (dry-run 용)")
    args = ap.parse_args()

    items = scan_new(args.asset, score_threshold=args.threshold, persist=not args.no_persist)
    if not items:
        print(f"[{args.asset}] 신규 추천 없음")
        return 0
    print(format_message(args.asset, items))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
