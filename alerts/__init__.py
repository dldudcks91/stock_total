"""Long-entry recommendation alert pipeline.

Reads ``data/cache/{asset}/_recs.parquet`` (produced by
:mod:`dashboards._precompute`), diffs against the last-seen symbol set, and
pushes new ``rec_score >= 80`` candidates to KakaoTalk ("나에게 보내기").

Entry point: ``.venv/Scripts/python.exe -m alerts.run --asset {kr|us|crypto}``.
"""
