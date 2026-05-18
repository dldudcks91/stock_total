"""Helper for /study run pattern.

Analysis modules import this to support both:
  --config <path/to/config.json>     # load all params from config (reproducible)
  --out-dir <run_folder>             # plus per-module CLI args (new exploration)

Output always goes to <run_folder>/output/.

Usage:
    from scripts._common.run_helper import parse_args, update_config

    def add_args(ap):
        ap.add_argument("--impulse-min", type=float, default=0.10)
        ap.add_argument("--vol-mult-min", type=float, default=None)

    out_dir, params, args = parse_args(add_args, defaults={
        "impulse_min": 0.10, "vol_mult_min": None,
    })
    # ... use params['impulse_min'] etc.
    # save: out_dir / "events.parquet" ...
    # later: update_config(args.config, data={"symbol_count": 553})
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple


def parse_args(
    add_args: Optional[Callable[[argparse.ArgumentParser], None]] = None,
    defaults: Optional[Dict[str, Any]] = None,
    description: str = "",
) -> Tuple[Path, Dict[str, Any], argparse.Namespace]:
    """Parse --config or --out-dir + per-module args.

    Returns (output_dir, params, raw_args).
      output_dir: <run_folder>/output (already mkdir'd)
      params:     merged dict (config.params overrides defaults, CLI overrides config)
      raw_args:   the argparse Namespace (has .config / .out_dir)
    """
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--config", type=Path, default=None,
                    help="config.json from /study init (loads all params)")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="run folder (parent of output/) — required if --config not set")
    if add_args is not None:
        add_args(ap)
    args = ap.parse_args()

    # Resolve run_folder + base params dict
    if args.config is not None:
        cfg_path = args.config.resolve()
        if not cfg_path.exists():
            ap.error(f"config not found: {cfg_path}")
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        run_dir = cfg_path.parent
        params = dict(defaults or {})
        params.update(cfg.get("params", {}) or {})
    elif args.out_dir is not None:
        run_dir = args.out_dir.resolve()
        if not run_dir.exists():
            ap.error(f"out-dir not found: {run_dir}")
        params = dict(defaults or {})
    else:
        ap.error("either --config or --out-dir is required")

    # CLI overrides — only for keys actually provided
    cli_overrides = {}
    for action in ap._actions:
        if action.dest in ("config", "out_dir", "help"):
            continue
        val = getattr(args, action.dest, None)
        if val is not None and val != action.default:
            cli_overrides[action.dest] = val
    params.update(cli_overrides)

    output_dir = run_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir, params, args


def _sanitize_json(obj):
    """Replace +/-inf and NaN with portable string sentinels."""
    import math
    if isinstance(obj, float):
        if math.isnan(obj):
            return None
        if math.isinf(obj):
            return "+inf" if obj > 0 else "-inf"
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    return obj


def update_config(config_path: Path, **updates) -> None:
    """Merge updates into config.json. Dict-valued keys deep-merged at level 1.
    Non-portable floats (inf/nan) sanitized to strings/None."""
    cfg_path = Path(config_path).resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    for k, v in updates.items():
        v = _sanitize_json(v)
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False,
                                     allow_nan=False) + "\n",
                          encoding="utf-8")


def resolve_config_path(args) -> Optional[Path]:
    """Return the resolved config.json path, or guess from --out-dir."""
    if getattr(args, "config", None) is not None:
        return args.config.resolve()
    if getattr(args, "out_dir", None) is not None:
        candidate = args.out_dir.resolve() / "config.json"
        return candidate if candidate.exists() else None
    return None
