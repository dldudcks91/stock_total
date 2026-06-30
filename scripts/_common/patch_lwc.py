"""Patch the vendored ``streamlit-lightweight-charts`` frontend build.

Three idempotent edits are applied to the component's ``main.*.chunk.js``:

1. **Fixed initial bars** (``/*lwc-ivb*/``) — replace the one-shot
   ``timeScale().fitContent()`` (which squashes ALL bars to fit the width) with
   ``scrollToRealTime()`` + ``barSpacing = chartWidth / N`` where ``N`` comes
   from the custom ``chart.initialVisibleBars`` option the Python renderer sets.
   So exactly ``N`` candles fill the opening view on any screen width; we send
   the FULL history and the user pans left for older bars (exchange style).

2. **Series collection** (``/*lwc-items*/``) — inside the series-creation loop,
   stash each ``{series, config}`` on the chart object (``c.__items``) so the
   crosshair handler can map a series back to its label/color.

3. **Crosshair value tooltip** (``/*lwc-tip*/``) — append a floating box to the
   chart container and ``subscribeCrosshairMove``; on hover it shows the bar's
   date, OHLC, every MA, volume, RSI and MACD value (driven by the
   ``legendLabel`` each series config carries).

Every injected block is wrapped in ``try/catch`` so a missing field or an
unexpected minified scope degrades gracefully — the chart never breaks. Edits
are guarded by marker comments, so re-runs are safe.

**Re-run after every ``pip install`` / reinstall of
``streamlit-lightweight-charts``** (a fresh install restores the original
build).

Usage
-----
    .venv/Scripts/python.exe -m scripts._common.patch_lwc          # apply
    .venv/Scripts/python.exe -m scripts._common.patch_lwc --check  # report only
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ── 1. Fixed initial visible bars ───────────────────────────────────────────
IVB_MARK = "/*lwc-ivb*/"
# Match ``<recv>.timeScale().fitContent()`` (fresh) OR ``.scrollToRealTime()``
# (already patched by a prior version). ``<recv>`` = minified chart variable.
_IVB_PAT = re.compile(r"(\w+)\.timeScale\(\)\.(?:fitContent|scrollToRealTime)\(\)")


def _ivb_snippet(recv: str) -> str:
    return (
        f"{recv}.timeScale().scrollToRealTime();{IVB_MARK}"
        f"try{{var _o=(e[a]&&e[a].chart)||{{}},_n=_o.initialVisibleBars;"
        f"if(_n){{var _w=({recv}.options()&&{recv}.options().width)||800,"
        f"_ro=(_o.timeScale&&_o.timeScale.rightOffset)||0;"
        f"{recv}.timeScale().applyOptions({{barSpacing:Math.max(_w/(_n+_ro),0.5)}});"
        f"{recv}.timeScale().scrollToRealTime()}}}}catch(_e){{}}"
    )


# ── 2. Collect {series, config} onto the chart object ───────────────────────
ITEMS_MARK = "/*lwc-items*/"
_ITEMS_OLD = "d.setData(f.data),f.markers&&d.setMarkers(f.markers)"
_ITEMS_NEW = (
    "d.setData(f.data),"
    f"{ITEMS_MARK}(c.__items=c.__items||[]).push({{s:d,cfg:f}}),"
    "f.markers&&d.setMarkers(f.markers)"
)

# ── 3. Crosshair value tooltip ──────────────────────────────────────────────
TIP_MARK = "/*lwc-tip*/"
# Anchor on the (already ivb-patched) scrollToRealTime call; capture receiver.
_TIP_ANCHOR = re.compile(r"(\w+)\.timeScale\(\)\.scrollToRealTime\(\);/\*lwc-ivb\*/")

# Floating tooltip. __RECV__ = chart api; container taken from r[a].current
# (the element whose clientWidth sized the chart). Pure ASCII, single line.
_TIP_TEMPLATE = (
    ";try{(function(_c,_cn){"
    "if(!_cn)return;"
    "_cn.style.position='relative';"
    "var _old=_cn.querySelector(':scope>.lwc-tip');if(_old)_old.remove();"
    "var _tip=document.createElement('div');_tip.className='lwc-tip';"
    "_tip.style.cssText='position:absolute;display:none;z-index:30;pointer-events:none;"
    "padding:5px 9px;font:11px/1.55 Inter,sans-serif;background:rgba(255,255,255,0.94);"
    "border:1px solid rgba(0,0,0,0.12);border-radius:5px;white-space:nowrap;"
    "box-shadow:0 1px 4px rgba(0,0,0,0.12);color:#1a1a1a';"
    "_cn.appendChild(_tip);"
    "function _f(v){return(typeof v!=='number'||!isFinite(v))?'-':"
    "v.toLocaleString(undefined,{maximumFractionDigits:2});}"
    "function _fv(v){if(typeof v!=='number'||!isFinite(v))return'-';var a=Math.abs(v);"
    "if(a>=1e12)return(v/1e12).toFixed(2)+'T';if(a>=1e9)return(v/1e9).toFixed(2)+'B';"
    "if(a>=1e6)return(v/1e6).toFixed(2)+'M';if(a>=1e3)return(v/1e3).toFixed(1)+'K';return _f(v);}"
    "_c.subscribeCrosshairMove(function(p){"
    "if(!p||p.time===undefined||!p.point||p.point.x<0||p.point.y<0){_tip.style.display='none';return;}"
    "var its=_c.__items||[],h='';"
    "var ts=p.time,ds=(ts&&typeof ts==='object')?"
    "(ts.year+'-'+('0'+ts.month).slice(-2)+'-'+('0'+ts.day).slice(-2)):"
    "new Date(ts*1000).toISOString().slice(0,10);"
    "h+='<div style=\"font-weight:700;margin-bottom:2px\">'+ds+'</div>';"
    "for(var i=0;i<its.length;i++){var it=its[i],lab=it.cfg&&it.cfg.legendLabel;if(!lab)continue;"
    "var dp=p.seriesData.get(it.s);if(dp==null)continue;"
    "var col=(it.cfg.options&&it.cfg.options.color)||'#555';"
    "if(it.cfg.type==='Candlestick'){var up=dp.close>=dp.open,cc=up?'#1FCC81':'#F6465D';"
    "h+='<div style=\"color:'+cc+'\">O'+_f(dp.open)+' H'+_f(dp.high)+' L'+_f(dp.low)+' C'+_f(dp.close)+'</div>';}"
    "else{var v=dp.value;if(v===undefined)continue;var tx=(lab==='Vol')?_fv(v):_f(v);"
    "h+='<div style=\"color:'+col+'\">'+lab+' '+tx+'</div>';}}"
    "_tip.innerHTML=h;_tip.style.display='block';"
    "var cw=_cn.clientWidth,ch=_cn.clientHeight,tw=_tip.offsetWidth,th=_tip.offsetHeight;"
    "var x=p.point.x+16;if(x+tw>cw)x=p.point.x-tw-16;if(x<0)x=0;"
    "var y=p.point.y+16;if(y+th>ch)y=ch-th-4;if(y<0)y=0;"
    "_tip.style.left=x+'px';_tip.style.top=y+'px';"
    "});})(__RECV__,(typeof r!=='undefined'&&r[a]&&r[a].current)||null);}catch(_e3){}"
)


def _tip_snippet(recv: str) -> str:
    return _TIP_TEMPLATE.replace("__RECV__", recv)


def _build_dir() -> Path:
    import streamlit_lightweight_charts as _pkg
    return Path(_pkg.__file__).resolve().parent / "frontend" / "build"


def _patch_text(text: str):
    """Apply the three edits to one file's text. Returns (new_text, n_edits)."""
    edits = 0

    # 1. ivb — only if not already done (marker absent)
    if IVB_MARK not in text:
        text, n = _IVB_PAT.subn(lambda m: _ivb_snippet(m.group(1)), text)
        edits += n

    # 2. items collection
    if ITEMS_MARK not in text and _ITEMS_OLD in text:
        text = text.replace(_ITEMS_OLD, _ITEMS_NEW)
        edits += 1

    # 3. crosshair tooltip — anchors on the ivb-patched scroll call
    if TIP_MARK not in text:
        def _repl(m: "re.Match") -> str:
            return m.group(0) + TIP_MARK + _tip_snippet(m.group(1))
        text, n = _TIP_ANCHOR.subn(_repl, text)
        edits += n

    return text, edits


def apply(check_only: bool = False) -> int:
    build = _build_dir()
    js_dir = build / "static" / "js"
    if not js_dir.is_dir():
        print(f"[patch_lwc] build js dir not found: {js_dir}", file=sys.stderr)
        return 2

    # Only the component's own chunks; never touch the library chunk (2.*).
    targets = sorted(js_dir.glob("main.*.chunk.js"))
    if not targets:
        print(f"[patch_lwc] no main.*.chunk.js under {js_dir}", file=sys.stderr)
        return 2

    changed = 0
    for f in targets:
        text = f.read_text(encoding="utf-8", errors="surrogatepass")
        new_text, n = _patch_text(text)
        if n == 0:
            print(f"[patch_lwc] up to date: {f.name}")
            continue
        if check_only:
            print(f"[patch_lwc] WOULD patch {f.name} ({n} edit(s))")
            changed += n
            continue
        f.write_text(new_text, encoding="utf-8", errors="surrogatepass")
        changed += n
        print(f"[patch_lwc] patched {f.name}: {n} edit(s)")

    if check_only:
        print(f"[patch_lwc] check: {changed} edit(s) needed.")
        return 1 if changed else 0

    print(f"[patch_lwc] done: {changed} edit(s) applied.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report what would change, don't write")
    args = ap.parse_args()
    raise SystemExit(apply(check_only=args.check))


if __name__ == "__main__":
    main()
