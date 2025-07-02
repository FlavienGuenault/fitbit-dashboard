"""Download Fitbit JSON files from Supabase Storage, aggregate daily metrics,
then upsert them into the `data_summary` table.

Usage:
    python ingest.py
"""

import io
import json
import os
import re
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client
from tqdm import tqdm

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY")

supa = create_client(SUPABASE_URL, SERVICE_KEY)

BUCKET = "fitbit"
CATEGORIES = {"br", "calories", "heart", "hrv", "steps"}

# 1) List every object in the bucket (up to 10 000 for now)
objects = supa.storage.from_(BUCKET).list(path="", search_options={"limit": 10000})

# 2) Group files by (usage_id, date)
data_by_day: dict[tuple[str, datetime.date], dict[str, str]] = {}

file_rx = re.compile(
    r"fitbit/(?P<user_id>[^/]+)/(?P<usage_id>[^/]+)/(?P<cat>[^/]+)/(?P<fname>.+\.json)"
)

for obj in objects:
    m = file_rx.match(obj["name"])
    if not m or m["cat"] not in CATEGORIES:
        continue

    usage_id = m["usage_id"]
    category = m["cat"]

    # Extract first date found in filename e.g. heart_20240809_…
    date_match = re.search(r"(\d{4}-?\d{2}-?\d{2})", m["fname"])
    if not date_match:
        continue

    raw_date = date_match.group(1)
    date_fmt = "%Y%m%d" if len(raw_date) == 8 else "%Y-%m-%d"
    date = datetime.strptime(raw_date, date_fmt).date()

    data_by_day.setdefault((usage_id, date), {})[category] = obj["name"]


def download_json(path: str):
    """Download a file from Storage and parse it as JSON."""
    blob = supa.storage.from_(BUCKET).download(path)
    return json.loads(io.BytesIO(blob).read())


to_upsert: list[dict[str, object]] = []

for (usage_id, date), cats in tqdm(data_by_day.items(), desc="Aggregating"):
    try:
        calories_total = int(float(download_json(cats["calories"])["activities-calories"][0]["value"]))
        steps_total = int(download_json(cats["steps"])["activities-steps"][0]["value"])
        rhr = float(download_json(cats["heart"])["activities-heart"][0]["value"])
        br_sleep = float(download_json(cats["br"])["br"][0]["value"]["fullSleepSummary"]["breathingRate"])

        # Sleep HRV: mean nightly RMSSD
        hrv_json = download_json(cats["hrv"])["hrv"][0]["minutes"]
        rmssds = [entry["value"]["rmssd"] for entry in hrv_json]
        hrv_sleep = float(pd.Series(rmssds).mean())

    except KeyError as exc:
        print("⚠️  Missing file or key:", exc, usage_id, date)
        continue

    to_upsert.append(
        {
            "usage_id": usage_id,
            "date": str(date),
            "calories_total": calories_total,
            "steps_total": steps_total,
            "rhr": rhr,
            "br_sleep": br_sleep,
            "hrv_sleep": hrv_sleep,
        }
    )

# 3) Upsert into the database
if to_upsert:
    supa.table("data_summary").upsert(to_upsert, on_conflict="date,usage_id").execute()
    print(f"✅ {len(to_upsert)} rows upserted into data_summary")
else:
    print("ℹ️  No data to insert.")
