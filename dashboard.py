"""
dashboard.py

Streamlit dashboard for browsing scan results interactively.

Run with:
    streamlit run dashboard.py

Requires a scan_results.csv in the project root (produced by
main.py or the notebook's Report.dataframe(...).to_csv(...) step).
For a live re-scan from inside the dashboard, use the "Re-run scan"
button, which calls the same DataLoader -> Scanner -> Report pipeline
main.py uses.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import config

RESULTS_PATH = Path("scan_results.csv")


##############################################################################
# Data loading
##############################################################################

@st.cache_data(ttl=600)
def load_results(path: Path) -> pd.DataFrame:

    if not path.exists():

        return pd.DataFrame()

    return pd.read_csv(path)


def run_live_scan() -> pd.DataFrame:

    from data import DataLoader
    from scanner import Scanner
    from quality import PatternQuality
    from report import Report

    loader = DataLoader()

    market = loader.load_universe()

    benchmark = loader.load_benchmark()

    scanner = Scanner()

    results = scanner.scan(market, PatternQuality(), benchmark=benchmark)

    report = Report.dataframe(results)

    report.to_csv(RESULTS_PATH, index=False)

    return report


##############################################################################
# Page
##############################################################################

st.set_page_config(page_title="Shoryuken Scanner", layout="wide")

st.title("Shoryuken Scanner")

st.caption(f"Universe: {config.UNIVERSE} · Benchmark: {config.BENCHMARK}")

with st.sidebar:

    st.header("Filters")

    if st.button("Re-run scan now", type="primary"):

        with st.spinner("Scanning - this can take a while on a large universe..."):

            df = run_live_scan()

        st.success(f"Scan complete: {len(df)} setups found.")

    else:

        df = load_results(RESULTS_PATH)

    if df.empty:

        st.info("No results yet. Click 'Re-run scan now' or generate scan_results.csv first.")

        st.stop()

    patterns = sorted(df["Pattern"].unique())

    selected_patterns = st.multiselect("Pattern", patterns, default=patterns)

    min_score = st.slider("Minimum score", 0, 100, 0)

    min_rr = st.slider("Minimum R:R", 0.0, 5.0, 0.0, step=0.5)

    min_rs = st.slider("Minimum RS rating", 0, 99, 0)


##############################################################################
# Filtered table
##############################################################################

filtered = df[
    df["Pattern"].isin(selected_patterns)
    & (df["Score"] >= min_score)
    & (df["RR"] >= min_rr)
]

if "RS" in filtered.columns:

    filtered = filtered[filtered["RS"].fillna(0) >= min_rs]

st.subheader(f"{len(filtered)} setup(s)")

st.dataframe(
    filtered.sort_values("Score", ascending=False),
    use_container_width=True,
    hide_index=True,
)


##############################################################################
# Breakdown
##############################################################################

col1, col2 = st.columns(2)

with col1:

    st.subheader("Setups per pattern")

    st.bar_chart(filtered["Pattern"].value_counts())

with col2:

    st.subheader("Score distribution")

    st.bar_chart(filtered["Score"].round(-1).value_counts().sort_index())


##############################################################################
# Ticker drill-down
##############################################################################

if len(filtered):

    st.subheader("Drill down")

    ticker = st.selectbox("Ticker", sorted(filtered["Ticker"].unique()))

    st.dataframe(
        filtered[filtered["Ticker"] == ticker],
        use_container_width=True,
        hide_index=True,
    )
