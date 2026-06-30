# -*- coding: utf-8 -*-
"""
Jenneson Climate-Finance Trading & Risk Platform

Local client-facing prototype inspired by the existing China A-share dashboard.
Run:
    python app.py
Open:
    http://127.0.0.1:8865
"""

from __future__ import annotations

import json
import math
import random
import sys
import threading
import time
import webbrowser
import csv
import io
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

try:
    import numpy as np
    import pandas as pd
except Exception:  # pragma: no cover
    np = None
    pd = None

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None


PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

PORT = 8865
DEFAULT_PORTFOLIO_VALUE = 50_000_000
START_YEAR = 2009
CURRENT_YEAR = datetime.now().year
METHOD2_END_YEAR = 2100
METHOD2_DRAWS = 900
METHOD2_DISCOUNT_RATE = 0.0407
METHOD2_DISCOUNT_SPREAD = 0.0036
METHOD2_ALPHA2 = 0.0028
METHOD2_ALPHA3_MAX = 0.248
CURRENT_WARMING_C = 1.28

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
UNIVERSE_CACHE = DATA_DIR / "us_listed_universe_cache.json"
NASA_GISTEMP_CSV_URL = "https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts+dSST.csv"
NOAA_CO2_CSV_URL = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_mm_mlo.csv"
NCEI_BILLION_EVENTS_JSON_URL = "https://www.ncei.noaa.gov/monitoring-content/billions/data/events.json"
CLIMATE_DATA_CACHE = DATA_DIR / "official_climate_data_cache.json"
NWS_ACTIVE_ALERTS_URL = "https://api.weather.gov/alerts/active?status=actual&message_type=alert"
DAILY_CLIMATE_CACHE = DATA_DIR / "daily_climate_alerts_cache.json"
NWS_USER_AGENT = "JennesonClimateFinancePrototype/1.0 (local research)"


SECTOR_ETFS = {
    "XLE": {
        "name": "Energy",
        "physical": 0.65,
        "transition": 0.95,
        "resilience": 0.25,
        "client_note": "Transition exposure and carbon-policy sensitivity are high.",
    },
    "XLU": {
        "name": "Utilities",
        "physical": 0.75,
        "transition": 0.55,
        "resilience": 0.60,
        "client_note": "Physical risk is high, but regulated cash-flow resilience can help.",
    },
    "XLI": {
        "name": "Industrials",
        "physical": 0.58,
        "transition": 0.62,
        "resilience": 0.42,
        "client_note": "Supply-chain and infrastructure exposure create mixed climate risk.",
    },
    "XLK": {
        "name": "Technology",
        "physical": 0.28,
        "transition": 0.32,
        "resilience": 0.82,
        "client_note": "Asset-light and adaptive, but data-center energy intensity matters.",
    },
    "XLF": {
        "name": "Financials",
        "physical": 0.42,
        "transition": 0.50,
        "resilience": 0.55,
        "client_note": "Climate risk enters through credit, insurance, and asset exposure.",
    },
}


ETF_WATCHLIST = {
    "Core Index": ["SPY", "QQQ", "DIA", "IWM"],
    "Sector SPDR": ["XLK", "XLE", "XLF", "XLU", "XLI", "XLV", "XLY", "XLP"],
    "Rates / Credit": ["TLT", "IEF", "LQD", "HYG"],
    "Climate / Clean Energy": ["ICLN", "QCLN", "TAN", "PBW"],
    "Commodities": ["GLD", "SLV", "USO", "UNG"],
}


DEFAULT_OPTIMIZER_ETFS = ["SPY", "QQQ", "XLK", "XLF", "XLU", "XLE", "ICLN"]
DEFAULT_OPTIMIZER_STOCKS = ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "NEE"]


OPTIMIZER_STYLES = {
    "balanced": {
        "label": "Balanced",
        "market_weight": 0.42,
        "climate_weight": 0.38,
        "risk_weight": 0.20,
        "stock_sleeve": 0.42,
        "note": "Blend market momentum, climate risk, and volatility control.",
    },
    "climate_defense": {
        "label": "Climate defense",
        "market_weight": 0.24,
        "climate_weight": 0.56,
        "risk_weight": 0.20,
        "stock_sleeve": 0.32,
        "note": "Prioritize lower climate VaR and stronger resilience.",
    },
    "growth": {
        "label": "Growth",
        "market_weight": 0.56,
        "climate_weight": 0.24,
        "risk_weight": 0.20,
        "stock_sleeve": 0.52,
        "note": "Allow more stock concentration when momentum is strong.",
    },
    "low_vol": {
        "label": "Low volatility",
        "market_weight": 0.28,
        "climate_weight": 0.32,
        "risk_weight": 0.40,
        "stock_sleeve": 0.28,
        "note": "Favor smoother holdings and reduce volatile single-name exposure.",
    },
}


OPTIMIZER_MODE_LABELS = {
    "etf_only": "ETF only",
    "etf_stock": "ETF + stock",
    "stock_only": "Stock only",
}


COMPANY_SECTOR_SENSITIVITY = {
    "Energy": 0.92,
    "Utilities": 0.70,
    "Industrials": 0.62,
    "Technology": 0.36,
    "Financial Services": 0.54,
    "Financials": 0.54,
    "Consumer Cyclical": 0.48,
    "Consumer Defensive": 0.38,
    "Healthcare": 0.34,
    "Basic Materials": 0.72,
    "Real Estate": 0.68,
    "Communication Services": 0.40,
}


CLIMATE_PROXY = [
    # year, NASA-like global temperature anomaly proxy, NOAA billion-dollar disaster frequency proxy
    (2008, 0.54, 12),
    (2009, 0.64, 10),
    (2010, 0.72, 13),
    (2011, 0.60, 16),
    (2012, 0.65, 11),
    (2013, 0.68, 10),
    (2014, 0.75, 13),
    (2015, 0.90, 15),
    (2016, 1.02, 16),
    (2017, 0.93, 17),
    (2018, 0.85, 14),
    (2019, 0.98, 14),
    (2020, 1.02, 22),
    (2021, 0.86, 20),
    (2022, 0.89, 18),
    (2023, 1.18, 28),
    (2024, 1.28, 27),
    (2025, 1.22, 24),
    (2026, 1.26, 25),
]


CLIMATE_SCENARIOS = [
    {
        "name": "Orderly Transition",
        "probability": 0.35,
        "physical_shock": 0.035,
        "transition_shock": 0.055,
        "litigation_shock": 0.010,
        "carbon_price": 75,
        "narrative": "Gradual policy tightening, higher carbon prices, manageable physical losses.",
    },
    {
        "name": "Disorderly Transition",
        "probability": 0.30,
        "physical_shock": 0.060,
        "transition_shock": 0.120,
        "litigation_shock": 0.025,
        "carbon_price": 145,
        "narrative": "Late policy action reprices carbon-intensive sectors quickly.",
    },
    {
        "name": "Hot House World",
        "probability": 0.25,
        "physical_shock": 0.155,
        "transition_shock": 0.035,
        "litigation_shock": 0.030,
        "carbon_price": 35,
        "narrative": "Weak policy response, stronger heat, flood, wildfire, and storm losses.",
    },
    {
        "name": "Liability Shock",
        "probability": 0.10,
        "physical_shock": 0.070,
        "transition_shock": 0.080,
        "litigation_shock": 0.090,
        "carbon_price": 110,
        "narrative": "Climate disclosure, insurance, and legal liability risk reprices issuers.",
    },
]


US_MARKET_NOTES = [
    "Universe uses U.S.-listed common stocks and sector ETFs with USD allocations.",
    "No China A-share 100-share lot rule is used; fractional or single-share sizing can be modeled.",
    "U.S. equities currently settle on T+1, but this is not the same as China-style T+1 resale restrictions.",
    "The prototype does not model PDT, margin, options, borrow fees, taxes, or live execution routing.",
]


EXCHANGE_MAP = {
    "Q": "NASDAQ",
    "N": "NYSE",
    "A": "NYSE American",
    "P": "NYSE Arca",
    "Z": "Cboe BZX",
    "V": "IEX",
}


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    except Exception:
        return default


def zscores(values):
    vals = [safe_float(v, 0.0) for v in values]
    if not vals:
        return []
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)
    std = math.sqrt(var)
    if std <= 1e-12:
        return [0.0 for _ in vals]
    return [(v - mean) / std for v in vals]


def clamp(value, low, high):
    return max(low, min(high, value))


def percentile(values, q):
    vals = sorted([safe_float(v, 0.0) for v in values])
    if not vals:
        return 0.0
    idx = min(len(vals) - 1, max(0, int(round((len(vals) - 1) * q))))
    return vals[idx]


def yahoo_symbol(symbol):
    return str(symbol).strip().upper().replace(".", "-")


def parse_pipe_rows(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    headers = lines[0].split("|")
    rows = []
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            continue
        parts = line.split("|")
        if len(parts) != len(headers):
            continue
        rows.append(dict(zip(headers, parts)))
    return rows


def download_text(url, timeout=12, headers=None):
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def read_cached_official_climate_data(max_age_days=7):
    if CLIMATE_DATA_CACHE.exists():
        age_days = (time.time() - CLIMATE_DATA_CACHE.stat().st_mtime) / 86400
        if age_days <= max_age_days:
            try:
                cached = json.loads(CLIMATE_DATA_CACHE.read_text(encoding="utf-8"))
                cached["source_mode"] = "cached official climate data"
                return cached
            except Exception:
                pass
    return None


def parse_nasa_gistemp(text):
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and lines[0].lower().startswith("land-ocean"):
        lines = lines[1:]
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    rows = {}
    for row in reader:
        try:
            year = int(row.get("Year", ""))
            annual = row.get("J-D", "").strip()
            if annual and annual != "***":
                rows[year] = float(annual)
        except Exception:
            continue
    return rows


def parse_noaa_co2(text):
    usable = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(usable)))
    by_year = {}
    for row in reader:
        try:
            year = int(row.get("year", ""))
            avg = float(row.get("average", "nan"))
            if avg > 0:
                by_year.setdefault(year, []).append(avg)
        except Exception:
            continue
    return {year: sum(vals) / len(vals) for year, vals in by_year.items() if vals}


def parse_ncei_disasters(text):
    raw = json.loads(text)
    counts = {}
    cost_proxy = {}
    for event in raw.values():
        try:
            beg = str(event.get("begDate", ""))
            year = int(beg[:4])
        except Exception:
            continue
        counts[year] = counts.get(year, 0) + 1
        low = safe_float(event.get("lower95"), 0)
        high = safe_float(event.get("upper95"), low)
        midpoint = (low + high) / 2 if high else low
        cost_proxy[year] = cost_proxy.get(year, 0) + midpoint
    return counts, cost_proxy


def fallback_climate_maps():
    temp = {year: anomaly for year, anomaly, _ in CLIMATE_PROXY}
    disasters = {year: count for year, _, count in CLIMATE_PROXY}
    co2 = {}
    for year in sorted(temp):
        co2[year] = 370 + max(0, year - 2000) * 2.35
    return temp, co2, disasters, {}


def load_official_climate_data(force_refresh=False):
    if not force_refresh:
        cached = read_cached_official_climate_data()
        if cached:
            return cached

    fallback_temp, fallback_co2, fallback_disasters, fallback_costs = fallback_climate_maps()
    source_notes = []
    try:
        temp_map = parse_nasa_gistemp(download_text(NASA_GISTEMP_CSV_URL, timeout=18))
        source_notes.append("NASA GISTEMP land-ocean annual temperature anomaly")
    except Exception:
        temp_map = fallback_temp
        source_notes.append("fallback temperature proxy")

    try:
        co2_map = parse_noaa_co2(download_text(NOAA_CO2_CSV_URL, timeout=18))
        source_notes.append("NOAA GML Mauna Loa monthly CO2")
    except Exception:
        co2_map = fallback_co2
        source_notes.append("fallback CO2 proxy")

    try:
        disaster_map, cost_map = parse_ncei_disasters(download_text(NCEI_BILLION_EVENTS_JSON_URL, timeout=25))
        source_notes.append("NOAA NCEI billion-dollar weather and climate disasters")
    except Exception:
        disaster_map, cost_map = fallback_disasters, fallback_costs
        source_notes.append("fallback disaster-frequency proxy")

    years = sorted(set(temp_map) | set(co2_map) | set(disaster_map))
    rows = []
    last_temp = None
    last_temp_year = None
    last_co2 = None
    last_co2_year = None
    for year in years:
        if year < 1980:
            continue
        temp = temp_map.get(year)
        temp_year = year if temp is not None else last_temp_year
        if temp is None:
            temp = last_temp if last_temp is not None else fallback_temp.get(year)
        else:
            last_temp = temp
            last_temp_year = year
        co2 = co2_map.get(year)
        co2_year = year if co2 is not None else last_co2_year
        if co2 is None:
            co2 = last_co2 if last_co2 is not None else fallback_co2.get(year)
        if co2 is not None:
            last_co2 = co2
            last_co2_year = year
        disasters = disaster_map.get(year)
        disaster_year = year if disasters is not None else None
        if disasters is None and source_notes[-1].startswith("fallback"):
            disasters = fallback_disasters.get(year, 0)
            disaster_year = year
        cost = cost_map.get(year, fallback_costs.get(year, 0))
        if temp is None and co2 is None and not disasters:
            continue
        rows.append(
            {
                "year": year,
                "temperature_anomaly": round(safe_float(temp, 0), 3),
                "temperature_year": temp_year,
                "temperature_source": "official" if temp_year == year else "official carry-forward",
                "co2_ppm": round(safe_float(co2, 0), 2),
                "co2_year": co2_year,
                "co2_source": "official" if co2_year == year else "official carry-forward",
                "billion_dollar_disasters": int(disasters) if disasters is not None else None,
                "disaster_year": disaster_year,
                "disaster_source": "official" if disaster_year == year else "not yet available",
                "disaster_cost_proxy": round(safe_float(cost, 0), 2),
            }
        )

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_mode": "official climate data",
        "source_notes": source_notes,
        "source_urls": {
            "nasa_gistemp": NASA_GISTEMP_CSV_URL,
            "noaa_co2": NOAA_CO2_CSV_URL,
            "ncei_disasters": NCEI_BILLION_EVENTS_JSON_URL,
        },
        "rows": rows,
    }
    try:
        CLIMATE_DATA_CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return payload


def climate_data_context():
    data = load_official_climate_data()
    rows = data.get("rows", [])
    if not rows:
        return {
            "current_warming": CURRENT_WARMING_C,
            "latest_year": CURRENT_YEAR,
            "co2_ppm": 420.0,
            "co2_10y_change": 20.0,
            "disaster_10y_avg": 18.0,
            "climate_pressure_multiplier": 1.0,
            "source_mode": "fallback",
        }
    latest = rows[-1]
    disaster_rows = [r for r in rows if r.get("billion_dollar_disasters") is not None]
    recent = disaster_rows[-10:] if len(disaster_rows) >= 10 else disaster_rows
    prior_idx = max(0, len(rows) - 11)
    prior = rows[prior_idx]
    disaster_10y_avg = sum(r.get("billion_dollar_disasters", 0) for r in recent) / max(1, len(recent))
    co2_change = safe_float(latest.get("co2_ppm"), 0) - safe_float(prior.get("co2_ppm"), 0)
    temp = safe_float(latest.get("temperature_anomaly"), CURRENT_WARMING_C)
    multiplier = 1.0 + clamp((temp - 1.0) * 0.12, -0.04, 0.10) + clamp((co2_change - 20) * 0.004, -0.04, 0.08) + clamp((disaster_10y_avg - 15) * 0.01, -0.03, 0.08)
    return {
        "current_warming": round(max(0.75, temp), 3),
        "latest_year": latest.get("year", CURRENT_YEAR),
        "co2_ppm": latest.get("co2_ppm", 0),
        "co2_10y_change": round(co2_change, 2),
        "disaster_10y_avg": round(disaster_10y_avg, 2),
        "climate_pressure_multiplier": round(clamp(multiplier, 0.85, 1.30), 4),
        "source_mode": data.get("source_mode", "official climate data"),
        "source_notes": data.get("source_notes", []),
        "source_urls": data.get("source_urls", {}),
    }


DAILY_ALERT_CATEGORY_WEIGHTS = {
    "heat": 1.45,
    "flood": 1.30,
    "fire": 1.35,
    "tropical": 1.60,
    "storm": 1.10,
    "winter": 0.55,
    "air_quality": 0.75,
}


CLIMATE_CATEGORY_LABELS = {
    "heat": "Heat",
    "flood": "Flood",
    "fire": "Wildfire",
    "tropical": "Tropical storm",
    "storm": "Severe storm",
    "winter": "Winter weather",
    "air_quality": "Air quality",
}


DAILY_CLIMATE_STOCKS = [
    {
        "ticker": "NEE",
        "name": "NextEra Energy",
        "theme": "Power grid / renewables",
        "stance": "mixed",
        "exposure": {"heat": 0.86, "storm": 0.52, "tropical": 0.46, "fire": 0.28},
        "note": "Power demand and grid reliability become more important during climate stress.",
    },
    {
        "ticker": "DUK",
        "name": "Duke Energy",
        "theme": "Regulated utilities",
        "stance": "risk",
        "exposure": {"heat": 0.78, "storm": 0.62, "tropical": 0.50, "winter": 0.34},
        "note": "Utilities face demand spikes, outage risk, and storm restoration costs.",
    },
    {
        "ticker": "XOM",
        "name": "Exxon Mobil",
        "theme": "Energy / Gulf infrastructure",
        "stance": "risk",
        "exposure": {"heat": 0.52, "tropical": 0.76, "storm": 0.35, "air_quality": 0.42},
        "note": "Energy infrastructure is sensitive to storms and transition headlines.",
    },
    {
        "ticker": "JPM",
        "name": "JPMorgan Chase",
        "theme": "Credit / financial exposure",
        "stance": "mixed",
        "exposure": {"flood": 0.45, "storm": 0.42, "fire": 0.30, "tropical": 0.40},
        "note": "Climate data can flow into credit, insurance, and regional loan exposure.",
    },
    {
        "ticker": "TRV",
        "name": "Travelers",
        "theme": "Property insurance",
        "stance": "risk",
        "exposure": {"flood": 0.82, "fire": 0.76, "storm": 0.88, "tropical": 0.74},
        "note": "Severe weather can increase catastrophe claims and reserve pressure.",
    },
    {
        "ticker": "CB",
        "name": "Chubb",
        "theme": "Insurance / catastrophe risk",
        "stance": "risk",
        "exposure": {"flood": 0.76, "fire": 0.68, "storm": 0.80, "tropical": 0.70},
        "note": "Catastrophe risk, pricing, and claims sensitivity rise with active alerts.",
    },
    {
        "ticker": "CAT",
        "name": "Caterpillar",
        "theme": "Infrastructure / rebuild",
        "stance": "beneficiary",
        "exposure": {"flood": 0.48, "storm": 0.54, "fire": 0.32, "tropical": 0.40},
        "note": "Disaster recovery and infrastructure spending can support demand.",
    },
    {
        "ticker": "DE",
        "name": "Deere",
        "theme": "Agriculture equipment",
        "stance": "risk",
        "exposure": {"heat": 0.62, "flood": 0.52, "winter": 0.28, "storm": 0.24},
        "note": "Crop conditions, drought, flood, and farm-income expectations matter.",
    },
    {
        "ticker": "FSLR",
        "name": "First Solar",
        "theme": "Solar / transition",
        "stance": "beneficiary",
        "exposure": {"heat": 0.58, "air_quality": 0.36, "storm": 0.18},
        "note": "Climate pressure can support clean-energy and grid-transition narratives.",
    },
    {
        "ticker": "ENPH",
        "name": "Enphase Energy",
        "theme": "Distributed solar",
        "stance": "beneficiary",
        "exposure": {"heat": 0.52, "fire": 0.30, "air_quality": 0.35, "storm": 0.22},
        "note": "Distributed power and resilience themes can become more relevant.",
    },
    {
        "ticker": "MSFT",
        "name": "Microsoft",
        "theme": "Data centers / power demand",
        "stance": "mixed",
        "exposure": {"heat": 0.34, "storm": 0.18, "air_quality": 0.18},
        "note": "Data-center power load and adaptation spending link climate to mega-cap tech.",
    },
    {
        "ticker": "NVDA",
        "name": "NVIDIA",
        "theme": "AI infrastructure",
        "stance": "mixed",
        "exposure": {"heat": 0.30, "storm": 0.14, "air_quality": 0.14},
        "note": "Climate relevance is indirect through power demand and infrastructure buildout.",
    },
]


DAILY_CLIMATE_ETFS = [
    {"ticker": "XLU", "role": "Utilities stress / resilience", "stance": "mixed", "exposure": {"heat": 0.82, "storm": 0.62, "tropical": 0.50, "winter": 0.32}},
    {"ticker": "XLE", "role": "Energy infrastructure risk", "stance": "risk", "exposure": {"heat": 0.52, "tropical": 0.78, "storm": 0.36, "air_quality": 0.42}},
    {"ticker": "XLF", "role": "Credit and insurance channel", "stance": "mixed", "exposure": {"flood": 0.50, "storm": 0.46, "fire": 0.34, "tropical": 0.42}},
    {"ticker": "XLI", "role": "Infrastructure / supply chain", "stance": "mixed", "exposure": {"flood": 0.44, "storm": 0.50, "fire": 0.30, "tropical": 0.34}},
    {"ticker": "XLK", "role": "Power demand / adaptive tech", "stance": "beneficiary", "exposure": {"heat": 0.34, "storm": 0.18, "air_quality": 0.18}},
    {"ticker": "ICLN", "role": "Clean-energy transition", "stance": "beneficiary", "exposure": {"heat": 0.56, "air_quality": 0.48, "storm": 0.18}},
    {"ticker": "TAN", "role": "Solar transition", "stance": "beneficiary", "exposure": {"heat": 0.60, "air_quality": 0.46, "fire": 0.22}},
    {"ticker": "QCLN", "role": "Clean tech / EV", "stance": "beneficiary", "exposure": {"heat": 0.42, "air_quality": 0.50, "storm": 0.16}},
    {"ticker": "GLD", "role": "Macro hedge", "stance": "hedge", "exposure": {"storm": 0.24, "flood": 0.24, "tropical": 0.24, "fire": 0.22, "heat": 0.18}},
    {"ticker": "TLT", "role": "Duration / risk-off hedge", "stance": "hedge", "exposure": {"storm": 0.20, "flood": 0.20, "tropical": 0.18, "fire": 0.18, "heat": 0.14}},
]


def read_cached_daily_climate_signal(max_age_hours=3):
    if DAILY_CLIMATE_CACHE.exists():
        age_hours = (time.time() - DAILY_CLIMATE_CACHE.stat().st_mtime) / 3600
        if age_hours <= max_age_hours:
            try:
                cached = json.loads(DAILY_CLIMATE_CACHE.read_text(encoding="utf-8"))
                cached["source_mode"] = "cached NWS active alerts"
                return cached
            except Exception:
                pass
    return None


def classify_nws_alert(event):
    text = str(event or "").lower()
    categories = []
    if "heat" in text:
        categories.append("heat")
    if "flood" in text or "hydrologic" in text:
        categories.append("flood")
    if "fire" in text or "red flag" in text:
        categories.append("fire")
    if "hurricane" in text or "tropical" in text or "storm surge" in text:
        categories.append("tropical")
    if "thunderstorm" in text or "tornado" in text or "wind" in text or "dust storm" in text:
        categories.append("storm")
    if "winter" in text or "blizzard" in text or "snow" in text or "ice" in text or "freeze" in text:
        categories.append("winter")
    if "air quality" in text or "ozone" in text:
        categories.append("air_quality")
    return categories or ["other"]


def severity_weight(severity):
    return {
        "Extreme": 1.80,
        "Severe": 1.45,
        "Moderate": 1.10,
        "Minor": 0.75,
        "Unknown": 0.90,
    }.get(str(severity or "Unknown"), 0.90)


def fallback_daily_climate_signal():
    context = climate_data_context()
    pressure = clamp((context["climate_pressure_multiplier"] - 0.90) / 0.40, 0.0, 1.0)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_mode": "fallback daily climate pulse",
        "source_url": NWS_ACTIVE_ALERTS_URL,
        "alerts_total": 0,
        "climate_alerts": 0,
        "weighted_alert_score": 0.0,
        "daily_pressure": round(pressure, 4),
        "allocation_pressure": round(pressure * 0.55, 4),
        "top_driver": "long-run climate pressure",
        "category_counts": {k: 0 for k in DAILY_ALERT_CATEGORY_WEIGHTS},
        "category_intensity": {k: 0.0 for k in DAILY_ALERT_CATEGORY_WEIGHTS},
        "sample_events": [],
    }


def load_daily_climate_signal(force_refresh=False):
    if not force_refresh:
        cached = read_cached_daily_climate_signal()
        if cached:
            return cached

    try:
        text = download_text(
            NWS_ACTIVE_ALERTS_URL,
            timeout=18,
            headers={"User-Agent": NWS_USER_AGENT, "Accept": "application/geo+json"},
        )
        raw = json.loads(text)
        features = raw.get("features", [])
        category_counts = {k: 0 for k in DAILY_ALERT_CATEGORY_WEIGHTS}
        category_scores = {k: 0.0 for k in DAILY_ALERT_CATEGORY_WEIGHTS}
        samples = []
        weighted_score = 0.0
        climate_alerts = 0

        for feature in features:
            props = feature.get("properties", {}) if isinstance(feature, dict) else {}
            event = props.get("event", "")
            categories = [c for c in classify_nws_alert(event) if c in DAILY_ALERT_CATEGORY_WEIGHTS]
            if not categories:
                continue
            climate_alerts += 1
            sev = severity_weight(props.get("severity"))
            primary = max(categories, key=lambda c: DAILY_ALERT_CATEGORY_WEIGHTS[c])
            event_score = sev * DAILY_ALERT_CATEGORY_WEIGHTS[primary]
            weighted_score += event_score
            category_counts[primary] += 1
            category_scores[primary] += event_score
            if len(samples) < 5:
                samples.append(
                    {
                        "event": event,
                        "category": primary,
                        "severity": props.get("severity", "Unknown"),
                        "area": str(props.get("areaDesc", ""))[:90],
                    }
                )

        daily_pressure = clamp(math.log1p(weighted_score) / math.log1p(260), 0.0, 1.0)
        context = climate_data_context()
        long_run_pressure = clamp((context["climate_pressure_multiplier"] - 0.90) / 0.40, 0.0, 1.0)
        allocation_pressure = clamp(0.72 * daily_pressure + 0.28 * long_run_pressure, 0.0, 1.0)
        top_driver = max(category_scores.items(), key=lambda kv: kv[1])[0] if weighted_score > 0 else "none"
        category_intensity = {
            k: round(clamp(v / max(1.0, weighted_score), 0.0, 1.0), 4)
            for k, v in category_scores.items()
        }
        payload = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_mode": "NWS active weather alerts",
            "source_url": NWS_ACTIVE_ALERTS_URL,
            "alerts_total": len(features),
            "climate_alerts": climate_alerts,
            "weighted_alert_score": round(weighted_score, 3),
            "daily_pressure": round(daily_pressure, 4),
            "allocation_pressure": round(allocation_pressure, 4),
            "top_driver": top_driver,
            "category_counts": category_counts,
            "category_intensity": category_intensity,
            "sample_events": samples,
        }
        DAILY_CLIMATE_CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    except Exception:
        return fallback_daily_climate_signal()


def apply_daily_climate_overlay(latest_alloc, daily_signal):
    if not latest_alloc:
        return []
    pressure = safe_float(daily_signal.get("allocation_pressure"), 0.0)
    categories = daily_signal.get("category_intensity", {})
    physical_load = clamp(
        0.24 * safe_float(categories.get("heat"), 0.0)
        + 0.22 * safe_float(categories.get("flood"), 0.0)
        + 0.21 * safe_float(categories.get("fire"), 0.0)
        + 0.25 * safe_float(categories.get("tropical"), 0.0)
        + 0.16 * safe_float(categories.get("storm"), 0.0)
        + 0.06 * safe_float(categories.get("winter"), 0.0),
        0.0,
        1.0,
    )
    transition_load = clamp(0.30 * pressure + 0.20 * safe_float(categories.get("air_quality"), 0.0), 0.0, 1.0)
    row_scores = []
    for row in latest_alloc:
        ticker = row["ticker"]
        meta = SECTOR_ETFS.get(ticker, {})
        sector_stress = (
            0.58 * safe_float(meta.get("physical"), 0.50) * max(pressure, physical_load)
            + 0.25 * safe_float(meta.get("transition"), 0.50) * transition_load
            + 0.17 * (1 - safe_float(meta.get("resilience"), 0.50)) * max(pressure, physical_load)
        )
        adaptive_score = safe_float(meta.get("resilience"), 0.50) - sector_stress
        row_scores.append((row, sector_stress, adaptive_score))

    mean_score = sum(score for _, _, score in row_scores) / max(1, len(row_scores))
    raw_weights = {}
    for row, sector_stress, adaptive_score in row_scores:
        long_weight = safe_float(row.get("climate_weight"), 0.0)
        multiplier = clamp(1 + 0.36 * pressure * (adaptive_score - mean_score), 0.72, 1.28)
        raw_weights[row["ticker"]] = max(0.025, long_weight * multiplier)
    total = sum(raw_weights.values()) or 1.0

    adjusted = []
    for row, sector_stress, adaptive_score in row_scores:
        out = dict(row)
        long_weight = safe_float(row.get("climate_weight"), 0.0)
        final_weight = raw_weights[row["ticker"]] / total
        out["base_climate_weight"] = round(long_weight, 4)
        out["climate_weight"] = round(final_weight, 4)
        out["target_dollars"] = round(final_weight * DEFAULT_PORTFOLIO_VALUE, 2)
        out["long_term_adjustment_bps"] = int(round((long_weight - safe_float(row.get("benchmark_weight"), 0.0)) * 10000))
        out["daily_adjustment_bps"] = int(round((final_weight - long_weight) * 10000))
        out["total_adjustment_bps"] = int(round((final_weight - safe_float(row.get("benchmark_weight"), 0.0)) * 10000))
        out["daily_sector_stress"] = round(sector_stress, 4)
        out["daily_adaptive_score"] = round(adaptive_score, 4)
        out["daily_driver"] = (
            f"{daily_signal.get('top_driver', 'daily')} alert pulse; "
            f"sector stress {sector_stress:.2f}, resilience {safe_float(SECTOR_ETFS.get(row['ticker'], {}).get('resilience'), 0.0):.2f}"
        )
        out["action"] = allocation_action(final_weight, safe_float(row.get("benchmark_weight"), 0.0))
        adjusted.append(out)
    return adjusted


def fallback_us_universe():
    rows = [
        ("AAPL", "Apple Inc. Common Stock", "NASDAQ", False),
        ("MSFT", "Microsoft Corporation Common Stock", "NASDAQ", False),
        ("NVDA", "NVIDIA Corporation Common Stock", "NASDAQ", False),
        ("AMZN", "Amazon.com Inc. Common Stock", "NASDAQ", False),
        ("GOOGL", "Alphabet Inc. Class A Common Stock", "NASDAQ", False),
        ("META", "Meta Platforms Inc. Class A Common Stock", "NASDAQ", False),
        ("TSLA", "Tesla Inc. Common Stock", "NASDAQ", False),
        ("JPM", "JPMorgan Chase & Co. Common Stock", "NYSE", False),
        ("XOM", "Exxon Mobil Corporation Common Stock", "NYSE", False),
        ("CVX", "Chevron Corporation Common Stock", "NYSE", False),
        ("NEE", "NextEra Energy Inc. Common Stock", "NYSE", False),
        ("CAT", "Caterpillar Inc. Common Stock", "NYSE", False),
        ("XLE", "Energy Select Sector SPDR Fund", "NYSE Arca", True),
        ("XLK", "Technology Select Sector SPDR Fund", "NYSE Arca", True),
    ]
    return [
        {
            "symbol": s,
            "name": n,
            "exchange": e,
            "is_etf": is_etf,
            "security_type": "ETF" if is_etf else "Common Stock",
            "source": "fallback",
        }
        for s, n, e, is_etf in rows
    ]


def load_us_listed_universe(force_refresh=False):
    if not force_refresh and UNIVERSE_CACHE.exists():
        age_days = (time.time() - UNIVERSE_CACHE.stat().st_mtime) / 86400
        if age_days <= 7:
            try:
                return json.loads(UNIVERSE_CACHE.read_text(encoding="utf-8"))
            except Exception:
                pass

    universe = []
    try:
        nasdaq_rows = parse_pipe_rows(download_text(NASDAQ_LISTED_URL))
        for row in nasdaq_rows:
            if row.get("Test Issue", "N") != "N":
                continue
            symbol = row.get("Symbol", "").strip()
            if not symbol:
                continue
            is_etf = row.get("ETF", "N") == "Y"
            universe.append(
                {
                    "symbol": symbol,
                    "name": row.get("Security Name", symbol).strip(),
                    "exchange": "NASDAQ",
                    "is_etf": is_etf,
                    "security_type": "ETF" if is_etf else "Common Stock",
                    "source": "nasdaqtrader",
                }
            )

        other_rows = parse_pipe_rows(download_text(OTHER_LISTED_URL))
        for row in other_rows:
            if row.get("Test Issue", "N") != "N":
                continue
            symbol = row.get("ACT Symbol", "").strip()
            if not symbol:
                continue
            is_etf = row.get("ETF", "N") == "Y"
            exchange = EXCHANGE_MAP.get(row.get("Exchange", ""), row.get("Exchange", "Other"))
            universe.append(
                {
                    "symbol": symbol,
                    "name": row.get("Security Name", symbol).strip(),
                    "exchange": exchange,
                    "is_etf": is_etf,
                    "security_type": "ETF" if is_etf else "Common Stock",
                    "source": "nasdaqtrader",
                }
            )
    except Exception:
        universe = fallback_us_universe()

    deduped = {}
    for row in universe:
        symbol = row["symbol"]
        if symbol not in deduped:
            deduped[symbol] = row
    out = sorted(deduped.values(), key=lambda r: (r["is_etf"], r["symbol"]))
    try:
        UNIVERSE_CACHE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return out


def search_us_universe(query="", limit=80, include_etfs=False):
    query = str(query or "").strip().upper()
    limit = int(clamp(safe_float(limit, 80), 1, 500))
    rows = load_us_listed_universe()
    if not include_etfs:
        rows = [r for r in rows if not r.get("is_etf")]
    if query:
        tokens = [t for t in query.replace(",", " ").split() if t]
        def matches(row):
            haystack = f"{row.get('symbol','')} {row.get('name','')} {row.get('exchange','')}".upper()
            return all(t in haystack for t in tokens)
        rows = [r for r in rows if matches(r)]
    return rows[:limit]


def climate_signal():
    official = load_official_climate_data()
    source_rows = official.get("rows", [])
    if not source_rows:
        years = [r[0] for r in CLIMATE_PROXY]
        temps = [r[1] for r in CLIMATE_PROXY]
        disasters = [r[2] for r in CLIMATE_PROXY]
        co2 = [0 for _ in years]
        costs = [0 for _ in years]
    else:
        source_rows = [r for r in source_rows if r.get("year", 0) >= 1980 and r.get("billion_dollar_disasters") is not None]
        years = [r["year"] for r in source_rows]
        temps = [r.get("temperature_anomaly", 0) for r in source_rows]
        disasters = [r.get("billion_dollar_disasters", 0) for r in source_rows]
        co2 = [r.get("co2_ppm", 0) for r in source_rows]
        costs = [r.get("disaster_cost_proxy", 0) for r in source_rows]
    zt = zscores(temps)
    zd = zscores(disasters)
    zc = zscores(co2)
    zk = zscores(costs)
    score = [0.40 * a + 0.20 * b + 0.25 * c + 0.15 * k for a, b, c, k in zip(zt, zd, zc, zk)]
    threshold = percentile(score, 0.75)
    rows = []
    for i, year in enumerate(years):
        state = "High Climate Risk" if score[i] >= threshold else "Normal Climate Risk"
        rows.append(
            {
                "year": year,
                "temperature_anomaly": round(temps[i], 3),
                "co2_ppm": round(co2[i], 2),
                "disaster_frequency": disasters[i],
                "disaster_cost_proxy": round(costs[i], 2),
                "temperature_z": round(zt[i], 3),
                "co2_z": round(zc[i], 3),
                "disaster_z": round(zd[i], 3),
                "cost_z": round(zk[i], 3),
                "climate_risk_score": round(score[i], 3),
                "risk_state": state,
                "top_quartile_threshold": round(threshold, 3),
            }
        )
    return rows


def regime_for_year(year, climate_rows):
    lookup = {r["year"]: r for r in climate_rows}
    prev = lookup.get(year - 1) or lookup.get(max(lookup))
    high = prev and prev["risk_state"] == "High Climate Risk"
    return {
        "allocation_year": year,
        "signal_year": prev["year"] if prev else year - 1,
        "regime": "High Climate Risk" if high else "Normal Climate Risk",
        "score": prev["climate_risk_score"] if prev else 0,
    }


def climate_weight_policy(regime):
    tickers = list(SECTOR_ETFS.keys())
    base = {t: 1 / len(tickers) for t in tickers}
    if regime != "High Climate Risk":
        return base
    raw = {}
    for ticker, meta in SECTOR_ETFS.items():
        risk = 0.55 * meta["physical"] + 0.45 * meta["transition"]
        resilience = meta["resilience"]
        raw[ticker] = max(0.05, 1.0 + 0.65 * resilience - 0.90 * risk)
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}


def sector_climate_loss_rate(meta, scenario):
    physical = scenario["physical_shock"] * meta["physical"]
    transition = scenario["transition_shock"] * meta["transition"]
    litigation = scenario["litigation_shock"] * (1 - meta["resilience"])
    gross = physical + transition + litigation
    resilience_offset = 0.030 * meta["resilience"]
    return max(0.0, gross - resilience_offset)


def climate_scenario_matrix(allocation_rows):
    if not allocation_rows:
        return [], {}
    latest_year = max(r["year"] for r in allocation_rows)
    latest_alloc = [r for r in allocation_rows if r["year"] == latest_year]
    weights = {r["ticker"]: safe_float(r["climate_weight"]) for r in latest_alloc}
    rows = []
    weighted_losses = []
    for scenario in CLIMATE_SCENARIOS:
        sector_losses = {}
        portfolio_loss = 0.0
        for ticker, meta in SECTOR_ETFS.items():
            loss = sector_climate_loss_rate(meta, scenario)
            sector_losses[ticker] = round(loss, 4)
            portfolio_loss += weights.get(ticker, 0.0) * loss
        weighted_losses.append((portfolio_loss, scenario["probability"]))
        rows.append(
            {
                "scenario": scenario["name"],
                "probability": scenario["probability"],
                "carbon_price": scenario["carbon_price"],
                "portfolio_loss_rate": round(portfolio_loss, 4),
                "portfolio_loss_dollars": round(portfolio_loss * DEFAULT_PORTFOLIO_VALUE, 2),
                "sector_losses": sector_losses,
                "narrative": scenario["narrative"],
            }
        )
    expected_loss = sum(loss * prob for loss, prob in weighted_losses)
    worst_loss = max((loss for loss, _ in weighted_losses), default=0.0)
    sorted_rows = sorted(rows, key=lambda r: r["portfolio_loss_rate"], reverse=True)
    tail = sorted_rows[:2]
    cvor_95 = sum(r["portfolio_loss_rate"] for r in tail) / max(1, len(tail))
    summary = {
        "expected_climate_loss_rate": round(expected_loss, 4),
        "expected_climate_loss_dollars": round(expected_loss * DEFAULT_PORTFOLIO_VALUE, 2),
        "worst_scenario_loss_rate": round(worst_loss, 4),
        "worst_scenario_loss_dollars": round(worst_loss * DEFAULT_PORTFOLIO_VALUE, 2),
        "cvor_95_loss_rate": round(cvor_95, 4),
        "cvor_95_loss_dollars": round(cvor_95 * DEFAULT_PORTFOLIO_VALUE, 2),
    }
    return rows, summary


def method2_damage_fraction(temp_c, alpha3):
    # Dietz et al. Method 2 uses D_t = 1 / (1 + g(T_t)).
    # The loss share is therefore 1 - D_t, with g(T) = alpha2*T^2 + (alpha3*T)^7.
    g_t = METHOD2_ALPHA2 * (temp_c ** 2) + ((alpha3 * temp_c) ** 7)
    return 1 - (1 / (1 + g_t))


def method2_temperature_path(step, steps, target_warming, current_warming=CURRENT_WARMING_C):
    progress = step / max(1, steps)
    return current_warming + (target_warming - current_warming) * (progress ** 1.15)


def method2_loss_pct_for_path(steps, cashflow_growth, discount_rate, target_warming, alpha3, company_exposure, current_warming):
    pv_no_damage = 0.0
    pv_climate_damage = 0.0
    cashflow_no_damage = 1.0
    for step in range(1, steps + 1):
        cashflow_no_damage *= 1 + cashflow_growth
        temp = method2_temperature_path(step, steps, target_warming, current_warming=current_warming)
        global_damage = method2_damage_fraction(temp, alpha3)
        issuer_damage = clamp(global_damage * company_exposure, 0.0, 0.75)
        discount = (1 + discount_rate) ** step
        pv_no_damage += cashflow_no_damage / discount
        pv_climate_damage += (cashflow_no_damage * (1 - issuer_damage)) / discount
    return max(0.0, (pv_no_damage - pv_climate_damage) / max(1e-12, pv_no_damage))


def summarize_method2_losses(losses, market_cap):
    losses = sorted(losses)
    mean_loss = sum(losses) / max(1, len(losses))
    p95 = percentile(losses, 0.95)
    p99 = percentile(losses, 0.99)
    tail = [x for x in losses if x >= p95] or [p95]
    tail_mean = sum(tail) / len(tail)
    return {
        "mean_pct": round(mean_loss, 4),
        "p95_pct": round(p95, 4),
        "p99_pct": round(p99, 4),
        "cvor95_pct": round(tail_mean, 4),
        "mean_dollars": round(mean_loss * market_cap, 2),
        "cvor95_dollars": round(tail_mean * market_cap, 2),
    }


def method2_data_quality(info):
    score = 20
    notes = []
    if info.get("marketCap"):
        score += 25
    else:
        notes.append("market cap fallback")
    if info.get("sector"):
        score += 20
    else:
        notes.append("sector inferred")
    if info.get("beta") is not None:
        score += 15
    else:
        notes.append("beta fallback")
    if info.get("revenueGrowth") is not None or info.get("earningsGrowth") is not None:
        score += 15
    else:
        notes.append("growth fallback")
    if info.get("shortName") or info.get("longName"):
        score += 5
    return {
        "score": int(clamp(score, 0, 100)),
        "label": "High" if score >= 80 else ("Medium" if score >= 55 else "Low"),
        "notes": ", ".join(notes) if notes else "market data available",
    }


def method2_company_cvor(ticker, info=None, draws=METHOD2_DRAWS, end_year=METHOD2_END_YEAR):
    info = info or {}
    context = climate_data_context()
    symbol = yahoo_symbol(ticker)
    sector = info.get("sector") or guess_sector(symbol)
    sensitivity = COMPANY_SECTOR_SENSITIVITY.get(sector, 0.50)
    market_cap = safe_float(info.get("marketCap"), fallback_market_cap(symbol))
    beta = safe_float(info.get("beta"), 1.0)
    revenue_growth = safe_float(info.get("revenueGrowth"), 0.0)
    earnings_growth = safe_float(info.get("earningsGrowth"), 0.0)
    growth_signal = revenue_growth if abs(revenue_growth) > 1e-6 else earnings_growth
    growth_signal = clamp(growth_signal, -0.05, 0.08)
    steps = max(20, int(end_year - CURRENT_YEAR))
    rng = random.Random(sum(ord(c) for c in symbol) + 2100)
    bau_losses = []
    mitigation_losses = []

    for _ in range(int(draws)):
        tfp_growth = clamp(rng.gauss(0.0084, 0.0059), -0.006, 0.026)
        cashflow_growth = clamp(0.024 + tfp_growth + 0.18 * growth_signal, 0.004, 0.060)
        climate_sensitivity = clamp(rng.lognormvariate(math.log(2.9) - 0.5 * (0.38 ** 2), 0.38), 0.75, 6.0)
        bau_target_warming = clamp(2.5 * climate_sensitivity / 2.9 * context["climate_pressure_multiplier"], max(context["current_warming"], 1.35), 5.95)
        mitigation_target_warming = min(bau_target_warming, clamp(2.0 * climate_sensitivity / 2.9, max(1.10, context["current_warming"] * 0.95), 3.35))
        alpha3 = rng.uniform(0.0, METHOD2_ALPHA3_MAX)
        discount_rate = clamp(METHOD2_DISCOUNT_RATE + 0.006 * (beta - 1.0), 0.025, 0.075)
        company_exposure = clamp((0.42 + 0.92 * sensitivity + 0.14 * max(0.0, beta - 1.0)) * context["climate_pressure_multiplier"], 0.28, 1.95)
        bau_losses.append(method2_loss_pct_for_path(steps, cashflow_growth, discount_rate, bau_target_warming, alpha3, company_exposure, context["current_warming"]))
        mitigation_losses.append(method2_loss_pct_for_path(steps, cashflow_growth, discount_rate, mitigation_target_warming, alpha3, company_exposure, context["current_warming"]))

    bau = summarize_method2_losses(bau_losses, market_cap)
    mitigation = summarize_method2_losses(mitigation_losses, market_cap)
    quality = method2_data_quality(info)
    return {
        "method2_mean_pct": bau["mean_pct"],
        "method2_p95_pct": bau["p95_pct"],
        "method2_p99_pct": bau["p99_pct"],
        "method2_cvor95_pct": bau["cvor95_pct"],
        "method2_mean_dollars": bau["mean_dollars"],
        "method2_cvor95_dollars": bau["cvor95_dollars"],
        "method2_2c_mean_pct": mitigation["mean_pct"],
        "method2_2c_p95_pct": mitigation["p95_pct"],
        "method2_2c_p99_pct": mitigation["p99_pct"],
        "method2_2c_cvor95_pct": mitigation["cvor95_pct"],
        "method2_2c_cvor95_dollars": mitigation["cvor95_dollars"],
        "method2_p95_reduction_pct": round(max(0.0, bau["p95_pct"] - mitigation["p95_pct"]), 4),
        "method2_cvor95_reduction_pct": round(max(0.0, bau["cvor95_pct"] - mitigation["cvor95_pct"]), 4),
        "method2_market_cap": round(market_cap, 2),
        "method2_discount_rate": round(clamp(METHOD2_DISCOUNT_RATE + 0.006 * (beta - 1.0), 0.025, 0.075), 4),
        "method2_horizon_year": end_year,
        "method2_draws": int(draws),
        "method2_sector": sector,
        "method2_sector_sensitivity": round(sensitivity, 3),
        "method2_current_warming": context["current_warming"],
        "method2_climate_data_year": context["latest_year"],
        "method2_co2_ppm": context["co2_ppm"],
        "method2_disaster_10y_avg": context["disaster_10y_avg"],
        "method2_climate_pressure_multiplier": context["climate_pressure_multiplier"],
        "method2_climate_source_mode": context["source_mode"],
        "method2_data_quality_score": quality["score"],
        "method2_data_quality_label": quality["label"],
        "method2_data_quality_notes": quality["notes"],
        "method2_note": "PV loss from climate-damaged cash-flow path vs no-damage counterfactual, based on Dietz et al. Method 2. The 2C path excludes mitigation costs, matching climate-impact VaR rather than net transition-cost PV.",
    }


def fetch_etf_prices(tickers, start=f"{START_YEAR}-01-01"):
    cache = DATA_DIR / "etf_prices_cache.json"
    if yf is not None:
        try:
            data = yf.download(tickers, start=start, auto_adjust=True, progress=False, threads=True)
            if data is not None and not data.empty:
                close = data["Close"] if "Close" in data.columns else data
                if hasattr(close, "dropna"):
                    annual = {}
                    for t in tickers:
                        series = close[t].dropna() if t in close else close.dropna()
                        if len(series) > 30:
                            yearly = series.resample("YE").last().pct_change().dropna()
                            annual[t] = {str(idx.year): round(float(v), 5) for idx, v in yearly.items()}
                    if annual:
                        cache.write_text(json.dumps(annual, indent=2), encoding="utf-8")
                        return annual, "yfinance live market data"
        except Exception:
            pass
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8")), "cached yfinance market data"
        except Exception:
            pass
    return simulated_annual_returns(tickers), "deterministic simulated market data"


def normalize_symbols(raw, max_count=12):
    if isinstance(raw, str):
        parts = raw.replace("\n", ",").replace(";", ",").split(",")
    else:
        parts = list(raw or [])
    symbols = []
    for item in parts:
        symbol = yahoo_symbol(str(item))
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols[:max_count]


def simulated_ohlcv(symbol, period="6mo", interval="1d"):
    if interval in {"1m", "2m", "5m", "15m", "30m"} or period == "1d":
        minute_step = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30}.get(interval, 1)
        bars = max(16, min(390, 390 // minute_step))
        rng = random.Random(sum(ord(c) for c in symbol) + bars + minute_step)
        price = 80 + (sum(ord(c) for c in symbol) % 180)
        rows = []
        market_open = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
        for i in range(bars):
            stamp = market_open.timestamp() + i * minute_step * 60
            date = datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")
            drift = rng.gauss(0.00008, 0.0028 * math.sqrt(minute_step))
            open_price = price
            close = open_price * (1 + drift)
            high = max(open_price, close) * (1 + abs(rng.gauss(0.0008, 0.0007)))
            low = min(open_price, close) * (1 - abs(rng.gauss(0.0008, 0.0007)))
            volume = int(10_000 + rng.random() * 900_000)
            rows.append(
                {
                    "date": date,
                    "open": round(open_price, 4),
                    "high": round(high, 4),
                    "low": round(low, 4),
                    "close": round(close, 4),
                    "volume": volume,
                }
            )
            price = close
        return rows

    days_map = {"5d": 5, "1mo": 22, "3mo": 66, "6mo": 132, "1y": 252, "2y": 504}
    days = days_map.get(period, 132)
    rng = random.Random(sum(ord(c) for c in symbol) + days)
    price = 80 + (sum(ord(c) for c in symbol) % 180)
    rows = []
    for i in range(days):
        date = datetime.fromtimestamp(time.time() - (days - i) * 86400).strftime("%Y-%m-%d")
        gap = rng.gauss(0, 0.006)
        drift = rng.gauss(0.0004, 0.018)
        open_price = price * (1 + gap)
        close = open_price * (1 + drift)
        high = max(open_price, close) * (1 + abs(rng.gauss(0.006, 0.006)))
        low = min(open_price, close) * (1 - abs(rng.gauss(0.006, 0.006)))
        volume = int(1_000_000 + rng.random() * 12_000_000)
        rows.append(
            {
                "date": date,
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": volume,
            }
        )
        price = close
    return rows


def frame_to_ohlcv_rows(frame):
    rows = []
    if frame is None or getattr(frame, "empty", True):
        return rows
    frame = frame.dropna(how="all")
    for idx, row in frame.iterrows():
        try:
            open_price = safe_float(row.get("Open"), None)
            high = safe_float(row.get("High"), None)
            low = safe_float(row.get("Low"), None)
            close = safe_float(row.get("Close"), None)
            volume = safe_float(row.get("Volume"), 0)
            if open_price is None or high is None or low is None or close is None:
                continue
            if hasattr(idx, "strftime"):
                if getattr(idx, "hour", 0) or getattr(idx, "minute", 0):
                    date_label = idx.strftime("%Y-%m-%d %H:%M")
                else:
                    date_label = idx.strftime("%Y-%m-%d")
            else:
                date_label = str(idx)[:16]
            rows.append(
                {
                    "date": date_label,
                    "open": round(open_price, 4),
                    "high": round(high, 4),
                    "low": round(low, 4),
                    "close": round(close, 4),
                    "volume": int(volume or 0),
                }
            )
        except Exception:
            continue
    return rows


def market_chart_payload(symbols, period="6mo", interval="1d"):
    symbols = normalize_symbols(symbols, max_count=12)
    if not symbols:
        symbols = ["SPY", "QQQ", "AAPL", "XOM"]
    period = period if period in {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y"} else "6mo"
    interval = interval if interval in {"1m", "2m", "5m", "15m", "30m", "1d", "1wk", "1mo"} else "1d"
    if period == "1d" and interval not in {"1m", "2m", "5m", "15m", "30m"}:
        interval = "1m"
    if interval in {"1m", "2m", "5m", "15m", "30m"} and period not in {"1d", "5d"}:
        period = "1d"
    charts = {}
    quotes = []
    source = "deterministic fallback"

    if yf is not None:
        try:
            data = yf.download(
                tickers=symbols,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if data is not None and not data.empty:
                source = "yfinance live/delayed OHLCV"
                for symbol in symbols:
                    if len(symbols) == 1:
                        frame = data.copy()
                    elif hasattr(data.columns, "nlevels") and data.columns.nlevels > 1 and symbol in data.columns.get_level_values(0):
                        frame = data[symbol].copy()
                    else:
                        frame = None
                    rows = frame_to_ohlcv_rows(frame)
                    if rows:
                        charts[symbol] = rows
        except Exception:
            charts = {}

    for symbol in symbols:
        if symbol not in charts:
            charts[symbol] = simulated_ohlcv(symbol, period=period, interval=interval)
        rows = charts.get(symbol, [])
        last = rows[-1] if rows else {}
        prev = rows[-2] if len(rows) >= 2 else last
        close = safe_float(last.get("close"), 0)
        prev_close = safe_float(prev.get("close"), close)
        change = close - prev_close
        change_pct = change / prev_close if prev_close else 0
        quotes.append(
            {
                "ticker": symbol,
                "last": round(close, 4),
                "change": round(change, 4),
                "change_pct": round(change_pct, 4),
                "open": last.get("open"),
                "high": last.get("high"),
                "low": last.get("low"),
                "volume": last.get("volume"),
                "bars": len(rows),
            }
        )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "period": period,
        "interval": interval,
        "source": source,
        "symbols": symbols,
        "active_ticker": next((symbol for symbol in symbols if charts.get(symbol)), symbols[0]),
        "quotes": quotes,
        "charts": charts,
    }


def etf_watchlist_payload():
    symbols = []
    for group_symbols in ETF_WATCHLIST.values():
        for symbol in group_symbols:
            if symbol not in symbols:
                symbols.append(symbol)
    market = market_chart_payload(symbols, period="1mo", interval="1d")
    quote_lookup = {q["ticker"]: q for q in market["quotes"]}
    rows = []
    for group, group_symbols in ETF_WATCHLIST.items():
        for symbol in group_symbols:
            q = quote_lookup.get(symbol, {"ticker": symbol})
            rows.append({**q, "group": group})
    return {
        "generated_at": market["generated_at"],
        "source": market["source"],
        "rows": rows,
        "groups": ETF_WATCHLIST,
    }


def market_stats(rows):
    rows = rows or []
    closes = [safe_float(r.get("close"), 0.0) for r in rows if safe_float(r.get("close"), 0.0) > 0]
    volumes = [safe_float(r.get("volume"), 0.0) for r in rows]
    if len(closes) < 2:
        return {
            "last": closes[-1] if closes else 0.0,
            "period_return": 0.0,
            "last_return": 0.0,
            "volatility": 0.0,
            "avg_volume": sum(volumes) / max(1, len(volumes)),
        }
    returns = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes)) if closes[i - 1] > 0]
    mean = sum(returns) / max(1, len(returns))
    vol = math.sqrt(sum((r - mean) ** 2 for r in returns) / max(1, len(returns) - 1)) if len(returns) > 1 else 0.0
    return {
        "last": closes[-1],
        "period_return": closes[-1] / closes[0] - 1 if closes[0] else 0.0,
        "last_return": returns[-1] if returns else 0.0,
        "volatility": vol,
        "avg_volume": sum(volumes) / max(1, len(volumes)),
    }


def etf_group(symbol):
    for group, symbols in ETF_WATCHLIST.items():
        if symbol in symbols:
            return group
    return "ETF"


def etf_climate_profile(symbol):
    if symbol in SECTOR_ETFS:
        meta = SECTOR_ETFS[symbol]
        risk = clamp(
            0.42 * safe_float(meta.get("physical"), 0.5)
            + 0.42 * safe_float(meta.get("transition"), 0.5)
            + 0.16 * (1 - safe_float(meta.get("resilience"), 0.5)),
            0.05,
            0.95,
        )
        return meta["name"], risk, meta["client_note"]
    if symbol in {"ICLN", "QCLN", "TAN", "PBW"}:
        return "Climate / Clean Energy", 0.26, "Cleaner-energy exposure can benefit from transition demand, but short-term volatility can be high."
    if symbol in {"TLT", "IEF", "LQD", "HYG"}:
        return "Rates / Credit", 0.38, "Climate risk enters through credit spreads, insurance, and macro-rate sensitivity."
    if symbol in {"GLD", "SLV"}:
        return "Commodities", 0.32, "Hard-asset hedge sleeve with indirect climate and inflation sensitivity."
    if symbol in {"USO", "UNG"}:
        return "Energy commodity", 0.78, "Direct fossil-energy commodity exposure is climate and policy sensitive."
    if symbol in {"SPY", "DIA", "IWM"}:
        return "Broad market", 0.48, "Broad index exposure diversifies issuer-specific climate risk."
    if symbol == "QQQ":
        return "Growth / Technology", 0.36, "Tech-heavy index is relatively asset-light but still exposed to power and data-center demand."
    return etf_group(symbol), 0.50, "ETF climate score is estimated from group exposure."


def optimizer_mode(mode):
    mode = str(mode or "etf_stock").lower()
    return mode if mode in OPTIMIZER_MODE_LABELS else "etf_stock"


def optimizer_horizon(horizon):
    horizon = str(horizon or "long").lower()
    return horizon if horizon in {"short", "long"} else "long"


def optimizer_style(style):
    style = str(style or "balanced").lower()
    return style if style in OPTIMIZER_STYLES else "balanced"


def allocation_signal(total_score, climate_score, risk_score, weight):
    if weight >= 0.18 and total_score >= 0.68:
        return "Core / overweight"
    if total_score >= 0.60:
        return "Add / hold"
    if climate_score < 0.35:
        return "Climate-risk watch"
    if risk_score < 0.35:
        return "Volatility watch"
    return "Small weight / monitor"


def portfolio_optimizer_payload(mode="etf_stock", capital=None, horizon="long", style="balanced", etfs="", stocks=""):
    mode = optimizer_mode(mode)
    horizon = optimizer_horizon(horizon)
    style_key = optimizer_style(style)
    profile = OPTIMIZER_STYLES[style_key]
    capital_value = clamp(safe_float(capital, DEFAULT_PORTFOLIO_VALUE), 10_000, 5_000_000_000)

    etf_symbols = normalize_symbols(etfs, max_count=18) if etfs else list(DEFAULT_OPTIMIZER_ETFS)
    stock_symbols = normalize_symbols(stocks, max_count=12) if stocks else list(DEFAULT_OPTIMIZER_STOCKS)
    include_etfs = mode in {"etf_only", "etf_stock"}
    include_stocks = mode in {"stock_only", "etf_stock"}
    if not include_etfs:
        etf_symbols = []
    if not include_stocks:
        stock_symbols = []

    symbols = []
    for symbol in etf_symbols + stock_symbols:
        if symbol not in symbols:
            symbols.append(symbol)
    if not symbols:
        symbols = list(DEFAULT_OPTIMIZER_ETFS)
        etf_symbols = list(DEFAULT_OPTIMIZER_ETFS)
        include_etfs = True

    market_period = "1d" if horizon == "short" else "3mo"
    market_interval = "1m" if horizon == "short" else "1d"
    market = market_chart_payload(symbols, period=market_period, interval=market_interval)
    chart_lookup = market.get("charts", {})

    stock_scan = {}
    if stock_symbols:
        try:
            stock_scan = {r["ticker"]: r for r in company_scan(stock_symbols)}
        except Exception:
            stock_scan = {}

    daily_signal = load_daily_climate_signal()
    daily_pressure = safe_float(daily_signal.get("allocation_pressure"), 0.0)
    rows = []
    for symbol in symbols:
        stats = market_stats(chart_lookup.get(symbol, []))
        last_price = stats["last"]
        short_term = horizon == "short"
        momentum_raw = stats["period_return"] * (16 if short_term else 5) + stats["last_return"] * (28 if short_term else 6)
        momentum_score = clamp(0.50 + momentum_raw, 0.03, 0.97)
        vol_limit = 0.0048 if short_term else 0.035
        risk_score = clamp(1 - stats["volatility"] / max(vol_limit, 1e-6), 0.03, 0.97)
        liquidity_score = clamp(math.log1p(stats["avg_volume"]) / math.log1p(60_000_000), 0.05, 0.98)
        market_score = clamp(0.55 * momentum_score + 0.25 * liquidity_score + 0.20 * risk_score, 0.03, 0.97)

        if symbol in stock_symbols:
            scan = stock_scan.get(symbol, {})
            asset_type = "Stock"
            sector = scan.get("sector") or guess_sector(symbol)
            cvor_proxy = max(
                safe_float(scan.get("method2_p95_pct"), 0.055),
                abs(safe_float(scan.get("market_cvar_95"), -0.03)) * 0.55,
            )
            climate_risk = clamp(cvor_proxy / 0.14, 0.05, 0.95)
            climate_score = clamp(1 - climate_risk, 0.05, 0.95)
            rationale = (
                f"{sector}; Method 2 P95 {cvor_proxy:.2%}; "
                f"{'today momentum' if short_term else '3M trend'} {stats['period_return']:.2%}."
            )
        else:
            asset_type = "ETF"
            sector, climate_risk, note = etf_climate_profile(symbol)
            cvor_proxy = climate_risk * 0.10
            climate_score = clamp(1 - climate_risk, 0.05, 0.95)
            rationale = f"{sector}; {note} {'Today 1m trend' if short_term else '3M trend'} {stats['period_return']:.2%}."

        total_score = (
            profile["market_weight"] * market_score
            + profile["climate_weight"] * climate_score
            + profile["risk_weight"] * risk_score
        )
        if short_term:
            total_score = 0.76 * total_score + 0.24 * market_score
        else:
            total_score = 0.82 * total_score + 0.18 * climate_score
        total_score *= 1 - 0.16 * daily_pressure * climate_risk
        rows.append(
            {
                "ticker": symbol,
                "asset_type": asset_type,
                "sector": sector,
                "last": round(last_price, 4),
                "momentum": round(stats["period_return"], 5),
                "volatility": round(stats["volatility"], 5),
                "market_score": round(market_score, 4),
                "climate_score": round(climate_score, 4),
                "risk_score": round(risk_score, 4),
                "total_score": round(clamp(total_score, 0.01, 0.99), 4),
                "cvor_proxy": round(cvor_proxy, 4),
                "raw_weight": max(0.002, clamp(total_score, 0.01, 0.99) ** 1.35),
                "rationale": rationale,
            }
        )

    if mode == "etf_only":
        sleeves = {"ETF": 1.0, "Stock": 0.0}
    elif mode == "stock_only":
        sleeves = {"ETF": 0.0, "Stock": 1.0}
    else:
        stock_sleeve = profile["stock_sleeve"]
        if horizon == "short":
            stock_sleeve += 0.08
        if style_key == "growth":
            stock_sleeve += 0.06
        if style_key in {"low_vol", "climate_defense"}:
            stock_sleeve -= 0.06
        stock_sleeve = clamp(stock_sleeve, 0.20, 0.62)
        sleeves = {"ETF": 1 - stock_sleeve, "Stock": stock_sleeve}

    for asset_type in ["ETF", "Stock"]:
        group = [r for r in rows if r["asset_type"] == asset_type]
        sleeve_weight = sleeves.get(asset_type, 0.0)
        raw_total = sum(r["raw_weight"] for r in group) or 1.0
        for row in group:
            weight = sleeve_weight * row["raw_weight"] / raw_total
            row["target_weight"] = round(weight, 4)
            row["target_dollars"] = round(weight * capital_value, 2)
            row["estimated_shares"] = round(row["target_dollars"] / row["last"], 2) if row["last"] else 0
            row["action"] = allocation_signal(row["total_score"], row["climate_score"], row["risk_score"], weight)

    rows = sorted(rows, key=lambda r: r.get("target_weight", 0.0), reverse=True)
    for row in rows:
        row.pop("raw_weight", None)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "mode_label": OPTIMIZER_MODE_LABELS[mode],
        "style": style_key,
        "style_label": profile["label"],
        "style_note": profile["note"],
        "horizon": horizon,
        "horizon_label": "Short-term holding" if horizon == "short" else "Long-term holding",
        "capital": round(capital_value, 2),
        "daily_climate_overlay": daily_pressure,
        "market_source": market["source"],
        "market_period": market["period"],
        "market_interval": market["interval"],
        "holding_note": (
            "Short-term mode uses today's 1-minute bars plus the live climate alert overlay."
            if horizon == "short"
            else "Long-term mode uses recent daily trend, Method 2 CVOR, and structural climate resilience."
        ),
        "rows": rows,
    }


def daily_climate_category_signal(daily_signal, category):
    counts = daily_signal.get("category_counts", {}) or {}
    intensity = daily_signal.get("category_intensity", {}) or {}
    count_score = clamp(safe_float(counts.get(category), 0.0) / 45.0, 0.0, 1.0)
    intensity_score = safe_float(intensity.get(category), 0.0)
    return clamp(0.72 * intensity_score + 0.28 * count_score, 0.0, 1.0)


def climate_relation_score(exposure, daily_signal):
    pressure = safe_float(daily_signal.get("allocation_pressure"), 0.0)
    if not exposure:
        return round(pressure * 0.25, 4)
    active = 0.0
    possible = 0.0
    for category, weight in exposure.items():
        w = safe_float(weight, 0.0)
        possible += w
        active += w * daily_climate_category_signal(daily_signal, category)
    if possible <= 0:
        return round(pressure * 0.25, 4)
    relation = active / possible
    relation = 0.74 * relation + 0.26 * pressure * min(1.0, possible / max(0.01, len(exposure)))
    return round(clamp(relation, 0.0, 1.0), 4)


def daily_climate_action(stance, relation, momentum):
    relation = safe_float(relation, 0.0)
    momentum = safe_float(momentum, 0.0)
    if relation < 0.12:
        return "Low signal / monitor"
    if stance == "beneficiary":
        if relation >= 0.34 and momentum >= 0:
            return "Daily buy candidate"
        return "Watch for entry"
    if stance == "hedge":
        return "Hedge candidate" if relation >= 0.26 else "Keep as hedge"
    if stance == "risk":
        if relation >= 0.38:
            return "Reduce / hedge"
        return "Risk watch"
    if relation >= 0.38 and momentum >= 0:
        return "Selective overweight"
    if relation >= 0.28:
        return "Hold with hedge"
    return "Monitor"


def category_reminder(category):
    reminders = {
        "heat": "Power demand, utilities, data centers, solar, and grid stress.",
        "flood": "Insurers, banks, real estate credit, industrial recovery, and transport.",
        "fire": "Utilities, insurers, timber, air quality, and distributed power.",
        "tropical": "Gulf energy, utilities, property insurance, logistics, and rebuilding.",
        "storm": "Insurance claims, utilities, construction, industrials, and power outages.",
        "winter": "Natural gas, utilities, power demand, and transport delays.",
        "air_quality": "Health, clean energy, EV, utilities, and regional activity.",
    }
    return reminders.get(category, "Monitor climate-sensitive sectors.")


def top_sample_area(daily_signal, category):
    samples = daily_signal.get("sample_events", []) or []
    for sample in samples:
        if sample.get("category") == category:
            return sample.get("area") or sample.get("event") or "-"
    return "-"


def daily_climate_alert_rows(daily_signal):
    counts = daily_signal.get("category_counts", {}) or {}
    rows = []
    for category in DAILY_ALERT_CATEGORY_WEIGHTS:
        count = int(safe_float(counts.get(category), 0))
        intensity = daily_climate_category_signal(daily_signal, category)
        if count <= 0 and intensity <= 0.01:
            continue
        rows.append(
            {
                "driver": category,
                "driver_label": CLIMATE_CATEGORY_LABELS.get(category, category.title()),
                "count": count,
                "intensity": round(intensity, 4),
                "reminder": category_reminder(category),
                "sample_area": top_sample_area(daily_signal, category),
            }
        )
    if not rows:
        rows.append(
            {
                "driver": "long_run",
                "driver_label": "Long-run climate pressure",
                "count": 0,
                "intensity": round(safe_float(daily_signal.get("allocation_pressure"), 0.0), 4),
                "reminder": "Use official temperature, CO2, and disaster-frequency inputs as the base climate risk signal.",
                "sample_area": "-",
            }
        )
    return sorted(rows, key=lambda r: (r["intensity"], r["count"]), reverse=True)


def daily_market_lookup(symbols):
    market = market_chart_payload(symbols, period="1d", interval="1m")
    charts = market.get("charts", {})
    return market, {symbol: market_stats(charts.get(symbol, [])) for symbol in symbols}


def daily_climate_stock_recommendations(daily_signal):
    ranked = []
    for item in DAILY_CLIMATE_STOCKS:
        relation = climate_relation_score(item.get("exposure", {}), daily_signal)
        ranked.append((relation, item))
    ranked = sorted(ranked, key=lambda x: x[0], reverse=True)[:10]
    symbols = [item["ticker"] for _, item in ranked]
    market, stats_lookup = daily_market_lookup(symbols)
    rows = []
    for relation, item in ranked:
        stats = stats_lookup.get(item["ticker"], {})
        momentum = safe_float(stats.get("period_return"), 0.0)
        rows.append(
            {
                "ticker": item["ticker"],
                "name": item["name"],
                "theme": item["theme"],
                "stance": item["stance"],
                "relation_score": relation,
                "last": round(safe_float(stats.get("last"), 0.0), 4),
                "today_return": round(momentum, 5),
                "volatility": round(safe_float(stats.get("volatility"), 0.0), 5),
                "action": daily_climate_action(item["stance"], relation, momentum),
                "climate_link": item["note"],
            }
        )
    return rows, market


def daily_climate_etf_recommendations(daily_signal):
    ranked = []
    for item in DAILY_CLIMATE_ETFS:
        relation = climate_relation_score(item.get("exposure", {}), daily_signal)
        ranked.append((relation, item))
    ranked = sorted(ranked, key=lambda x: x[0], reverse=True)[:10]
    symbols = [item["ticker"] for _, item in ranked]
    market, stats_lookup = daily_market_lookup(symbols)
    rows = []
    for relation, item in ranked:
        stats = stats_lookup.get(item["ticker"], {})
        group, climate_risk, note = etf_climate_profile(item["ticker"])
        momentum = safe_float(stats.get("period_return"), 0.0)
        rows.append(
            {
                "ticker": item["ticker"],
                "group": group,
                "role": item["role"],
                "stance": item["stance"],
                "relation_score": relation,
                "climate_risk": round(climate_risk, 4),
                "last": round(safe_float(stats.get("last"), 0.0), 4),
                "today_return": round(momentum, 5),
                "action": daily_climate_action(item["stance"], relation, momentum),
                "climate_link": note,
            }
        )
    return rows, market


def daily_climate_board_payload():
    daily_signal = load_daily_climate_signal()
    alert_rows = daily_climate_alert_rows(daily_signal)
    stock_rows, stock_market = daily_climate_stock_recommendations(daily_signal)
    etf_rows, etf_market = daily_climate_etf_recommendations(daily_signal)
    active_themes = [r["driver_label"] for r in alert_rows[:4]]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_mode": daily_signal.get("source_mode", "-"),
        "source_url": daily_signal.get("source_url", NWS_ACTIVE_ALERTS_URL),
        "alerts_total": daily_signal.get("alerts_total", 0),
        "climate_alerts": daily_signal.get("climate_alerts", 0),
        "top_driver": daily_signal.get("top_driver", "none"),
        "daily_pressure": daily_signal.get("daily_pressure", 0.0),
        "allocation_pressure": daily_signal.get("allocation_pressure", 0.0),
        "active_themes": active_themes,
        "market_source": stock_market.get("source") or etf_market.get("source"),
        "market_interval": stock_market.get("interval") or etf_market.get("interval"),
        "stock_recommendations": stock_rows,
        "etf_recommendations": etf_rows,
        "daily_alerts": alert_rows,
    }


def simulated_annual_returns(tickers):
    rng = random.Random(42)
    annual = {t: {} for t in tickers}
    for year in range(START_YEAR + 1, datetime.now().year + 1):
        market = rng.gauss(0.08, 0.13)
        for t in tickers:
            beta = {"XLE": 1.15, "XLU": 0.65, "XLI": 1.05, "XLK": 1.18, "XLF": 1.10}.get(t, 1)
            tilt = {"XLE": -0.005, "XLU": 0.012, "XLI": 0.003, "XLK": 0.025, "XLF": 0.006}.get(t, 0)
            annual[t][str(year)] = round(market * beta + tilt + rng.gauss(0, 0.06), 5)
    return annual


def run_backtest():
    tickers = list(SECTOR_ETFS.keys())
    climate_rows = climate_signal()
    returns, source = fetch_etf_prices(tickers)
    years = sorted({int(y) for t in returns.values() for y in t.keys() if int(y) >= START_YEAR})
    equal_value = 1.0
    climate_value = 1.0
    rows = []
    allocation_rows = []
    for year in years:
        regime = regime_for_year(year, climate_rows)
        eq_w = {t: 1 / len(tickers) for t in tickers}
        cw = climate_weight_policy(regime["regime"])
        eq_ret = sum(eq_w[t] * returns.get(t, {}).get(str(year), 0) for t in tickers)
        cl_ret = sum(cw[t] * returns.get(t, {}).get(str(year), 0) for t in tickers)
        equal_value *= 1 + eq_ret
        climate_value *= 1 + cl_ret
        rows.append(
            {
                "year": year,
                "signal_year": regime["signal_year"],
                "regime": regime["regime"],
                "climate_score": regime["score"],
                "equal_weight_return": round(eq_ret, 5),
                "climate_aware_return": round(cl_ret, 5),
                "return_difference": round(cl_ret - eq_ret, 5),
                "equal_weight_wealth": round(equal_value, 4),
                "climate_aware_wealth": round(climate_value, 4),
            }
        )
        for ticker in tickers:
            allocation_rows.append(
                {
                    "year": year,
                    "ticker": ticker,
                    "sector": SECTOR_ETFS[ticker]["name"],
                    "benchmark_weight": round(eq_w[ticker], 4),
                    "climate_weight": round(cw[ticker], 4),
                    "action": allocation_action(cw[ticker], eq_w[ticker]),
                    "target_dollars": round(cw[ticker] * DEFAULT_PORTFOLIO_VALUE, 2),
                    "sector_note": SECTOR_ETFS[ticker]["client_note"],
                }
            )
    return rows, allocation_rows, source


def allocation_action(weight, benchmark):
    diff = weight - benchmark
    if diff > 0.03:
        return "Overweight / Buy"
    if diff < -0.03:
        return "Underweight / Reduce"
    return "Hold near benchmark"


def max_drawdown(values):
    peak = -1e9
    worst = 0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1)
    return worst


def risk_summary(backtest_rows):
    climate_ret = [r["climate_aware_return"] for r in backtest_rows]
    bench_ret = [r["equal_weight_return"] for r in backtest_rows]
    climate_wealth = [r["climate_aware_wealth"] for r in backtest_rows]
    bench_wealth = [r["equal_weight_wealth"] for r in backtest_rows]
    mean = sum(climate_ret) / max(1, len(climate_ret))
    vol = math.sqrt(sum((x - mean) ** 2 for x in climate_ret) / max(1, len(climate_ret) - 1))
    sharpe = mean / vol if vol > 1e-9 else 0
    return {
        "climate_total_return": round(climate_wealth[-1] - 1, 4) if climate_wealth else 0,
        "benchmark_total_return": round(bench_wealth[-1] - 1, 4) if bench_wealth else 0,
        "excess_return": round((climate_wealth[-1] - bench_wealth[-1]), 4) if climate_wealth and bench_wealth else 0,
        "climate_max_drawdown": round(max_drawdown(climate_wealth), 4),
        "benchmark_max_drawdown": round(max_drawdown(bench_wealth), 4),
        "annual_sharpe_proxy": round(sharpe, 3),
        "winning_years": sum(1 for r in backtest_rows if r["return_difference"] > 0),
        "years_tested": len(backtest_rows),
    }


def company_scan(tickers):
    climate_rows = climate_signal()
    latest_score = climate_rows[-1]["climate_risk_score"]
    context = climate_data_context()
    pressure = max(0.02, min(0.24, (0.06 + latest_score * 0.025) * context["climate_pressure_multiplier"]))
    out = []
    for raw in tickers:
        ticker = yahoo_symbol(raw)
        if not ticker:
            continue
        info = {}
        returns = []
        source = "fallback"
        if yf is not None:
            try:
                tk = yf.Ticker(ticker)
                info = tk.info or {}
                hist = tk.history(period="3y", auto_adjust=True)
                if hist is not None and not hist.empty:
                    returns = hist["Close"].pct_change().dropna().tolist()
                    source = "yfinance"
            except Exception:
                info = {}
        if not returns:
            rng = random.Random(sum(ord(c) for c in ticker))
            returns = [rng.gauss(0.0004, 0.018) for _ in range(650)]
        sorted_ret = sorted(returns)
        tail_n = max(1, int(len(sorted_ret) * 0.05))
        market_cvar = sum(sorted_ret[:tail_n]) / tail_n
        sector = info.get("sector") or guess_sector(ticker)
        sensitivity = COMPANY_SECTOR_SENSITIVITY.get(sector, 0.50)
        market_cap = safe_float(info.get("marketCap"), fallback_market_cap(ticker))
        beta = safe_float(info.get("beta"), 1.0)
        method2 = method2_company_cvor(ticker, info=info)
        physical_var = market_cap * pressure * sensitivity * 0.48
        transition_var = market_cap * pressure * sensitivity * 0.37 * max(0.70, min(1.40, beta))
        litigation_var = market_cap * pressure * max(0.10, 1 - sensitivity) * 0.15
        climate_var = (physical_var + transition_var + litigation_var) * max(0.65, min(1.45, beta))
        cvor_ratio = climate_var / market_cap if market_cap else 0
        out.append(
            {
                "ticker": ticker,
                "company": info.get("shortName") or info.get("longName") or ticker,
                "sector": sector,
                "market_cap": round(market_cap, 2),
                "beta": round(beta, 3),
                "market_cvar_95": round(market_cvar, 5),
                "climate_pressure": round(pressure, 4),
                "sector_sensitivity": round(sensitivity, 3),
                "physical_var": round(physical_var, 2),
                "transition_var": round(transition_var, 2),
                "litigation_var": round(litigation_var, 2),
                "climate_var": round(climate_var, 2),
                "climate_var_pct_mcap": round(cvor_ratio, 4),
                "source": source,
                "method2_mean_pct": method2["method2_mean_pct"],
                "method2_p95_pct": method2["method2_p95_pct"],
                "method2_p99_pct": method2["method2_p99_pct"],
                "method2_cvor95_pct": method2["method2_cvor95_pct"],
                "method2_cvor95_dollars": method2["method2_cvor95_dollars"],
                "method2_2c_p95_pct": method2["method2_2c_p95_pct"],
                "method2_2c_p99_pct": method2["method2_2c_p99_pct"],
                "method2_2c_cvor95_pct": method2["method2_2c_cvor95_pct"],
                "method2_2c_cvor95_dollars": method2["method2_2c_cvor95_dollars"],
                "method2_p95_reduction_pct": method2["method2_p95_reduction_pct"],
                "method2_cvor95_reduction_pct": method2["method2_cvor95_reduction_pct"],
                "method2_discount_rate": method2["method2_discount_rate"],
                "method2_draws": method2["method2_draws"],
                "method2_current_warming": method2["method2_current_warming"],
                "method2_climate_data_year": method2["method2_climate_data_year"],
                "method2_co2_ppm": method2["method2_co2_ppm"],
                "method2_disaster_10y_avg": method2["method2_disaster_10y_avg"],
                "method2_climate_pressure_multiplier": method2["method2_climate_pressure_multiplier"],
                "method2_climate_source_mode": method2["method2_climate_source_mode"],
                "method2_data_quality_score": method2["method2_data_quality_score"],
                "method2_data_quality_label": method2["method2_data_quality_label"],
                "method2_data_quality_notes": method2["method2_data_quality_notes"],
                "action": issuer_action(market_cvar, sensitivity, beta, max(cvor_ratio, method2["method2_p95_pct"])),
            }
        )
    return out


def guess_sector(ticker):
    mapping = {
        "AAPL": "Technology",
        "MSFT": "Technology",
        "NVDA": "Technology",
        "XOM": "Energy",
        "CVX": "Energy",
        "JPM": "Financial Services",
        "BAC": "Financial Services",
        "NEE": "Utilities",
        "DUK": "Utilities",
        "CAT": "Industrials",
    }
    return mapping.get(ticker, "Technology")


def fallback_market_cap(ticker):
    base = 80_000_000_000
    return base * (1 + (sum(ord(c) for c in ticker) % 25))


def issuer_action(cvar, sensitivity, beta, cvor_ratio=0.0):
    if cvor_ratio >= 0.10:
        return "Reduce / hedge climate concentration"
    if sensitivity >= 0.75 and beta >= 1.1:
        return "High climate VaR watchlist"
    if cvar < -0.035:
        return "Market-tail risk elevated"
    if sensitivity <= 0.40:
        return "Relatively adaptive exposure"
    return "Monitor with sector overlay"


def build_payload():
    climate_rows = climate_signal()
    official_climate = load_official_climate_data()
    context = climate_data_context()
    daily_signal = load_daily_climate_signal()
    backtest_rows, allocation_rows, market_source = run_backtest()
    latest_year = max(r["year"] for r in allocation_rows)
    latest_alloc = apply_daily_climate_overlay([r for r in allocation_rows if r["year"] == latest_year], daily_signal)
    current_allocation_rows = [r for r in allocation_rows if r["year"] != latest_year] + latest_alloc
    summary = risk_summary(backtest_rows)
    scenario_rows, cvor_summary = climate_scenario_matrix(current_allocation_rows)
    latest_regime = regime_for_year(latest_year, climate_rows)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "platform": "Jenneson Climate-Finance Trading & Risk Platform",
        "climate_source": "NASA GISTEMP-style anomaly proxy + NOAA billion-dollar disaster frequency proxy",
        "market_source": market_source,
        "methodology": "Simplified Climate Value at Risk inspired by Dietz et al. (2016)",
        "method2_methodology": {
            "paper": "Dietz, Bowen, Dixon and Gradwell (2016), 'Climate value at risk' of global financial assets",
            "equation": "Climate VaR = PV(no-damage cash-flow growth path) - PV(climate-damaged cash-flow growth path), divided by PV(no-damage path).",
            "implementation": "Company-level approximation using U.S. issuer sector sensitivity, beta, market cap, cash-flow growth proxy, DICE-style damage function, and Monte Carlo uncertainty.",
            "draws": METHOD2_DRAWS,
            "discount_rate": METHOD2_DISCOUNT_RATE,
            "horizon": METHOD2_END_YEAR,
            "damage_function": "g(T)=0.0028*T^2+(alpha3*T)^7, with alpha3 sampled from 0 to 0.248.",
            "scenario_comparison": "Each issuer is evaluated under a BAU warming path and a 2C mitigation path. The 2C column excludes mitigation costs and shows climate-impact risk reduction.",
            "climate_data_upgrade": "Current warming, CO2 trend, and U.S. billion-dollar disaster frequency now come from NASA/NOAA/NCEI official data when available.",
        },
        "portfolio_value": DEFAULT_PORTFOLIO_VALUE,
        "latest_regime": latest_regime,
        "climate_rows": climate_rows,
        "official_climate_rows": official_climate.get("rows", []),
        "official_climate_sources": official_climate.get("source_urls", {}),
        "official_climate_notes": official_climate.get("source_notes", []),
        "climate_data_context": context,
        "daily_climate_signal": daily_signal,
        "allocation_rows": current_allocation_rows,
        "latest_allocation": latest_alloc,
        "backtest_rows": backtest_rows,
        "risk_summary": summary,
        "scenario_rows": scenario_rows,
        "cvor_summary": cvor_summary,
        "us_market_notes": US_MARKET_NOTES,
        "sector_meta": SECTOR_ETFS,
    }


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Jenneson Climate-Finance Trading & Risk Platform</title>
  <style>
    :root {
      --bg:#f5f7fb; --panel:#ffffff; --panel2:#f9fbff; --line:#dbe3ef; --text:#172033;
      --muted:#66758f; --blue:#2463eb; --green:#078a4f; --red:#d93025; --amber:#b66a00;
      --shadow:0 8px 22px rgba(18,31,54,.08);
    }
    *{box-sizing:border-box}
    html{scroll-behavior:smooth}
    body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif;font-size:13px;line-height:1.35;-webkit-font-smoothing:antialiased}
    header{min-height:52px;display:flex;align-items:center;gap:14px;padding:8px 18px;border-bottom:1px solid var(--line);background:#fff;position:sticky;top:0;z-index:20;box-shadow:0 1px 12px rgba(18,31,54,.05)}
    .brand-dot{width:9px;height:24px;border-radius:8px;background:linear-gradient(180deg,#2563eb,#16a34a)}
    h1{font-size:16px;margin:0;font-weight:800}
    .badge{padding:4px 8px;border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--muted);font-size:12px}
    .layout{display:grid;grid-template-columns:280px minmax(0,1fr);gap:14px;padding:14px;max-width:1880px;margin:0 auto}
    aside{position:sticky;top:66px;height:calc(100vh - 80px);background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px;overflow:auto}
    main{display:flex;flex-direction:column;gap:12px;min-width:0}
    label{font-weight:700;font-size:12px;color:#2d3a50;display:block;margin-bottom:6px}
    textarea,input,button,select{font:inherit}
    textarea,input,select{width:100%;border:1px solid #cfd9e8;border-radius:7px;padding:9px;background:#fff;color:var(--text)}
    textarea:focus,input:focus,select:focus{outline:2px solid rgba(37,99,235,.18);border-color:#8bb2ff}
    textarea{min-height:92px;resize:vertical}
    button{border:1px solid #bcd0ff;background:#2563eb;color:#fff;border-radius:7px;padding:9px 12px;font-weight:800;cursor:pointer}
    button.secondary{background:#fff;color:#2563eb}
    .hint{color:var(--muted);font-size:12px;line-height:1.45}
    .grid{display:grid;gap:8px}
    .grid.kpi{grid-template-columns:repeat(6,minmax(0,1fr))}
    .grid.two{grid-template-columns:1.35fr .85fr}
    .grid.three{grid-template-columns:repeat(3,minmax(0,1fr))}
    .grid.four{grid-template-columns:repeat(4,minmax(0,1fr))}
    .panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;box-shadow:0 1px 0 rgba(20,35,60,.03);overflow:hidden;scroll-margin-top:72px}
    .panel-head{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-bottom:1px solid #e9eef6;background:#fbfdff;font-weight:800}
    .panel-body{padding:12px;overflow:auto}
    .kpi-card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px;min-height:82px;overflow:hidden}
    .kpi-label{color:var(--muted);font-size:12px}
    .kpi-value{font-size:23px;font-weight:850;margin-top:5px;white-space:nowrap}
    .green{color:var(--green)} .red{color:var(--red)} .amber{color:var(--amber)} .blue{color:var(--blue)}
    table{width:100%;border-collapse:collapse;min-width:860px}
    #quoteTable{min-width:100%;table-layout:auto}
    #quoteTable th,#quoteTable td{padding:9px 7px;font-size:12px;white-space:nowrap}
    #riskTable{min-width:520px}
    #method2Table{min-width:720px}
    #allocationTable,#optimizerTable,#dailyStockTable,#dailyEtfRecoTable,#dailyAlertTable,#universeTable,#scenarioTable,#climateDataTable,#etfTable,#companyTable,#detailTable,#dailyImpactTable{min-width:860px}
    th,td{padding:8px;border-bottom:1px solid #edf1f7;text-align:left;vertical-align:top}
    th{font-size:12px;color:#52627c;background:#fbfcff}
    tr:hover{background:#f7fbff}
    .compact-table{min-width:620px}
    canvas{width:100%;height:260px;border:1px solid #e1e8f2;border-radius:6px;background:#fff}
    canvas.tall{height:390px}
    .log{font-family:Consolas,monospace;background:#0f172a;color:#dbeafe;border-radius:7px;padding:10px;height:150px;overflow:auto;font-size:12px}
    .pill{display:inline-flex;align-items:center;gap:4px;border:1px solid #d7e1ef;border-radius:999px;padding:3px 7px;background:#fff;font-size:11px;margin:2px}
    .pill.high{background:#fff1f1;color:#b42318;border-color:#ffc9c2}
    .pill.ok{background:#edfdf5;color:#047857;border-color:#bbf7d0}
    .pill.info{background:#eff6ff;color:#1d4ed8;border-color:#bfdbfe}
    .section-title{font-size:13px;font-weight:850;margin:4px 0 8px}
    .toolbar{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
    .toolbar button{padding:7px 10px}
    .toolbar button.active{background:#0f172a;border-color:#0f172a}
    .toolbar .chart-tool{padding:6px 9px;font-size:12px}
    .chart-shell{position:relative;border:1px solid #dce5f1;border-radius:8px;background:#fff;overflow:hidden}
    .chart-shell.dark{background:#101827;border-color:#243247}
    .trading-chart{height:430px;min-height:360px}
    .indicator-chart{height:150px;border-top:1px solid #e6edf7}
    .chart-shell.dark .indicator-chart{border-top-color:#243247}
    .chart-readout{position:absolute;z-index:3;left:10px;top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:6px 8px;border:1px solid rgba(148,163,184,.28);border-radius:7px;background:rgba(255,255,255,.88);backdrop-filter:blur(8px);font-size:12px;font-weight:750;color:#243147}
    .chart-shell.dark .chart-readout{background:rgba(15,23,42,.86);color:#dbeafe;border-color:#334155}
    .chart-readout span{white-space:nowrap}
    canvas.chart-fallback{display:none;height:560px;border:0;border-radius:0}
    .control-row{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}
    .small-input{margin-bottom:8px}
    .mini-stat{display:inline-flex;align-items:center;gap:6px;margin-right:10px;color:var(--muted)}
    .signal-card{border:1px solid #dbe3ef;border-radius:8px;background:#fff;padding:10px;min-height:70px}
    .signal-card .label{color:var(--muted);font-size:11px;font-weight:750}
    .signal-card .value{font-size:20px;font-weight:850;margin-top:4px}
    .data-note{display:flex;gap:8px;align-items:center;flex-wrap:wrap;color:var(--muted);font-size:12px}
    .side-nav{display:grid;gap:6px;margin-bottom:12px}
    .side-nav a{display:flex;align-items:center;justify-content:space-between;text-decoration:none;color:#25324a;border:1px solid #dbe3ef;border-radius:7px;padding:8px 9px;background:#fbfdff;font-weight:750}
    .side-nav a:hover{border-color:#9bbcff;background:#f3f7ff}
    .heat-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:6px}
    .heat-cell{border:1px solid #dbe3ef;border-radius:7px;padding:8px;background:#fff;min-height:58px}
    .heat-cell .top{display:flex;align-items:center;justify-content:space-between;font-weight:850}
    .heat-cell .sub{font-size:11px;color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .heat-cell.pos{background:#eefdf6;border-color:#b9f2d3}
    .heat-cell.neg{background:#fff2f1;border-color:#ffc8c2}
    .risk-meter{height:8px;border-radius:999px;background:#edf2f7;overflow:hidden;margin-top:6px}
    .risk-meter span{display:block;height:100%;border-radius:999px;background:#2563eb}
    .risk-meter span.warn{background:#b66a00}
    .risk-meter span.danger{background:#d93025}
    @media (max-width:1100px){header{position:relative}.layout{grid-template-columns:1fr}.grid.kpi,.grid.two,.grid.three,.grid.four{grid-template-columns:1fr}aside{position:relative;top:0;height:auto}.kpi-value{font-size:21px}table{min-width:760px}}
  </style>
</head>
<body>
<header>
  <div class="brand-dot"></div>
  <h1>Jenneson Climate-Finance Trading & Risk Platform</h1>
  <span class="badge" id="regimeBadge">Loading regime...</span>
  <span class="badge" id="sourceBadge">Data source: loading</span>
  <span style="margin-left:auto" class="badge" id="timeBadge">-</span>
</header>
<div class="layout">
  <aside>
    <nav class="side-nav" aria-label="Dashboard sections">
      <a href="#market-section">Market <span>OHLCV</span></a>
      <a href="#daily-climate-section">Daily Climate <span>Signal</span></a>
      <a href="#climate-section">Climate <span>Live</span></a>
      <a href="#allocation-section">Allocation <span>ETF</span></a>
      <a href="#optimizer-section">Optimizer <span>Portfolio</span></a>
      <a href="#issuer-section">Issuers <span>Method 2</span></a>
    </nav>
    <label>Current Data Feeds</label>
    <div class="hint">
      Prices use live/delayed U.S. stock and ETF data. Climate uses current NWS active alerts plus NASA/NOAA/NCEI inputs.
    </div>
    <hr style="border:0;border-top:1px solid var(--line);margin:14px 0">
    <label>Company Climate VaR Scanner</label>
    <textarea id="tickerInput">AAPL, MSFT, XOM, NEE, JPM</textarea>
    <button onclick="scanCompanies()">Scan Issuers</button>
    <button class="secondary" onclick="loadDashboard()" style="margin-top:8px;width:100%">Refresh Dashboard</button>
    <hr style="border:0;border-top:1px solid var(--line);margin:14px 0">
    <label>Rolling K-Line Watchlist</label>
    <textarea id="chartInput">SPY, QQQ, AAPL, XOM, ICLN</textarea>
    <button onclick="loadMarketChart()" style="width:100%">Load K-Line</button>
    <div class="hint" style="margin-top:8px">
      Works for U.S. stocks and ETFs. Today mode uses 1-minute intraday bars and refreshes the chart frequently.
    </div>
    <hr style="border:0;border-top:1px solid var(--line);margin:14px 0">
    <label>Portfolio Optimizer</label>
    <div class="control-row">
      <select id="optimizerMode">
        <option value="etf_stock">ETF + stock</option>
        <option value="etf_only">ETF only</option>
        <option value="stock_only">Stock only</option>
      </select>
      <select id="optimizerHorizon">
        <option value="long">Long-term</option>
        <option value="short">Short-term</option>
      </select>
    </div>
    <div class="control-row">
      <select id="optimizerStyle">
        <option value="balanced">Balanced</option>
        <option value="climate_defense">Climate defense</option>
        <option value="growth">Growth</option>
        <option value="low_vol">Low volatility</option>
      </select>
      <input id="optimizerCapital" value="50000000" inputmode="numeric">
    </div>
    <label>ETF Candidates</label>
    <textarea id="optimizerEtfs">SPY, QQQ, XLK, XLF, XLU, XLE, ICLN</textarea>
    <label>Stock Candidates</label>
    <textarea id="optimizerStocks">AAPL, MSFT, NVDA, JPM, XOM, NEE</textarea>
    <button onclick="runOptimizer()" style="width:100%">Run Optimizer</button>
    <div class="hint" style="margin-top:8px">
      Chooses weights, dollar allocation, and estimated shares based on market trend, volatility, liquidity, climate CVOR, and holding period.
    </div>
  </aside>
  <main>
    <section class="grid kpi" id="summary-section">
      <div class="kpi-card"><div class="kpi-label">Climate Regime</div><div id="kpiRegime" class="kpi-value">-</div></div>
      <div class="kpi-card"><div class="kpi-label">Daily Climate Alerts</div><div id="kpiScore" class="kpi-value">-</div></div>
      <div class="kpi-card"><div class="kpi-label">Daily Overlay</div><div id="kpiReturn" class="kpi-value">-</div></div>
      <div class="kpi-card"><div class="kpi-label">Top Climate Driver</div><div id="kpiExcess" class="kpi-value">-</div></div>
      <div class="kpi-card"><div class="kpi-label">Climate Data Year</div><div id="kpiDrawdown" class="kpi-value">-</div></div>
      <div class="kpi-card"><div class="kpi-label">Portfolio CVOR 95%</div><div id="kpiCvor" class="kpi-value">-</div></div>
    </section>

    <section class="grid two" id="market-section">
      <div class="panel">
        <div class="panel-head"><span>Rolling K-Line Chart</span><span id="marketSourceTag">Market data loading</span></div>
        <div class="panel-body">
          <div class="toolbar">
            <button class="secondary range-btn" onclick="setMarketWindow('1d','1m', this)">Today</button>
            <button class="secondary range-btn" onclick="setMarketWindow('5d','5m', this)">5D</button>
            <button class="secondary range-btn" onclick="setMarketWindow('1mo','1d', this)">1M</button>
            <button class="secondary range-btn" onclick="setMarketWindow('3mo','1d', this)">3M</button>
            <button class="active range-btn" onclick="setMarketWindow('6mo','1d', this)">6M</button>
            <button class="secondary range-btn" onclick="setMarketWindow('1y','1d', this)">1Y</button>
            <button class="secondary range-btn" onclick="setMarketWindow('2y','1d', this)">2Y</button>
            <button class="secondary" onclick="loadMarketChart()">Refresh</button>
            <span id="activeTickerTag" class="pill info">-</span>
            <button id="layerMa" class="chart-tool active" onclick="toggleChartLayer('ma', this)">MA20</button>
            <button id="layerEma" class="chart-tool active" onclick="toggleChartLayer('ema', this)">EMA50</button>
            <button id="layerVwap" class="chart-tool active" onclick="toggleChartLayer('vwap', this)">VWAP</button>
            <button id="layerBands" class="chart-tool secondary" onclick="toggleChartLayer('bands', this)">BB</button>
            <button id="layerVolume" class="chart-tool active" onclick="toggleChartLayer('volume', this)">Volume</button>
            <button id="layerMacd" class="chart-tool secondary" onclick="toggleChartLayer('macd', this)">MACD</button>
            <button id="chartThemeBtn" class="chart-tool secondary" onclick="toggleChartTheme()">Dark</button>
            <button class="chart-tool secondary" onclick="fitTradingChart()">Fit</button>
            <button class="chart-tool secondary" onclick="exportTradingChart()">Snapshot</button>
          </div>
          <div id="chartShell" class="chart-shell">
            <div id="chartReadout" class="chart-readout">Loading market chart</div>
            <div id="tradingChart" class="trading-chart"></div>
            <div id="indicatorChart" class="indicator-chart"></div>
            <canvas id="candleChart" class="tall chart-fallback"></canvas>
          </div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-head"><span>Current Quote Board</span><span>Stocks + ETFs</span></div>
        <div class="panel-body">
          <table id="quoteTable"></table>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head"><span>Current ETF Prices</span><span>Core, sectors, rates, climate, commodities</span></div>
      <div class="panel-body">
        <table id="etfTable"></table>
      </div>
    </section>

    <section class="panel" id="daily-climate-section">
      <div class="panel-head"><span>Daily Climate Intelligence</span><span id="dailyClimateTag">Loading daily signal</span></div>
      <div class="panel-body">
        <div id="dailyClimateSummary" class="grid four" style="margin-bottom:10px"></div>
        <div class="grid two">
          <div>
            <div class="section-title">Most Related Stocks</div>
            <table id="dailyStockTable"></table>
          </div>
          <div>
            <div class="section-title">ETF Recommendations</div>
            <table id="dailyEtfRecoTable"></table>
          </div>
        </div>
        <div class="section-title" style="margin-top:12px">Daily Climate Alerts</div>
        <table id="dailyAlertTable"></table>
      </div>
    </section>

    <section class="grid two" id="climate-section">
      <div class="panel">
        <div class="panel-head"><span>Current Climate Data</span><span>NWS + NASA/NOAA/NCEI</span></div>
        <div class="panel-body">
          <div id="dailyClimateCards" class="grid four"></div>
          <div class="data-note" style="margin:10px 0 4px">
            <span class="pill info">Daily alerts</span>
            <span class="pill info">Temperature</span>
            <span class="pill info">CO2</span>
            <span class="pill info">Disaster frequency</span>
          </div>
          <table id="climateDataTable"></table>
        </div>
      </div>
      <div class="panel">
        <div class="panel-head"><span>How Climate Data Moves Allocation</span><span>Daily +/- bps</span></div>
        <div class="panel-body">
          <table id="dailyImpactTable"></table>
        </div>
      </div>
    </section>

    <section class="panel" id="allocation-section">
      <div class="panel-head"><span>Portfolio Allocation Dashboard</span><span>Mock $50 million mandate</span></div>
      <div class="panel-body">
        <table id="allocationTable"></table>
      </div>
    </section>

    <section class="panel" id="optimizer-section">
      <div class="panel-head"><span>Portfolio Optimizer</span><span id="optimizerTag">ETF + stock / capital-aware</span></div>
      <div class="panel-body">
        <div id="optimizerSummary" class="grid four" style="margin-bottom:10px"></div>
        <table id="optimizerTable"></table>
      </div>
    </section>

    <section class="panel" id="cvor-section">
      <div class="panel-head"><span>CVOR Scenario Matrix</span><span>Physical + transition + liability risk</span></div>
      <div class="panel-body">
        <table id="scenarioTable"></table>
      </div>
    </section>

    <section class="panel" id="issuer-section">
      <div class="panel-head"><span>Company-Level Climate VaR Scanner</span><span>Issuer prototype</span></div>
      <div class="panel-body">
        <table id="companyTable"></table>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head"><span>Issuer CVOR Heat Strip</span><span>BAU P95 / 2C reduction</span></div>
      <div class="panel-body">
        <div id="issuerHeatStrip" class="heat-strip"></div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head"><span>Issuer Detail Breakdown</span><span>Physical / transition / liability and Method 2 tail risk</span></div>
      <div class="panel-body">
        <table id="detailTable"></table>
      </div>
    </section>

  </main>
</div>
<script src="https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"></script>
<script>
let DASH = null;
let MARKET = null;
let MARKET_PERIOD = "6mo";
let MARKET_INTERVAL = "1d";
let ACTIVE_TICKER = null;
let OPTIMIZER = null;
let DAILY_CLIMATE_BOARD = null;
let TRADING_CHART = null;
let CHART_LAYERS = {ma:true, ema:true, vwap:true, bands:false, volume:true, macd:false, dark:false};
let CANVAS_CHART = {key:null,start:0,end:0,cross:null,drag:false,dragX:0,dragStart:0,dragEnd:0};

function fmtPct(x){ return ((Number(x)||0)*100).toFixed(2)+"%"; }
function fmtMoney(x){ return "$"+Number(x||0).toLocaleString(undefined,{maximumFractionDigits:0}); }
function fmtPrice(x){ const n=Number(x); if(!Number.isFinite(n) || n<=0)return "-"; return "$"+n.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}); }
function fmtVolume(x){ const n=Number(x); if(!Number.isFinite(n) || n<=0)return "-"; if(n>=1e9)return (n/1e9).toFixed(2)+"B"; if(n>=1e6)return (n/1e6).toFixed(2)+"M"; if(n>=1e3)return (n/1e3).toFixed(1)+"K"; return String(Math.round(n)); }
function fmtBps(x){ const n=Number(x)||0; return (n>0?"+":"") + n.toFixed(0) + " bps"; }
function clsFor(v){ return Number(v)>=0 ? "green" : "red"; }
function clamp(x, lo, hi){ return Math.max(lo, Math.min(hi, Number(x))); }

async function loadDashboard(){
  const res = await fetch("/api/dashboard");
  DASH = await res.json();
  renderDashboard(DASH);
  await scanCompanies();
  await loadMarketChart();
  await loadEtfWatchlist();
  await loadDailyClimateBoard();
  await runOptimizer();
}

async function loadMarketChart(){
  const tickers = document.getElementById("chartInput").value;
  const res = await fetch("/api/market_chart?tickers="+encodeURIComponent(tickers)+"&period="+encodeURIComponent(MARKET_PERIOD)+"&interval="+encodeURIComponent(MARKET_INTERVAL));
  MARKET = await res.json();
  ACTIVE_TICKER = MARKET.symbols.includes(ACTIVE_TICKER) ? ACTIVE_TICKER : (MARKET.active_ticker || MARKET.symbols[0]);
  renderMarketQuotes();
  drawCandleChart();
}

async function loadEtfWatchlist(){
  const res = await fetch("/api/etf_watchlist");
  const data = await res.json();
  const table = document.getElementById("etfTable");
  table.innerHTML = `<tr><th>Group</th><th>ETF</th><th>Last</th><th>Change</th><th>Day Range</th><th>Volume</th></tr>` +
    data.rows.map(r=>`<tr>
      <td>${r.group}</td><td><b>${r.ticker}</b></td><td>${fmtPrice(r.last)}</td>
      <td class="${clsFor(r.change_pct)}">${fmtPct(r.change_pct)}</td>
      <td>${fmtPrice(r.low)} - ${fmtPrice(r.high)}</td><td>${fmtVolume(r.volume)}</td>
    </tr>`).join("");
}

async function loadDailyClimateBoard(){
  const res = await fetch("/api/daily_climate_board");
  DAILY_CLIMATE_BOARD = await res.json();
  renderDailyClimateBoard(DAILY_CLIMATE_BOARD);
}

function actionPill(action){
  const a = String(action || "");
  if(a.includes("buy") || a.includes("overweight") || a.includes("Add")) return "ok";
  if(a.includes("Reduce") || a.includes("Risk") || a.includes("hedge")) return "high";
  return "info";
}

function renderDailyClimateBoard(d){
  if(!d) return;
  const driver = String(d.top_driver || "none").replace("_"," ");
  document.getElementById("dailyClimateTag").textContent = `${d.source_mode} | ${d.market_interval || "1m"} market pulse`;
  document.getElementById("dailyClimateSummary").innerHTML = [
    ["Top driver", driver],
    ["Climate alerts", Number(d.climate_alerts || 0).toLocaleString()],
    ["Daily pressure", fmtPct(d.daily_pressure || 0)],
    ["Affected themes", (d.active_themes || []).slice(0,3).join(", ") || "Long-run pressure"]
  ].map(c=>`<div class="signal-card"><div class="label">${c[0]}</div><div class="value">${c[1]}</div></div>`).join("");

  const stockTable = document.getElementById("dailyStockTable");
  stockTable.innerHTML = `<tr><th>Ticker</th><th>Theme</th><th>Relation</th><th>Today</th><th>Action</th><th>Climate Link</th></tr>` +
    (d.stock_recommendations || []).map(r=>`<tr>
      <td><b>${r.ticker}</b><br><span class="hint">${r.name}</span></td>
      <td>${r.theme}<br><span class="hint">${r.stance}</span></td>
      <td><b>${fmtPct(r.relation_score)}</b></td>
      <td class="${clsFor(r.today_return)}">${fmtPct(r.today_return)}<br><span class="hint">${fmtPrice(r.last)}</span></td>
      <td><span class="pill ${actionPill(r.action)}">${r.action}</span></td>
      <td>${r.climate_link}</td>
    </tr>`).join("");

  const etfTable = document.getElementById("dailyEtfRecoTable");
  etfTable.innerHTML = `<tr><th>ETF</th><th>Role</th><th>Relation</th><th>Today</th><th>Action</th><th>Climate Link</th></tr>` +
    (d.etf_recommendations || []).map(r=>`<tr>
      <td><b>${r.ticker}</b><br><span class="hint">${r.group}</span></td>
      <td>${r.role}<br><span class="hint">${r.stance}</span></td>
      <td><b>${fmtPct(r.relation_score)}</b><br><span class="hint">Risk ${fmtPct(r.climate_risk)}</span></td>
      <td class="${clsFor(r.today_return)}">${fmtPct(r.today_return)}<br><span class="hint">${fmtPrice(r.last)}</span></td>
      <td><span class="pill ${actionPill(r.action)}">${r.action}</span></td>
      <td>${r.climate_link}</td>
    </tr>`).join("");

  const alertTable = document.getElementById("dailyAlertTable");
  alertTable.innerHTML = `<tr><th>Driver</th><th>Alert Count</th><th>Intensity</th><th>Reminder</th><th>Sample Area</th></tr>` +
    (d.daily_alerts || []).map(r=>`<tr>
      <td><b>${r.driver_label}</b></td>
      <td>${Number(r.count || 0).toLocaleString()}</td>
      <td>${fmtPct(r.intensity)}</td>
      <td>${r.reminder}</td>
      <td>${r.sample_area || "-"}</td>
    </tr>`).join("");
}

async function runOptimizer(){
  const params = new URLSearchParams({
    mode: document.getElementById("optimizerMode").value,
    horizon: document.getElementById("optimizerHorizon").value,
    style: document.getElementById("optimizerStyle").value,
    capital: document.getElementById("optimizerCapital").value,
    etfs: document.getElementById("optimizerEtfs").value,
    stocks: document.getElementById("optimizerStocks").value
  });
  const res = await fetch("/api/portfolio_optimizer?"+params.toString());
  OPTIMIZER = await res.json();
  renderOptimizer(OPTIMIZER);
}

function renderOptimizer(o){
  if(!o) return;
  document.getElementById("optimizerTag").textContent = `${o.mode_label} | ${o.horizon_label} | ${fmtMoney(o.capital)}`;
  const summary = document.getElementById("optimizerSummary");
  summary.innerHTML = [
    ["Mode", o.mode_label],
    ["Style", o.style_label],
    ["Holding", o.horizon_label],
    ["Climate overlay", fmtPct(o.daily_climate_overlay || 0)]
  ].map(c=>`<div class="signal-card"><div class="label">${c[0]}</div><div class="value">${c[1]}</div></div>`).join("");
  const table = document.getElementById("optimizerTable");
  table.innerHTML = `<tr><th>Ticker</th><th>Type</th><th>Sector</th><th>Weight</th><th>Capital</th><th>Est. Shares</th><th>Last</th><th>Market</th><th>Climate</th><th>Action</th><th>Why</th></tr>` +
    (o.rows || []).map(r=>`<tr>
      <td><b>${r.ticker}</b></td>
      <td>${r.asset_type}</td>
      <td>${r.sector}</td>
      <td><b>${fmtPct(r.target_weight)}</b></td>
      <td>${fmtMoney(r.target_dollars)}</td>
      <td>${Number(r.estimated_shares || 0).toLocaleString(undefined,{maximumFractionDigits:2})}</td>
      <td>${fmtPrice(r.last)}</td>
      <td>${Number(r.market_score || 0).toFixed(2)}<br><span class="hint">${fmtPct(r.momentum)} move</span></td>
      <td>${Number(r.climate_score || 0).toFixed(2)}<br><span class="hint">CVOR proxy ${fmtPct(r.cvor_proxy)}</span></td>
      <td><span class="pill ${r.action.includes("Core") || r.action.includes("Add") ? "ok" : (r.action.includes("watch") ? "high" : "info")}">${r.action}</span></td>
      <td>${r.rationale}<br><span class="hint">${o.style_note} ${o.holding_note}</span></td>
    </tr>`).join("");
}

function setMarketWindow(period, interval, btn){
  MARKET_PERIOD = period;
  MARKET_INTERVAL = interval || "1d";
  document.querySelectorAll(".range-btn").forEach(b=>b.classList.remove("active"));
  if(btn) btn.classList.add("active");
  loadMarketChart();
}

function selectChartTicker(ticker){
  ACTIVE_TICKER = ticker;
  renderMarketQuotes();
  drawCandleChart();
}

function renderMarketQuotes(){
  if(!MARKET) return;
  const intraday = MARKET.interval !== "1d" ? " | refreshed about every 20s" : "";
  document.getElementById("marketSourceTag").textContent = MARKET.source + " | " + MARKET.period + " / " + MARKET.interval + intraday;
  document.getElementById("activeTickerTag").textContent = ACTIVE_TICKER || "-";
  renderMarketHeatStrip(MARKET.quotes || []);
  const table = document.getElementById("quoteTable");
  table.innerHTML = `<tr><th>Ticker</th><th>Last</th><th>Chg%</th><th>High</th><th>Low</th><th>Volume</th></tr>` +
    MARKET.quotes.map(q=>`<tr onclick="selectChartTicker('${q.ticker}')" style="cursor:pointer">
      <td><b>${q.ticker}</b> ${q.ticker===ACTIVE_TICKER?'<span class="pill info">chart</span>':''}</td>
      <td>${fmtPrice(q.last)}</td>
      <td class="${clsFor(q.change_pct)}"><b>${fmtPct(q.change_pct)}</b></td>
      <td>${fmtPrice(q.high)}</td><td>${fmtPrice(q.low)}</td><td>${fmtVolume(q.volume)}</td>
    </tr>`).join("");
}

function renderMarketHeatStrip(quotes){
  const strip = document.getElementById("marketHeatStrip");
  if(!strip) return;
  strip.innerHTML = quotes.map(q=>{
    const cls = Number(q.change_pct) >= 0 ? "pos" : "neg";
    return `<div class="heat-cell ${cls}" onclick="selectChartTicker('${q.ticker}')" style="cursor:pointer">
      <div class="top"><span>${q.ticker}</span><span class="${cls==='pos'?'green':'red'}">${fmtPct(q.change_pct)}</span></div>
      <div class="sub">${fmtPrice(q.last)} | Vol ${fmtVolume(q.volume)} | ${q.bars} bars</div>
    </div>`;
  }).join("");
}

function renderDashboard(d){
  document.getElementById("timeBadge").textContent = "Updated " + d.generated_at;
  document.getElementById("sourceBadge").textContent = "Market: " + d.market_source;
  document.getElementById("regimeBadge").textContent = d.latest_regime.regime + " | signal " + d.latest_regime.signal_year;
  document.getElementById("kpiRegime").textContent = d.latest_regime.regime.replace(" Climate Risk","");
  document.getElementById("kpiRegime").className = "kpi-value " + (d.latest_regime.regime.includes("High") ? "red" : "green");
  const daily = d.daily_climate_signal || {};
  document.getElementById("kpiScore").textContent = Number(daily.climate_alerts || 0).toLocaleString();
  document.getElementById("kpiScore").className = "kpi-value amber";
  document.getElementById("kpiReturn").textContent = fmtPct(daily.allocation_pressure || 0);
  document.getElementById("kpiReturn").className = "kpi-value blue";
  document.getElementById("kpiExcess").textContent = String(daily.top_driver || "none").replace("_"," ");
  document.getElementById("kpiExcess").className = "kpi-value amber";
  document.getElementById("kpiDrawdown").textContent = d.climate_data_context.latest_year || "-";
  document.getElementById("kpiDrawdown").className = "kpi-value blue";
  document.getElementById("kpiCvor").textContent = fmtPct(d.cvor_summary.cvor_95_loss_rate);
  document.getElementById("kpiCvor").className = "kpi-value amber";
  renderAllocation(d.latest_allocation);
  renderScenarios(d.scenario_rows);
  renderClimateData(d);
  renderDailyClimateSignal(d);
}

function renderClimateData(d){
  const c = d.climate_data_context;
  const sources = d.official_climate_sources || {};
  const notes = (d.official_climate_notes || []).join("; ");
  const latestRows = (d.official_climate_rows || []).slice(-5).reverse();
  const table = document.getElementById("climateDataTable");
  const summary = [
    ["Climate data year", c.latest_year],
    ["Current warming input", `${Number(c.current_warming).toFixed(3)} C`],
    ["CO2 input", `${Number(c.co2_ppm).toFixed(2)} ppm`],
    ["10Y CO2 change", `${Number(c.co2_10y_change).toFixed(2)} ppm`],
    ["10Y disaster frequency", `${Number(c.disaster_10y_avg).toFixed(2)} / year`],
    ["Pressure multiplier", Number(c.climate_pressure_multiplier).toFixed(3)],
    ["Source mode", c.source_mode],
    ["Source notes", notes],
  ];
  table.innerHTML = `<tr><th>Input</th><th>Value</th><th>Recent Official Data</th></tr>` +
    summary.map((r,idx)=>`<tr>
      <td><b>${r[0]}</b></td><td>${r[1]}</td>
      <td>${idx===0 ? latestRows.map(x=>`${x.year}: temp ${Number(x.temperature_anomaly).toFixed(2)}C (${x.temperature_source}), CO2 ${Number(x.co2_ppm).toFixed(1)}ppm (${x.co2_source}), disasters ${x.billion_dollar_disasters ?? "-"} (${x.disaster_source})`).join("<br>") : ""}</td>
    </tr>`).join("") +
    `<tr><td><b>Official URLs</b></td><td colspan="2">
      <span class="pill info">NASA GISTEMP</span> ${sources.nasa_gistemp || ""}<br>
      <span class="pill info">NOAA CO2</span> ${sources.noaa_co2 || ""}<br>
      <span class="pill info">NCEI Disasters</span> ${sources.ncei_disasters || ""}
    </td></tr>`;
}

function renderDailyClimateSignal(d){
  const s = d.daily_climate_signal || {};
  const cards = document.getElementById("dailyClimateCards");
  const top = s.top_driver || "none";
  const source = s.source_mode || "-";
  cards.innerHTML = [
    ["Climate alerts", Number(s.climate_alerts || 0).toLocaleString()],
    ["Daily pressure", fmtPct(s.daily_pressure || 0)],
    ["Allocation overlay", fmtPct(s.allocation_pressure || 0)],
    ["Top driver", top.replace("_"," ")]
  ].map(c=>`<div class="signal-card"><div class="label">${c[0]}</div><div class="value">${c[1]}</div></div>`).join("");
  const rows = d.latest_allocation || [];
  const table = document.getElementById("dailyImpactTable");
  table.innerHTML = `<tr><th>ETF</th><th>Long-Term Weight</th><th>Daily Overlay</th><th>Final Weight</th><th>Daily Stress</th><th>Driver</th><th>Source</th></tr>` +
    rows.map(r=>{
      const bps = Number(r.daily_adjustment_bps || 0);
      return `<tr>
        <td><b>${r.ticker}</b></td>
        <td>${fmtPct(r.base_climate_weight ?? r.climate_weight)}</td>
        <td class="${bps>=0?'green':'red'}"><b>${fmtBps(bps)}</b></td>
        <td><b>${fmtPct(r.climate_weight)}</b></td>
        <td>${Number(r.daily_sector_stress || 0).toFixed(3)}</td>
        <td>${r.daily_driver || r.sector_note}</td>
        <td>${source}</td>
      </tr>`;
    }).join("");
}

function renderAllocation(rows){
  const table = document.getElementById("allocationTable");
  table.innerHTML = `<tr><th>ETF</th><th>Sector</th><th>Benchmark</th><th>Long-Term Climate</th><th>Daily +/-</th><th>Final Target</th><th>Target Dollars</th><th>Action</th><th>Climate Logic</th></tr>` +
    rows.map(r => `<tr>
      <td><b>${r.ticker}</b></td><td>${r.sector}</td><td>${fmtPct(r.benchmark_weight)}</td>
      <td>${fmtPct(r.base_climate_weight ?? r.climate_weight)} <span class="hint">(${fmtBps(r.long_term_adjustment_bps || 0)})</span></td>
      <td class="${Number(r.daily_adjustment_bps || 0)>=0?'green':'red'}"><b>${fmtBps(r.daily_adjustment_bps || 0)}</b></td>
      <td><b>${fmtPct(r.climate_weight)}</b></td><td>${fmtMoney(r.target_dollars)}</td>
      <td><span class="pill ${r.action.includes("Over")?"ok":(r.action.includes("Under")?"high":"info")}">${r.action}</span></td>
      <td>${r.daily_driver || r.sector_note}<br><span class="hint">${r.sector_note}</span></td>
    </tr>`).join("");
}

function renderMethod2(m){
  const table = document.getElementById("method2Table");
  const rows = [
    ["Paper", m.paper],
    ["Core equation", m.equation],
    ["Company-level implementation", m.implementation],
    ["Damage function", m.damage_function],
    ["Monte Carlo draws per issuer", m.draws],
    ["Base private discount rate", fmtPct(m.discount_rate)],
    ["Horizon", `Current year to ${m.horizon}`],
    ["Scenario comparison", m.scenario_comparison],
    ["Climate data upgrade", m.climate_data_upgrade],
  ];
  table.innerHTML = `<tr><th>Method 2 Component</th><th>Platform Implementation</th></tr>` +
    rows.map(r=>`<tr><td><b>${r[0]}</b></td><td>${r[1]}</td></tr>`).join("");
}

function renderScenarios(rows){
  const table = document.getElementById("scenarioTable");
  table.innerHTML = `<tr><th>Scenario</th><th>Probability</th><th>Carbon Price</th><th>Portfolio Loss</th><th>Loss Dollars</th><th>Largest Sector Loss</th><th>Narrative</th></tr>` +
    rows.map(r=>{
      const losses = Object.entries(r.sector_losses || {}).sort((a,b)=>b[1]-a[1]);
      const top = losses.length ? `${losses[0][0]} ${fmtPct(losses[0][1])}` : "-";
      return `<tr>
        <td><b>${r.scenario}</b></td><td>${fmtPct(r.probability)}</td><td>$${r.carbon_price}/tCO2e</td>
        <td class="red">${fmtPct(r.portfolio_loss_rate)}</td><td>${fmtMoney(r.portfolio_loss_dollars)}</td>
        <td>${top}</td><td>${r.narrative}</td>
      </tr>`;
    }).join("");
}

async function searchUniverse(){
  const query = document.getElementById("universeInput").value;
  const res = await fetch("/api/universe_search?query="+encodeURIComponent(query)+"&limit=80");
  const rows = await res.json();
  const table = document.getElementById("universeTable");
  table.innerHTML = `<tr><th>Ticker</th><th>Name</th><th>Exchange</th><th>Type</th><th>Action</th></tr>` +
    rows.map(r=>`<tr>
      <td><b>${r.symbol}</b></td><td>${r.name}</td><td>${r.exchange}</td><td>${r.security_type}</td>
      <td><button class="secondary" onclick="addTicker('${r.symbol}')">Add</button></td>
    </tr>`).join("");
}

function addTicker(symbol){
  const input = document.getElementById("tickerInput");
  const existing = input.value.split(",").map(x=>x.trim().toUpperCase()).filter(Boolean);
  if(!existing.includes(symbol)) existing.unshift(symbol);
  input.value = existing.join(", ");
}

function renderRisk(s){
  const table = document.getElementById("riskTable");
  const rows = [
    ["Climate-aware total return", fmtPct(s.climate_total_return), clsFor(s.climate_total_return)],
    ["Benchmark total return", fmtPct(s.benchmark_total_return), clsFor(s.benchmark_total_return)],
    ["Excess wealth multiple", Number(s.excess_return).toFixed(3)+"x", clsFor(s.excess_return)],
    ["Climate-aware max drawdown", fmtPct(s.climate_max_drawdown), "red"],
    ["Benchmark max drawdown", fmtPct(s.benchmark_max_drawdown), "red"],
    ["Sharpe proxy", s.annual_sharpe_proxy, s.annual_sharpe_proxy>=0 ? "green" : "red"],
    ["Winning years", `${s.winning_years} / ${s.years_tested}`, "blue"],
  ];
  table.innerHTML = `<tr><th>Metric</th><th>Value</th></tr>` + rows.map(r=>`<tr><td>${r[0]}</td><td class="${r[2]}"><b>${r[1]}</b></td></tr>`).join("");
}

function renderLog(d){
  const latest = d.latest_allocation;
  const lines = [
    `[${d.generated_at}] Platform loaded for Jenneson climate-finance prototype.`,
    `Methodology: ${d.methodology}.`,
    `Regime: ${d.latest_regime.regime}; signal year ${d.latest_regime.signal_year}; score ${Number(d.latest_regime.score).toFixed(2)}.`,
    `Market data: ${d.market_source}.`,
    `Allocation engine produced ${latest.length} ETF actions for a ${fmtMoney(d.portfolio_value)} mock portfolio.`,
    `Portfolio CVOR 95: ${fmtPct(d.cvor_summary.cvor_95_loss_rate)} or ${fmtMoney(d.cvor_summary.cvor_95_loss_dollars)} under adverse climate scenarios.`,
    `U.S. system: ${d.us_market_notes[0]}`,
    `Client framing: simplified Climate VaR prototype, not a full issuer-level scenario model.`
  ];
  document.getElementById("modelLog").textContent = lines.join("\n");
}

async function scanCompanies(){
  const tickers = document.getElementById("tickerInput").value;
  const res = await fetch("/api/company_scan?tickers="+encodeURIComponent(tickers));
  const rows = await res.json();
  const table = document.getElementById("companyTable");
  table.innerHTML = `<tr><th>Ticker</th><th>Company</th><th>Sector</th><th>Beta</th><th>Market CVaR 95%</th><th>BAU P95</th><th>BAU P99</th><th>2C P95</th><th>P95 Reduction</th><th>BAU CVOR95 $</th><th>Data Quality</th><th>Action</th><th>Source</th></tr>` +
    rows.map(r=>`<tr>
      <td><b>${r.ticker}</b></td><td>${r.company}</td><td>${r.sector}</td><td>${r.beta}</td>
      <td class="red">${fmtPct(r.market_cvar_95)}</td>
      <td class="amber">${fmtPct(r.method2_p95_pct)}</td>
      <td class="red">${fmtPct(r.method2_p99_pct)}</td>
      <td class="blue">${fmtPct(r.method2_2c_p95_pct)}</td>
      <td class="green">${fmtPct(r.method2_p95_reduction_pct)}</td>
      <td>${fmtMoney(r.method2_cvor95_dollars)}</td>
      <td><span class="pill ${r.method2_data_quality_score>=80?"ok":(r.method2_data_quality_score>=55?"info":"high")}">${r.method2_data_quality_label} ${r.method2_data_quality_score}</span><br><span class="hint">${r.method2_data_quality_notes}</span></td>
      <td>${r.action}</td><td>${r.source}</td>
    </tr>`).join("");
  renderIssuerHeatStrip(rows);
  renderIssuerDetails(rows);
}

function renderIssuerHeatStrip(rows){
  const strip = document.getElementById("issuerHeatStrip");
  if(!strip) return;
  strip.innerHTML = rows.map(r=>{
    const p95 = Number(r.method2_p95_pct)||0;
    const reduction = Number(r.method2_p95_reduction_pct)||0;
    const level = p95 >= 0.08 ? "danger" : (p95 >= 0.045 ? "warn" : "");
    const fill = Math.max(4, Math.min(100, p95*1000));
    const cls = p95 >= 0.06 ? "neg" : "pos";
    return `<div class="heat-cell ${cls}">
      <div class="top"><span>${r.ticker}</span><span class="${p95>=0.06?'red':'green'}">${fmtPct(p95)}</span></div>
      <div class="sub">${r.sector} | 2C reduces ${fmtPct(reduction)}</div>
      <div class="risk-meter"><span class="${level}" style="width:${fill}%"></span></div>
    </div>`;
  }).join("");
}

function renderIssuerDetails(rows){
  const table = document.getElementById("detailTable");
  table.innerHTML = `<tr><th>Ticker</th><th>Physical VaR</th><th>Transition VaR</th><th>Liability VaR</th><th>Simple Total CVOR</th><th>BAU CVOR95</th><th>2C CVOR95</th><th>Tail Reduction</th><th>Discount</th><th>Draws</th></tr>` +
    rows.map(r=>`<tr>
      <td><b>${r.ticker}</b></td>
      <td>${fmtMoney(r.physical_var)}</td><td>${fmtMoney(r.transition_var)}</td><td>${fmtMoney(r.litigation_var)}</td>
      <td>${fmtMoney(r.climate_var)} <span class="hint">(${fmtPct(r.climate_var_pct_mcap)} mcap)</span></td>
      <td class="red">${fmtPct(r.method2_cvor95_pct)} / ${fmtMoney(r.method2_cvor95_dollars)}</td>
      <td class="blue">${fmtPct(r.method2_2c_cvor95_pct)} / ${fmtMoney(r.method2_2c_cvor95_dollars)}</td>
      <td class="green">${fmtPct(r.method2_cvor95_reduction_pct)}</td>
      <td>${fmtPct(r.method2_discount_rate)}</td><td>${r.method2_draws}<br><span class="hint">${r.method2_climate_data_year}, ${Number(r.method2_current_warming).toFixed(2)}C, ${Number(r.method2_co2_ppm).toFixed(1)}ppm</span></td>
    </tr>`).join("");
}

function chartTime(row){
  const raw = String(row.date || "");
  if(raw.includes(" ")){
    const dt = new Date(raw.replace(" ", "T"));
    if(Number.isFinite(dt.getTime())) return Math.floor(dt.getTime()/1000);
  }
  return raw.slice(0,10);
}

function timeLabel(t){
  if(typeof t === "number"){
    const d = new Date(t*1000);
    return d.toLocaleString(undefined,{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"});
  }
  return String(t || "-");
}

function chartRows(){
  if(!MARKET || !ACTIVE_TICKER) return [];
  return (MARKET.charts[ACTIVE_TICKER] || []).filter(r =>
    Number.isFinite(Number(r.open)) && Number.isFinite(Number(r.high)) &&
    Number.isFinite(Number(r.low)) && Number.isFinite(Number(r.close))
  );
}

function toCandleData(rows){
  return rows.map(r=>({
    time: chartTime(r),
    open: Number(r.open),
    high: Number(r.high),
    low: Number(r.low),
    close: Number(r.close)
  }));
}

function toVolumeData(rows){
  return rows.map(r=>({
    time: chartTime(r),
    value: Number(r.volume || 0),
    color: Number(r.close) >= Number(r.open) ? "rgba(16,185,129,.42)" : "rgba(239,68,68,.38)"
  }));
}

function smaSeries(rows, period){
  const out = [];
  for(let i=period-1;i<rows.length;i++){
    const slice = rows.slice(i-period+1,i+1).map(r=>Number(r.close));
    out.push({time:chartTime(rows[i]), value:slice.reduce((a,b)=>a+b,0)/period});
  }
  return out;
}

function emaValues(values, period){
  const k = 2/(period+1);
  const out = [];
  let prev = null;
  const seed = [];
  values.forEach((v,i)=>{
    const n = Number(v);
    if(!Number.isFinite(n)){ out.push(null); return; }
    if(prev === null){
      seed.push(n);
      if(seed.length < period){ out.push(null); return; }
      prev = seed.slice(-period).reduce((a,b)=>a+b,0)/period;
    } else {
      prev = n*k + prev*(1-k);
    }
    out.push(prev);
  });
  return out;
}

function emaSeries(rows, period){
  const vals = emaValues(rows.map(r=>r.close), period);
  return vals.map((v,i)=>v===null?null:{time:chartTime(rows[i]), value:v}).filter(Boolean);
}

function vwapSeries(rows){
  const out = [];
  let pv = 0, vv = 0;
  rows.forEach(r=>{
    const vol = Math.max(1, Number(r.volume || 0));
    const typical = (Number(r.high)+Number(r.low)+Number(r.close))/3;
    pv += typical * vol; vv += vol;
    out.push({time:chartTime(r), value:pv/vv});
  });
  return out;
}

function bollingerSeries(rows, period=20, mult=2){
  const upper = [], mid = [], lower = [];
  for(let i=period-1;i<rows.length;i++){
    const slice = rows.slice(i-period+1,i+1).map(r=>Number(r.close));
    const mean = slice.reduce((a,b)=>a+b,0)/period;
    const std = Math.sqrt(slice.reduce((a,b)=>a+(b-mean)*(b-mean),0)/period);
    const time = chartTime(rows[i]);
    upper.push({time, value:mean + mult*std});
    mid.push({time, value:mean});
    lower.push({time, value:mean - mult*std});
  }
  return {upper, mid, lower};
}

function rsiSeries(rows, period=14){
  const closes = rows.map(r=>Number(r.close));
  const out = [];
  for(let i=period;i<closes.length;i++){
    let gain = 0, loss = 0;
    for(let j=i-period+1;j<=i;j++){
      const diff = closes[j]-closes[j-1];
      if(diff >= 0) gain += diff; else loss -= diff;
    }
    const rs = loss === 0 ? 100 : gain / loss;
    const rsi = loss === 0 ? 100 : 100 - 100/(1+rs);
    out.push({time:chartTime(rows[i]), value:rsi});
  }
  return out;
}

function macdSeries(rows){
  const closes = rows.map(r=>Number(r.close));
  const ema12 = emaValues(closes, 12);
  const ema26 = emaValues(closes, 26);
  const macdVals = closes.map((_,i)=>ema12[i]===null || ema26[i]===null ? null : ema12[i]-ema26[i]);
  const signalVals = emaValues(macdVals.map(v=>v===null?NaN:v), 9);
  const line = [], signal = [], hist = [];
  macdVals.forEach((v,i)=>{
    if(v === null || signalVals[i] === null) return;
    const time = chartTime(rows[i]);
    line.push({time, value:v});
    signal.push({time, value:signalVals[i]});
    hist.push({time, value:v-signalVals[i], color:(v-signalVals[i])>=0?"rgba(16,185,129,.55)":"rgba(239,68,68,.50)"});
  });
  return {line, signal, hist};
}

function chartTheme(){
  const dark = CHART_LAYERS.dark;
  return {
    bg: dark ? "#101827" : "#ffffff",
    panel: dark ? "#0f172a" : "#ffffff",
    text: dark ? "#dbeafe" : "#334155",
    grid: dark ? "rgba(148,163,184,.16)" : "rgba(148,163,184,.22)",
    border: dark ? "#334155" : "#d9e2ef",
    up: "#10b981",
    down: "#ef4444",
    blue: "#3b82f6",
    amber: "#f59e0b",
    purple: "#8b5cf6",
    cyan: "#06b6d4"
  };
}

function baseChartOptions(height){
  const t = chartTheme();
  return {
    height,
    layout:{background:{type:"solid",color:t.bg},textColor:t.text,fontFamily:"Segoe UI, Arial"},
    grid:{vertLines:{color:t.grid},horzLines:{color:t.grid}},
    crosshair:{mode: window.LightweightCharts?.CrosshairMode?.Normal ?? 0},
    rightPriceScale:{borderColor:t.border,scaleMargins:{top:.08,bottom:.26}},
    timeScale:{borderColor:t.border,timeVisible:true,secondsVisible:false,rightOffset:8,barSpacing:7,minBarSpacing:2},
    localization:{priceFormatter:p=>"$"+Number(p).toFixed(2)}
  };
}

function resetTradingChart(){
  const priceEl = document.getElementById("tradingChart");
  const indEl = document.getElementById("indicatorChart");
  if(priceEl) priceEl.innerHTML = "";
  if(indEl) indEl.innerHTML = "";
  TRADING_CHART = null;
}

function ensureTradingChart(){
  if(!window.LightweightCharts) return false;
  const priceEl = document.getElementById("tradingChart");
  const indEl = document.getElementById("indicatorChart");
  if(!priceEl || !indEl) return false;
  if(TRADING_CHART) return true;
  const t = chartTheme();
  const chart = LightweightCharts.createChart(priceEl, baseChartOptions(priceEl.clientHeight || 430));
  const indicator = LightweightCharts.createChart(indEl, {
    ...baseChartOptions(indEl.clientHeight || 150),
    rightPriceScale:{borderColor:t.border,scaleMargins:{top:.12,bottom:.12}},
    localization:{priceFormatter:p=>Number(p).toFixed(2)}
  });
  const candle = chart.addCandlestickSeries({
    upColor:t.up,downColor:t.down,borderUpColor:t.up,borderDownColor:t.down,wickUpColor:t.up,wickDownColor:t.down,
    priceLineVisible:true,lastValueVisible:true
  });
  const volume = chart.addHistogramSeries({priceScaleId:"",priceFormat:{type:"volume"},lastValueVisible:false,priceLineVisible:false});
  volume.priceScale().applyOptions({scaleMargins:{top:.78,bottom:0}});
  const ma = chart.addLineSeries({color:t.blue,lineWidth:2,lastValueVisible:false,priceLineVisible:false});
  const ema = chart.addLineSeries({color:t.amber,lineWidth:2,lastValueVisible:false,priceLineVisible:false});
  const vwap = chart.addLineSeries({color:t.purple,lineWidth:2,lastValueVisible:false,priceLineVisible:false});
  const bbUpper = chart.addLineSeries({color:"rgba(6,182,212,.72)",lineWidth:1,lastValueVisible:false,priceLineVisible:false});
  const bbMid = chart.addLineSeries({color:"rgba(6,182,212,.40)",lineWidth:1,lastValueVisible:false,priceLineVisible:false});
  const bbLower = chart.addLineSeries({color:"rgba(6,182,212,.72)",lineWidth:1,lastValueVisible:false,priceLineVisible:false});
  const rsi = indicator.addLineSeries({color:t.blue,lineWidth:2,lastValueVisible:true,priceLineVisible:false});
  const macd = indicator.addLineSeries({color:t.blue,lineWidth:2,lastValueVisible:false,priceLineVisible:false});
  const signal = indicator.addLineSeries({color:t.amber,lineWidth:2,lastValueVisible:false,priceLineVisible:false});
  const hist = indicator.addHistogramSeries({priceFormat:{type:"price",precision:2,minMove:.01},lastValueVisible:false,priceLineVisible:false});
  let syncing = false;
  chart.timeScale().subscribeVisibleLogicalRangeChange(range=>{
    if(syncing || !range) return;
    syncing = true; indicator.timeScale().setVisibleLogicalRange(range); syncing = false;
  });
  indicator.timeScale().subscribeVisibleLogicalRangeChange(range=>{
    if(syncing || !range) return;
    syncing = true; chart.timeScale().setVisibleLogicalRange(range); syncing = false;
  });
  chart.subscribeCrosshairMove(param=>{
    if(!param || !param.time || !param.seriesData) { updateChartReadout(); return; }
    const bar = param.seriesData.get(candle);
    if(bar) updateChartReadout({time:param.time,...bar});
  });
  TRADING_CHART = {chart,indicator,candle,volume,ma,ema,vwap,bbUpper,bbMid,bbLower,rsi,macd,signal,hist,key:null};
  resizeTradingChart();
  return true;
}

function resizeTradingChart(){
  if(!TRADING_CHART) return;
  const priceEl = document.getElementById("tradingChart");
  const indEl = document.getElementById("indicatorChart");
  if(priceEl) TRADING_CHART.chart.resize(Math.max(320, priceEl.clientWidth), Math.max(320, priceEl.clientHeight));
  if(indEl) TRADING_CHART.indicator.resize(Math.max(320, indEl.clientWidth), Math.max(120, indEl.clientHeight));
}

function updateChartReadout(bar=null){
  const rows = chartRows();
  const last = rows[rows.length-1];
  const prev = rows[rows.length-2] || last;
  const b = bar || (last ? {time:chartTime(last),open:Number(last.open),high:Number(last.high),low:Number(last.low),close:Number(last.close)} : null);
  const readout = document.getElementById("chartReadout");
  if(!readout || !b) return;
  const change = last && prev ? Number(last.close)/Number(prev.close)-1 : 0;
  const vol = last ? fmtVolume(last.volume) : "-";
  readout.innerHTML = `
    <span><b>${ACTIVE_TICKER || "-"}</b></span>
    <span>${timeLabel(b.time)}</span>
    <span>O ${fmtPrice(b.open)}</span>
    <span>H ${fmtPrice(b.high)}</span>
    <span>L ${fmtPrice(b.low)}</span>
    <span>C ${fmtPrice(b.close)}</span>
    <span class="${clsFor(change)}">${fmtPct(change)}</span>
    <span>Vol ${vol}</span>`;
}

function renderProfessionalKline(){
  const shell = document.getElementById("chartShell");
  const priceEl = document.getElementById("tradingChart");
  const indEl = document.getElementById("indicatorChart");
  const canvas = document.getElementById("candleChart");
  if(!window.LightweightCharts || !shell || !priceEl || !indEl){
    if(priceEl) priceEl.style.display = "none";
    if(indEl) indEl.style.display = "none";
    if(canvas) canvas.style.display = "block";
    return false;
  }
  if(canvas) canvas.style.display = "none";
  priceEl.style.display = "block";
  indEl.style.display = "block";
  shell.classList.toggle("dark", CHART_LAYERS.dark);
  if(!ensureTradingChart()) return false;
  const rows = chartRows();
  if(!rows.length) return true;
  const key = `${ACTIVE_TICKER}|${MARKET?.period}|${MARKET?.interval}`;
  const candles = toCandleData(rows);
  TRADING_CHART.candle.setData(candles);
  TRADING_CHART.volume.setData(CHART_LAYERS.volume ? toVolumeData(rows) : []);
  TRADING_CHART.ma.setData(CHART_LAYERS.ma ? smaSeries(rows,20) : []);
  TRADING_CHART.ema.setData(CHART_LAYERS.ema ? emaSeries(rows,50) : []);
  TRADING_CHART.vwap.setData(CHART_LAYERS.vwap ? vwapSeries(rows) : []);
  const bb = bollingerSeries(rows,20,2);
  TRADING_CHART.bbUpper.setData(CHART_LAYERS.bands ? bb.upper : []);
  TRADING_CHART.bbMid.setData(CHART_LAYERS.bands ? bb.mid : []);
  TRADING_CHART.bbLower.setData(CHART_LAYERS.bands ? bb.lower : []);
  if(CHART_LAYERS.macd){
    const m = macdSeries(rows);
    TRADING_CHART.rsi.setData([]);
    TRADING_CHART.macd.setData(m.line);
    TRADING_CHART.signal.setData(m.signal);
    TRADING_CHART.hist.setData(m.hist);
  } else {
    TRADING_CHART.rsi.setData(rsiSeries(rows,14));
    TRADING_CHART.macd.setData([]);
    TRADING_CHART.signal.setData([]);
    TRADING_CHART.hist.setData([]);
  }
  if(TRADING_CHART.key !== key){
    TRADING_CHART.chart.timeScale().fitContent();
    TRADING_CHART.indicator.timeScale().fitContent();
    TRADING_CHART.key = key;
  }
  updateChartReadout();
  resizeTradingChart();
  return true;
}

function drawCandleChart(){
  try {
    drawCanvasFallback();
  } catch (err) {
    console.error("K-line render failed", err);
    const readout = document.getElementById("chartReadout");
    if(readout) readout.textContent = "K-line render error: " + (err && err.message ? err.message : err);
  }
}

function toggleChartLayer(layer, btn){
  CHART_LAYERS[layer] = !CHART_LAYERS[layer];
  if(btn){
    btn.classList.toggle("active", CHART_LAYERS[layer]);
    btn.classList.toggle("secondary", !CHART_LAYERS[layer]);
  }
  drawCandleChart();
}

function toggleChartTheme(){
  CHART_LAYERS.dark = !CHART_LAYERS.dark;
  const btn = document.getElementById("chartThemeBtn");
  if(btn) btn.textContent = CHART_LAYERS.dark ? "Light" : "Dark";
  resetTradingChart();
  drawCandleChart();
}

function fitTradingChart(){
  const rows = chartRows();
  CANVAS_CHART.start = 0;
  CANVAS_CHART.end = Math.max(0, rows.length - 1);
  CANVAS_CHART.key = `${ACTIVE_TICKER}|${MARKET?.period}|${MARKET?.interval}`;
  drawCanvasFallback();
}

function exportTradingChart(){
  const shot = document.getElementById("candleChart");
  if(!shot) return;
  const link = document.createElement("a");
  link.download = `${ACTIVE_TICKER || "chart"}-${MARKET?.period || "chart"}-${MARKET?.interval || "1d"}.png`;
  link.href = shot.toDataURL("image/png");
  link.click();
}

function drawCanvasFallback(){
  const canvas = document.getElementById("candleChart");
  if(!canvas || !MARKET || !ACTIVE_TICKER) return;
  const priceEl = document.getElementById("tradingChart");
  const indEl = document.getElementById("indicatorChart");
  if(priceEl) priceEl.style.display = "none";
  if(indEl) indEl.style.display = "none";
  canvas.style.display = "block";
  const shell = document.getElementById("chartShell");
  if(shell) shell.classList.toggle("dark", CHART_LAYERS.dark);

  const rows = chartRows();
  const key = `${ACTIVE_TICKER}|${MARKET.period}|${MARKET.interval}|${rows.length}`;
  if(CANVAS_CHART.key !== key){
    const windowSize = MARKET.interval === "1d" ? Math.min(rows.length, 170) : Math.min(rows.length, 180);
    CANVAS_CHART.start = Math.max(0, rows.length - windowSize);
    CANVAS_CHART.end = Math.max(0, rows.length - 1);
    CANVAS_CHART.cross = null;
    CANVAS_CHART.key = key;
  }
  CANVAS_CHART.start = clamp(Math.round(CANVAS_CHART.start), 0, Math.max(0, rows.length - 2));
  CANVAS_CHART.end = clamp(Math.round(CANVAS_CHART.end), CANVAS_CHART.start + 1, Math.max(1, rows.length - 1));
  const visible = rows.slice(CANVAS_CHART.start, CANVAS_CHART.end + 1);

  if(!canvas.dataset.bound){
    canvas.dataset.bound = "1";
    canvas.addEventListener("mousemove", e=>{
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      if(CANVAS_CHART.drag){
        const rowsNow = chartRows();
        const count = Math.max(2, CANVAS_CHART.dragEnd - CANVAS_CHART.dragStart + 1);
        const chartW = Math.max(1, rect.width - 62 - 70);
        const step = chartW / Math.max(1, count - 1);
        const delta = Math.round((CANVAS_CHART.dragX - x) / Math.max(1, step));
        let start = CANVAS_CHART.dragStart + delta;
        start = clamp(start, 0, Math.max(0, rowsNow.length - count));
        CANVAS_CHART.start = start;
        CANVAS_CHART.end = start + count - 1;
      } else {
        CANVAS_CHART.cross = {x,y};
      }
      drawCanvasFallback();
    });
    canvas.addEventListener("mouseleave", ()=>{
      CANVAS_CHART.cross = null;
      CANVAS_CHART.drag = false;
      drawCanvasFallback();
    });
    canvas.addEventListener("mousedown", e=>{
      const rect = canvas.getBoundingClientRect();
      CANVAS_CHART.drag = true;
      CANVAS_CHART.dragX = e.clientX - rect.left;
      CANVAS_CHART.dragStart = CANVAS_CHART.start;
      CANVAS_CHART.dragEnd = CANVAS_CHART.end;
    });
    window.addEventListener("mouseup", ()=>{ CANVAS_CHART.drag = false; });
    canvas.addEventListener("wheel", e=>{
      e.preventDefault();
      const rowsNow = chartRows();
      const count = CANVAS_CHART.end - CANVAS_CHART.start + 1;
      const zoomIn = e.deltaY < 0;
      const nextCount = clamp(Math.round(count * (zoomIn ? 0.82 : 1.22)), 28, Math.max(30, rowsNow.length));
      const rect = canvas.getBoundingClientRect();
      const frac = clamp((e.clientX - rect.left - 62) / Math.max(1, rect.width - 132), 0, 1);
      const center = CANVAS_CHART.start + Math.round(count * frac);
      let start = Math.round(center - nextCount * frac);
      start = clamp(start, 0, Math.max(0, rowsNow.length - nextCount));
      CANVAS_CHART.start = start;
      CANVAS_CHART.end = Math.min(rowsNow.length - 1, start + nextCount - 1);
      drawCanvasFallback();
    }, {passive:false});
  }

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width*dpr));
  canvas.height = Math.max(1, Math.round(rect.height*dpr));
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr,dpr);
  const w = rect.width, h = rect.height;
  const t = chartTheme();
  ctx.clearRect(0,0,w,h);
  ctx.fillStyle=t.bg;
  ctx.fillRect(0,0,w,h);
  if(!rows.length){
    ctx.fillStyle=t.text; ctx.font="13px Segoe UI"; ctx.fillText("No market bars available.", 20, 32); return;
  }
  const pad = {l:62,r:70,t:42,b:28};
  const priceBottom = Math.max(330, h - 150);
  const priceH = priceBottom - pad.t;
  const indTop = priceBottom + 22;
  const indBottom = h - pad.b;
  const indH = Math.max(90, indBottom - indTop);
  const chartW = w - pad.l - pad.r;
  const volH = Math.min(82, priceH * 0.26);
  const volTop = priceBottom - volH;

  const byTime = series => {
    const m = new Map();
    series.forEach(p=>m.set(String(p.time), Number(p.value)));
    return m;
  };
  const maMap = byTime(smaSeries(rows, 20));
  const emaMap = byTime(emaSeries(rows, 50));
  const vwapMap = byTime(vwapSeries(rows));
  const bb = bollingerSeries(rows, 20, 2);
  const bbUpperMap = byTime(bb.upper), bbMidMap = byTime(bb.mid), bbLowerMap = byTime(bb.lower);

  const highs = visible.map(r=>Number(r.high));
  const lows = visible.map(r=>Number(r.low));
  const extraVals = [];
  visible.forEach(r=>{
    const k = String(chartTime(r));
    if(CHART_LAYERS.ma && maMap.has(k)) extraVals.push(maMap.get(k));
    if(CHART_LAYERS.ema && emaMap.has(k)) extraVals.push(emaMap.get(k));
    if(CHART_LAYERS.vwap && vwapMap.has(k)) extraVals.push(vwapMap.get(k));
    if(CHART_LAYERS.bands){
      [bbUpperMap, bbMidMap, bbLowerMap].forEach(m=>{ if(m.has(k)) extraVals.push(m.get(k)); });
    }
  });
  let minP = Math.min(...lows), maxP = Math.max(...highs);
  extraVals.forEach(v=>{ if(Number.isFinite(v)){ minP=Math.min(minP,v); maxP=Math.max(maxP,v); } });
  if(minP===maxP){ minP-=1; maxP+=1; }
  const pExtra = (maxP-minP)*0.10; minP-=pExtra; maxP+=pExtra;
  const maxVol = Math.max(...visible.map(r=>Number(r.volume)||0), 1);
  const xStep = chartW/Math.max(1, visible.length-1);
  const candleW = Math.max(2, Math.min(15, xStep*0.58));
  const xFor = i => pad.l + xStep*i;
  const yFor = p => pad.t + priceH*(1-(Number(p)-minP)/(maxP-minP));

  ctx.strokeStyle=t.grid; ctx.lineWidth=1; ctx.font="11px Segoe UI"; ctx.fillStyle=t.text;
  for(let i=0;i<=5;i++){
    const y=pad.t+priceH*i/5;
    ctx.beginPath(); ctx.moveTo(pad.l,y); ctx.lineTo(w-pad.r,y); ctx.stroke();
    const val=maxP-(maxP-minP)*i/5;
    ctx.fillText("$"+val.toFixed(2), w-pad.r+8, y+4);
  }
  const labelIdx = [0,.25,.5,.75,1].map(p=>Math.round((visible.length-1)*p));
  labelIdx.forEach(i=>{
    const x = xFor(i);
    ctx.beginPath(); ctx.moveTo(x,pad.t); ctx.lineTo(x,priceBottom); ctx.stroke();
    ctx.fillText(String(visible[i]?.date || "").slice(MARKET.interval==="1d"?5:5, MARKET.interval==="1d"?10:16), Math.max(pad.l, Math.min(w-pad.r-70, x-28)), priceBottom+16);
  });
  ctx.strokeStyle=t.border;
  ctx.beginPath(); ctx.rect(pad.l,pad.t,chartW,priceH); ctx.stroke();

  if(CHART_LAYERS.volume){
    visible.forEach((r,i)=>{
      const x=xFor(i);
      const v=Number(r.volume)||0;
      const up = Number(r.close)>=Number(r.open);
      const vh = volH*(v/maxVol);
      ctx.fillStyle = up ? "rgba(16,185,129,.28)" : "rgba(239,68,68,.24)";
      ctx.fillRect(x-candleW/2, priceBottom - vh, candleW, vh);
    });
    ctx.fillStyle=t.text; ctx.font="11px Segoe UI"; ctx.fillText("Volume", pad.l+6, volTop+14);
  }

  visible.forEach((r,i)=>{
    const x=xFor(i);
    const o=Number(r.open), c=Number(r.close), hi=Number(r.high), lo=Number(r.low), v=Number(r.volume)||0;
    const up = c>=o;
    const color = up ? t.up : t.down;
    ctx.strokeStyle=color; ctx.fillStyle=color;
    ctx.lineWidth = Math.max(1, Math.min(2, candleW*.22));
    ctx.beginPath(); ctx.moveTo(x, yFor(hi)); ctx.lineTo(x, yFor(lo)); ctx.stroke();
    const yOpen=yFor(o), yClose=yFor(c);
    const bodyTop=Math.min(yOpen,yClose), bodyH=Math.max(2.2, Math.abs(yClose-yOpen));
    if(up){
      ctx.fillStyle = t.bg;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.3;
      ctx.fillRect(x-candleW/2, bodyTop, candleW, bodyH);
      ctx.strokeRect(x-candleW/2, bodyTop, candleW, bodyH);
    } else {
      ctx.fillStyle = color;
      ctx.fillRect(x-candleW/2, bodyTop, candleW, bodyH);
    }
  });

  function drawMappedLine(map, color, width=1.8, dashed=false){
    ctx.save();
    ctx.strokeStyle=color; ctx.lineWidth=width;
    if(dashed) ctx.setLineDash([4,4]);
    ctx.beginPath();
    let started=false;
    visible.forEach((r,i)=>{
      const v = map.get(String(chartTime(r)));
      if(!Number.isFinite(v)) return;
      const x=xFor(i), y=yFor(v);
      if(!started){ ctx.moveTo(x,y); started=true; } else ctx.lineTo(x,y);
    });
    if(started) ctx.stroke();
    ctx.restore();
  }
  if(CHART_LAYERS.bands){
    drawMappedLine(bbUpperMap, "rgba(6,182,212,.78)", 1.2);
    drawMappedLine(bbMidMap, "rgba(6,182,212,.40)", 1.1, true);
    drawMappedLine(bbLowerMap, "rgba(6,182,212,.78)", 1.2);
  }
  if(CHART_LAYERS.ma) drawMappedLine(maMap, t.blue, 2.1);
  if(CHART_LAYERS.ema) drawMappedLine(emaMap, t.amber, 2.0);
  if(CHART_LAYERS.vwap) drawMappedLine(vwapMap, t.purple, 1.8);

  ctx.strokeStyle=t.grid;
  ctx.fillStyle=t.text;
  ctx.font="11px Segoe UI";
  ctx.beginPath(); ctx.moveTo(pad.l,indTop); ctx.lineTo(w-pad.r,indTop); ctx.stroke();
  ctx.strokeStyle=t.border; ctx.strokeRect(pad.l, indTop, chartW, indH);
  if(CHART_LAYERS.macd){
    const m = macdSeries(rows);
    const maps = [byTime(m.line), byTime(m.signal), byTime(m.hist)];
    const vals = [];
    visible.forEach(r=>maps.forEach(mp=>{ const v=mp.get(String(chartTime(r))); if(Number.isFinite(v)) vals.push(v); }));
    let minI = Math.min(...vals, -0.01), maxI = Math.max(...vals, 0.01);
    if(minI===maxI){ minI-=1; maxI+=1; }
    const yI = v => indTop + indH*(1-(v-minI)/(maxI-minI));
    const zero = yI(0);
    ctx.strokeStyle=t.grid; ctx.beginPath(); ctx.moveTo(pad.l,zero); ctx.lineTo(w-pad.r,zero); ctx.stroke();
    visible.forEach((r,i)=>{
      const v = maps[2].get(String(chartTime(r)));
      if(!Number.isFinite(v)) return;
      const x = xFor(i);
      ctx.fillStyle = v>=0 ? "rgba(16,185,129,.55)" : "rgba(239,68,68,.50)";
      ctx.fillRect(x-candleW/2, Math.min(zero,yI(v)), candleW, Math.max(1, Math.abs(yI(v)-zero)));
    });
    const drawIndicatorLine = (map,color)=>{
      ctx.strokeStyle=color; ctx.lineWidth=1.8; ctx.beginPath(); let started=false;
      visible.forEach((r,i)=>{ const v=map.get(String(chartTime(r))); if(!Number.isFinite(v))return; const x=xFor(i), y=yI(v); if(!started){ctx.moveTo(x,y); started=true;} else ctx.lineTo(x,y); });
      if(started)ctx.stroke();
    };
    drawIndicatorLine(maps[0], t.blue);
    drawIndicatorLine(maps[1], t.amber);
    ctx.fillText("MACD", pad.l+6, indTop+16);
  } else {
    const rsiMap = byTime(rsiSeries(rows,14));
    const yR = v => indTop + indH*(1-v/100);
    [70,50,30].forEach(level=>{
      ctx.strokeStyle = level===50 ? t.grid : "rgba(245,158,11,.32)";
      ctx.beginPath(); ctx.moveTo(pad.l,yR(level)); ctx.lineTo(w-pad.r,yR(level)); ctx.stroke();
      ctx.fillStyle=t.text; ctx.fillText(String(level), w-pad.r+8, yR(level)+4);
    });
    ctx.strokeStyle=t.blue; ctx.lineWidth=1.9; ctx.beginPath(); let started=false;
    visible.forEach((r,i)=>{ const v=rsiMap.get(String(chartTime(r))); if(!Number.isFinite(v))return; const x=xFor(i), y=yR(v); if(!started){ctx.moveTo(x,y); started=true;} else ctx.lineTo(x,y); });
    if(started)ctx.stroke();
    ctx.fillStyle=t.text; ctx.fillText("RSI 14", pad.l+6, indTop+16);
  }

  const first=visible[0], last=visible[visible.length-1];
  const chg = Number(last.close) - Number((rows[rows.length-2] || last).close);
  const chgPct = chg / Number((rows[rows.length-2] || last).close || 1);
  ctx.fillStyle=t.text; ctx.font="bold 14px Segoe UI";
  ctx.fillText(`${ACTIVE_TICKER} ${fmtPrice(last.close)}  ${fmtPct(chgPct)}  ${MARKET.period}/${MARKET.interval}`, pad.l, 22);
  ctx.font="11px Segoe UI";
  ctx.fillText(`${first.date} -> ${last.date} | ${visible.length}/${rows.length} bars | wheel zoom, drag pan`, pad.l+245, 22);

  if(CANVAS_CHART.cross){
    const cx = clamp(CANVAS_CHART.cross.x, pad.l, w-pad.r);
    const cy = clamp(CANVAS_CHART.cross.y, pad.t, indBottom);
    const idx = clamp(Math.round((cx-pad.l)/Math.max(1,xStep)), 0, visible.length-1);
    const r = visible[idx];
    const x = xFor(idx);
    ctx.save();
    ctx.setLineDash([5,5]);
    ctx.strokeStyle = CHART_LAYERS.dark ? "rgba(226,232,240,.50)" : "rgba(71,85,105,.45)";
    ctx.beginPath(); ctx.moveTo(x,pad.t); ctx.lineTo(x,indBottom); ctx.stroke();
    if(cy <= priceBottom){
      ctx.beginPath(); ctx.moveTo(pad.l,cy); ctx.lineTo(w-pad.r,cy); ctx.stroke();
      const price = maxP - (cy-pad.t)/priceH*(maxP-minP);
      ctx.setLineDash([]);
      ctx.fillStyle="#111827"; ctx.fillRect(w-pad.r+4, cy-11, 58, 22);
      ctx.fillStyle="#fff"; ctx.font="bold 11px Segoe UI"; ctx.fillText("$"+price.toFixed(2), w-pad.r+8, cy+4);
    }
    ctx.setLineDash([]);
    ctx.fillStyle="#111827"; ctx.fillRect(Math.max(pad.l, Math.min(w-pad.r-110, x-44)), priceBottom+2, 110, 22);
    ctx.fillStyle="#fff"; ctx.font="bold 11px Segoe UI"; ctx.fillText(String(r.date).slice(2,16), Math.max(pad.l+4, Math.min(w-pad.r-106, x-40)), priceBottom+17);
    ctx.restore();
    updateChartReadout({time:chartTime(r),open:Number(r.open),high:Number(r.high),low:Number(r.low),close:Number(r.close)});
  } else {
    updateChartReadout({time:chartTime(last),open:Number(last.open),high:Number(last.high),low:Number(last.low),close:Number(last.close)});
  }
}

function drawLineChart(id, labels, series){
  const canvas = document.getElementById(id);
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width*dpr));
  canvas.height = Math.max(1, Math.round(rect.height*dpr));
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr,dpr);
  const w = rect.width, h = rect.height;
  ctx.clearRect(0,0,w,h);
  const legendRows = series.length > 3 ? 2 : 1;
  const pad = {l:42,r:18,t:22 + (legendRows - 1) * 16,b:34};
  const vals = series.flatMap(s=>s.values).filter(v=>Number.isFinite(Number(v))).map(Number);
  let min = Math.min(...vals), max = Math.max(...vals);
  if (min===max){ min-=1; max+=1; }
  const extra=(max-min)*0.12; min-=extra; max+=extra;
  ctx.strokeStyle="#e3eaf4"; ctx.lineWidth=1;
  ctx.font="11px Segoe UI";
  ctx.fillStyle="#64748b";
  for(let i=0;i<5;i++){
    const y=pad.t+(h-pad.t-pad.b)*i/4;
    ctx.beginPath(); ctx.moveTo(pad.l,y); ctx.lineTo(w-pad.r,y); ctx.stroke();
    const val=max-(max-min)*i/4;
    ctx.fillText(val.toFixed(2),4,y+4);
  }
  const xFor=i=>pad.l+(w-pad.l-pad.r)*(i/Math.max(1,labels.length-1));
  const yFor=v=>pad.t+(h-pad.t-pad.b)*(1-(v-min)/(max-min));
  series.forEach(s=>{
    ctx.strokeStyle=s.color; ctx.lineWidth=2; ctx.beginPath();
    s.values.forEach((v,i)=>{ const x=xFor(i), y=yFor(Number(v)); if(i===0)ctx.moveTo(x,y); else ctx.lineTo(x,y); });
    ctx.stroke();
  });
  let lx=pad.l, ly=12;
  series.forEach(s=>{
    const label = String(s.name);
    const approx = 22 + label.length * 6.5;
    if(lx + approx > w - pad.r){ lx = pad.l; ly += 14; }
    ctx.fillStyle=s.color; ctx.fillRect(lx,ly-4,12,3);
    ctx.fillStyle="#334155"; ctx.fillText(label,lx+16,ly);
    lx += approx + 18;
  });
  ctx.fillStyle="#64748b";
  if(labels.length){ ctx.fillText(labels[0],pad.l,h-10); ctx.fillText(labels[labels.length-1],w-pad.r-36,h-10); }
}

window.addEventListener("resize",()=>{ if(DASH) renderDashboard(DASH); if(MARKET) drawCandleChart(); if(OPTIMIZER) renderOptimizer(OPTIMIZER); if(DAILY_CLIMATE_BOARD) renderDailyClimateBoard(DAILY_CLIMATE_BOARD); });
loadDashboard();
setInterval(()=>{ loadMarketChart(); }, 20000);
setInterval(()=>{ loadEtfWatchlist(); }, 60000);
setInterval(()=>{ loadDailyClimateBoard(); }, 300000);
setInterval(()=>{ loadDashboard(); }, 900000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self):
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep terminal quiet and product-like
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ["/", "/index.html"]:
            self._send_html()
            return
        if parsed.path == "/api/dashboard":
            self._send_json(build_payload())
            return
        if parsed.path == "/api/company_scan":
            q = parse_qs(parsed.query)
            tickers = ",".join(q.get("tickers", ["AAPL,MSFT,XOM,NEE,JPM"]))
            self._send_json(company_scan(tickers.split(",")))
            return
        if parsed.path == "/api/universe_search":
            q = parse_qs(parsed.query)
            query = q.get("query", [""])[0]
            limit = q.get("limit", ["80"])[0]
            include_etfs = q.get("include_etfs", ["false"])[0].lower() in ["1", "true", "yes"]
            self._send_json(search_us_universe(query=query, limit=limit, include_etfs=include_etfs))
            return
        if parsed.path == "/api/market_chart":
            q = parse_qs(parsed.query)
            tickers = q.get("tickers", ["SPY,QQQ,AAPL,XOM"])[0]
            period = q.get("period", ["6mo"])[0]
            interval = q.get("interval", ["1d"])[0]
            self._send_json(market_chart_payload(tickers, period=period, interval=interval))
            return
        if parsed.path == "/api/etf_watchlist":
            self._send_json(etf_watchlist_payload())
            return
        if parsed.path == "/api/portfolio_optimizer":
            q = parse_qs(parsed.query)
            self._send_json(
                portfolio_optimizer_payload(
                    mode=q.get("mode", ["etf_stock"])[0],
                    capital=q.get("capital", [str(DEFAULT_PORTFOLIO_VALUE)])[0],
                    horizon=q.get("horizon", ["long"])[0],
                    style=q.get("style", ["balanced"])[0],
                    etfs=q.get("etfs", [",".join(DEFAULT_OPTIMIZER_ETFS)])[0],
                    stocks=q.get("stocks", [",".join(DEFAULT_OPTIMIZER_STOCKS)])[0],
                )
            )
            return
        if parsed.path == "/api/daily_climate_board":
            self._send_json(daily_climate_board_payload())
            return
        if parsed.path == "/api/daily_climate_signal":
            self._send_json(load_daily_climate_signal())
            return
        self._send_json({"error": "Not found"}, status=404)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Jenneson Climate-Finance Platform started: {url}")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
