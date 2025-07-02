"""Streamlit dashboard for visualising daily Fitbit metrics stored in
`data_summary`.

Run:
    streamlit run dashboard.py
"""

# ── Imports ────────────────────────────────────────────────────────────────
import os
import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

# ── Supabase client ────────────────────────────────────────────────────────
load_dotenv()  # loads SUPABASE_URL + SUPABASE_ANON_KEY from .env
supa = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_ANON_KEY"),
)

# ── Streamlit page config ─────────────────────────────────────────────────
st.set_page_config(page_title="Fitbit Dashboard", layout="wide")
st.title("📈 Fitbit –  Overview")

# ── 1 )  List available usage_id values ───────────────────────────────────
usage_resp = supa.table("data_summary").select("usage_id").execute()
usage_lookup = sorted({row["usage_id"] for row in usage_resp.data if row["usage_id"]})

if not usage_lookup:
    st.error("No usage_id found in data_summary (or RLS permissions missing).")
    st.stop()

selected_id = st.selectbox("Select a usage_id:", usage_lookup)

# ── 2 )  Load all rows for that ID ────────────────────────────────────────
rows = (
    supa.table("data_summary")
        .select("*")
        .eq("usage_id", selected_id)
        .order("date", desc=False)
        .execute()
).data

df = pd.DataFrame(rows)
df["date"] = pd.to_datetime(df["date"])  # make sure it's datetime dtype

if df.empty:
    st.warning("No data available for this usage_id.")
    st.stop()

# ── 3 )  Date‑range picker + client‑side filter (NEW) ─────────────────────
min_date, max_date = df["date"].min(), df["date"].max()

start, end = st.date_input(
    "Filter by date range:",
    value=(min_date.date(), max_date.date()),
    min_value=min_date.date(),
    max_value=max_date.date(),
    format="YYYY/MM/DD", 
)

# If user enters a single date, Streamlit returns a date, not a tuple.
if isinstance(start, tuple):
    start, end = start  # unpack

start_ts, end_ts = pd.to_datetime(start), pd.to_datetime(end)
df = df[(df["date"] >= start_ts) & (df["date"] <= end_ts)]

if df.empty:
    st.warning("No rows in the selected date range.")
    st.stop()

# ── 4 )  Visualisations ───────────────────────────────────────────────────
cols = st.columns(3)

with cols[0]:
    st.subheader("Steps")
    st.plotly_chart(px.bar(df, x="date", y="steps_total"))

with cols[1]:
    st.subheader("Calories")
    st.plotly_chart(px.bar(df, x="date", y="calories_total"))

with cols[2]:
    st.subheader("Resting HR")
    st.plotly_chart(px.line(df, x="date", y="rhr", markers=True))

st.subheader("Sleep – HRV & Breathing Rate")
st.plotly_chart(
    px.line(df, x="date", y=["hrv_sleep", "br_sleep"], markers=True)
)

st.dataframe(df)
