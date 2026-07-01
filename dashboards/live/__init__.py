"""Live ticker dashboard views (Bitget / KOSPI / NASDAQ).

This package consolidates the three "live table" views into a single tabbed
page so AgGrid component instances stay mounted when the user switches between
markets — Streamlit ``st.tabs`` keeps all tab panes in the DOM (only the active
one is visible via CSS), which dodges the AgGrid iframe-remount cost that the
old separate-page layout incurred on every Bitget ⇄ KOSPI navigation.

Module layout
-------------
- ``_common``       — shared helpers (age caption, background subprocess section)
- ``_crypto_compute`` — Bitget cache compute (parquet → ref levels + pct columns)
- ``_bitget_grid``  — Bitget AgGrid column spec + JsCode formatters + CSS
- ``bitget`` / ``kospi`` / ``nasdaq`` — per-market ``render()`` orchestrators,
  each called from the tabbed page in ``dashboards/pages/3_Live.py``.

Stock-side compute (KOSPI/NASDAQ) lives in the existing ``dashboards/_stock_grid``
module since both stock markets share schema; only the orchestration differs.
The TradingView-style chart renderer (``render_tv_chart``) also lives there and
is shared across all three markets — crypto feeds pass through
``normalize_crypto_ohlcv`` so the renderer sees a single input schema.
"""
