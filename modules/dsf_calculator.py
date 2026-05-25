"""
LIC DSF Calculation Engine.
Implements the 2017 revised LIC DSF methodology:
  - Composite Indicator (CI) and country classification
  - External PPG debt thresholds
  - Public debt benchmark
  - Stress tests (standardized + tailored)
  - Mechanical risk signal → final risk rating
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Literal

from modules.country_meta import (
    CI_COEFFICIENTS,
    CI_CUTOFF_WEAK_MEDIUM,
    CI_CUTOFF_MEDIUM_STRONG,
    EXTERNAL_THRESHOLDS,
    PUBLIC_BENCHMARKS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CIResult:
    ci_score:       float
    classification: Literal["Weak", "Medium", "Strong"]
    cpia:           float
    avg_growth:     float
    avg_reserves:   float
    avg_remit:      float
    avg_world_g:    float
    contributions:  dict = field(default_factory=dict)


@dataclass
class ThresholdResult:
    indicator:      str
    value:          float
    threshold:      float
    breached:       bool
    pct_of_thresh:  float   # value as % of threshold (100 = at threshold)


@dataclass
class StressTestResult:
    name:           str
    scenario:       str
    indicators:     list[ThresholdResult]
    any_breach:     bool


@dataclass
class RiskRating:
    mechanical_signal:  Literal["Low", "Moderate", "High", "In Debt Distress"]
    final_rating:       Literal["Low", "Moderate", "High", "In Debt Distress"]
    granularity:        str | None          # For moderate: "Substantial" / "Some" / "Limited"
    baseline_breach:    bool
    stress_breach:      bool
    key_drivers:        list[str]
    in_distress:        bool


# ─────────────────────────────────────────────────────────────────────────────
# 1. Composite Indicator
# ─────────────────────────────────────────────────────────────────────────────

def compute_ci(
    cpia:         float,
    gdp_growth:   pd.Series,
    reserves:     pd.Series,
    remittances:  pd.Series,
    world_growth: pd.Series,
    base_year:    int,
) -> CIResult:
    """
    Compute the Composite Indicator using the LIC DSF probit coefficients.
    Window: 5 historical years + 5 projection years centred on base_year.
    CI = 0.385*CPIA + 0.02719*g + 0.04052*res − 0.03990*res² + 0.02022*rem + 0.13520*gw
    """
    c = CI_COEFFICIENTS
    window = list(range(base_year - 4, base_year + 6))   # 10-year window

    def _avg(series: pd.Series) -> float:
        s = series.reindex(window).dropna()
        return float(s.mean()) if not s.empty else 0.0

    g_avg   = _avg(gdp_growth)
    res_avg = _avg(reserves)
    rem_avg = _avg(remittances)
    gw_avg  = _avg(world_growth)

    ci = (
        c["cpia"]         * cpia
      + c["gdp_growth"]   * g_avg
      + c["reserves"]     * res_avg
      + c["reserves_sq"]  * (res_avg ** 2)
      + c["remittances"]  * rem_avg
      + c["world_growth"] * gw_avg
    )

    # Classification
    if ci < CI_CUTOFF_WEAK_MEDIUM:
        classification = "Weak"
    elif ci <= CI_CUTOFF_MEDIUM_STRONG:
        classification = "Medium"
    else:
        classification = "Strong"

    contributions = {
        "CPIA":          c["cpia"]        * cpia,
        "GDP Growth":    c["gdp_growth"]  * g_avg,
        "Reserves":      c["reserves"]    * res_avg + c["reserves_sq"] * res_avg**2,
        "Remittances":   c["remittances"] * rem_avg,
        "World Growth":  c["world_growth"]* gw_avg,
    }

    return CIResult(
        ci_score=round(ci, 3),
        classification=classification,
        cpia=cpia,
        avg_growth=g_avg,
        avg_reserves=res_avg,
        avg_remit=rem_avg,
        avg_world_g=gw_avg,
        contributions=contributions,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Compute Baseline Debt Indicators
# ─────────────────────────────────────────────────────────────────────────────

def _safe_div(num, den):
    if pd.isna(num) or pd.isna(den) or den == 0:
        return np.nan
    return float(num) / float(den)


def compute_external_indicators(df: pd.DataFrame, base_year: int, n_years: int = 10) -> pd.DataFrame:
    """
    Compute the 4 LIC DSF external PPG indicators over the projection horizon.
    Returns DataFrame with columns:
      pv_debt_gdp, pv_debt_exports, ds_exports, ds_revenues
    Indexed by year.
    """
    years = list(range(base_year + 1, base_year + n_years + 1))
    out   = pd.DataFrame(index=years, dtype=float)
    out.index.name = "year"

    for yr in years:
        if yr not in df.index:
            continue
        row = df.loc[yr]

        # GDP in USD millions
        gdp_mn = _safe_val(row, "gdp_usd_mn")
        if gdp_mn is None:
            gdp_mn = _safe_val(row, "gdp_usd_wb")
            if gdp_mn:
                gdp_mn /= 1e6   # WB gives USD absolute

        # Exports (USD millions)
        exp_mn = _safe_val(row, "exports_wb_usd")
        if exp_mn and exp_mn > 1e8:   # probably in USD, convert to millions
            exp_mn /= 1e6

        # Revenue (% GDP → USD mn)
        rev_pct = _safe_val(row, "gov_rev_gdp")
        rev_mn  = (gdp_mn * rev_pct / 100) if (gdp_mn and rev_pct) else None

        # PV of PPG external debt (USD millions)
        pv_usd = _safe_val(row, "pv_debt_usd")
        if pv_usd and pv_usd > 1e8:
            pv_usd /= 1e6       # WB stores in current USD (not millions)

        # Debt service (USD millions)
        ds_usd = _safe_val(row, "ds_total_usd")
        if ds_usd and ds_usd > 1e8:
            ds_usd /= 1e6

        # 1. PV debt / GDP
        out.loc[yr, "pv_debt_gdp"] = (
            row.get("pv_debt_gdp", np.nan) if "pv_debt_gdp" in row.index and not pd.isna(row["pv_debt_gdp"])
            else _safe_div(pv_usd, gdp_mn) * 100 if (pv_usd and gdp_mn) else np.nan
        )

        # 2. PV debt / Exports
        pv_exp = row.get("pv_debt_exports", np.nan) if "pv_debt_exports" in row.index else np.nan
        if pd.isna(pv_exp) and pv_usd and exp_mn:
            pv_exp = pv_usd / exp_mn * 100
        out.loc[yr, "pv_debt_exports"] = pv_exp

        # 3. Debt service / Exports
        ds_exp = row.get("ds_exports_pct", np.nan) if "ds_exports_pct" in row.index else np.nan
        if pd.isna(ds_exp) and ds_usd and exp_mn:
            ds_exp = ds_usd / exp_mn * 100
        out.loc[yr, "ds_exports"] = ds_exp

        # 4. Debt service / Revenue
        ds_rev = row.get("ds_revenues_pct", np.nan) if "ds_revenues_pct" in row.index else np.nan
        if pd.isna(ds_rev) and ds_usd and rev_mn:
            ds_rev = ds_usd / rev_mn * 100
        out.loc[yr, "ds_revenues"] = ds_rev

    return out


def _safe_val(row, col):
    """Return float value from row if column exists and not NaN."""
    try:
        v = row[col]
        return float(v) if not pd.isna(v) else None
    except (KeyError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 2b.  PV of Debt — Two-Component Decomposition
# ─────────────────────────────────────────────────────────────────────────────

def compute_pv_from_face_value(
    face_pct_gdp:      float,
    coupon_rate_pct:   float,
    avg_maturity_yr:   float,
    discount_rate_pct: float = 5.0,
    amortization:      str   = "level",
) -> float:
    """
    Compute the present value of a debt stock from its face value and
    assumed loan characteristics.  Returns PV as % of GDP (same units as
    face_pct_gdp).

    Parameters
    ----------
    face_pct_gdp      : Nominal (face) value of debt as % of GDP.
    coupon_rate_pct   : Average annual interest rate on the portfolio (e.g. 8.0).
    avg_maturity_yr   : Average remaining maturity in years.
    discount_rate_pct : Discount rate — IMF/WB standard for LIC DSF is 5%.
    amortization      : 'level'  — equal annual principal repayments
                                    (typical for concessional IDA/bilat loans).
                        'bullet' — all principal at maturity + annual coupons
                                    (typical for market-access bonds).

    Formula (level amortisation)
    ----------------------------
    For t = 1 … T:
      principal_t  = FaceValue / T
      interest_t   = remaining_balance × coupon_rate
      cash_flow_t  = principal_t + interest_t
      PV           = Σ cash_flow_t / (1 + r)^t

    Formula (bullet)
    ----------------
    PV = FaceValue × coupon_rate × Σ 1/(1+r)^t  (t=1…T)
       + FaceValue / (1+r)^T
    """
    if pd.isna(face_pct_gdp) or face_pct_gdp <= 0 or avg_maturity_yr <= 0:
        return np.nan

    r  = discount_rate_pct / 100.0
    c  = coupon_rate_pct   / 100.0
    F  = float(face_pct_gdp)
    T  = max(1, int(round(float(avg_maturity_yr))))

    pv = 0.0

    if amortization == "bullet":
        # Annual coupon payments + bullet principal at maturity
        for t in range(1, T + 1):
            pv += (F * c) / (1.0 + r) ** t
        pv += F / (1.0 + r) ** T

    else:  # "level" — equal annual amortisation (default)
        annual_principal = F / T
        remaining        = F
        for t in range(1, T + 1):
            interest   = remaining * c
            cash_flow  = annual_principal + interest
            pv        += cash_flow / (1.0 + r) ** t
            remaining -= annual_principal

    return round(pv, 4)


def grant_element(
    face_pct_gdp:      float,
    coupon_rate_pct:   float,
    avg_maturity_yr:   float,
    discount_rate_pct: float = 5.0,
    amortization:      str   = "level",
) -> float:
    """
    Grant element = (Face − PV) / Face × 100  (expressed in %).
    A positive grant element means the loan is concessional at the given
    discount rate.  The IMF/WB classify a loan as concessional if the
    grant element ≥ 35% at a 5% discount rate.
    """
    if pd.isna(face_pct_gdp) or face_pct_gdp <= 0:
        return np.nan
    pv = compute_pv_from_face_value(
        face_pct_gdp, coupon_rate_pct, avg_maturity_yr,
        discount_rate_pct, amortization,
    )
    if pd.isna(pv):
        return np.nan
    return round((face_pct_gdp - pv) / face_pct_gdp * 100, 2)


def compute_total_pv_series(
    df:                pd.DataFrame,
    base_year:         int,
    n_years:           int   = 10,
    # ── Domestic debt assumptions ──────────────────────────────────────────
    dom_coupon_pct:    float = 8.0,
    dom_maturity_yr:   float = 5.0,
    dom_discount_pct:  float = 5.0,
    dom_amortization:  str   = "level",
    # ── External debt assumptions (only used when override_ext_pv=True) ───
    override_ext_pv:   bool  = False,
    ext_coupon_pct:    float = 2.0,
    ext_maturity_yr:   float = 15.0,
    ext_discount_pct:  float = 5.0,
    ext_amortization:  str   = "level",
) -> pd.DataFrame:
    """
    Compute the two-component PV-of-debt breakdown over the projection
    horizon and sum into a total.

    Component 1 — External PPG debt
      Default: use the World Bank pre-computed series (DT.DOD.PVLX.CD)
               already in df["pv_debt_gdp"], which embeds the standard 5%
               discount rate.
      Override: recompute from face value df["ppg_debt_usd"] using
               ext_coupon_pct / ext_maturity_yr / ext_discount_pct.

    Component 2 — Domestic public debt
      Face value = Total Public Debt (WEO GGXWDG_NGDP) − External PPG (% GDP).
      PV computed from face value using dom_coupon_pct / dom_maturity_yr /
      dom_discount_pct.

    Returns DataFrame indexed by year with columns:
      ext_face_gdp        external PPG debt face value (% GDP)
      ext_pv_gdp          external PPG debt PV (% GDP)
      ext_grant_element   grant element on external debt (%)
      dom_face_gdp        domestic debt face value (% GDP)
      dom_pv_gdp          domestic debt PV (% GDP)
      dom_grant_element   grant element on domestic debt (%)
      total_face_gdp      ext_face + dom_face (% GDP)
      total_pv_gdp        ext_pv  + dom_pv   (% GDP)
    """
    years = list(range(base_year + 1, base_year + n_years + 1))
    out   = pd.DataFrame(index=years, dtype=float)
    out.index.name = "year"

    for yr in years:
        if yr not in df.index:
            continue
        row = df.loc[yr]

        # ── GDP in USD millions ───────────────────────────────────────────
        gdp_mn = _safe_val(row, "gdp_usd_mn")
        if gdp_mn is None:
            gdp_wb = _safe_val(row, "gdp_usd_wb")
            if gdp_wb:
                gdp_mn = gdp_wb / 1e6

        # ── External PPG: face value % GDP ───────────────────────────────
        ppg_usd = _safe_val(row, "ppg_debt_usd")   # World Bank DT.DOD.DPPG.CD (current USD)
        ext_face = None
        if ppg_usd is not None and gdp_mn is not None and gdp_mn > 0:
            ext_face = (ppg_usd / 1e6) / gdp_mn * 100  # USD → USD mn → % GDP

        out.loc[yr, "ext_face_gdp"] = ext_face

        # ── External PPG: present value % GDP ────────────────────────────
        if override_ext_pv and ext_face is not None:
            ext_pv = compute_pv_from_face_value(
                ext_face, ext_coupon_pct, ext_maturity_yr,
                ext_discount_pct, ext_amortization,
            )
            out.loc[yr, "ext_pv_gdp"] = ext_pv
            out.loc[yr, "ext_grant_element"] = grant_element(
                ext_face, ext_coupon_pct, ext_maturity_yr,
                ext_discount_pct, ext_amortization,
            )
        else:
            # Use World Bank pre-computed PV (standard approach)
            ext_pv = _safe_val(row, "pv_debt_gdp")
            out.loc[yr, "ext_pv_gdp"] = ext_pv
            # Implied grant element from WB PV vs face value
            if ext_pv is not None and ext_face is not None and ext_face > 0:
                out.loc[yr, "ext_grant_element"] = (ext_face - ext_pv) / ext_face * 100

        # ── Total public debt % GDP (WEO GGXWDG_NGDP) ────────────────────
        total_pub = _safe_val(row, "pub_debt_gdp")

        # ── Domestic debt face value = Total − External PPG ───────────────
        dom_face = None
        if total_pub is not None and ext_face is not None:
            dom_face = max(float(total_pub) - float(ext_face), 0.0)
        elif total_pub is not None:
            # Fallback: no external breakdown → flag as missing
            dom_face = None

        out.loc[yr, "dom_face_gdp"] = dom_face

        # ── Domestic debt: PV ─────────────────────────────────────────────
        if dom_face is not None and dom_face > 0:
            dom_pv = compute_pv_from_face_value(
                dom_face, dom_coupon_pct, dom_maturity_yr,
                dom_discount_pct, dom_amortization,
            )
            out.loc[yr, "dom_pv_gdp"] = dom_pv
            out.loc[yr, "dom_grant_element"] = grant_element(
                dom_face, dom_coupon_pct, dom_maturity_yr,
                dom_discount_pct, dom_amortization,
            )
        else:
            out.loc[yr, "dom_pv_gdp"]        = 0.0
            out.loc[yr, "dom_grant_element"]  = np.nan

        # ── Combined totals ───────────────────────────────────────────────
        ext_f_v = out.loc[yr, "ext_face_gdp"]  if not pd.isna(out.loc[yr, "ext_face_gdp"])  else 0.0
        dom_f_v = out.loc[yr, "dom_face_gdp"]  if not pd.isna(out.loc[yr, "dom_face_gdp"])  else 0.0
        ext_p_v = out.loc[yr, "ext_pv_gdp"]    if not pd.isna(out.loc[yr, "ext_pv_gdp"])    else 0.0
        dom_p_v = out.loc[yr, "dom_pv_gdp"]    if not pd.isna(out.loc[yr, "dom_pv_gdp"])    else 0.0

        if ext_f_v > 0 or dom_f_v > 0:
            out.loc[yr, "total_face_gdp"] = ext_f_v + dom_f_v
        if ext_p_v > 0 or dom_p_v > 0:
            out.loc[yr, "total_pv_gdp"]   = ext_p_v + dom_p_v

    return out


def compute_public_indicator(df: pd.DataFrame, base_year: int, n_years: int = 10) -> pd.Series:
    """
    Compute total public debt (% GDP) over projection horizon.
    Returns pd.Series indexed by year.
    """
    years = list(range(base_year + 1, base_year + n_years + 1))
    out   = pd.Series(index=years, dtype=float)
    for yr in years:
        if yr in df.index and "pub_debt_gdp" in df.columns:
            out[yr] = df.loc[yr, "pub_debt_gdp"]
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. Threshold Comparison
# ─────────────────────────────────────────────────────────────────────────────

def check_thresholds(
    indicators:     pd.DataFrame,
    classification: str,
    scenario:       str = "Baseline",
) -> list[ThresholdResult]:
    """
    Compare computed indicators against LIC DSF thresholds.
    indicators: DataFrame with columns pv_debt_gdp, pv_debt_exports, ds_exports, ds_revenues.
    Returns list of ThresholdResult (one per indicator, worst year).
    """
    thresh = EXTERNAL_THRESHOLDS[classification]
    ind_map = {
        "pv_debt_gdp":    ("PV Debt / GDP (%)",      thresh["pv_gdp"]),
        "pv_debt_exports":("PV Debt / Exports (%)",  thresh["pv_exports"]),
        "ds_exports":     ("Debt Service / Exports (%)", thresh["ds_exports"]),
        "ds_revenues":    ("Debt Service / Revenue (%)", thresh["ds_revenues"]),
    }
    results = []
    for col, (name, limit) in ind_map.items():
        if col not in indicators.columns:
            continue
        col_data = indicators[col].dropna()
        if col_data.empty:
            continue
        worst_val = float(col_data.max())
        breached  = worst_val > limit
        results.append(ThresholdResult(
            indicator=name,
            value=round(worst_val, 1),
            threshold=limit,
            breached=breached,
            pct_of_thresh=round(worst_val / limit * 100, 1),
        ))
    return results


def check_public_threshold(
    pub_debt_gdp:   pd.Series,
    classification: str,
) -> ThresholdResult:
    """Check total public debt against benchmark."""
    benchmark = PUBLIC_BENCHMARKS[classification]
    worst     = float(pub_debt_gdp.dropna().max()) if not pub_debt_gdp.dropna().empty else 0.0
    return ThresholdResult(
        indicator="Total Public Debt / GDP (%)",
        value=round(worst, 1),
        threshold=benchmark,
        breached=worst > benchmark,
        pct_of_thresh=round(worst / benchmark * 100, 1) if benchmark else 0.0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Stress Tests
# ─────────────────────────────────────────────────────────────────────────────

def _historical_shock(series: pd.Series, hist_years: list[int], proj_years: list[int]) -> float:
    """Compute shock size: min(hist_avg - 1SD, proj_avg - 1SD)."""
    hist = series.reindex(hist_years).dropna()
    proj = series.reindex(proj_years).dropna()
    if hist.empty:
        return float("inf")   # no shock if no data
    hist_shock = float(hist.mean() - hist.std())
    proj_shock = float(proj.mean() - proj.std()) if not proj.empty else hist_shock
    return min(hist_shock, proj_shock)


def run_stress_tests(
    df:             pd.DataFrame,
    classification: str,
    base_year:      int,
    n_proj:         int = 10,
    contingent_pct: float = 5.0,
) -> list[StressTestResult]:
    """
    Run all standardized stress tests.
    Returns a list of StressTestResult.
    """
    hist_years = list(range(base_year - 9, base_year + 1))
    proj_years = list(range(base_year + 1, base_year + n_proj + 1))

    results = []

    # ── Helper: apply shocked df and evaluate ──────────────────────────────
    def _eval_shocked(shocked_df: pd.DataFrame, name: str, scenario: str) -> StressTestResult:
        ind = compute_external_indicators(shocked_df, base_year, n_proj)
        trs = check_thresholds(ind, classification, scenario=scenario)
        return StressTestResult(
            name=name,
            scenario=scenario,
            indicators=trs,
            any_breach=any(t.breached for t in trs),
        )

    # ── 1. Historical Scenario ─────────────────────────────────────────────
    hist_df = df.copy()
    for col in ["gdp_growth", "pbal_gdp", "gdp_deflator", "ca_gdp"]:
        if col in df.columns:
            hist_avg = float(df[col].reindex(hist_years).dropna().mean())
            for yr in proj_years:
                if yr in hist_df.index:
                    hist_df.loc[yr, col] = hist_avg
    results.append(_eval_shocked(hist_df, "Historical Scenario", "historical"))

    # ── 2. GDP Growth Shock ────────────────────────────────────────────────
    gdp_shock_df = df.copy()
    if "gdp_growth" in df.columns:
        shock_g = _historical_shock(df["gdp_growth"], hist_years, proj_years)
        for yr in proj_years[:2]:   # years 1 and 2
            if yr in gdp_shock_df.index:
                gdp_shock_df.loc[yr, "gdp_growth"] = shock_g
                if "gdp_deflator" in gdp_shock_df.columns:
                    baseline_g = df.loc[yr, "gdp_growth"] if yr in df.index else shock_g
                    gdp_shock_df.loc[yr, "gdp_deflator"] = (
                        df.loc[yr, "gdp_deflator"] - 0.6 * (baseline_g - shock_g)
                        if yr in df.index and not pd.isna(df.loc[yr, "gdp_deflator"])
                        else gdp_shock_df.loc[yr, "gdp_deflator"]
                    )
    results.append(_eval_shocked(gdp_shock_df, "Real GDP Growth Shock", "gdp_shock"))

    # ── 3. Export Shock ────────────────────────────────────────────────────
    exp_shock_df = df.copy()
    for exp_col in ["exports_wb_usd", "exports_usd", "BX"]:
        if exp_col in df.columns:
            exp_series = df[exp_col]
            pct_change = exp_series.pct_change() * 100
            shock_exp  = _historical_shock(pct_change, hist_years, proj_years)
            for yr in proj_years[:2]:
                if yr in exp_shock_df.index and yr - 1 in exp_shock_df.index:
                    prev = exp_shock_df.loc[yr - 1, exp_col]
                    exp_shock_df.loc[yr, exp_col] = prev * (1 + shock_exp / 100) if not pd.isna(prev) else prev
            break
    results.append(_eval_shocked(exp_shock_df, "Export Growth Shock", "exports_shock"))

    # ── 4. Other Flows Shock (Remittances + FDI) ──────────────────────────
    flows_shock_df = df.copy()
    if "remittances_gdp" in df.columns:
        shock_rem = _historical_shock(df["remittances_gdp"], hist_years, proj_years)
        for yr in proj_years[:2]:
            if yr in flows_shock_df.index:
                flows_shock_df.loc[yr, "remittances_gdp"] = max(shock_rem, 0)
    results.append(_eval_shocked(flows_shock_df, "Other Flows Shock", "other_flows"))

    # ── 5. Depreciation Shock (30% nominal depreciation) ─────────────────
    dep_shock_df = df.copy()
    first_proj   = proj_years[0] if proj_years else None
    if first_proj and first_proj in dep_shock_df.index:
        # 30% depreciation → USD value of GDP (denominator) falls
        # debt in USD stays same → ratios rise by ~30%
        DEP_FACTOR = 1.30   # debt/GDP increases by 30%
        for col in ["pv_debt_gdp", "pv_debt_exports", "ds_exports", "ds_revenues"]:
            if col in dep_shock_df.columns and not pd.isna(dep_shock_df.loc[first_proj, col]):
                dep_shock_df.loc[first_proj, col] *= DEP_FACTOR
        # GDP in USD falls by 30/130 = ~23%
        if "gdp_usd_mn" in dep_shock_df.columns:
            dep_shock_df.loc[first_proj, "gdp_usd_mn"] /= DEP_FACTOR
        if "gdp_usd" in dep_shock_df.columns:
            dep_shock_df.loc[first_proj, "gdp_usd"] /= DEP_FACTOR
        # Inflation pass-through (30% shock * 0.3 passthrough)
        if "gdp_deflator" in dep_shock_df.columns:
            dep_shock_df.loc[first_proj, "gdp_deflator"] = (
                dep_shock_df.loc[first_proj, "gdp_deflator"] + 9.0
            )
    results.append(_eval_shocked(dep_shock_df, "Exchange Rate Depreciation (30%)", "depreciation"))

    # ── 6. Combination Shock (half magnitude of all above simultaneously) ─
    combo_df = df.copy()
    if "gdp_growth" in df.columns and proj_years:
        shock_g   = _historical_shock(df["gdp_growth"], hist_years, proj_years)
        for yr in proj_years[:2]:
            if yr in combo_df.index:
                baseline_g = df.loc[yr, "gdp_growth"] if yr in df.index else 0
                combo_df.loc[yr, "gdp_growth"] = baseline_g - 0.5 * (baseline_g - shock_g)
    for exp_col in ["exports_wb_usd", "exports_usd"]:
        if exp_col in df.columns:
            pct_change = df[exp_col].pct_change() * 100
            shock_exp  = _historical_shock(pct_change, hist_years, proj_years)
            for yr in proj_years[:2]:
                if yr in combo_df.index and yr - 1 in combo_df.index:
                    prev = combo_df.loc[yr - 1, exp_col]
                    baseline_chg = (df.loc[yr, exp_col] / df.loc[yr - 1, exp_col] - 1) * 100 \
                        if (yr in df.index and yr - 1 in df.index and not pd.isna(df.loc[yr - 1, exp_col])) else 0
                    combo_df.loc[yr, exp_col] = prev * (1 + (baseline_chg + 0.5 * (shock_exp - baseline_chg)) / 100) \
                        if not pd.isna(prev) else prev
            break
    if first_proj and first_proj in combo_df.index:
        for col in ["pv_debt_gdp", "pv_debt_exports", "ds_exports", "ds_revenues"]:
            if col in combo_df.columns and not pd.isna(combo_df.loc[first_proj, col]):
                combo_df.loc[first_proj, col] *= 1.15   # half of 30% depreciation
    results.append(_eval_shocked(combo_df, "Combination Shock", "combination"))

    # ── 7. Contingent Liability Shock (public debt only) ──────────────────
    contingent_df = df.copy()
    if proj_years and proj_years[0] in contingent_df.index and "pub_debt_gdp" in contingent_df.columns:
        contingent_df.loc[proj_years[0], "pub_debt_gdp"] = (
            contingent_df.loc[proj_years[0], "pub_debt_gdp"] + contingent_pct
        )
    pub_contingent = compute_public_indicator(contingent_df, base_year, n_proj)
    pub_thresh      = check_public_threshold(pub_contingent, classification)
    results.append(StressTestResult(
        name="Contingent Liability Shock",
        scenario="contingent",
        indicators=[pub_thresh],
        any_breach=pub_thresh.breached,
    ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 5. Risk Rating
# ─────────────────────────────────────────────────────────────────────────────

def determine_risk_rating(
    baseline_thresholds:  list[ThresholdResult],
    pub_baseline:         ThresholdResult,
    stress_tests:         list[StressTestResult],
    in_distress_flag:     bool = False,
    classification:       str  = "Medium",
) -> RiskRating:
    """
    Determine the mechanical risk signal and final rating per LIC DSF methodology.

    Logic:
    - In Debt Distress: existing restructuring / arrears → rating = In Debt Distress
    - High: any breach under baseline → mechanical High
    - Moderate: breaches only under stress tests (not baseline) → mechanical Moderate
    - Low: no breach under baseline or stress tests → mechanical Low

    The final rating equals the mechanical signal (judgement overlay not modelled here).
    """
    drivers = []

    baseline_breach = any(t.breached for t in baseline_thresholds) or pub_baseline.breached
    stress_breach   = any(st.any_breach for st in stress_tests
                         if st.scenario != "historical")  # Historical ≠ binding

    # Identify breached indicators for reporting
    for t in baseline_thresholds:
        if t.breached:
            drivers.append(f"Baseline: {t.indicator} ({t.value:.1f}% vs threshold {t.threshold}%)")
    if pub_baseline.breached:
        drivers.append(f"Baseline: {pub_baseline.indicator} ({pub_baseline.value:.1f}% vs benchmark {pub_baseline.threshold}%)")
    for st in stress_tests:
        if st.any_breach and st.scenario != "historical":
            for t in st.indicators:
                if t.breached:
                    drivers.append(f"{st.name}: {t.indicator} ({t.value:.1f}%)")

    # Mechanical signal
    if in_distress_flag:
        signal = "In Debt Distress"
    elif baseline_breach:
        signal = "High"
    elif stress_breach:
        signal = "Moderate"
    else:
        signal = "Low"

    # Moderate risk granularity (distance to thresholds)
    granularity = None
    if signal == "Moderate":
        granularity = _compute_granularity(baseline_thresholds)

    return RiskRating(
        mechanical_signal=signal,
        final_rating=signal,   # user can override in UI
        granularity=granularity,
        baseline_breach=baseline_breach,
        stress_breach=stress_breach,
        key_drivers=drivers[:6],  # top 6 drivers
        in_distress=in_distress_flag,
    )


def _compute_granularity(thresholds: list[ThresholdResult]) -> str:
    """
    Moderate Risk Tool — classify into Substantial / Some / Limited space.
    Criteria (% of threshold):
      Stock indicators (PV/GDP, PV/Exports): Substantial < 60%, Some = 60–80%, Limited ≥ 80%
      Flow indicators (DS/Exports, DS/Rev):  Substantial < 65%, Some = 65–88%, Limited ≥ 88%
    """
    stock_indicators = {"PV Debt / GDP (%)", "PV Debt / Exports (%)"}
    flow_indicators  = {"Debt Service / Exports (%)", "Debt Service / Revenue (%)"}

    worst_stock = max(
        (t.pct_of_thresh for t in thresholds if t.indicator in stock_indicators),
        default=0.0
    )
    worst_flow = max(
        (t.pct_of_thresh for t in thresholds if t.indicator in flow_indicators),
        default=0.0
    )

    # Use the most binding (worst) indicator
    if worst_stock >= 80 or worst_flow >= 88:
        return "Limited Space to Absorb Shocks"
    elif worst_stock >= 60 or worst_flow >= 65:
        return "Some Space to Absorb Shocks"
    else:
        return "Substantial Space to Absorb Shocks"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Full DSA Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_full_dsa(
    df:              pd.DataFrame,
    ci_result:       CIResult,
    base_year:       int,
    world_growth:    pd.Series,
    in_distress:     bool  = False,
    contingent_pct:  float = 5.0,
    # ── PV decomposition assumptions ─────────────────────────────────────────
    dom_coupon_pct:   float = 8.0,
    dom_maturity_yr:  float = 5.0,
    dom_discount_pct: float = 5.0,
    dom_amortization: str   = "level",
    override_ext_pv:  bool  = False,
    ext_coupon_pct:   float = 2.0,
    ext_maturity_yr:  float = 15.0,
    ext_discount_pct: float = 5.0,
    ext_amortization: str   = "level",
) -> dict:
    """
    Run the complete LIC DSA:
      1. Compute baseline external indicators
      2. Compute baseline public debt indicator
      3. Compute two-component PV decomposition (external + domestic)
      4. Check thresholds
      5. Run stress tests
      6. Determine risk rating
    Returns a dict with all results.
    """
    classification = ci_result.classification

    # Baseline external indicators
    ext_indicators  = compute_external_indicators(df, base_year, n_years=10)

    # Baseline public debt
    pub_debt_series = compute_public_indicator(df, base_year, n_years=10)

    # Two-component PV decomposition (external + domestic)
    pv_decomp = compute_total_pv_series(
        df, base_year, n_years=10,
        dom_coupon_pct   = dom_coupon_pct,
        dom_maturity_yr  = dom_maturity_yr,
        dom_discount_pct = dom_discount_pct,
        dom_amortization = dom_amortization,
        override_ext_pv  = override_ext_pv,
        ext_coupon_pct   = ext_coupon_pct,
        ext_maturity_yr  = ext_maturity_yr,
        ext_discount_pct = ext_discount_pct,
        ext_amortization = ext_amortization,
    )

    # Threshold checks
    baseline_thresholds = check_thresholds(ext_indicators, classification, "Baseline")
    pub_threshold       = check_public_threshold(pub_debt_series, classification)

    # Stress tests
    stress_results = run_stress_tests(df, classification, base_year, n_proj=10, contingent_pct=contingent_pct)

    # Risk rating
    rating = determine_risk_rating(
        baseline_thresholds=baseline_thresholds,
        pub_baseline=pub_threshold,
        stress_tests=stress_results,
        in_distress_flag=in_distress,
        classification=classification,
    )

    return {
        "ci":                  ci_result,
        "classification":      classification,
        "thresholds":          EXTERNAL_THRESHOLDS[classification],
        "pub_benchmark":       PUBLIC_BENCHMARKS[classification],
        "ext_indicators":      ext_indicators,
        "pub_debt_series":     pub_debt_series,
        "pv_decomp":           pv_decomp,           # NEW: two-component PV breakdown
        "baseline_thresholds": baseline_thresholds,
        "pub_threshold":       pub_threshold,
        "stress_tests":        stress_results,
        "rating":              rating,
        # Store PV assumptions for display
        "pv_assumptions": {
            "dom_coupon_pct":   dom_coupon_pct,
            "dom_maturity_yr":  dom_maturity_yr,
            "dom_discount_pct": dom_discount_pct,
            "dom_amortization": dom_amortization,
            "override_ext_pv":  override_ext_pv,
            "ext_coupon_pct":   ext_coupon_pct if override_ext_pv else 5.0,
            "ext_maturity_yr":  ext_maturity_yr if override_ext_pv else "(WB pre-computed)",
            "ext_discount_pct": ext_discount_pct,
        },
    }
