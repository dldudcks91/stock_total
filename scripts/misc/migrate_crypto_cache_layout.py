"""구 레이아웃(flat) → 신 레이아웃(gran 서브디렉터리)으로 크립토 캐시 이동.

Before: data/cache/crypto/bitget_{SYMBOL}_{gran}.parquet
After : data/cache/crypto/{gran}/{SYMBOL}.parquet

dry-run 기본. --apply 시 실제 이동.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "crypto"
PATTERN = re.compile(r"^bitget_(?P<sym>.+)_(?P<gran>1h|4h|1d|1w|1M)\.parquet$")
VALID_GRANS = {"1h", "4h", "1d", "1w", "1M"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 이동 수행 (기본은 dry-run)")
    args = ap.parse_args()

    if not CACHE_DIR.exists():
        print(f"cache dir 없음: {CACHE_DIR}")
        return

    moves: list[tuple[Path, Path]] = []
    skipped: list[Path] = []

    for p in sorted(CACHE_DIR.iterdir()):
        if not p.is_file():
            continue
        m = PATTERN.match(p.name)
        if not m:
            skipped.append(p)
            continue
        sym, gran = m.group("sym"), m.group("gran")
        dst = CACHE_DIR / gran / f"{sym}.parquet"
        moves.append((p, dst))

    print(f"이동 대상: {len(moves)}개")
    print(f"건너뜀:    {len(skipped)}개")
    if skipped:
        for s in skipped:
            print(f"  - skip: {s.name}")

    # granularity 분포
    by_gran: dict[str, int] = {}
    for _, dst in moves:
        g = dst.parent.name
        by_gran[g] = by_gran.get(g, 0) + 1
    for g, n in sorted(by_gran.items()):
        print(f"  {g}: {n}")

    if not args.apply:
        print("\n[dry-run] --apply 를 붙이면 실제 이동")
        for src, dst in moves[:3]:
            print(f"  {src.name}  ->  {dst.relative_to(CACHE_DIR)}")
        if len(moves) > 3:
            print(f"  ... ({len(moves) - 3} more)")
        return

    # 충돌 사전 점검
    collisions = [(s, d) for s, d in moves if d.exists()]
    if collisions:
        print(f"\n[ERROR] 대상 파일이 이미 존재 ({len(collisions)}개). 중단.")
        for s, d in collisions[:5]:
            print(f"  {d}")
        sys.exit(1)

    # 서브디렉터리 생성
    for g in by_gran:
        (CACHE_DIR / g).mkdir(exist_ok=True)

    # 이동
    ok = 0
    for src, dst in moves:
        src.rename(dst)
        ok += 1
    print(f"\n완료: {ok}/{len(moves)} 이동")


if __name__ == "__main__":
    main()
