"""
Data fetcher for the LIC DSF Tool.
Data sources:
  1. IMF WEO (live)  — via `imf-reader` package → scrapes imf.org WEO publication
  2. World Bank API  — debt stocks, PV of debt, CPIA, reserves, remittances
  3. World Bank WLD  — world GDP growth for CI formula
"""

import time
import warnings
import requests
import pandas as pd
import numpy as np
import streamlit as st

warnings.filterwarnings("ignore")

WB_BASE = "https://api.worldbank.org/v2"

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 LIC-DSF-Tool/1.0"})


# ─────────────────────────────────────────────────────────────────────────────
# 1.  IMF WEO (live) via imf-reader
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=21600, show_spinner=False)   # 6-hour cache — WEO only updates April/October
def _fetch_weo_raw() -> pd.DataFrame:
    """
    Fetch the full latest IMF WEO dataset from imf.org.
    Returns long-format DataFrame with all countries and indicators.
    Cached for 6 hours (WEO releases are April & October only).
    """
    import imf_reader.weo as weo
    df = weo.fetch_data()                       # fetches latest WEO (Oct 2025)
    df["TIME_PERIOD"] = pd.to_numeric(df["TIME_PERIOD"], errors="coerce")
    df = df.dropna(subset=["TIME_PERIOD"])      # drop rows with no year
    df["TIME_PERIOD"] = df["TIME_PERIOD"].astype(int)
    df["OBS_VALUE"]   = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    return df


def fetch_weo_series(area_code: str, concept_code: str) -> pd.Series:
    """
    Extract one WEO time series for one country from the cached WEO dataset.
    area_code    : ISO3 country code  (e.g. 'SEN', 'KEN') or group ('G001' = World)
    concept_code : WEO indicator code (e.g. 'NGDP_RPCH', 'GGXWDG_NGDP')
    Returns pd.Series indexed by year (int).
    """
    df  = _fetch_weo_raw()
    sub = df[(df["REF_AREA_CODE"] == area_code) & (df["CONCEPT_CODE"] == concept_code)]
    if sub.empty:
        return pd.Series(dtype=float)
    s = sub.set_index("TIME_PERIOD")["OBS_VALUE"].dropna().astype(float)
    return s.sort_index()


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_weo_country(iso3: str) -> dict[str, pd.Series]:
    """
    Fetch all required WEO indicators for one country.
    Returns dict of {concept_code: pd.Series(year → value)}.
    """
    NEEDED = [
        "NGDPD",          # GDP current prices (USD bn)
        "NGDP_RPCH",      # Real GDP growth (%)
        "NGDP_D",         # GDP deflator (% change)
        "GGR_NGDP",       # General govt revenue (% GDP)
        "GGXONLB_NGDP",   # Primary balance (% GDP)
        "GGXWDG_NGDP",    # Gross debt (% GDP)
        "BCA_NGDPD",      # Current account (% GDP)
        "NID_NGDP",       # Total investment (% GDP)
        "PCPIPCH",        # Inflation, average consumer prices (%)
        "NGDP_R",         # Real GDP (domestic currency)
    ]
    df  = _fetch_weo_raw()
    sub = df[df["REF_AREA_CODE"] == iso3]
    result = {}
    for code in NEEDED:
        rows = sub[sub["CONCEPT_CODE"] == code]
        if rows.empty:
            continue
        s = rows.set_index("TIME_PERIOD")["OBS_VALUE"].dropna().astype(float).sort_index()
        if not s.empty:
            result[code] = s
    return result


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_world_growth() -> pd.Series:
    """
    Fetch world real GDP growth (WEO Group G001 = World).
    Returns pd.Series indexed by year.
    """
    return fetch_weo_series("G001", "NGDP_RPCH")


def get_weo_version() -> str:
    """Return the WEO version string (e.g. 'October 2025')."""
    try:
        import imf_reader.weo as weo
        # imf-reader logs version info; fetch and infer from latest
        df = _fetch_weo_raw()
        yr = df["TIME_PERIOD"].max()
        return f"Live (latest WEO, up to {yr})"
    except Exception:
        return "Unknown"


# ─────────────────────────────────────────────────────────────────────────────
# 2.  World Bank API  (debt, CPIA, reserves, remittances)
# ─────────────────────────────────────────────────────────────────────────────

def _get_json(url: str, params: dict | None = None, retries: int = 3) -> list | dict | None:
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=20)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(1.5 ** attempt)
            else:
                st.warning(f"⚠️ World Bank API: {e}")
                return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_wb_indicator(
    iso2:   str,
    code:   str,
    start:  int = 2005,
    end:    int = 2025,
    source: int | None = None,   # e.g. 6 = IDS (International Debt Statistics)
) -> pd.Series:
    """Fetch one World Bank indicator. Returns pd.Series indexed by year.
    Pass source=6 to query specifically from the IDS database.
    """
    url    = f"{WB_BASE}/country/{iso2}/indicator/{code}"
    params: dict = {"format": "json", "per_page": 50, "date": f"{start}:{end}"}
    if source is not None:
        params["source"] = source
    data = _get_json(url, params=params)
    if not data or len(data) < 2 or not data[1]:
        return pd.Series(dtype=float)
    series = {}
    for row in data[1]:
        try:
            if row["value"] is not None:
                series[int(row["date"])] = float(row["value"])
        except (KeyError, TypeError, ValueError):
            pass
    return pd.Series(series, dtype=float).sort_index()


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_cpia_scores(iso2: str) -> dict:
    """Fetch 4 CPIA cluster averages and compute overall CPIA score."""
    clusters = {
        "A": "IQ.CPA.ECON.XQ",
        "B": "IQ.CPA.STRC.XQ",
        "C": "IQ.CPA.POLS.XQ",
        "D": "IQ.CPA.PUBS.XQ",
    }
    result, scores, latest_yr = {}, [], None
    for cl, code in clusters.items():
        s = fetch_wb_indicator(iso2, code, start=2015, end=2025)
        if not s.empty:
            val = float(s.iloc[-1])
            yr  = int(s.index[-1])
            result[f"cpia_{cl}"] = val
            scores.append(val)
            if latest_yr is None or yr > latest_yr:
                latest_yr = yr
    result["cpia_overall"] = round(sum(scores) / len(scores), 3) if scores else None
    result["year"]         = latest_yr
    return result


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_wb_debt(iso2: str) -> dict[str, pd.Series]:
    """
    Fetch all World Bank debt + auxiliary macro indicators for a country.
    Returns dict keyed by both short alias and original WB code.
    """
    WB_CODES = {
        "DT.DOD.DPPG.CD":        "ppg_debt_usd",       # PPG external debt stock (USD)
        "DT.DOD.PVLX.CD":        "pv_debt_usd",         # PV of external debt (USD)
        "DT.DOD.PVLX.EX.ZS":    "pv_debt_exports",      # PV debt / exports (%)
        "DT.DOD.PVLX.GN.ZS":    "pv_debt_gni",          # PV debt / GNI (%)
        "DT.TDS.DPPG.CD":        "ds_total_usd",         # PPG debt service (USD)
        "DT.TDS.DPPG.EX.ZS":    "ds_exports_pct",        # DS / exports (%)
        "DT.INT.DPPG.CD":        "interest_usd",         # Interest payments (USD)
        "DT.AMT.DPPG.CD":        "principal_usd",        # Principal repayments (USD)
        "BX.TRF.PWKR.DT.GD.ZS": "remittances_gdp",      # Remittances (% GDP)
        "FI.RES.TOTL.MO":        "reserves_months",      # Reserves (months of imports)
        "BX.GSR.GNFS.CD":        "exports_wb_usd",       # Exports goods+services (USD)
        "BM.GSR.GNFS.CD":        "imports_wb_usd",       # Imports goods+services (USD)
        "NY.GDP.MKTP.CD":        "gdp_usd_wb",           # GDP (current USD)
        "GC.REV.XGRT.GD.ZS":    "gov_rev_gdp_wb",        # Govt revenue (% GDP)
        "BN.CAB.XOKA.GD.ZS":    "ca_gdp_wb",            # Current account (% GDP)
    }
    result = {}
    for code, alias in WB_CODES.items():
        s = fetch_wb_indicator(iso2, code, start=2005, end=2025)
        result[alias] = s
        result[code]  = s   # also by WB code for compatibility
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Unified macro DataFrame
# ─────────────────────────────────────────────────────────────────────────────

def build_macro_dataframe(
    weo_data:  dict[str, pd.Series],
    wb_data:   dict[str, pd.Series],
    base_year: int,
    n_proj:    int = 5,
) -> pd.DataFrame:
    """
    Merge WEO (live) and World Bank data into a single macro DataFrame.
    WEO takes priority (includes projections); WB fills historical gaps.
    Index: year (int). Columns: standardised variable names.
    """
    hist_start = base_year - 9
    proj_end   = base_year + n_proj
    years = list(range(hist_start, proj_end + 1))

    df = pd.DataFrame(index=years, dtype=float)
    df.index.name = "year"

    def _fill(col: str, series: pd.Series | None, priority: bool = True):
        if series is None or series.empty:
            return
        s = series.reindex(years)
        if col not in df.columns:
            df[col] = s.values
        elif priority:
            mask = s.notna()
            df.loc[mask[mask].index, col] = s[mask].values
        else:
            mask = df[col].isna() & s.notna()
            df.loc[mask[mask].index, col] = s[mask].values

    # ── WEO indicators (high priority, includes projections) ────────────────
    # NOTE: NGDP_D in WEO (via imf-reader) is the GDP DEFLATOR INDEX (base≈2000=100),
    #       NOT the year-over-year % change. We therefore use PCPIPCH (CPI inflation
    #       average, already in % change) as a proxy for the GDP deflator. CPI and GDP
    #       deflator are closely correlated for most LICs.
    weo_map = {
        "gdp_usd":      weo_data.get("NGDPD"),         # USD bn
        "gdp_growth":   weo_data.get("NGDP_RPCH"),     # real GDP % change
        "gdp_deflator": weo_data.get("PCPIPCH"),       # CPI inflation % — proxy for deflator
        "revenue_gdp":  weo_data.get("GGR_NGDP"),      # % GDP
        "pbal_gdp":     weo_data.get("GGXONLB_NGDP"),  # % GDP
        "pub_debt_gdp": weo_data.get("GGXWDG_NGDP"),   # % GDP
        "ca_gdp":       weo_data.get("BCA_NGDPD"),     # % GDP
        "investment":   weo_data.get("NID_NGDP"),      # % GDP
        "inflation":    weo_data.get("PCPIPCH"),       # % — CPI
    }
    for col, s in weo_map.items():
        _fill(col, s, priority=True)

    # ── World Bank debt + auxiliary (fill gaps / historical depth) ───────────
    wb_map = {
        "ppg_debt_usd":   wb_data.get("ppg_debt_usd"),
        "pv_debt_usd":    wb_data.get("pv_debt_usd"),
        "pv_debt_exports":wb_data.get("pv_debt_exports"),
        "pv_debt_gni":    wb_data.get("pv_debt_gni"),
        "ds_total_usd":   wb_data.get("ds_total_usd"),
        "ds_exports_pct": wb_data.get("ds_exports_pct"),
        "interest_usd":   wb_data.get("interest_usd"),
        "principal_usd":  wb_data.get("principal_usd"),
        "remittances_gdp":wb_data.get("remittances_gdp"),
        "reserves_months":wb_data.get("reserves_months"),
        "exports_wb_usd": wb_data.get("exports_wb_usd"),
        "imports_wb_usd": wb_data.get("imports_wb_usd"),
        "gdp_usd_wb":     wb_data.get("gdp_usd_wb"),
        "gov_rev_gdp":    wb_data.get("gov_rev_gdp_wb"),
        "ca_gdp":         wb_data.get("ca_gdp_wb"),
    }
    for col, s in wb_map.items():
        _fill(col, s, priority=False)   # WB fills gaps only

    # ── Derived columns ──────────────────────────────────────────────────────
    # GDP in USD millions (WEO NGDPD is in USD billions)
    if "gdp_usd" in df.columns:
        df["gdp_usd_mn"] = df["gdp_usd"] * 1e3
    # Fill from WB absolute GDP if WEO missing
    if "gdp_usd_wb" in df.columns:
        wb_mn = df["gdp_usd_wb"] / 1e6
        if "gdp_usd_mn" not in df.columns:
            df["gdp_usd_mn"] = wb_mn
        else:
            mask = df["gdp_usd_mn"].isna() & wb_mn.notna()
            df.loc[mask, "gdp_usd_mn"] = wb_mn[mask]

    # Revenue % GDP: WEO → WB fallback
    if "revenue_gdp" in df.columns:
        _fill("gov_rev_gdp", df["revenue_gdp"], priority=False)

    # Debt service / revenue (%)
    # Units: ds_total_usd in absolute USD → /1e6 → USD mn; gdp_usd_mn in USD mn
    if {"ds_total_usd", "gdp_usd_mn", "gov_rev_gdp"}.issubset(df.columns):
        rev_mn = df["gdp_usd_mn"] * df["gov_rev_gdp"] / 100
        ds_mn  = df["ds_total_usd"] / 1e6
        df["ds_revenues_pct"] = (ds_mn / rev_mn * 100).replace([np.inf, -np.inf], np.nan)

    # Debt service / exports (%)
    # Units: both in absolute USD → ratio is dimensionally consistent
    if {"ds_total_usd", "exports_wb_usd"}.issubset(df.columns):
        ds_exp = (df["ds_total_usd"] / df["exports_wb_usd"] * 100
                  ).replace([np.inf, -np.inf], np.nan)
        if "ds_exports_pct" not in df.columns:
            df["ds_exports_pct"] = ds_exp
        else:
            # Fill gaps only (WB direct series takes priority)
            mask = df["ds_exports_pct"].isna() & ds_exp.notna()
            df.loc[mask, "ds_exports_pct"] = ds_exp[mask]

    # PV of debt / GDP
    # Units: pv_debt_usd in absolute USD → /1e6 → USD mn; gdp_usd_mn in USD mn
    if {"pv_debt_usd", "gdp_usd_mn"}.issubset(df.columns):
        pv_mn = df["pv_debt_usd"] / 1e6
        df["pv_debt_gdp"] = (pv_mn / df["gdp_usd_mn"] * 100).replace([np.inf, -np.inf], np.nan)

    # PV of debt / exports (%)
    # Units: both in absolute USD → ratio is dimensionally consistent
    if {"pv_debt_usd", "exports_wb_usd"}.issubset(df.columns):
        pv_exp = (df["pv_debt_usd"] / df["exports_wb_usd"] * 100
                  ).replace([np.inf, -np.inf], np.nan)
        if "pv_debt_exports" not in df.columns:
            df["pv_debt_exports"] = pv_exp
        else:
            # Fill gaps only (WB direct series DT.DOD.PVLX.EX.ZS takes priority)
            mask = df["pv_debt_exports"].isna() & pv_exp.notna()
            df.loc[mask, "pv_debt_exports"] = pv_exp[mask]

    return df


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Debt dynamics projection (years 6–10 beyond WEO horizon)
# ─────────────────────────────────────────────────────────────────────────────

def _ratio_from_hist(df: pd.DataFrame, num_col: str, den_col: str,
                     hist_years: list, n_avg: int = 3) -> float | None:
    """
    Compute the average ratio num/den over the most recent n_avg available years.
    Returns None if no data.
    """
    rows = []
    for yr in sorted(hist_years, reverse=True):
        if yr not in df.index:
            continue
        n = df.loc[yr, num_col] if num_col in df.columns else np.nan
        d = df.loc[yr, den_col] if den_col in df.columns else np.nan
        if pd.isna(n) or pd.isna(d) or d == 0:
            continue
        rows.append(n / d)
        if len(rows) >= n_avg:
            break
    return float(np.mean(rows)) if rows else None


def project_debt_dynamics(df: pd.DataFrame, base_year: int) -> pd.DataFrame:
    """
    Extend macro variables beyond the WEO 5-year horizon (projection years 6–10)
    AND fill external debt variables for the full projection window (base+1 to base+10)
    using historical ratio-based projections when WB data is unavailable.

    Fills:
      Fiscal/macro: gdp_growth, gdp_deflator, pbal_gdp, gov_rev_gdp, pub_debt_gdp, gdp_usd
      External:     exports_wb_usd, ppg_debt_usd, pv_debt_usd, ds_total_usd
      Ratios:       pv_debt_gdp, pv_debt_exports, ds_exports_pct, ds_revenues_pct
    """
    df      = df.copy()
    weo_end = base_year + 5
    proj_end = base_year + 10

    # ── Ensure all projection rows exist ─────────────────────────────────────
    for yr in range(base_year + 1, proj_end + 1):
        if yr not in df.index:
            df.loc[yr] = np.nan

    hist_years = [y for y in df.index if y <= base_year]

    # ── Long-run fiscal anchors ───────────────────────────────────────────────
    def _lt(col, default, lo, hi):
        vals = df.loc[df.index <= base_year, col].dropna() if col in df.columns else pd.Series()
        v = float(vals.mean()) if not vals.empty else default
        return max(min(v, hi), lo)

    lt_g   = _lt("gdp_growth",  3.5,  0.5,  8.0)
    lt_pi  = _lt("gdp_deflator",2.5,  1.0, 10.0)
    lt_pb  = _lt("pbal_gdp",   -2.0, -8.0,  5.0)
    lt_rev = _lt("gov_rev_gdp", 20.0, 10.0, 40.0)

    # ── Historical external-debt ratios (for projection baseline) ─────────────
    # Use ratios relative to GDP to project external debt stocks forward
    ppg_gdp_ratio  = _ratio_from_hist(df, "ppg_debt_usd",  "gdp_usd_mn", hist_years)  # PPG debt / GDP (USD)
    pv_ppg_ratio   = _ratio_from_hist(df, "pv_debt_usd",   "ppg_debt_usd", hist_years)  # PV / nominal PPG
    ds_ppg_ratio   = _ratio_from_hist(df, "ds_total_usd",  "ppg_debt_usd", hist_years)  # DS / nominal PPG
    exp_gdp_ratio  = _ratio_from_hist(df, "exports_wb_usd","gdp_usd_mn", hist_years)   # Exports / GDP (USD)
    remit_last     = df.loc[df.index <= base_year, "remittances_gdp"].dropna().tail(3).mean() \
                     if "remittances_gdp" in df.columns else np.nan
    res_last       = df.loc[df.index <= base_year, "reserves_months"].dropna().tail(3).mean() \
                     if "reserves_months" in df.columns else np.nan

    # ── Project all years base+1 … base+10 ───────────────────────────────────
    for yr in range(base_year + 1, proj_end + 1):
        n       = yr - weo_end
        blend   = min(max(n, 0) / 5.0, 1.0)   # 0 for WEO years, up to 1 for yr+10
        yr_prev = yr - 1

        def _cv(col, lt):
            v = df.loc[yr, col] if col in df.columns and yr in df.index else np.nan
            return v if not pd.isna(v) else lt

        def _weo_v(col, lt):
            v = df.loc[weo_end, col] if (weo_end in df.index and col in df.columns) else lt
            return v if not pd.isna(v) else lt

        def _prev(col):
            v = df.loc[yr_prev, col] if (yr_prev in df.index and col in df.columns) else np.nan
            return v if not pd.isna(v) else None

        # ── Macro / fiscal ───────────────────────────────────────────────────
        if yr > weo_end:
            if "gdp_growth" in df.columns and pd.isna(df.loc[yr, "gdp_growth"]):
                df.loc[yr, "gdp_growth"] = (1 - blend) * _weo_v("gdp_growth", lt_g) + blend * lt_g

            if "gdp_deflator" in df.columns and pd.isna(df.loc[yr, "gdp_deflator"]):
                df.loc[yr, "gdp_deflator"] = lt_pi

            if "pbal_gdp" in df.columns and pd.isna(df.loc[yr, "pbal_gdp"]):
                df.loc[yr, "pbal_gdp"] = (1 - blend) * _weo_v("pbal_gdp", lt_pb) + blend * lt_pb

            if "gov_rev_gdp" in df.columns and pd.isna(df.loc[yr, "gov_rev_gdp"]):
                df.loc[yr, "gov_rev_gdp"] = lt_rev

            # Public debt accumulation identity
            if "pub_debt_gdp" in df.columns:
                d_prev = _prev("pub_debt_gdp")
                if d_prev is not None:
                    g   = _cv("gdp_growth",   lt_g)  / 100
                    pi_ = _cv("gdp_deflator", lt_pi) / 100
                    pb  = _cv("pbal_gdp",     lt_pb)
                    r   = 0.04
                    df.loc[yr, "pub_debt_gdp"] = (1 + r) / ((1 + g) * (1 + pi_)) * d_prev - pb

            # GDP in USD (nominal growth)
            if "gdp_usd" in df.columns and pd.isna(df.loc[yr, "gdp_usd"]):
                prev_gdp = _prev("gdp_usd")
                if prev_gdp is not None:
                    g   = _cv("gdp_growth",   lt_g)  / 100
                    pi_ = _cv("gdp_deflator", lt_pi) / 100
                    df.loc[yr, "gdp_usd"]    = prev_gdp * (1 + g) * (1 + pi_)
                    df.loc[yr, "gdp_usd_mn"] = df.loc[yr, "gdp_usd"] * 1e3

        # ── Auxiliary external variables (fill for ALL projection years) ──────
        # These are WB data so unavailable for projections — fill from ratios

        # Nominal growth factor for this year
        g_yr   = _cv("gdp_growth",   lt_g) / 100
        pi_yr  = _cv("gdp_deflator", lt_pi) / 100
        nom_g  = (1 + g_yr) * (1 + pi_yr)

        gdp_mn = _cv("gdp_usd_mn", None)
        if gdp_mn is None or pd.isna(gdp_mn):
            gdp_mn = None

        # Exports (USD mn): grow with nominal GDP
        if "exports_wb_usd" in df.columns and pd.isna(df.loc[yr, "exports_wb_usd"]):
            prev_exp = _prev("exports_wb_usd")
            if prev_exp is not None:
                df.loc[yr, "exports_wb_usd"] = prev_exp * nom_g
            elif exp_gdp_ratio and gdp_mn:
                df.loc[yr, "exports_wb_usd"] = exp_gdp_ratio * gdp_mn

        # Imports (USD mn): grow with nominal GDP
        if "imports_wb_usd" in df.columns and pd.isna(df.loc[yr, "imports_wb_usd"]):
            prev_imp = _prev("imports_wb_usd")
            if prev_imp is not None:
                df.loc[yr, "imports_wb_usd"] = prev_imp * nom_g

        # Remittances (% GDP): hold at recent average
        if "remittances_gdp" in df.columns and pd.isna(df.loc[yr, "remittances_gdp"]):
            if not pd.isna(remit_last):
                df.loc[yr, "remittances_gdp"] = remit_last

        # Reserves (months imports): hold at recent average
        if "reserves_months" in df.columns and pd.isna(df.loc[yr, "reserves_months"]):
            if not pd.isna(res_last):
                df.loc[yr, "reserves_months"] = res_last

        # PPG external debt stock (USD mn): grow at nominal GDP rate
        if "ppg_debt_usd" in df.columns and pd.isna(df.loc[yr, "ppg_debt_usd"]):
            prev_ppg = _prev("ppg_debt_usd")
            if prev_ppg is not None:
                df.loc[yr, "ppg_debt_usd"] = prev_ppg * nom_g
            elif ppg_gdp_ratio and gdp_mn:
                df.loc[yr, "ppg_debt_usd"] = ppg_gdp_ratio * gdp_mn

        # PV of PPG external debt (USD mn): pv_ppg_ratio × nominal PPG
        if "pv_debt_usd" in df.columns and pd.isna(df.loc[yr, "pv_debt_usd"]):
            ppg_yr = df.loc[yr, "ppg_debt_usd"] if "ppg_debt_usd" in df.columns else np.nan
            if not pd.isna(ppg_yr) and pv_ppg_ratio:
                df.loc[yr, "pv_debt_usd"] = pv_ppg_ratio * ppg_yr

        # Total debt service (USD mn): ds_ppg_ratio × nominal PPG
        if "ds_total_usd" in df.columns and pd.isna(df.loc[yr, "ds_total_usd"]):
            ppg_yr = df.loc[yr, "ppg_debt_usd"] if "ppg_debt_usd" in df.columns else np.nan
            if not pd.isna(ppg_yr) and ds_ppg_ratio:
                df.loc[yr, "ds_total_usd"] = ds_ppg_ratio * ppg_yr

        # ── Recompute ratio columns ──────────────────────────────────────────
        # Note on units:
        #   WB debt/export series are in ABSOLUTE current USD (e.g., 21_633_233_308 for $21.6bn)
        #   gdp_usd_mn is in MILLIONS of USD (e.g., 32_850 for $32.85bn GDP)
        #   → Convert WB series to millions (*1e-6) before dividing by gdp_usd_mn
        #   → PV/Exports and DS/Exports are both in absolute USD → ratio is fine as-is
        gdp_mn_yr = df.loc[yr, "gdp_usd_mn"] if "gdp_usd_mn" in df.columns else np.nan
        pv_usd_yr = df.loc[yr, "pv_debt_usd"] if "pv_debt_usd" in df.columns else np.nan
        ds_usd_yr = df.loc[yr, "ds_total_usd"] if "ds_total_usd" in df.columns else np.nan
        exp_usd_yr = df.loc[yr, "exports_wb_usd"] if "exports_wb_usd" in df.columns else np.nan

        # PV debt / GDP (%): convert PV (absolute USD) → millions first
        if "pv_debt_gdp" not in df.columns:
            df["pv_debt_gdp"] = np.nan
        if pd.isna(df.loc[yr, "pv_debt_gdp"]) and not pd.isna(pv_usd_yr) and not pd.isna(gdp_mn_yr) and gdp_mn_yr > 0:
            pv_mn = pv_usd_yr / 1e6          # absolute USD → USD millions
            df.loc[yr, "pv_debt_gdp"] = pv_mn / gdp_mn_yr * 100

        # PV debt / Exports (%): both in absolute USD → ratio is dimensionally consistent
        if "pv_debt_exports" not in df.columns:
            df["pv_debt_exports"] = np.nan
        if pd.isna(df.loc[yr, "pv_debt_exports"]) and not pd.isna(pv_usd_yr) and not pd.isna(exp_usd_yr) and exp_usd_yr > 0:
            df.loc[yr, "pv_debt_exports"] = pv_usd_yr / exp_usd_yr * 100

        # DS / Exports (%): both in absolute USD → dimensionally consistent
        if "ds_exports_pct" not in df.columns:
            df["ds_exports_pct"] = np.nan
        if pd.isna(df.loc[yr, "ds_exports_pct"]) and not pd.isna(ds_usd_yr) and not pd.isna(exp_usd_yr) and exp_usd_yr > 0:
            df.loc[yr, "ds_exports_pct"] = ds_usd_yr / exp_usd_yr * 100

        # DS / Revenue (%): convert DS (absolute USD) → millions, revenue from GDP (millions)
        if "ds_revenues_pct" not in df.columns:
            df["ds_revenues_pct"] = np.nan
        rev_pct = _cv("gov_rev_gdp", lt_rev)
        if pd.isna(df.loc[yr, "ds_revenues_pct"]) and not pd.isna(ds_usd_yr) and not pd.isna(gdp_mn_yr) and rev_pct > 0:
            ds_mn  = ds_usd_yr / 1e6          # absolute USD → USD millions
            rev_mn = gdp_mn_yr * rev_pct / 100  # already in millions
            if rev_mn > 0:
                df.loc[yr, "ds_revenues_pct"] = ds_mn / rev_mn * 100

    return df.sort_index()


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Top-level pipeline function
# ─────────────────────────────────────────────────────────────────────────────

def fetch_all_data(iso3: str, iso2: str, base_year: int) -> tuple:
    """
    Fetch all data needed for DSA.
    Returns: (weo_data, wb_data, world_growth)
    """
    weo_data     = fetch_weo_country(iso3)
    wb_data      = fetch_wb_debt(iso2)
    world_growth = fetch_world_growth()
    return weo_data, wb_data, world_growth


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Data Explorer — multi-country WEO + World Bank helpers
# ─────────────────────────────────────────────────────────────────────────────

# Human-readable labels for every WEO concept code in the latest release
WEO_CATALOG: dict[str, str] = {
    # ── National accounts ────────────────────────────────────────────────────
    "NGDPD":       "GDP, Current Prices (USD bn)",
    "NGDP":        "GDP, Current Prices (Nat. Currency bn)",
    "NGDP_R":      "GDP, Constant Prices (Nat. Currency bn)",
    "NGDP_RPCH":   "Real GDP Growth (%)",
    "NGDP_D":      "GDP Deflator Index (2000 = 100)",
    "NGDP_FY":     "GDP, Fiscal Year (Nat. Currency)",
    "NGDPDPC":     "GDP per Capita, Current Prices (USD)",
    "NGDPPC":      "GDP per Capita, Current Prices (Nat. Currency)",
    "NGDPRPC":     "GDP per Capita, Constant Prices (Nat. Currency)",
    "NGDPRPPPPC":  "GDP per Capita, PPP (Intl. $)",
    "PPPGDP":      "GDP, PPP (Intl. $ bn)",
    "PPPPC":       "GDP per Capita, PPP (Intl. $)",
    "PPPSH":       "GDP Share of World PPP (%)",
    "PPPEX":       "Implied PPP Conversion Rate (Nat. Currency / Intl. $)",
    "NID_NGDP":    "Total Investment (% GDP)",
    "NGSD_NGDP":   "Gross National Savings (% GDP)",
    # ── Inflation & prices ───────────────────────────────────────────────────
    "PCPIPCH":     "CPI Inflation, Average (%)",
    "PCPIEPCH":    "CPI Inflation, End of Year (%)",
    "PCPI":        "Consumer Price Index (2016 = 100)",
    "PCPIE":       "Consumer Price Index, End of Period (2016 = 100)",
    # ── Government finance ───────────────────────────────────────────────────
    "GGR_NGDP":    "Govt Revenue (% GDP)",
    "GGX_NGDP":    "Govt Total Expenditure (% GDP)",
    "GGXCNL_NGDP": "Govt Net Lending / Borrowing (% GDP)",
    "GGXONLB_NGDP":"Govt Primary Balance (% GDP)",
    "GGXWDG_NGDP": "Govt Gross Debt (% GDP)",
    "GGSB":        "Govt Structural Balance (% Potential GDP)",
    "GGR":         "Govt Revenue (Nat. Currency bn)",
    "GGX":         "Govt Total Expenditure (Nat. Currency bn)",
    "GGXCNL":      "Govt Net Lending / Borrowing (Nat. Currency bn)",
    "GGXONLB":     "Govt Primary Balance (Nat. Currency bn)",
    "GGXWDG":      "Govt Gross Debt (Nat. Currency bn)",
    # ── External sector ──────────────────────────────────────────────────────
    "BCA":         "Current Account Balance (USD bn)",
    "BCA_NGDPD":   "Current Account Balance (% GDP)",
    "TM_RPCH":     "Import Volume Growth (%)",
    "TMG_RPCH":    "Import Volume of Goods Growth (%)",
    "TX_RPCH":     "Export Volume Growth (%)",
    "TXG_RPCH":    "Export Volume of Goods Growth (%)",
    # ── Demographics & labour ────────────────────────────────────────────────
    "LP":          "Population (millions)",
    "LUR":         "Unemployment Rate (%)",
}

# Curated World Bank indicators with human-readable labels
WB_EXPLORER_CATALOG: dict[str, str] = {
    # ── External debt ────────────────────────────────────────────────────────
    "DT.DOD.DPPG.CD":      "PPG External Debt Stock (current USD)",
    "DT.DOD.PVLX.CD":      "PV of External Debt (current USD)",
    "DT.TDS.DPPG.CD":      "PPG Debt Service Paid (current USD)",
    "DT.DOD.PVLX.EX.ZS":  "PV of Debt / Exports (%)",
    "DT.DOD.PVLX.GN.ZS":  "PV of Debt / GNI (%)",
    "DT.TDS.DPPG.EX.ZS":  "Debt Service / Exports (%)",
    "DT.INT.DPPG.CD":      "PPG Interest Payments (current USD)",
    "DT.AMT.DPPG.CD":      "PPG Principal Repayments (current USD)",
    # ── Macro ────────────────────────────────────────────────────────────────
    "NY.GDP.MKTP.CD":      "GDP, Current Prices (current USD)",
    "NY.GDP.MKTP.KD.ZG":  "GDP Growth Rate (%)",
    "NY.GDP.PCAP.CD":      "GDP per Capita (current USD)",
    "FP.CPI.TOTL.ZG":     "CPI Inflation (%)",
    "GC.REV.XGRT.GD.ZS":  "Govt Revenue excl. Grants (% GDP)",
    "GC.DOD.TOTL.GD.ZS":  "Central Govt Debt (% GDP)",
    "BN.CAB.XOKA.GD.ZS":  "Current Account Balance (% GDP)",
    # ── External flows ───────────────────────────────────────────────────────
    "BX.GSR.GNFS.CD":      "Exports of Goods & Services (current USD)",
    "BM.GSR.GNFS.CD":      "Imports of Goods & Services (current USD)",
    "BX.TRF.PWKR.DT.GD.ZS": "Personal Remittances Received (% GDP)",
    "BX.KLT.DINV.WD.GD.ZS": "FDI Net Inflows (% GDP)",
    "FI.RES.TOTL.MO":     "Total Reserves (months of imports)",
    "FI.RES.TOTL.CD":     "Total Reserves (current USD)",
    # ── Social ───────────────────────────────────────────────────────────────
    "SP.POP.TOTL":         "Population, Total",
    "SP.POP.GROW":         "Population Growth (%)",
    "SI.POV.DDAY":         "Poverty Headcount at $2.15/day (% pop.)",
    "SH.XPD.CHEX.GD.ZS":  "Current Health Expenditure (% GDP)",
    "SE.XPD.TOTL.GD.ZS":  "Govt Expenditure on Education (% GDP)",
    # ── CPIA ─────────────────────────────────────────────────────────────────
    "IQ.CPA.ECON.XQ":     "CPIA — Economic Management (score 1–6)",
    "IQ.CPA.STRC.XQ":     "CPIA — Structural Policies (score 1–6)",
    "IQ.CPA.POLS.XQ":     "CPIA — Social Inclusion & Equity (score 1–6)",
    "IQ.CPA.PUBS.XQ":     "CPIA — Public Sector Management (score 1–6)",
}

# IDS (International Debt Statistics) — curated catalog served by the WB v2 API.
# A small subset (~19) of the full IDS universe is accessible via the standard
# REST endpoint without special parameters.
IDS_CATALOG: dict[str, str] = {
    "DT.DOD.DECT.CD":     "External Debt Stocks, Total (current USD)",
    "DT.DOD.DECT.GN.ZS":  "External Debt / GNI (%)",
    "DT.DOD.DLXF.CD":     "Long-Term External Debt Stock (current USD)",
    "DT.DOD.DPPG.CD":     "PPG External Debt Stock (current USD)",
    "DT.DOD.DSTC.CD":     "Short-Term Debt, Total (current USD)",
    "DT.DOD.DSTC.ZS":     "Short-Term Debt / Total External Debt (%)",
    "DT.DOD.MIDA.CD":     "PPG Debt — IDA Credits & Grants (current USD)",
    "DT.DOD.MIBR.CD":     "PPG Debt — IBRD (current USD)",
    "DT.DOD.DIMF.CD":     "PPG Debt — IMF Credit Outstanding (current USD)",
    "DT.DOD.PVLX.CD":     "PV of External PPG Debt (current USD)",
    "DT.DOD.PVLX.EX.ZS":  "PV of Debt / Exports (%)",
    "DT.DOD.PVLX.GN.ZS":  "PV of Debt / GNI (%)",
    "DT.TDS.DECT.CD":     "Total Debt Service Paid (current USD)",
    "DT.TDS.DECT.EX.ZS":  "Total Debt Service / Exports (%)",
    "DT.TDS.DECT.GN.ZS":  "Total Debt Service / GNI (%)",
    "DT.TDS.DPPG.CD":     "PPG Debt Service Paid (current USD)",
    "DT.TDS.DPPG.GN.ZS":  "PPG Debt Service / GNI (%)",
    "DT.TDS.MLAT.CD":     "Debt Service — Multilateral Creditors (current USD)",
    "DT.TDS.DIMF.CD":     "Debt Service — IMF (current USD)",
}

# ─────────────────────────────────────────────────────────────────────────────
# IDS Bulk — full creditor-level catalog (served from bulk Excel download)
# ─────────────────────────────────────────────────────────────────────────────

# Curated selection of the 572 series available in the full IDS bulk file.
# Grouped logically for the Explorer UI.
# Flat lookup: code → label  (auto-built from grouped structure below)
IDS_BULK_CATALOG: dict[str, str] = {}

# Grouped structure: category → {code: label}
# Used to build the grouped multiselect in the Explorer.
IDS_BULK_CATALOG_GROUPED: dict[str, dict[str, str]] = {
    "📊 Total External Debt Stocks": {
        "DT.DOD.DECT.CD":    "External Debt, Total (current USD)",
        "DT.DOD.DECT.GN.ZS": "External Debt / GNI (%)",
        "DT.DOD.DECT.EX.ZS": "External Debt / Exports (%)",
        "DT.DOD.DECT.PC.CD": "External Debt per Capita (USD)",
        "DT.DOD.DLXF.CD":    "Long-Term External Debt (current USD)",
        "DT.DOD.DPPG.CD":    "PPG External Debt, Total (current USD)",
        "DT.DOD.DSTC.CD":    "Short-Term External Debt (current USD)",
        "DT.DOD.DSTC.ZS":    "Short-Term Debt / Total External Debt (%)",
    },
    "🏦 By Creditor Type (PPG Stocks)": {
        "DT.DOD.OFFT.CD":    "Official Creditors, Total (current USD)",
        "DT.DOD.BLAT.CD":    "Bilateral Creditors (current USD)",
        "DT.DOD.MLAT.CD":    "Multilateral Creditors (current USD)",
        "DT.DOD.MLAT.ZS":    "Multilateral Debt / Total External Debt (%)",
        "DT.DOD.PRVT.CD":    "Private Creditors, Total (current USD)",
        "DT.DOD.PBND.CD":    "Bonds (current USD)",
        "DT.DOD.PCBK.CD":    "Commercial Banks (current USD)",
        "DT.DOD.PROP.CD":    "Other Private Creditors (current USD)",
    },
    "🟢 Concessional Debt": {
        "DT.DOD.ALLC.CD":    "Concessional Debt, Total (current USD)",
        "DT.DOD.ALLC.ZS":    "Concessional Debt / Total External Debt (%)",
        "DT.DOD.BLTC.CD":    "Bilateral Concessional (current USD)",
        "DT.DOD.MLTC.CD":    "Multilateral Concessional (current USD)",
    },
    "🏛️ By Multilateral Institution": {
        "DT.DOD.MIDA.CD":    "IDA Credits & Grants (current USD)",
        "DT.DOD.MIBR.CD":    "IBRD (current USD)",
        "DT.DOD.DIMF.CD":    "IMF Credit & SDR Allocations (current USD)",
    },
    "📉 PV of Debt": {
        "DT.DOD.PVLX.CD":    "PV of External Debt (current USD)",
        "DT.DOD.PVLX.EX.ZS": "PV of Debt / Exports (%)",
        "DT.DOD.PVLX.GN.ZS": "PV of Debt / GNI (%)",
    },
    "💳 Total Debt Service": {
        "DT.TDS.DECT.CD":    "Total Debt Service (current USD)",
        "DT.TDS.DECT.EX.ZS": "Total Debt Service / Exports (%)",
        "DT.TDS.DECT.GN.ZS": "Total Debt Service / GNI (%)",
        "DT.TDS.DPPG.CD":    "PPG Debt Service (current USD)",
    },
    "💳 Debt Service by Creditor": {
        "DT.TDS.OFFT.CD":    "Debt Service — Official Creditors (current USD)",
        "DT.TDS.BLAT.CD":    "Debt Service — Bilateral (current USD)",
        "DT.TDS.MLAT.CD":    "Debt Service — Multilateral (current USD)",
        "DT.TDS.PRVT.CD":    "Debt Service — Private Creditors (current USD)",
        "DT.TDS.PBND.CD":    "Debt Service — Bonds (current USD)",
        "DT.TDS.PCBK.CD":    "Debt Service — Commercial Banks (current USD)",
    },
    "📥 Disbursements": {
        "DT.DIS.DPPG.CD":    "Disbursements, PPG Total (current USD)",
        "DT.DIS.OFFT.CD":    "Disbursements — Official Creditors (current USD)",
        "DT.DIS.BLAT.CD":    "Disbursements — Bilateral (current USD)",
        "DT.DIS.MLAT.CD":    "Disbursements — Multilateral (current USD)",
        "DT.DIS.PRVT.CD":    "Disbursements — Private Creditors (current USD)",
        "DT.DIS.PBND.CD":    "Disbursements — Bonds (current USD)",
        "DT.DIS.PCBK.CD":    "Disbursements — Commercial Banks (current USD)",
        "DT.DIS.MIDA.CD":    "Disbursements — IDA (current USD)",
    },
    "🔢 Interest & Principal": {
        "DT.INT.DECT.CD":    "Interest on External Debt, Total (current USD)",
        "DT.INT.DPPG.CD":    "Interest — PPG (current USD)",
        "DT.INT.BLAT.CD":    "Interest — Bilateral (current USD)",
        "DT.INT.MLAT.CD":    "Interest — Multilateral (current USD)",
        "DT.AMT.DPPG.CD":    "Principal Repayments, PPG (current USD)",
        "DT.AMT.BLAT.CD":    "Principal — Bilateral (current USD)",
        "DT.AMT.MLAT.CD":    "Principal — Multilateral (current USD)",
    },
}

# Populate flat catalog from grouped structure
for _cat_items in IDS_BULK_CATALOG_GROUPED.values():
    IDS_BULK_CATALOG.update(_cat_items)


@st.cache_data(ttl=86400, show_spinner=False)   # 24h — IDS bulk file updated annually
def fetch_ids_bulk() -> pd.DataFrame:
    """
    Download the full IDS dataset from World Bank DataBank as an Excel ZIP (~26 MB).
    Returns long-format DataFrame with columns: iso3, series_code, year (int), value (float).
    Cached 24 hours — the source file is only updated once a year.
    """
    import zipfile
    import io as _io

    url = "https://databank.worldbank.org/data/download/IDS_Excel.zip"
    try:
        resp = session.get(url, timeout=120)
        resp.raise_for_status()
    except Exception as e:
        st.warning(f"⚠️ Could not download IDS bulk file: {e}")
        return pd.DataFrame(columns=["iso3", "series_code", "year", "value"])

    z        = zipfile.ZipFile(_io.BytesIO(resp.content))
    df_wide  = pd.read_excel(z.open("IDS_ALLCountries.xlsx"), sheet_name=0, engine="openpyxl")

    id_cols   = ["Country Code", "Series Code"]
    year_cols = [c for c in df_wide.columns if isinstance(c, int) and 1990 <= c <= 2024]

    long = (
        df_wide[id_cols + year_cols]
        .melt(id_vars=id_cols, var_name="year", value_name="value")
        .rename(columns={"Country Code": "iso3", "Series Code": "series_code"})
    )
    long["year"]  = long["year"].astype(int)
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long.dropna(subset=["value"]).reset_index(drop=True)
    return long


def query_ids_bulk(
    iso3_list:    list[str],
    series_codes: list[str],
    start:        int = 2000,
    end:          int = 2024,
    name_map:     dict | None = None,   # {iso3: display_name}
    series_labels:dict | None = None,   # {series_code: human label}
) -> pd.DataFrame:
    """
    Query the cached IDS bulk dataset.

    Returns wide DataFrame: index = Year (int).
    Columns are:
      - Just country display name when a single series is requested.
      - "Country — Short Series Label" when multiple series are requested.
    """
    df_long = fetch_ids_bulk()
    if df_long.empty:
        return pd.DataFrame()

    mask = (
        df_long["iso3"].isin(iso3_list) &
        df_long["series_code"].isin(series_codes) &
        (df_long["year"] >= start) &
        (df_long["year"] <= end)
    )
    sub = df_long[mask].copy()
    if sub.empty:
        return pd.DataFrame()

    single = len(series_codes) == 1

    def _cname(iso3: str) -> str:
        return (name_map or {}).get(iso3, iso3)

    def _sname(code: str) -> str:
        lbl = (series_labels or IDS_BULK_CATALOG).get(code, code)
        return lbl.split("(")[0].strip()   # drop "(current USD)" etc.

    if single:
        sub["col"] = sub["iso3"].map(_cname)
    else:
        sub["col"] = sub["iso3"].map(_cname) + " — " + sub["series_code"].map(_sname)

    wide = sub.pivot_table(index="year", columns="col", values="value", aggfunc="first")
    wide.index.name   = "Year"
    wide.columns.name = None
    return wide.sort_index()


@st.cache_data(ttl=21600, show_spinner=False)
def get_weo_available_countries() -> dict[str, str]:
    """
    Return {display_name: iso3_code} for every country/group in the WEO dataset,
    sorted alphabetically.  Names sourced from LIC_COUNTRIES metadata first,
    then a supplementary map of major economies and WEO regional aggregates.
    """
    from modules.country_meta import LIC_COUNTRIES

    lic_iso3_to_name: dict[str, str] = {v["iso3"]: name for name, v in LIC_COUNTRIES.items()}

    EXTRA: dict[str, str] = {
        # Major economies
        "ALB": "Albania",         "AGO": "Angola",          "ARG": "Argentina",
        "ARM": "Armenia",         "AUS": "Australia",        "AZE": "Azerbaijan",
        "BLR": "Belarus",         "BRA": "Brazil",           "BGR": "Bulgaria",
        "CHL": "Chile",           "CHN": "China",            "COL": "Colombia",
        "HRV": "Croatia",         "CZE": "Czech Republic",   "EGY": "Egypt",
        "SLV": "El Salvador",     "EST": "Estonia",          "DEU": "Germany",
        "GHA": "Ghana",           "GTM": "Guatemala",        "HUN": "Hungary",
        "IDN": "Indonesia",       "IRN": "Iran",             "IRQ": "Iraq",
        "ISR": "Israel",          "ITA": "Italy",            "JPN": "Japan",
        "JOR": "Jordan",          "KAZ": "Kazakhstan",       "KEN": "Kenya",
        "KOR": "Korea, Rep.",     "KWT": "Kuwait",           "LVA": "Latvia",
        "LBN": "Lebanon",         "LBY": "Libya",            "LTU": "Lithuania",
        "MYS": "Malaysia",        "MEX": "Mexico",           "MAR": "Morocco",
        "NAM": "Namibia",         "NGA": "Nigeria",          "NOR": "Norway",
        "OMN": "Oman",            "PAK": "Pakistan",         "PAN": "Panama",
        "PRY": "Paraguay",        "PER": "Peru",             "PHL": "Philippines",
        "POL": "Poland",          "PRT": "Portugal",         "ROU": "Romania",
        "RUS": "Russia",          "SAU": "Saudi Arabia",     "SRB": "Serbia",
        "ZAF": "South Africa",    "ESP": "Spain",            "LKA": "Sri Lanka",
        "SDN": "Sudan",           "SWE": "Sweden",           "CHE": "Switzerland",
        "THA": "Thailand",        "TUN": "Tunisia",          "TUR": "Turkey",
        "UKR": "Ukraine",         "ARE": "United Arab Emirates",
        "GBR": "United Kingdom",  "USA": "United States",    "URY": "Uruguay",
        "VEN": "Venezuela",       "VNM": "Vietnam",          "YEM": "Yemen",
        "ZMB": "Zambia",          "ZWE": "Zimbabwe",
        # WEO aggregates
        "G001": "🌍 World",
        "G007": "G7 — Advanced Economies",
        "G020": "G20",
    }

    # LIC names override EXTRA where both exist
    combined: dict[str, str] = {**EXTRA, **lic_iso3_to_name}

    df    = _fetch_weo_raw()
    iso3s = df["REF_AREA_CODE"].dropna().unique()

    result = {}
    for iso3 in iso3s:
        result[combined.get(iso3, iso3)] = iso3   # fallback: show ISO3 as name

    return dict(sorted(result.items()))


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_weo_explorer(
    iso3_tuple:   tuple,
    concept_code: str,
    start_year:   int,
    end_year:     int,
    name_map:     tuple | None = None,   # tuple of (iso3, display_name) pairs
) -> pd.DataFrame:
    """
    Fetch one WEO concept for multiple countries.
    Returns wide DataFrame: index = Year (int), columns = ISO3 or display_name.
    All args must be hashable (tuples) so @st.cache_data works.
    """
    df  = _fetch_weo_raw()
    sub = df[
        df["REF_AREA_CODE"].isin(iso3_tuple) &
        (df["CONCEPT_CODE"] == concept_code)  &
        (df["TIME_PERIOD"]  >= start_year)    &
        (df["TIME_PERIOD"]  <= end_year)
    ]
    if sub.empty:
        return pd.DataFrame()
    wide = sub.pivot_table(index="TIME_PERIOD", columns="REF_AREA_CODE", values="OBS_VALUE")
    wide.index.name   = "Year"
    wide.columns.name = None
    if name_map:
        wide = wide.rename(columns=dict(name_map))
    return wide.sort_index()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_wb_explorer(
    iso2_tuple: tuple,
    wb_code:    str,
    start_year: int,
    end_year:   int,
    name_map:   tuple | None = None,   # tuple of (iso2, display_name) pairs
) -> pd.DataFrame:
    """
    Fetch one World Bank indicator for multiple countries.
    Returns wide DataFrame: index = Year (int), columns = ISO2 or display_name.
    Works for both WDI and IDS-family DT.* indicators via the standard v2 endpoint.
    """
    result: dict[str, pd.Series] = {}
    for iso2 in iso2_tuple:
        s = fetch_wb_indicator(iso2, wb_code, start=start_year, end=end_year)
        if not s.empty:
            result[iso2] = s
    if not result:
        return pd.DataFrame()
    wide = pd.DataFrame(result)
    wide.index.name = "Year"
    if name_map:
        wide = wide.rename(columns=dict(name_map))
    return wide.sort_index()


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Country MoF / Statistics Office links
# ─────────────────────────────────────────────────────────────────────────────

def get_country_mof_url(country_name: str) -> dict:
    MOF_URLS = {
        "Senegal": {
            # ── Fiscal & budget data ──────────────────────────────────────────
            "mof":          "https://www.finances.gouv.sn",
            "mof_label":    "Ministère des Finances et du Budget — Homepage",
            # Official enacted Finance Law 2025 (Loi n°2025-02)
            "budget_law":   "https://www.finances.gouv.sn/publication/loi-n2025-02-portant-loi-de-finances-pour-lannee-2025/",
            "budget_label": "Loi n°2025-02 — Loi de Finances pour l'année 2025 (revenues, expenditures, debt ceiling)",
            # Rectifying Finance Law 2025
            "lfr":          "https://www.finances.gouv.sn/publication/loi-de-finances-rectificative-lfr-2025/",
            "lfr_label":    "Loi de Finances Rectificative (LFR) 2025 (revised budget, updated public debt figures)",
            # All budget laws archive
            "laws_archive":  "https://www.finances.gouv.sn/catpub/lois-de-finances/",
            "laws_label":    "Archive — Lois de Finances & Règlements (all years)",
            # Medium-term fiscal framework
            "dpbep":        "https://www.finances.gouv.sn/ressources/documents",
            "dpbep_label":  "MoF Documents — DPPD, DPBEP, quarterly budget execution reports",
            # ── Statistics ───────────────────────────────────────────────────
            "stats":        "https://www.ansd.sn",
            "stats_label":  "ANSD — Agence Nationale de la Statistique et de la Démographie",
            "stats_pub":    "https://www.ansd.sn/publications",
            "stats_pub_label": "ANSD Publications (comptes nationaux, ESPS, NAS)",
            # ── Debt management ──────────────────────────────────────────────
            "debt":         "https://www.dpee.sn",
            "debt_label":   "DPEE — Direction de la Prévision et des Études Économiques",
            # ── IMF ──────────────────────────────────────────────────────────
            # Country page — lists all IMF publications for Senegal incl. program reviews
            "imf_country":  "https://www.imf.org/en/countries/sen",
            "imf_label":    "IMF — Senegal Country Page (staff reports, program reviews, DSA)",
            # Latest full country report with DSA (2023 — no standalone Article IV in 2024;
            # 2024 activity was EFF/ECF program review missions)
            "imf_article_iv": "https://www.imf.org/-/media/files/publications/cr/2023/english/1senea2023002.pdf",
            "imf_iv_label": "IMF Country Report No. 23/250 — Senegal (2023, incl. DSA appendix) [PDF]",
            # 2024 press release (program review, no full report published yet)
            "imf_2024":     "https://www.imf.org/en/news/articles/2024/09/12/pr24329-senegal-imf-staff-concludes-visit",
            "imf_2024_label": "IMF Press Release — September 2024 Mission to Senegal (EFF/ECF/RSF review)",
            # ── Notes ────────────────────────────────────────────────────────
            "notes": (
                "Revenue/GDP and fiscal balance: IMF WEO series GGR_NGDP & GGXONLB_NGDP. "
                "Public debt/GDP: IMF WEO GGXWDG_NGDP (significantly revised upward following Senegal's 2024 fiscal audit). "
                "External PPG debt stock, PV of debt, debt service: World Bank IDS API (DT.DOD.DPPG.CD, DT.DOD.PVLX.CD, DT.TDS.DPPG.CD). "
                "CPIA score: World Bank CPIA API (IQ.CPA.ECON/STRC/POLS/PUBS.XQ). "
                "Remittances (% GDP): World Bank WDI (BX.TRF.PWKR.DT.GD.ZS). "
                "Reserves: N/A — Senegal is a WAEMU member; reserves pooled at BCEAO."
            ),
        },
        "Kenya":      {"mof": "https://www.treasury.go.ke", "stats": "https://www.knbs.or.ke",
                        "notes": "Medium Term Debt Strategy published annually"},
        "Ghana":      {"mof": "https://www.mofep.gov.gh",   "stats": "https://statsghana.gov.gh",
                        "notes": "Annual Debt Management Report on MoF site"},
        "Tanzania":   {"mof": "https://www.mof.go.tz",      "stats": "https://www.nbs.go.tz",
                        "notes": "Government Budget Book and Annual Report"},
        "Rwanda":     {"mof": "https://www.minecofin.gov.rw","stats": "https://www.statistics.gov.rw"},
        "Ethiopia":   {"mof": "https://www.mofec.gov.et",   "stats": "https://www.csa.gov.et"},
        "Uganda":     {"mof": "https://www.finance.go.ug",  "stats": "https://www.ubos.org",
                        "notes": "Annual Debt Statistical Bulletin"},
        "Mozambique": {"mof": "https://www.mef.gov.mz",     "stats": "https://www.ine.gov.mz"},
        "Zambia":     {"mof": "https://www.mof.gov.zm",     "stats": "https://www.zamstats.gov.zm"},
        "Bangladesh": {"mof": "https://www.mof.gov.bd",     "stats": "https://www.bbs.gov.bd"},
        "Nigeria":    {"mof": "https://www.finance.gov.ng", "stats": "https://www.nigerianstat.gov.ng",
                        "notes": "DMO Quarterly Report on Public Debt"},
        "Cambodia":   {"mof": "https://www.mef.gov.kh",     "stats": "https://www.nis.gov.kh"},
    }
    return MOF_URLS.get(country_name, {
        "notes": "Use IMF Article IV / World Bank DSA reports for country-specific debt data.",
        "imf_article_iv": "https://www.imf.org/en/Publications/CR",
        "wb_dssi": "https://databank.worldbank.org/source/international-debt-statistics:-dssi",
    })
