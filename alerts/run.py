"""알림 파이프라인 단일 진입점: fetch → precompute → scan → 카카오 전송.

Usage::

    .venv/Scripts/python.exe -m alerts.run --asset kr
    .venv/Scripts/python.exe -m alerts.run --asset us
    .venv/Scripts/python.exe -m alerts.run --asset crypto

옵션::

    --no-fetch       fetch 단계 skip (캐시만 활용)
    --no-precompute  precompute 단계 skip
    --dry-run        scan 까지만 하고 카카오 전송은 print
    --threshold N    score 컷 임계치 (기본 80)

cron 에서 호출 시 stdout/stderr 를 로그 파일로 리다이렉트:

    33 16 * * 1-5 cd /home/.../stock_total && .venv/bin/python -m alerts.run --asset kr >> logs/kr.log 2>&1
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# venv python — Windows / Linux 둘 다 지원
_PY = _ROOT / ".venv" / ("Scripts/python.exe" if sys.platform.startswith("win") else "bin/python")
if not _PY.exists():
    _PY = Path(sys.executable)  # fallback


def _run(cmd: list, label: str) -> int:
    """서브프로세스 실행. stdout/stderr 는 부모로 그대로 통과."""
    print(f"\n[{label}] $ {' '.join(str(c) for c in cmd)}", flush=True)
    t0 = time.perf_counter()
    rc = subprocess.run(cmd).returncode
    took = time.perf_counter() - t0
    print(f"[{label}] exit={rc} ({took:.1f}s)", flush=True)
    return rc


def fetch(asset: str) -> int:
    """자산별 데이터 fetch 명령. 실패해도 알림 시도는 계속.

    KR/US: ``data.sources.stocks --market {KOSPI|NASDAQ}`` (FDR 증분).
    Crypto: ``data.sources.bitget --granularity {1h|1d}`` (두 번 호출).
    """
    if asset == "kr":
        return _run([str(_PY), "-m", "data.sources.stocks", "--market", "KOSPI"], "fetch")
    if asset == "us":
        return _run([str(_PY), "-m", "data.sources.stocks", "--market", "NASDAQ"], "fetch")
    if asset == "crypto":
        # 4h/1w 는 1h/1d 캐시에서 메모리 리샘플 — 1h + 1d 만 fetch 하면 됨.
        rc1 = _run([str(_PY), "-m", "data.sources.bitget", "--granularity", "1h"], "fetch:1h")
        rc2 = _run([str(_PY), "-m", "data.sources.bitget", "--granularity", "1d"], "fetch:1d")
        return rc1 or rc2
    raise ValueError(f"unsupported asset: {asset}")


def precompute(asset: str) -> int:
    return _run([str(_PY), "-m", "dashboards._precompute", "--asset", asset], "precompute")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="알림 파이프라인 — fetch+precompute+scan+카톡")
    ap.add_argument("--asset", required=True, choices=["kr", "us", "crypto"])
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--no-precompute", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="scan 결과만 출력하고 카톡 전송은 skip")
    ap.add_argument("--threshold", type=float, default=80.0)
    args = ap.parse_args()

    asset = args.asset
    t0 = time.perf_counter()
    print(f"=== [alerts.run] asset={asset} dry_run={args.dry_run} ===", flush=True)

    # 1. fetch
    if not args.no_fetch:
        fetch_rc = fetch(asset)
        if fetch_rc != 0:
            print(f"[warn] fetch 실패 (exit={fetch_rc}) — 캐시 기준으로 진행", flush=True)

    # 2. precompute
    if not args.no_precompute:
        pre_rc = precompute(asset)
        if pre_rc != 0:
            print(f"[error] precompute 실패 (exit={pre_rc}) — 알림 skip", flush=True)
            return pre_rc

    # 3. scan (state 파일 갱신 포함)
    from alerts.scan import scan_new, format_message
    # dry-run 일 때도 state 는 갱신해두는 게 자연스럽지만, 첫 실행 검증을 위해
    # dry-run 이면 persist=False 로 둔다 (반복 호출해도 같은 결과 나오게).
    items = scan_new(asset, score_threshold=args.threshold, persist=not args.dry_run)
    print(f"[scan] 신규 {len(items)}건", flush=True)

    if not items:
        print(f"=== [alerts.run] 완료 ({time.perf_counter()-t0:.1f}s) — 신규 없음 ===", flush=True)
        return 0

    msg = format_message(asset, items)
    print("---- 메시지 ----")
    print(msg)
    print("----------------")

    # 4. 카카오 전송
    if args.dry_run:
        print("[dry-run] 카카오 전송 skip", flush=True)
    else:
        try:
            from alerts.kakao import get_sender
            sender = get_sender()
            sender.send_text(msg)
            print("[kakao] 전송 OK", flush=True)
        except Exception as e:
            print(f"[error] 카카오 전송 실패: {e}", flush=True)
            return 1

    print(f"=== [alerts.run] 완료 ({time.perf_counter()-t0:.1f}s) ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
