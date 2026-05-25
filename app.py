"""
LIC DSF Assessment Tool
=======================
Web-based Debt Sustainability Framework assessment tool for Low-Income Countries.
Pulls live data from IMF WEO and World Bank IDS/DSSI APIs.
Implements the 2017 Revised LIC DSF methodology.

Run with:
    streamlit run app.py
"""

import io
import os
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from datetime import datetime

# ── App config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="LIC DSF Assessment Tool",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Module imports ────────────────────────────────────────────────────────────
from modules.country_meta import (
    LIC_COUNTRIES, EXTERNAL_THRESHOLDS, PUBLIC_BENCHMARKS,
    CI_CUTOFF_WEAK_MEDIUM, CI_CUTOFF_MEDIUM_STRONG,
    WAEMU_ISO3, CEMAC_ISO3, POOLED_RESERVES_ISO3, POOLED_RESERVES_NOTE,
)
from modules.data_fetcher import (
    fetch_all_data, fetch_weo_country, fetch_wb_debt, fetch_cpia_scores,
    fetch_world_growth, build_macro_dataframe, project_debt_dynamics,
    get_country_mof_url, get_weo_version,
    # Data Explorer
    WEO_CATALOG, WB_EXPLORER_CATALOG, IDS_CATALOG,
    IDS_BULK_CATALOG, IDS_BULK_CATALOG_GROUPED,
    get_weo_available_countries, fetch_weo_explorer, fetch_wb_explorer,
    fetch_ids_bulk, query_ids_bulk,
)
from modules.dsf_calculator import (
    compute_ci, compute_external_indicators, compute_public_indicator,
    check_thresholds, check_public_threshold, run_stress_tests,
    run_full_dsa,
)
from modules.charts import (
    plot_ci_gauge, plot_external_indicators, plot_public_debt,
    plot_threshold_summary, plot_macro_overview, plot_stress_heatmap,
    risk_color,
)
from modules.report import generate_excel_report


# ─────────────────────────────────────────────────────────────────────────────
# Custom CSS
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* IMF-inspired color scheme */
:root {
    --imf-blue: #003087;
    --imf-orange: #E05206;
    --imf-light: #EEF2FF;
}

.main > div { padding-top: 1rem; }

/* Risk badge */
.risk-badge {
    display: inline-block;
    padding: 6px 20px;
    border-radius: 20px;
    font-weight: bold;
    font-size: 1.1rem;
    letter-spacing: 0.5px;
}
.risk-low      { background: #C8E6C9; color: #1B5E20; }
.risk-moderate { background: #FFF9C4; color: #F57F17; }
.risk-high     { background: #FFCCBC; color: #BF360C; }
.risk-distress { background: #F8BBD0; color: #880E4F; }

/* Metric cards */
.metric-card {
    background: white;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 4px 0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.metric-card .label { font-size: 0.8rem; color: #666; font-weight: 500; }
.metric-card .value { font-size: 1.4rem; font-weight: bold; color: #003087; }

/* Section headers */
.section-header {
    background: linear-gradient(90deg, #003087 0%, #1565C0 100%);
    color: white;
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: bold;
    font-size: 1rem;
    margin: 12px 0 8px 0;
}

/* Breach indicator */
.breach-yes { color: #CC0000; font-weight: bold; }
.breach-no  { color: #2E7D32; font-weight: bold; }

/* Sidebar styling */
.css-1d391kg { background-color: #F8F9FF; }

/* Hide streamlit menu & footer */
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Session state defaults
# ─────────────────────────────────────────────────────────────────────────────

def _init_state():
    defaults = {
        "data_loaded":    False,
        "df_macro":       None,
        "weo_data":       None,
        "wb_data":        None,
        "world_growth":   None,
        "cpia_data":      None,
        "dsa_results":    None,
        "ci_result":      None,
        "selected_country": "Senegal",
        "base_year":      datetime.today().year - 1,
        "cpia_override":  None,
        "in_distress":    False,
        "contingent_pct": 5.0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — Controls
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://www.imf.org/~/media/Images/IMF/live-web/imf-logo/imf-logo-eng.ashx",
             width=120, use_container_width=False,
             caption="")
    st.markdown("## 🌍 LIC DSF Tool")
    st.markdown("*IMF/World Bank 2017 Revised Framework*")
    st.divider()

    # Country selection
    country_list = sorted(LIC_COUNTRIES.keys())
    selected_country = st.selectbox(
        "Select Country",
        country_list,
        index=country_list.index(st.session_state["selected_country"])
        if st.session_state["selected_country"] in country_list else 0,
        help="Choose a LIC/IDA-eligible country for DSA",
    )
    st.session_state["selected_country"] = selected_country
    meta = LIC_COUNTRIES[selected_country]

    st.caption(f"ISO: {meta['iso3']} | Region: {meta['region']}")

    # Base year
    base_year = st.number_input(
        "Base Year (last actual)",
        min_value=2015,
        max_value=datetime.today().year,
        value=st.session_state["base_year"],
        step=1,
        help="Year of most recent actual data. WEO projections start from base_year+1.",
    )
    st.session_state["base_year"] = base_year

    st.divider()
    st.markdown("#### ⚙️ DSF Parameters")

    # CPIA override
    default_cpia = meta.get("cpia") or 3.0
    cpia_val = st.number_input(
        "CPIA Score (1–6)",
        min_value=1.0,
        max_value=6.0,
        value=float(st.session_state.get("cpia_override") or default_cpia),
        step=0.1,
        format="%.2f",
        help="World Bank CPIA score. Pre-filled from database; fetch from API or override manually.",
    )
    st.session_state["cpia_override"] = cpia_val

    contingent_pct = st.number_input(
        "Contingent Liability Shock (% GDP)",
        min_value=0.0,
        max_value=30.0,
        value=float(st.session_state["contingent_pct"]),
        step=0.5,
        help="Size of contingent liability shock (≥5% per LIC DSF). Add SOE debt, financial sector risk, etc.",
    )
    st.session_state["contingent_pct"] = contingent_pct

    in_distress = st.checkbox(
        "Country in Debt Distress",
        value=st.session_state["in_distress"],
        help="Check if the country is already in debt distress (active restructuring or arrears)",
    )
    st.session_state["in_distress"] = in_distress

    st.divider()

    # Fetch button
    fetch_btn = st.button(
        "🔄 Fetch Data & Run DSA",
        type="primary",
        use_container_width=True,
        help="Pull live data from IMF WEO and World Bank APIs, then compute DSA",
    )

    if st.session_state["data_loaded"]:
        rerun_btn = st.button(
            "♻️ Re-Run DSA (current data)",
            use_container_width=True,
            help="Re-run the DSA with updated parameters without re-fetching data",
        )
    else:
        rerun_btn = False

    st.divider()

    # Data sources info
    with st.expander("📡 Data Sources", expanded=False):
        st.markdown("""
**IMF WEO** *(live — imf-reader)*
- Fetches latest WEO from imf.org
- GDP, growth, fiscal, projections
- Cached 6 hrs (WEO updates Apr/Oct)

**World Bank IDS/DSSI** *(live API)*
- PPG external debt stocks & PV
- Debt service, reserves, remittances

**CPIA** *(World Bank API, annual)*
- 4-cluster composite score
- Used in CI formula

**Country MoF / Stats Office**
- See [Data Sources tab] for links
        """)

    # About
    with st.expander("ℹ️ About", expanded=False):
        st.markdown("""
This tool implements the **2017 Revised LIC DSF** methodology jointly developed by the IMF and World Bank.

**Key references:**
- [LIC DSF Policy Paper (2017)](https://www.imf.org/external/pp/longres.aspx?id=4997)
- [Guidance Note on LIC DSF](https://www.imf.org/external/pp/longres.aspx?id=5106)
- [IMF DSAx Glossary](https://www.imf.org)

Data sources: IMF WEO & World Bank IDS public APIs.
        """)


# ─────────────────────────────────────────────────────────────────────────────
# Data Fetching & DSA Computation
# ─────────────────────────────────────────────────────────────────────────────

def run_dsa_pipeline(country: str, base_yr: int, cpia: float, in_dist: bool, cont_pct: float):
    """Full live-data fetch + DSA computation pipeline."""
    meta = LIC_COUNTRIES[country]
    iso3 = meta["iso3"]
    iso2 = meta["iso2"]

    progress = st.progress(0, text="🌐 Fetching live IMF WEO data…")

    # 1. Live WEO data via imf-reader (cached 6 hrs; fast on repeated runs)
    weo_data = fetch_weo_country(iso3)
    n_weo = sum(1 for s in weo_data.values() if not s.empty)
    progress.progress(35, text=f"✅ {n_weo} WEO indicators loaded. Fetching World Bank data…")

    # 2. World Bank debt data
    wb_data = fetch_wb_debt(iso2)
    progress.progress(60, text="📡 Fetching world growth + CPIA…")

    # 3. World growth (WEO G001)
    world_growth = fetch_world_growth()

    # 4. CPIA from WB API
    cpia_api   = fetch_cpia_scores(iso2)
    cpia_final = cpia
    if cpia_api.get("cpia_overall") and abs(cpia - (meta.get("cpia") or 3.0)) < 0.01:
        cpia_final = cpia_api["cpia_overall"]
        st.session_state["cpia_override"] = cpia_final

    progress.progress(72, text="🔧 Building macro dataset…")

    # 5. Unified macro DataFrame
    df_macro = build_macro_dataframe(weo_data, wb_data, base_yr, n_proj=5)
    df_macro = project_debt_dynamics(df_macro, base_yr)

    progress.progress(86, text="📊 Computing CI and running DSA…")

    # 6. CI inputs — WEO series primary, WB fallback
    gdp_growth_s  = weo_data.get("NGDP_RPCH", pd.Series(dtype=float))
    reserves_s    = wb_data.get("reserves_months", pd.Series(dtype=float))
    remittances_s = wb_data.get("remittances_gdp", pd.Series(dtype=float))

    # 7. Composite Indicator
    ci_result = compute_ci(
        cpia=cpia_final,
        gdp_growth=gdp_growth_s,
        reserves=reserves_s,
        remittances=remittances_s,
        world_growth=world_growth,
        base_year=base_yr,
    )

    # 8. Full DSA
    dsa_results = run_full_dsa(
        df=df_macro,
        ci_result=ci_result,
        base_year=base_yr,
        world_growth=world_growth,
        in_distress=in_dist,
        contingent_pct=cont_pct,
    )

    progress.progress(100, text="✅ Done!")
    progress.empty()

    return weo_data, wb_data, world_growth, df_macro, ci_result, dsa_results


if fetch_btn:
    with st.spinner(f"Fetching data for {selected_country}…"):
        try:
            (weo_data, wb_data, world_growth,
             df_macro, ci_result, dsa_results) = run_dsa_pipeline(
                selected_country, base_year,
                st.session_state["cpia_override"] or default_cpia,
                in_distress, contingent_pct,
            )
            st.session_state.update({
                "data_loaded":  True,
                "weo_data":     weo_data,
                "wb_data":      wb_data,
                "world_growth": world_growth,
                "df_macro":     df_macro,
                "ci_result":    ci_result,
                "dsa_results":  dsa_results,
            })
            st.success(f"✅ Data fetched and DSA completed for **{selected_country}**")
        except Exception as e:
            st.error(f"Error during data fetch: {e}")
            st.exception(e)

elif rerun_btn and st.session_state["data_loaded"]:
    with st.spinner("Re-running DSA…"):
        try:
            df_macro    = st.session_state["df_macro"]
            world_growth= st.session_state["world_growth"]
            weo_data    = st.session_state["weo_data"]
            wb_data     = st.session_state["wb_data"]

            gdp_growth_s  = weo_data.get("NGDP_RPCH", pd.Series(dtype=float))
            reserves_s    = wb_data.get("reserves_months", pd.Series(dtype=float))
            remittances_s = wb_data.get("remittances_gdp", pd.Series(dtype=float))

            ci_result = compute_ci(
                cpia=st.session_state["cpia_override"] or default_cpia,
                gdp_growth=gdp_growth_s,
                reserves=reserves_s,
                remittances=remittances_s,
                world_growth=world_growth,
                base_year=base_year,
            )
            dsa_results = run_full_dsa(
                df=df_macro,
                ci_result=ci_result,
                base_year=base_year,
                world_growth=world_growth,
                in_distress=in_distress,
                contingent_pct=contingent_pct,
            )
            st.session_state["ci_result"]   = ci_result
            st.session_state["dsa_results"] = dsa_results
            st.success("DSA re-computed!")
        except Exception as e:
            st.error(f"Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main Content — Tabs
# ─────────────────────────────────────────────────────────────────────────────

tab_home, tab_macro, tab_ci, tab_ext, tab_pub, tab_rating, tab_sources, tab_export, tab_explorer = st.tabs([
    "🏠 Home",
    "📊 Macro",
    "🔢 CI",
    "📈 Ext. DSA",
    "🏛️ Pub. DSA",
    "⚠️ Rating",
    "🔗 Sources",
    "📥 Export",
    "🔍 Explorer",
])


# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — Home
# ════════════════════════════════════════════════════════════════════════════
with tab_home:
    col_l, col_r = st.columns([3, 2])
    with col_l:
        st.markdown("""
# 🌍 LIC DSF Assessment Tool

This tool automates the **IMF/World Bank Debt Sustainability Framework for Low-Income Countries (LIC DSF)** assessment using live public data.

### What it does
1. **Fetches** real-time macro data from IMF WEO and World Bank IDS/DSSI APIs
2. **Computes** the Composite Indicator (CI) to classify debt-carrying capacity
3. **Runs** the full External and Public DSA with standardized stress tests
4. **Rates** debt sustainability risk: Low / Moderate / High / In Debt Distress
5. **Exports** a structured Excel report

### How to use
1. Select a country in the **sidebar**
2. Set the **base year** (last year of actual data)
3. Verify/override the **CPIA score**
4. Click **"Fetch Data & Run DSA"**
5. Explore results in the tabs above
        """)

    with col_r:
        st.markdown("### The 10-Step LIC DSF Process")
        steps = [
            ("1. Overview",           "What is the LIC DSF and who uses it"),
            ("2. Data Input",         "GDP, fiscal, BOP, debt coverage"),
            ("3. Realism",            "Baseline assumption validation"),
            ("4. Debt-Carrying Cap.", "CI score → Weak / Medium / Strong"),
            ("5. Stress Tests",       "Standardized shocks applied"),
            ("6. Outputs",            "DSA tables and fan charts"),
            ("7. Market Financing",   "Eurobond / market access analysis"),
            ("8. Judgement",          "Overlays on mechanical signal"),
            ("9. Final Rating",       "Low / Moderate / High / Distress"),
            ("10. Granularity",       "Sub-rating for Moderate countries"),
        ]
        for step, desc in steps:
            st.markdown(f"**{step}** — {desc}")

    st.divider()

    # Quick status if data loaded
    if st.session_state["data_loaded"]:
        rating   = st.session_state["dsa_results"]["rating"]
        ci       = st.session_state["ci_result"]
        country  = st.session_state["selected_country"]

        st.markdown(f"### Latest Results — **{country}** (Base Year: {st.session_state['base_year']})")

        risk_cls = {
            "Low": "risk-low",
            "Moderate": "risk-moderate",
            "High": "risk-high",
            "In Debt Distress": "risk-distress",
        }.get(rating.final_rating, "risk-moderate")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Risk Rating", rating.final_rating)
        with col2:
            st.metric("Classification", ci.classification)
        with col3:
            st.metric("CI Score", f"{ci.ci_score:.3f}")
        with col4:
            st.metric("CPIA", f"{ci.cpia:.2f}")

        st.markdown(
            f'<span class="risk-badge {risk_cls}">{rating.final_rating}</span>',
            unsafe_allow_html=True,
        )
        if rating.granularity:
            st.caption(f"Moderate granularity: **{rating.granularity}**")

        if rating.key_drivers:
            st.markdown("**Key risk drivers:**")
            for d in rating.key_drivers:
                st.markdown(f"- {d}")
    else:
        st.info("👈 Select a country and click **Fetch Data & Run DSA** to begin.")

        col_src1, col_src2 = st.columns(2)
        with col_src1:
            st.markdown("**Live Data Sources**")
            st.markdown("""
- 🌐 **IMF WEO** (latest publication via `imf-reader`) — GDP, growth, fiscal projections
- 🌐 **World Bank IDS/DSSI** (API) — PPG external debt, PV, debt service
- 🌐 **World Bank CPIA** (API) — country classification score
- 🌐 **World Bank WLD** (API) — world GDP growth for CI formula
            """)
        with col_src2:
            st.markdown("**No local files required.** All data pulled live on demand.")
            st.caption("WEO data is cached for 6 hours (WEO releases are April & October).")
            st.caption("World Bank data is cached for 1 hour.")

        st.divider()
        # Show framework diagram
        st.markdown("### LIC DSF Thresholds by Classification")
        thresh_df = pd.DataFrame({
            "Indicator": [
                "PV Debt / GDP (%)",
                "PV Debt / Exports (%)",
                "Debt Service / Exports (%)",
                "Debt Service / Revenue (%)",
                "Total Public Debt / GDP (benchmark)",
            ],
            "Weak": [30, 140, 10, 14, 35],
            "Medium": [40, 180, 15, 18, 55],
            "Strong": [55, 240, 21, 23, 70],
        })
        st.dataframe(
            thresh_df.set_index("Indicator"),
            use_container_width=True,
            height=210,
        )
        st.caption("Source: IMF/World Bank LIC DSF Policy Paper (2017)")


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — Macro Overview
# ════════════════════════════════════════════════════════════════════════════
with tab_macro:
    if not st.session_state["data_loaded"]:
        st.info("Run the DSA first to see macro data.")
    else:
        df_macro = st.session_state["df_macro"]
        base_yr  = st.session_state["base_year"]
        country  = st.session_state["selected_country"]

        st.markdown(f"### Macroeconomic Dashboard — {country}")

        # Summary metrics (most recent year)
        if base_yr in df_macro.index:
            row = df_macro.loc[base_yr]
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            with c1:
                st.metric("GDP (USD bn)",
                          f"{row.get('gdp_usd', 'N/A'):.1f}" if not pd.isna(row.get('gdp_usd', np.nan)) else "N/A")
            with c2:
                st.metric("Real Growth",
                          f"{row.get('gdp_growth', 'N/A'):.1f}%" if not pd.isna(row.get('gdp_growth', np.nan)) else "N/A")
            with c3:
                st.metric("Revenue/GDP",
                          f"{row.get('gov_rev_gdp', 'N/A'):.1f}%" if not pd.isna(row.get('gov_rev_gdp', np.nan)) else "N/A")
            with c4:
                st.metric("Primary Bal/GDP",
                          f"{row.get('pbal_gdp', 'N/A'):.1f}%" if not pd.isna(row.get('pbal_gdp', np.nan)) else "N/A")
            with c5:
                st.metric("Pub Debt/GDP",
                          f"{row.get('pub_debt_gdp', 'N/A'):.1f}%" if not pd.isna(row.get('pub_debt_gdp', np.nan)) else "N/A")
            with c6:
                st.metric("Reserves (months)",
                          f"{row.get('reserves_months', 'N/A'):.1f}" if not pd.isna(row.get('reserves_months', np.nan)) else "N/A")

        # Macro overview chart
        fig_mac = plot_macro_overview(df_macro, base_yr, country)
        st.plotly_chart(fig_mac, use_container_width=True)

        # Raw data table
        with st.expander("📋 View Raw Macro Data", expanded=False):
            display_cols = {
                "gdp_usd":       "GDP (USD bn)",
                "gdp_growth":    "Real GDP Growth (%)",
                "gdp_deflator":  "GDP Deflator (%)",
                "gov_rev_gdp":   "Govt Revenue (% GDP)",
                "pbal_gdp":      "Primary Balance (% GDP)",
                "pub_debt_gdp":  "Public Debt (% GDP)",
                "ca_gdp":        "Current Account (% GDP)",
                "reserves_months":"Reserves (months)",
                "remittances_gdp":"Remittances (% GDP)",
                "ppg_debt_usd":  "PPG Ext Debt (USD mn)",
                "pv_debt_usd":   "PV Ext Debt (USD)",
                "ds_total_usd":  "Debt Service (USD)",
            }
            avail_cols = {c: l for c, l in display_cols.items() if c in df_macro.columns}
            df_show = df_macro[list(avail_cols.keys())].rename(columns=avail_cols)
            df_show.index.name = "Year"

            # Display with projection-year indicator column (no pandas Styler needed)
            df_show.insert(0, "Type", ["📊 Actual" if y <= base_yr else "🔵 Proj." for y in df_show.index])
            st.dataframe(
                df_show.round(2).fillna("—"),
                use_container_width=True,
                height=400,
            )
            st.caption("🔵 Proj. = WEO projections / extrapolated values")

        # External debt detail
        st.markdown('<div class="section-header">External Debt Profile</div>', unsafe_allow_html=True)
        wb_data = st.session_state["wb_data"]
        ext_cols = {
            "DT.DOD.DPPG.CD":   "PPG Ext Debt (USD)",
            "DT.DOD.PVLX.CD":   "PV of Ext Debt (USD)",
            "DT.TDS.DPPG.CD":   "Debt Service (USD)",
            "DT.DOD.PVLX.EX.ZS":"PV Debt/Exports (%)",
            "DT.TDS.DPPG.EX.ZS":"DS/Exports (%)",
        }
        ext_dfs = {}
        for code, label in ext_cols.items():
            if code in wb_data and not wb_data[code].empty:
                ext_dfs[label] = wb_data[code]

        if ext_dfs:
            ext_df = pd.DataFrame(ext_dfs)
            ext_df.index.name = "Year"
            st.dataframe(
                ext_df.round(1).fillna("—"),
                use_container_width=True, height=250,
            )


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — Composite Indicator
# ════════════════════════════════════════════════════════════════════════════
with tab_ci:
    if not st.session_state["data_loaded"]:
        st.info("Run the DSA first to see the Composite Indicator.")
    else:
        ci     = st.session_state["ci_result"]
        dsa_r  = st.session_state["dsa_results"]

        st.markdown("### Composite Indicator & Debt-Carrying Capacity Classification")

        # CI gauge + contributions
        fig_ci = plot_ci_gauge(ci.ci_score, ci.classification, ci.contributions)
        st.plotly_chart(fig_ci, use_container_width=True)

        # Classification explanation
        cls_info = {
            "Weak":   ("Weak capacity",   "#FFE0CC", "🟠",
                       "Tighter thresholds apply. Country faces structural vulnerabilities."),
            "Medium": ("Medium capacity", "#FFF3CC", "🟡",
                       "Intermediate thresholds. Moderate macro/institutional environment."),
            "Strong": ("Strong capacity", "#D4EDDA", "🟢",
                       "Higher thresholds. Strong institutions and macro management."),
        }
        cls_label, cls_bg, cls_icon, cls_text = cls_info[ci.classification]
        st.markdown(
            f"""<div style="background:{cls_bg}; padding:12px 16px; border-radius:8px; margin:8px 0">
            <b>{cls_icon} {ci.classification} Country ({cls_label})</b><br>
            {cls_text}
            </div>""",
            unsafe_allow_html=True,
        )

        # CI formula breakdown
        st.markdown('<div class="section-header">CI Formula Details</div>', unsafe_allow_html=True)
        st.latex(r"""
            CI = 0.385 \times CPIA
               + 0.02719 \times g
               + 0.04052 \times reserves
               - 0.03990 \times reserves^2
               + 0.02022 \times remittances
               + 0.13520 \times g_w
        """)

        # Compute each of the 6 term contributions individually
        # (ci.contributions merges the two reserves terms into one key)
        _c6 = [
            round(0.385    * ci.cpia,              3),
            round(0.02719  * ci.avg_growth,        3),
            round(0.04052  * ci.avg_reserves,      3),
            round(-0.03990 * ci.avg_reserves**2,   3),
            round(0.02022  * ci.avg_remit,         3),
            round(0.13520  * ci.avg_world_g,       3),
        ]
        formula_data = pd.DataFrame({
            "Component": ["CPIA Score", "Avg Real GDP Growth", "Avg Reserves (months)",
                          "Reserves² (adj.)", "Avg Remittances (% GDP)", "Avg World Growth"],
            "Coefficient": [0.385, 0.02719, 0.04052, -0.03990, 0.02022, 0.13520],
            "Input Value": [
                f"{ci.cpia:.2f}",
                f"{ci.avg_growth:.2f}%",
                f"{ci.avg_reserves:.2f} months",
                f"{ci.avg_reserves**2:.2f}",
                f"{ci.avg_remit:.2f}%",
                f"{ci.avg_world_g:.2f}%",
            ],
            "Contribution": _c6,
        })
        st.dataframe(formula_data.set_index("Component"), use_container_width=True, height=260)

        # Monetary-union note: WAEMU/CEMAC countries pool reserves regionally
        _iso3 = meta.get("iso3", "")
        if _iso3 in WAEMU_ISO3:
            st.info(
                "🏦 **WAEMU monetary union member** — Foreign reserves are pooled at the "
                "**BCEAO** (Banque Centrale des États de l'Afrique de l'Ouest) and are not "
                "held at the country level. Country-specific import-coverage data is "
                "unavailable; the Reserves term in the CI formula is set to 0. "
                "The union-level reserve adequacy is monitored separately by the BCEAO."
            )
        elif _iso3 in CEMAC_ISO3:
            st.info(
                "🏦 **CEMAC monetary union member** — Foreign reserves are pooled at the "
                "**BEAC** (Banque des États de l'Afrique Centrale) and are not held at the "
                "country level. Country-specific import-coverage data is unavailable; "
                "the Reserves term in the CI formula is set to 0."
            )

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("CI Score", f"{ci.ci_score:.3f}")
        with col_b:
            st.metric("Classification", ci.classification)
        with col_c:
            st.metric("Cutoffs", "< 2.69 = Weak | ≤ 3.05 = Medium | > 3.05 = Strong")

        st.divider()

        # Applicable thresholds table
        st.markdown("### Applicable Thresholds")
        thresh = EXTERNAL_THRESHOLDS[ci.classification]
        pub_bm = PUBLIC_BENCHMARKS[ci.classification]

        thresh_df = pd.DataFrame([
            {"Indicator": "PV of Debt / GDP (%)",        "Threshold": thresh["pv_gdp"],      "Type": "External PPG"},
            {"Indicator": "PV of Debt / Exports (%)",    "Threshold": thresh["pv_exports"],  "Type": "External PPG"},
            {"Indicator": "Debt Service / Exports (%)",  "Threshold": thresh["ds_exports"],  "Type": "External PPG"},
            {"Indicator": "Debt Service / Revenue (%)",  "Threshold": thresh["ds_revenues"], "Type": "External PPG"},
            {"Indicator": "Total Public Debt / GDP (%)", "Threshold": pub_bm,                "Type": "Public (benchmark)"},
        ])
        st.dataframe(thresh_df.set_index("Indicator"), use_container_width=True, height=230)
        st.caption("Note: The public debt threshold is a benchmark, not a binding limit.")


# ════════════════════════════════════════════════════════════════════════════
# TAB 4 — External DSA
# ════════════════════════════════════════════════════════════════════════════
with tab_ext:
    if not st.session_state["data_loaded"]:
        st.info("Run the DSA first to see External DSA results.")
    else:
        dsa_r  = st.session_state["dsa_results"]
        ci     = dsa_r["ci"]
        thresh = dsa_r["thresholds"]
        ext_df = dsa_r["ext_indicators"]
        base_yr= st.session_state["base_year"]
        country= st.session_state["selected_country"]

        st.markdown(f"### External PPG Debt Sustainability Analysis — {country}")
        st.caption(
            f"Classification: **{ci.classification}** | "
            f"Thresholds — PV/GDP: {thresh['pv_gdp']}% | "
            f"PV/Exp: {thresh['pv_exports']}% | "
            f"DS/Exp: {thresh['ds_exports']}% | "
            f"DS/Rev: {thresh['ds_revenues']}%"
        )

        # Baseline threshold status
        st.markdown('<div class="section-header">Baseline Threshold Status</div>', unsafe_allow_html=True)
        threshold_cols = st.columns(4)
        for i, t in enumerate(dsa_r["baseline_thresholds"]):
            with threshold_cols[i % 4]:
                delta_val = t.value - t.threshold
                st.metric(
                    label=t.indicator,
                    value=f"{t.value:.1f}%",
                    delta=f"{delta_val:+.1f}% vs threshold ({t.threshold}%)",
                    delta_color="inverse",
                )
                status_cls = "breach-yes" if t.breached else "breach-no"
                status_txt = "⚠️ BREACHED" if t.breached else "✅ Below Threshold"
                st.markdown(f'<span class="{status_cls}">{status_txt}</span>', unsafe_allow_html=True)

        # Build stress bands
        stress_bands = {}
        for st_test in dsa_r["stress_tests"]:
            if st_test.scenario == "historical":
                continue
            # Map stress test results to a DataFrame for charting
            stress_row = {}
            for t in st_test.indicators:
                ind_map = {
                    "PV Debt / GDP (%)":       "pv_debt_gdp",
                    "PV Debt / Exports (%)":   "pv_debt_exports",
                    "Debt Service / Exports (%)": "ds_exports",
                    "Debt Service / Revenue (%)": "ds_revenues",
                }
                col_name = ind_map.get(t.indicator)
                if col_name:
                    stress_row[col_name] = t.value
            if stress_row and not ext_df.empty:
                # Create a synthetic DataFrame for visualization
                stress_df = ext_df.copy()
                for col_n, val in stress_row.items():
                    if col_n in stress_df.columns:
                        stress_df[col_n] = val   # simplified: worst value for all years
                stress_bands[st_test.name] = stress_df

        # Main indicator chart
        fig_ext = plot_external_indicators(
            ext_baseline=ext_df,
            thresholds=thresh,
            stress_bands=stress_bands if stress_bands else None,
            base_year=base_yr,
        )
        st.plotly_chart(fig_ext, use_container_width=True)

        # Threshold summary bar chart
        st.markdown('<div class="section-header">Threshold Breach Summary (all scenarios)</div>', unsafe_allow_html=True)
        fig_summ = plot_threshold_summary(
            dsa_r["baseline_thresholds"],
            ci.classification,
            dsa_r["stress_tests"],
        )
        st.plotly_chart(fig_summ, use_container_width=True)

        # Raw indicator table
        with st.expander("📋 External Indicator Values by Year", expanded=False):
            if not ext_df.empty:
                display_df = ext_df.copy()
                display_df.columns = [
                    "PV Debt/GDP (%)" if c == "pv_debt_gdp" else
                    "PV Debt/Exports (%)" if c == "pv_debt_exports" else
                    "DS/Exports (%)" if c == "ds_exports" else
                    "DS/Revenue (%)" if c == "ds_revenues" else c
                    for c in display_df.columns
                ]
                # Highlight breaches
                thresh_cols = {
                    "PV Debt/GDP (%)":      thresh["pv_gdp"],
                    "PV Debt/Exports (%)":  thresh["pv_exports"],
                    "DS/Exports (%)":       thresh["ds_exports"],
                    "DS/Revenue (%)":       thresh["ds_revenues"],
                }

                # Add a breach indicator row instead of cell coloring (no Styler needed)
                breach_row = {}
                for col_n in display_df.columns:
                    lim = thresh_cols.get(col_n, 9999)
                    worst = display_df[col_n].dropna().max() if col_n in display_df.columns and not display_df[col_n].dropna().empty else 0
                    breach_row[col_n] = f"⚠️ {worst:.1f}% (>{lim}%)" if worst > lim else f"✓ {worst:.1f}%"
                breach_df = pd.DataFrame([breach_row], index=["Worst year"])

                st.dataframe(
                    display_df.round(1).fillna("—"),
                    use_container_width=True, height=320,
                )
                st.dataframe(breach_df, use_container_width=True)
                st.caption("⚠️ = threshold breached | ✓ = within threshold")


# ════════════════════════════════════════════════════════════════════════════
# TAB 5 — Public DSA
# ════════════════════════════════════════════════════════════════════════════
with tab_pub:
    if not st.session_state["data_loaded"]:
        st.info("Run the DSA first to see Public DSA results.")
    else:
        dsa_r  = st.session_state["dsa_results"]
        ci     = dsa_r["ci"]
        base_yr= st.session_state["base_year"]
        country= st.session_state["selected_country"]
        df_mac = st.session_state["df_macro"]

        pub_bm  = dsa_r["pub_benchmark"]
        pub_ser = dsa_r["pub_debt_series"]
        pub_thr = dsa_r["pub_threshold"]

        st.markdown(f"### Total Public Sector Debt Analysis — {country}")
        st.caption(
            f"Benchmark for **{ci.classification}** country: **{pub_bm}% of GDP** "
            "(informational — not a binding threshold)"
        )

        # Status card
        col_a, col_b, col_c = st.columns([1, 1, 2])
        with col_a:
            st.metric(
                "Peak Public Debt",
                f"{pub_thr.value:.1f}% GDP",
                delta=f"{pub_thr.value - pub_bm:+.1f}% vs benchmark",
                delta_color="inverse",
            )
        with col_b:
            st.metric("Benchmark", f"{pub_bm}% GDP")
        with col_c:
            status = "⚠️ Benchmark Exceeded" if pub_thr.breached else "✅ Below Benchmark"
            color  = "#FFCCCC" if pub_thr.breached else "#CCFFCC"
            st.markdown(
                f'<div style="background:{color}; padding:12px; border-radius:8px; margin-top:8px">'
                f'<b>{status}</b><br>'
                f'Peak value: {pub_thr.value:.1f}% of GDP vs benchmark: {pub_bm}%'
                f'</div>',
                unsafe_allow_html=True,
            )

        # Historical series
        if "pub_debt_gdp" in df_mac.columns:
            hist_pub = df_mac.loc[df_mac.index <= base_yr, "pub_debt_gdp"].dropna()
        else:
            hist_pub = None

        # Contingent shock series
        contingent_st = next(
            (st_t for st_t in dsa_r["stress_tests"] if st_t.scenario == "contingent"),
            None
        )

        fig_pub = plot_public_debt(
            pub_debt_series=pub_ser,
            pub_benchmark=pub_bm,
            hist_series=hist_pub,
            base_year=base_yr,
        )
        st.plotly_chart(fig_pub, use_container_width=True)

        # Public DSA explanation
        with st.expander("📖 About the Public DSA", expanded=False):
            st.markdown(f"""
**Total Public Debt Coverage**: General government + SOE debt guaranteed by the government.

**Benchmark ({pub_bm}% of GDP for {ci.classification} country)**: This is a signal
that calls for increased scrutiny, but is *not* a formal binding threshold. Breaching
it contributes to the overall risk assessment but does not automatically trigger a High rating.

**Stress tests on public debt**:
- GDP growth shock (reduces GDP denominator)
- Primary balance shock (increases borrowing)
- Contingent liability shock (+{st.session_state['contingent_pct']:.1f}% GDP one-off addition)

**Key fiscal indicators** (for the current base year, {base_yr}):
- Revenue / GDP: `{df_mac.loc[base_yr, 'gov_rev_gdp']:.1f}%`  *(if available)*
- Primary balance / GDP: `{df_mac.loc[base_yr, 'pbal_gdp']:.1f}%`  *(if available)*
            """ if base_yr in df_mac.index and "gov_rev_gdp" in df_mac.columns and "pbal_gdp" in df_mac.columns
            else f"""
**Benchmark**: {pub_bm}% of GDP for {ci.classification} country.
Fetch data and run the DSA to see detailed fiscal indicators.
            """)

        # Table
        with st.expander("📋 Public Debt Projection Table", expanded=False):
            pub_df_show = pd.DataFrame({
                "Year": pub_ser.index,
                "Total Public Debt (% GDP)": pub_ser.values.round(1),
                f"Benchmark ({pub_bm}%)": [pub_bm] * len(pub_ser),
                "Headroom (pp)": [(pub_bm - v) for v in pub_ser.values.round(1)],
            }).set_index("Year")
            # Add status column instead of row coloring (no Styler needed)
            pub_df_show["Status"] = pub_df_show["Headroom (pp)"].apply(
                lambda h: "⚠️ BREACH" if h < 0 else ("⚠️ Near" if h < 5 else "✓ OK")
            )
            st.dataframe(
                pub_df_show.round(1).fillna("—"),
                use_container_width=True, height=350,
            )


# ════════════════════════════════════════════════════════════════════════════
# TAB 6 — Risk Rating
# ════════════════════════════════════════════════════════════════════════════
with tab_rating:
    if not st.session_state["data_loaded"]:
        st.info("Run the DSA first to see the risk rating.")
    else:
        dsa_r   = st.session_state["dsa_results"]
        rating  = dsa_r["rating"]
        ci      = dsa_r["ci"]
        country = st.session_state["selected_country"]

        st.markdown(f"### Risk Rating Summary — {country}")

        # ── Main rating banner ────────────────────────────────────────────
        color_map = {
            "Low":            ("#2E7D32", "#C8E6C9"),
            "Moderate":       ("#E65100", "#FFF9C4"),
            "High":           ("#BF360C", "#FFCCBC"),
            "In Debt Distress":("#880E4F","#F8BBD0"),
        }
        text_col, bg_col = color_map.get(rating.final_rating, ("#333", "#FFF"))

        st.markdown(
            f"""<div style="background:{bg_col}; border:2px solid {text_col};
                border-radius:12px; padding:20px; text-align:center; margin:8px 0">
                <div style="font-size:2rem; font-weight:bold; color:{text_col}">
                    {rating.final_rating}
                </div>
                <div style="font-size:1rem; color:{text_col}; margin-top:4px">
                    Overall Risk of External Debt Distress
                </div>
            </div>""",
            unsafe_allow_html=True,
        )

        # ── Rating components ─────────────────────────────────────────────
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Mechanical Signal", rating.mechanical_signal)
            sig_logic = (
                "Baseline breach → High" if rating.baseline_breach else
                "Stress breach only → Moderate" if rating.stress_breach else
                "No breach → Low"
            )
            st.caption(sig_logic)
        with col2:
            st.metric("Baseline Breach", "Yes" if rating.baseline_breach else "No")
            st.metric("Stress Breach",   "Yes" if rating.stress_breach   else "No")
        with col3:
            st.metric("Classification", ci.classification)
            if rating.granularity:
                st.metric("Moderate Granularity", rating.granularity)

        # ── Risk rating logic explanation ──────────────────────────────────
        st.markdown('<div class="section-header">How the Rating Was Determined</div>', unsafe_allow_html=True)
        rating_logic = {
            "Low": "No threshold is breached under the baseline OR under any standardized stress test.",
            "Moderate": "No threshold is breached under the baseline, but at least one stress test triggers a breach. The country has limited space to absorb shocks.",
            "High": "At least one threshold is breached under the baseline scenario. The country faces elevated debt vulnerabilities.",
            "In Debt Distress": "The country is in active debt restructuring, has payment arrears, or faces significant and sustained threshold breaches under the baseline.",
        }
        st.info(rating_logic.get(rating.final_rating, ""))

        # ── Key drivers ────────────────────────────────────────────────────
        if rating.key_drivers:
            st.markdown('<div class="section-header">Key Risk Drivers</div>', unsafe_allow_html=True)
            for driver in rating.key_drivers:
                icon = "🔴" if "Baseline" in driver else "🟡"
                st.markdown(f"{icon} {driver}")

        # ── Moderate risk granularity ──────────────────────────────────────
        if rating.final_rating == "Moderate" and rating.granularity:
            st.markdown('<div class="section-header">Moderate Risk Tool — Granularity</div>', unsafe_allow_html=True)
            gran_info = {
                "Substantial Space to Absorb Shocks": (
                    "✅ Substantial Space",
                    "Indicators remain well below thresholds (below 60% for stock, 65% for flow indicators).",
                    "#C8E6C9",
                ),
                "Some Space to Absorb Shocks": (
                    "⚠️ Some Space",
                    "Indicators are in the 60–80% range (stock) or 65–88% range (flow) of their thresholds.",
                    "#FFF9C4",
                ),
                "Limited Space to Absorb Shocks": (
                    "🔴 Limited Space",
                    "Indicators are close to (within ~20% of) their thresholds. High vulnerability.",
                    "#FFCCBC",
                ),
            }
            if rating.granularity in gran_info:
                label, desc, bg = gran_info[rating.granularity]
                st.markdown(
                    f'<div style="background:{bg}; padding:12px 16px; border-radius:8px">'
                    f'<b>{label}</b><br>{desc}</div>',
                    unsafe_allow_html=True,
                )

        # ── Stress test heatmap ────────────────────────────────────────────
        st.markdown('<div class="section-header">Stress Test Heatmap</div>', unsafe_allow_html=True)
        fig_heat = plot_stress_heatmap(dsa_r["stress_tests"])
        if fig_heat.data:
            st.plotly_chart(fig_heat, use_container_width=True)

        # ── Stress test details table ──────────────────────────────────────
        with st.expander("📋 Stress Test Detail", expanded=True):
            st_rows = []
            for st_test in dsa_r["stress_tests"]:
                row = {"Scenario": st_test.name, "Any Breach": "YES" if st_test.any_breach else "NO"}
                for t in st_test.indicators:
                    ind_map = {
                        "PV Debt / GDP (%)":           "PV/GDP (% thresh)",
                        "PV Debt / Exports (%)":       "PV/Exp (% thresh)",
                        "Debt Service / Exports (%)":  "DS/Exp (% thresh)",
                        "Debt Service / Revenue (%)":  "DS/Rev (% thresh)",
                        "Total Public Debt / GDP (%)": "PubDebt/GDP (% benchmark)",
                    }
                    col_label = ind_map.get(t.indicator, t.indicator)
                    row[col_label] = f"{t.pct_of_thresh:.0f}%"
                st_rows.append(row)

            st_df = pd.DataFrame(st_rows).set_index("Scenario")

            # Add emoji indicators to values — no Styler needed
            def _add_indicator(val):
                if isinstance(val, str) and val.endswith("%"):
                    try:
                        pct = float(val[:-1])
                        if pct >= 100:
                            return f"⚠️ {val}"
                        elif pct >= 80:
                            return f"🔶 {val}"
                        return val
                    except ValueError:
                        pass
                if val == "YES":
                    return "⚠️ YES"
                if val == "NO":
                    return "✓ NO"
                return val

            st_df_display = st_df.map(_add_indicator)   # pandas 2.1+ uses map() not applymap()
            st.dataframe(
                st_df_display,
                use_container_width=True,
                height=300,
            )

        # ── Judgement override ─────────────────────────────────────────────
        with st.expander("⚖️ Judgement Overlay (Optional)", expanded=False):
            st.markdown("""
The LIC DSF mechanical risk signal can be overridden by **analyst judgement**
when there are factors not captured in the model, such as:
- Short-lived or marginal threshold breaches (< 1% of threshold)
- Large liquid asset buffers (sovereign wealth fund, FX reserves)
- Conflict or crisis situations affecting data quality
- One-off fiscal measures distorting the baseline
- Natural disaster impacts already embedded in the data
            """)
            st.selectbox(
                "Override final rating (leave as 'Mechanical' to use model output)",
                ["Mechanical (no override)", "Low", "Moderate", "High", "In Debt Distress"],
                key="rating_override",
            )
            st.text_area("Justification for override", key="rating_justification", height=100)


# ════════════════════════════════════════════════════════════════════════════
# TAB 7 — Data Sources
# ════════════════════════════════════════════════════════════════════════════
with tab_sources:
    country  = st.session_state["selected_country"]
    meta     = LIC_COUNTRIES[country]
    iso2     = meta["iso2"]
    iso3     = meta["iso3"]
    mof_urls = get_country_mof_url(country)
    weo_ver  = get_weo_version()

    st.markdown(f"### Data Sources — {country}")
    st.caption(
        "This table shows exactly which API endpoint or series provided each variable used in the DSA. "
        "All data is fetched live at run-time; no local CSV files are used."
    )

    # ── Section 1: Variable-level data provenance ─────────────────────────
    st.markdown("#### 📋 Variable-by-Variable Provenance")
    provenance = [
        ("GDP (current USD bn)",          "IMF WEO",       "NGDPD",              f"https://www.imf.org/en/Publications/WEO/weo-database/", weo_ver),
        ("Real GDP growth (%)",           "IMF WEO",       "NGDP_RPCH",          f"https://www.imf.org/en/Publications/WEO/weo-database/", weo_ver),
        ("CPI inflation / GDP deflator",  "IMF WEO",       "PCPIPCH",            f"https://www.imf.org/en/Publications/WEO/weo-database/", weo_ver),
        ("Government revenue (% GDP)",    "IMF WEO",       "GGR_NGDP",           f"https://www.imf.org/en/Publications/WEO/weo-database/", weo_ver),
        ("Primary balance (% GDP)",       "IMF WEO",       "GGXONLB_NGDP",       f"https://www.imf.org/en/Publications/WEO/weo-database/", weo_ver),
        ("Public debt (% GDP)",           "IMF WEO",       "GGXWDG_NGDP",        f"https://www.imf.org/en/Publications/WEO/weo-database/", weo_ver),
        ("Current account (% GDP)",       "IMF WEO",       "BCA_NGDPD",          f"https://www.imf.org/en/Publications/WEO/weo-database/", weo_ver),
        ("Investment (% GDP)",            "IMF WEO",       "NID_NGDP",           f"https://www.imf.org/en/Publications/WEO/weo-database/", weo_ver),
        ("World real GDP growth (%)",     "World Bank WDI","NY.GDP.MKTP.KD.ZG",  f"https://api.worldbank.org/v2/country/WLD/indicator/NY.GDP.MKTP.KD.ZG?format=json", "World aggregate"),
        ("CPIA score",                    "World Bank CPIA","IQ.CPA.ECON/STRC/POLS/PUBS.XQ", f"https://api.worldbank.org/v2/country/{iso2}/indicator/IQ.CPA.PUBS.XQ?format=json", "Average of 4 clusters"),
        ("External PPG debt stock (USD)", "World Bank IDS","DT.DOD.DPPG.CD",     f"https://api.worldbank.org/v2/country/{iso2}/indicator/DT.DOD.DPPG.CD?format=json", "IDS/DSSI"),
        ("PV of external debt (USD)",     "World Bank IDS","DT.DOD.PVLX.CD",     f"https://api.worldbank.org/v2/country/{iso2}/indicator/DT.DOD.PVLX.CD?format=json", "IDS/DSSI"),
        ("Total PPG debt service (USD)",  "World Bank IDS","DT.TDS.DPPG.CD",     f"https://api.worldbank.org/v2/country/{iso2}/indicator/DT.TDS.DPPG.CD?format=json", "IDS/DSSI"),
        ("Exports goods+services (USD)",  "World Bank WDI","BX.GSR.GNFS.CD",     f"https://api.worldbank.org/v2/country/{iso2}/indicator/BX.GSR.GNFS.CD?format=json", "BOP data"),
        ("Remittances (% GDP)",           "World Bank WDI","BX.TRF.PWKR.DT.GD.ZS",f"https://api.worldbank.org/v2/country/{iso2}/indicator/BX.TRF.PWKR.DT.GD.ZS?format=json","CI formula input"),
        ("Reserves (months of imports)",  "World Bank WDI","FI.RES.TOTL.MO",     f"https://api.worldbank.org/v2/country/{iso2}/indicator/FI.RES.TOTL.MO?format=json", "N/A for WAEMU/CEMAC — pooled at central bank"),
    ]
    prov_df = pd.DataFrame(provenance, columns=["Variable", "Source", "Series / Indicator Code", "Live API Endpoint", "Notes"])
    st.dataframe(prov_df.set_index("Variable"), use_container_width=True, height=520)

    st.divider()

    # ── Section 2: Live connection status ────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 🌐 Live Data Connections")
        st.success(f"✅ IMF WEO: **{weo_ver}** — fetched via `imf-reader`")

        conn_sources = [
            ("IMF WEO (via imf-reader)",
             "https://www.imf.org/en/Publications/WEO/weo-database/",
             f"GDP, growth, fiscal & debt projections through 2031 — version: {weo_ver}"),
            ("World Bank IDS/DSSI API",
             f"https://api.worldbank.org/v2/country/{iso2}/indicator/DT.DOD.PVLX.CD?format=json",
             "External PPG debt stock, PV of debt, debt service, principal, interest payments"),
            ("World Bank CPIA API",
             f"https://api.worldbank.org/v2/country/{iso2}/indicator/IQ.CPA.PUBS.XQ?format=json",
             "CPIA scores (4 clusters: Economic, Structural, Social, Governance) → CI formula"),
            ("World Bank WDI API — World",
             "https://api.worldbank.org/v2/country/WLD/indicator/NY.GDP.MKTP.KD.ZG?format=json",
             "World real GDP growth — CI formula input (gw)"),
            ("World Bank WDI API — Country",
             f"https://api.worldbank.org/v2/country/{iso2}/indicator/BX.TRF.PWKR.DT.GD.ZS?format=json",
             "Remittances (% GDP), exports of goods+services — CI formula & ratio denominators"),
        ]
        for name, url, desc in conn_sources:
            st.markdown(f"**[{name}]({url})**  \n_{desc}_")
            st.divider()

    with col2:
        # ── Country-specific publications ────────────────────────────────
        st.markdown("#### 🏛️ Country-Specific Publications")

        if mof_urls and any(k.endswith("_label") or k in ("mof","stats","debt","imf_article_iv","imf_country") for k in mof_urls):
            # Structured rich format (new-style entries with _label keys)
            pub_groups = [
                ("📑 Fiscal & Budget", [
                    ("mof",          "mof_label"),
                    ("budget_law",   "budget_label"),
                    ("lfr",          "lfr_label"),
                    ("laws_archive", "laws_label"),
                    ("dpbep",        "dpbep_label"),
                ]),
                ("📊 Statistics", [
                    ("stats",        "stats_label"),
                    ("stats_pub",    "stats_pub_label"),
                ]),
                ("🏦 Debt Management", [
                    ("debt",         "debt_label"),
                ]),
                ("🌐 IMF", [
                    ("imf_country",   "imf_label"),
                    ("imf_article_iv","imf_iv_label"),
                    ("imf_2024",      "imf_2024_label"),
                ]),
            ]
            for group_title, pairs in pub_groups:
                entries = [(mof_urls[uk], mof_urls.get(lk, uk)) for uk, lk in pairs
                           if uk in mof_urls and isinstance(mof_urls[uk], str) and mof_urls[uk].startswith("http")]
                if entries:
                    st.markdown(f"**{group_title}**")
                    for url, label in entries:
                        st.markdown(f"- [{label}]({url})")
            if "notes" in mof_urls:
                st.info(f"ℹ️ **Data provenance note:** {mof_urls['notes']}")
        else:
            # Fallback for countries without structured entries
            imf_cr_url = f"https://www.imf.org/en/publications/cr?country={iso3}"
            imf_country_url = f"https://www.imf.org/en/countries/{iso3}"
            st.markdown(f"- [IMF Country Page — {country}]({imf_country_url})")
            st.markdown(f"- [IMF Country Reports (Article IV, DSA)]({imf_cr_url})")
            if mof_urls:
                for key, val in mof_urls.items():
                    if key not in ("notes",) and isinstance(val, str) and val.startswith("http"):
                        label = {"mof":"Ministry of Finance","stats":"National Statistics Office",
                                 "debt":"Debt Management Office"}.get(key, key.upper())
                        st.markdown(f"- [{label}]({val})")
                if "notes" in mof_urls:
                    st.info(mof_urls["notes"])
            else:
                st.info("No pre-configured publications. Refer to IMF Article IV links above.")

        st.markdown("#### 📥 Bulk Data Downloads")
        dl_sources = [
            ("IMF WEO Database (full — Excel/CSV)",
             "https://www.imf.org/en/Publications/WEO/weo-database/2025/April",
             "Full WEO dataset, all countries, all variables"),
            ("World Bank IDS DataBank",
             "https://databank.worldbank.org/source/international-debt-statistics:-dssi#",
             "IDS/DSSI country data — custom downloads"),
            ("World Bank Open Data",
             "https://data.worldbank.org/",
             "Full WDI, CPIA, remittances, reserves indicators"),
        ]
        for name, url, desc in dl_sources:
            st.markdown(f"**[{name}]({url})**  \n_{desc}_")


# ════════════════════════════════════════════════════════════════════════════
# TAB 8 — Export
# ════════════════════════════════════════════════════════════════════════════
with tab_export:
    st.markdown("### 📥 Export DSA Results")

    if not st.session_state["data_loaded"]:
        st.info("Run the DSA first to generate exports.")
    else:
        country  = st.session_state["selected_country"]
        base_yr  = st.session_state["base_year"]
        dsa_r    = st.session_state["dsa_results"]
        ci       = st.session_state["ci_result"]
        df_macro = st.session_state["df_macro"]

        analyst_name = st.text_input("Analyst Name (optional)", placeholder="Your name")

        col1, col2 = st.columns(2)

        # ── Excel Export ──────────────────────────────────────────────────
        with col1:
            st.markdown("#### 📊 Excel Report")
            st.markdown("""
Multi-sheet Excel workbook containing:
- **Summary**: Rating, CI, threshold status
- **Composite Indicator**: Formula inputs & contributions
- **Macro Data**: Full historical + projected dataset
- **External DSA**: Indicator table by year
- **Stress Tests**: All scenario results
- **Methodology**: Notes & references
            """)
            if st.button("Generate Excel Report", type="primary"):
                with st.spinner("Generating Excel report…"):
                    try:
                        xlsx_bytes = generate_excel_report(
                            country_name=country,
                            ci_result=ci,
                            dsa_results=dsa_r,
                            df_macro=df_macro,
                            base_year=base_yr,
                            analyst=analyst_name,
                        )
                        fname = f"DSA_{country.replace(' ', '_')}_{base_yr}_{datetime.today().strftime('%Y%m%d')}.xlsx"
                        st.download_button(
                            label="⬇️ Download Excel Report",
                            data=xlsx_bytes,
                            file_name=fname,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary",
                        )
                        st.success("Excel report ready!")
                    except Exception as e:
                        st.error(f"Error generating Excel: {e}")

        # ── CSV Export ────────────────────────────────────────────────────
        with col2:
            st.markdown("#### 📄 CSV Data Exports")
            st.markdown("Download individual datasets as CSV files.")

            if not df_macro.empty:
                csv_macro = df_macro.to_csv(index=True)
                st.download_button(
                    "⬇️ Macro Data (CSV)",
                    csv_macro,
                    file_name=f"macro_{country.replace(' ','_')}_{base_yr}.csv",
                    mime="text/csv",
                )

            ext_df = dsa_r["ext_indicators"]
            if not ext_df.empty:
                csv_ext = ext_df.to_csv(index=True)
                st.download_button(
                    "⬇️ External DSA Indicators (CSV)",
                    csv_ext,
                    file_name=f"ext_dsa_{country.replace(' ','_')}_{base_yr}.csv",
                    mime="text/csv",
                )

            # Stress test summary
            st_rows = []
            for st_test in dsa_r["stress_tests"]:
                row = {"Scenario": st_test.name, "Any Breach": st_test.any_breach}
                for t in st_test.indicators:
                    row[f"{t.indicator} (value)"]    = t.value
                    row[f"{t.indicator} (% thresh)"] = t.pct_of_thresh
                st_rows.append(row)
            if st_rows:
                st_df  = pd.DataFrame(st_rows)
                csv_st = st_df.to_csv(index=False)
                st.download_button(
                    "⬇️ Stress Test Results (CSV)",
                    csv_st,
                    file_name=f"stress_tests_{country.replace(' ','_')}_{base_yr}.csv",
                    mime="text/csv",
                )

        st.divider()
        st.markdown("#### 📋 Text Summary")

        summary_text = f"""
LIC DSF DEBT SUSTAINABILITY ASSESSMENT
{'='*50}
Country:        {country}
Base Year:      {base_yr}
Date:           {datetime.today().strftime('%Y-%m-%d')}
Analyst:        {analyst_name or 'Auto-generated'}

CLASSIFICATION
{'─'*30}
Composite Indicator (CI): {ci.ci_score:.3f}
Classification:           {ci.classification}
CI Cutoffs: Weak < 2.69 ≤ Medium ≤ 3.05 < Strong

INPUTS FOR CI
{'─'*30}
CPIA Score:               {ci.cpia:.2f}
10yr Avg Real GDP Growth: {ci.avg_growth:.2f}%
10yr Avg Reserves:        {ci.avg_reserves:.2f} months
10yr Avg Remittances:     {ci.avg_remit:.2f}% of GDP
10yr Avg World Growth:    {ci.avg_world_g:.2f}%

EXTERNAL DSA THRESHOLDS ({ci.classification})
{'─'*30}
PV Debt / GDP:            {dsa_r['thresholds']['pv_gdp']}%
PV Debt / Exports:        {dsa_r['thresholds']['pv_exports']}%
Debt Service / Exports:   {dsa_r['thresholds']['ds_exports']}%
Debt Service / Revenue:   {dsa_r['thresholds']['ds_revenues']}%
Public Debt Benchmark:    {dsa_r['pub_benchmark']}% (Total/GDP)

BASELINE ASSESSMENT
{'─'*30}
Baseline Breach:  {'YES' if dsa_r['rating'].baseline_breach else 'NO'}
Stress Breach:    {'YES' if dsa_r['rating'].stress_breach else 'NO'}

KEY INDICATORS (peak over projection horizon)
{'─'*30}
""" + "\n".join(f"{t.indicator}: {t.value:.1f}% (threshold: {t.threshold}%) {'← BREACHED' if t.breached else ''}"
                for t in dsa_r["baseline_thresholds"]) + f"""

RISK RATING
{'─'*30}
Mechanical Signal:  {dsa_r['rating'].mechanical_signal}
Final Rating:       {dsa_r['rating'].final_rating}
{'Granularity: ' + dsa_r['rating'].granularity if dsa_r['rating'].granularity else ''}

KEY RISK DRIVERS
{'─'*30}
""" + "\n".join(f"• {d}" for d in dsa_r["rating"].key_drivers) + f"""

FRAMEWORK REFERENCE
{'─'*30}
IMF/World Bank LIC DSF (2017 Revised)
Policy Paper: SM/17/292
Data: IMF WEO (live, via imf-reader) + World Bank IDS/DSSI API
"""
        st.text_area("DSA Summary", summary_text, height=400)
        st.download_button(
            "⬇️ Download Text Summary",
            summary_text,
            file_name=f"DSA_summary_{country.replace(' ','_')}_{base_yr}.txt",
            mime="text/plain",
        )


# ════════════════════════════════════════════════════════════════════════════
# TAB 9 — Data Explorer (WEO + World Bank, multi-country, any variable)
# ════════════════════════════════════════════════════════════════════════════
with tab_explorer:
    st.markdown("## 🔍 Data Explorer")
    st.caption(
        "Browse any variable from the **IMF WEO** or **World Bank** for one or more countries. "
        "Fully independent from the DSA — no need to run the assessment first. "
        "Data is fetched live from the same APIs used by the DSA."
    )

    # ── build WB name→iso2 lookup (LIC countries + common comparators) ────
    _WB_NAME_TO_ISO2: dict[str, str] = {
        name: meta["iso2"] for name, meta in LIC_COUNTRIES.items()
    }
    _WB_EXTRA_ISO2: dict[str, str] = {
        "China": "CN", "India": "IN", "United States": "US",
        "Brazil": "BR", "South Africa": "ZA", "Nigeria": "NG",
        "Ghana": "GH", "Kenya": "KE", "Egypt": "EG", "Morocco": "MA",
        "Tunisia": "TN", "Indonesia": "ID", "Vietnam": "VN",
        "Pakistan": "PK", "Bangladesh": "BD", "Mexico": "MX",
        "Colombia": "CO", "Philippines": "PH", "Turkey": "TR",
    }
    for _k, _v in _WB_EXTRA_ISO2.items():
        _WB_NAME_TO_ISO2.setdefault(_k, _v)

    # ── name→iso3 lookup for IDS bulk (uses ISO3 like WEO) ───────────────────
    _IDS_NAME_TO_ISO3: dict[str, str] = {
        name: meta["iso3"] for name, meta in LIC_COUNTRIES.items()
    }
    _IDS_EXTRA_ISO3: dict[str, str] = {
        "China": "CHN", "India": "IND", "United States": "USA",
        "Brazil": "BRA", "South Africa": "ZAF", "Nigeria": "NGA",
        "Ghana": "GHA", "Kenya": "KEN", "Egypt": "EGY", "Morocco": "MAR",
        "Tunisia": "TUN", "Indonesia": "IDN", "Vietnam": "VNM",
        "Pakistan": "PAK", "Bangladesh": "BGD", "Mexico": "MEX",
        "Colombia": "COL", "Philippines": "PHL", "Turkey": "TUR",
        "Argentina": "ARG", "Ethiopia": "ETH", "Tanzania": "TZA",
        "Uganda": "UGA", "Zambia": "ZMB", "Cameroon": "CMR",
        "Angola": "AGO", "Mozambique": "MOZ", "Zimbabwe": "ZWE",
    }
    for _k, _v in _IDS_EXTRA_ISO3.items():
        _IDS_NAME_TO_ISO3.setdefault(_k, _v)

    # ════════════════════════════════════════════════════════════════════════
    # SECTION A — IMF WEO
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("### 📡 IMF WEO")

    with st.form("weo_explorer_form"):
        _c1, _c2, _c3 = st.columns([3, 3, 2])
        with _c1:
            _weo_all_countries = get_weo_available_countries()   # {name: iso3}
            _weo_sel = st.multiselect(
                "Countries / Regions",
                options=list(_weo_all_countries.keys()),
                default=["Senegal"],
                help="Select one or more countries or WEO regional aggregates (🌍 World, G7…).",
            )
        with _c2:
            _weo_codes = sorted(WEO_CATALOG.keys())
            _weo_vars = st.multiselect(
                "Variables (select one or more)",
                options=_weo_codes,
                default=["NGDP_RPCH"],
                format_func=lambda c: f"{c}  —  {WEO_CATALOG[c]}",
                help="Select one or more WEO indicators.",
            )
        with _c3:
            _weo_yr = st.slider("Year range", 2000, 2031, (2010, 2031), key="weo_yr_slider")
        _weo_submit = st.form_submit_button(
            "📊 Fetch WEO Data", type="primary", use_container_width=True
        )

    if _weo_submit and _weo_sel and _weo_vars:
        _iso3s     = tuple(_weo_all_countries[n] for n in _weo_sel if n in _weo_all_countries)
        _nm        = tuple((_weo_all_countries[n], n) for n in _weo_sel if n in _weo_all_countries)
        _single_v  = len(_weo_vars) == 1
        _weo_frames, _weo_meta = [], []
        with st.spinner(f"Fetching {len(_weo_vars)} WEO variable(s) for {len(_weo_sel)} country/ies…"):
            for _v in _weo_vars:
                _lbl = WEO_CATALOG.get(_v, _v)
                _df_v = fetch_weo_explorer(_iso3s, _v, _weo_yr[0], _weo_yr[1], name_map=_nm)
                if _df_v.empty:
                    continue
                if not _single_v:
                    _short = _lbl.split("(")[0].strip()
                    _df_v  = _df_v.add_suffix(f" — {_short}")
                _weo_frames.append(_df_v)
                _weo_meta.append({"Variable Code": _v, "Description": _lbl,
                                  "Source": "IMF WEO via imf-reader",
                                  "Year range": f"{_weo_yr[0]}–{_weo_yr[1]}",
                                  "Extracted": pd.Timestamp.now().strftime("%Y-%m-%d")})
        _weo_combined = pd.concat(_weo_frames, axis=1) if _weo_frames else pd.DataFrame()
        _weo_combined.index.name = "Year"
        st.session_state["weo_expl_df"]    = _weo_combined
        st.session_state["weo_expl_meta"]  = _weo_meta
        st.session_state["weo_expl_codes"] = _weo_vars
        st.session_state["weo_expl_yr"]    = _weo_yr

    if st.session_state.get("weo_expl_df") is not None:
        _df    = st.session_state["weo_expl_df"]
        _meta  = st.session_state.get("weo_expl_meta", [])
        _vcodes= st.session_state.get("weo_expl_codes", [])
        _yr    = st.session_state.get("weo_expl_yr", (2010, 2031))

        if not _df.empty:
            _title = "IMF WEO  ·  " + ", ".join(
                f"{c}: {WEO_CATALOG.get(c,c).split('(')[0].strip()}" for c in _vcodes
            )
            _fig = px.line(
                _df.reset_index(), x="Year", y=_df.columns.tolist(),
                title=_title,
                labels={"value": "Value", "variable": "Series"},
            )
            _fig.update_layout(
                height=460, hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            )
            st.plotly_chart(_fig, use_container_width=True)

            st.markdown("**Data table** — column headers show `Country — Indicator` when multiple indicators selected")
            st.dataframe(_df.round(3), use_container_width=True)

            _buf = io.BytesIO()
            with pd.ExcelWriter(_buf, engine="xlsxwriter") as _xw:
                _df.to_excel(_xw, sheet_name="WEO Data")
                if _meta:
                    pd.DataFrame(_meta).to_excel(_xw, sheet_name="Metadata", index=False)
            st.download_button(
                "⬇️  Download Excel",
                data=_buf.getvalue(),
                file_name=f"WEO_{'_'.join(_vcodes[:3])}_{_yr[0]}-{_yr[1]}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            st.warning("No WEO data found for this variable / country combination.")

    st.divider()

    # ════════════════════════════════════════════════════════════════════════
    # SECTION B — World Bank  (WDI  |  IDS)
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("### 🏦 World Bank")
    st.caption(
        "Two databases available: **WDI** (World Development Indicators — broad macro/social) "
        "and **IDS** (International Debt Statistics — detailed creditor-level external debt breakdown, source=6)."
    )

    _wb_db_tab, _ids_db_tab = st.tabs([
        "📈 WDI — World Development Indicators",
        "💰 IDS — International Debt Statistics",
    ])

    # ── shared helper: fetch multi-indicator × multi-country → wide labeled DF ──
    def _fetch_multi_wb(
        iso2_tuple: tuple,
        codes: list,
        catalog: dict,
        yr_range: tuple,
        name_to_iso2: dict,
        selected_names: list,
        sheet_name: str,
        source_label: str,
        state_key: str,
    ):
        """
        Fetch multiple (indicator × country) combinations.
        Returns a wide DataFrame where columns are either:
          - just country name (if single indicator)
          - "Country — Short Indicator Name" (if multiple indicators)
        Also stores metadata list for the Excel download.
        """
        iso2_to_name = {v: k for k, v in name_to_iso2.items()}
        single_ind   = len(codes) == 1

        frames, meta_rows = [], []
        for code in codes:
            label = catalog.get(code, code)
            df_one = fetch_wb_explorer(
                iso2_tuple, code, yr_range[0], yr_range[1],
                name_map=tuple((name_to_iso2[n], n) for n in selected_names if n in name_to_iso2),
            )
            if df_one.empty:
                continue
            if single_ind:
                frames.append(df_one)
            else:
                # Prefix each country column with a short indicator label
                short = label.split("(")[0].strip()   # drop units in parens
                df_one = df_one.add_suffix(f" — {short}")
                # Reorder to group by country: Country A — ind1, Country A — ind2, …
                frames.append(df_one)
            meta_rows.append({
                "Indicator Code": code,
                "Description":    label,
                "Source":         source_label,
                "Year range":     f"{yr_range[0]}–{yr_range[1]}",
                "Extracted":      pd.Timestamp.now().strftime("%Y-%m-%d"),
            })

        if not frames:
            return None, []
        combined = pd.concat(frames, axis=1)
        combined.index.name = "Year"
        return combined, meta_rows

    # ── WDI tab ──────────────────────────────────────────────────────────────
    with _wb_db_tab:
        with st.form("wb_explorer_form"):
            _b1, _b2, _b3 = st.columns([3, 3, 2])
            with _b1:
                _wb_sel = st.multiselect(
                    "Countries",
                    options=sorted(_WB_NAME_TO_ISO2.keys()),
                    default=["Senegal"],
                    help="Includes all LIC countries plus common comparators.",
                )
            with _b2:
                _wb_codes_all = sorted(WB_EXPLORER_CATALOG.keys())
                _wb_preset = st.multiselect(
                    "Indicators (select one or more)",
                    options=_wb_codes_all,
                    default=["NY.GDP.MKTP.KD.ZG"],
                    format_func=lambda c: f"{c}  —  {WB_EXPLORER_CATALOG[c]}",
                    help="Select up to 8 indicators. Hold Ctrl/Cmd to multi-select.",
                )
                _wb_custom = st.text_input(
                    "…or enter any WB indicator code (overrides presets above)",
                    placeholder="e.g. SP.URB.TOTL.IN.ZS",
                )
            with _b3:
                _wb_yr = st.slider("Year range", 1990, 2025, (2005, 2025), key="wb_yr_slider")
            _wb_submit = st.form_submit_button(
                "📊 Fetch WDI Data", type="primary", use_container_width=True
            )

        if _wb_submit and _wb_sel:
            _custom_stripped = _wb_custom.strip()
            _wb_codes_final  = [_custom_stripped] if _custom_stripped else (_wb_preset or ["NY.GDP.MKTP.KD.ZG"])
            _iso2s = tuple(_WB_NAME_TO_ISO2[n] for n in _wb_sel if n in _WB_NAME_TO_ISO2)
            with st.spinner(f"Fetching {len(_wb_codes_final)} WDI indicator(s) for {len(_wb_sel)} country/ies…"):
                _wb_df, _wb_meta = _fetch_multi_wb(
                    _iso2s, _wb_codes_final, WB_EXPLORER_CATALOG,
                    _wb_yr, _WB_NAME_TO_ISO2, _wb_sel,
                    "WDI Data", "World Bank WDI API (api.worldbank.org/v2)", "wdi",
                )
            st.session_state["wb_expl_df"]   = _wb_df
            st.session_state["wb_expl_meta"] = _wb_meta
            st.session_state["wb_expl_codes"]= _wb_codes_final
            st.session_state["wb_expl_yr"]   = _wb_yr
            st.session_state["wb_expl_src"]  = "WDI"

        if st.session_state.get("wb_expl_df") is not None and st.session_state.get("wb_expl_src") == "WDI":
            _df   = st.session_state["wb_expl_df"]
            _meta = st.session_state.get("wb_expl_meta", [])
            _yrcodes = st.session_state.get("wb_expl_codes", [])
            _yr   = st.session_state.get("wb_expl_yr", (2005, 2025))

            if _df is not None and not _df.empty:
                _title = "World Bank WDI  ·  " + ", ".join(
                    f"{c}: {WB_EXPLORER_CATALOG.get(c, c).split('(')[0].strip()}"
                    for c in _yrcodes
                )
                _fig = px.line(
                    _df.reset_index(), x="Year", y=_df.columns.tolist(),
                    title=_title,
                    labels={"value": "Value", "variable": "Series"},
                )
                _fig.update_layout(
                    height=460, hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                )
                st.plotly_chart(_fig, use_container_width=True)

                # Dataframe with indicator labels in header
                st.markdown("**Data table** — column headers show `Country — Indicator`")
                st.dataframe(_df.round(3), use_container_width=True)

                # Excel download
                _buf = io.BytesIO()
                with pd.ExcelWriter(_buf, engine="xlsxwriter") as _xw:
                    _df.to_excel(_xw, sheet_name="WDI Data")
                    if _meta:
                        pd.DataFrame(_meta).to_excel(_xw, sheet_name="Metadata", index=False)
                _fname = f"WDI_{'_'.join(c.replace('.','') for c in _yrcodes[:3])}_{_yr[0]}-{_yr[1]}.xlsx"
                st.download_button(
                    "⬇️  Download Excel",
                    data=_buf.getvalue(),
                    file_name=_fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="wdi_dl_btn",
                )
            else:
                st.warning("No WDI data found for the selected indicators and countries.")

    # ── IDS tab — powered by World Bank DataBank bulk download ───────────────
    with _ids_db_tab:
        st.info(
            "**Full IDS (International Debt Statistics)** — loaded from the World Bank DataBank "
            "bulk file (~26 MB, cached 24 h). Includes **complete creditor-level breakdowns**: "
            "bilateral vs multilateral, official vs private, bonds, commercial banks, "
            "concessional debt, disbursements by creditor, interest & principal by creditor. "
            "~50 key series available; covers most developing countries through 2023–2024."
        )

        _ids_country_opts = sorted(_IDS_NAME_TO_ISO3.keys())

        # Build flat options list in category order, with separator headers
        # Separators start with "── " — filtered out before fetching data
        _IDS_SEP_PREFIX = "── "
        _ids_options_ordered: list[str] = []
        _ids_label_map: dict[str, str] = {}
        for _cat_name, _cat_items in IDS_BULK_CATALOG_GROUPED.items():
            _sep = f"{_IDS_SEP_PREFIX}{_cat_name}"
            _ids_options_ordered.append(_sep)
            _ids_label_map[_sep] = _sep          # header shown as-is
            for _code, _lbl in _cat_items.items():
                _ids_options_ordered.append(_code)
                _ids_label_map[_code] = f"    {_code}  —  {_lbl}"   # indent indicator

        with st.form("ids_explorer_form"):
            _i1, _i2, _i3 = st.columns([3, 3, 2])
            with _i1:
                _ids_sel = st.multiselect(
                    "Countries",
                    options=_ids_country_opts,
                    default=["Senegal"],
                    help="Select one or more countries.",
                )
            with _i2:
                _ids_preset = st.multiselect(
                    "Indicators — grouped by category",
                    options=_ids_options_ordered,
                    default=["DT.DOD.DECT.CD", "DT.DOD.BLAT.CD", "DT.DOD.MLAT.CD"],
                    format_func=lambda c: _ids_label_map.get(c, c),
                    help=(
                        "Scroll through categories: Total Stocks → By Creditor → "
                        "Concessional → By Institution → PV → Debt Service → "
                        "Disbursements → Interest & Principal. "
                        "Category headers (── …) are ignored if accidentally selected."
                    ),
                )
                _ids_custom = st.text_input(
                    "…or any IDS series code (overrides presets)",
                    placeholder="e.g. DT.DIS.OFFT.CD",
                    help="Any DT.* code from the IDS bulk file. Overrides the preset selection above.",
                )
            with _i3:
                _ids_yr = st.slider("Year range", 1990, 2024, (2005, 2023), key="ids_yr_slider")
            _ids_submit = st.form_submit_button(
                "📊 Fetch IDS Data (full creditor breakdown)", type="primary", use_container_width=True
            )

        if _ids_submit and _ids_sel:
            _ids_custom_stripped = _ids_custom.strip()
            if _ids_custom_stripped:
                # Support comma- or space-separated list of custom codes
                _ids_codes_final = [c.strip() for c in _ids_custom_stripped.replace(",", " ").split() if c.strip()]
            else:
                # Strip category-header separators from selected items
                _ids_codes_final = [
                    c for c in (_ids_preset or ["DT.DOD.DECT.CD"])
                    if not c.startswith(_IDS_SEP_PREFIX)
                ]
                if not _ids_codes_final:
                    _ids_codes_final = ["DT.DOD.DECT.CD"]

            _ids_iso3s   = [_IDS_NAME_TO_ISO3[n] for n in _ids_sel if n in _IDS_NAME_TO_ISO3]
            _ids_nm_map  = {_IDS_NAME_TO_ISO3[n]: n for n in _ids_sel if n in _IDS_NAME_TO_ISO3}

            with st.spinner("Loading IDS bulk dataset (~26 MB, cached 24 h)…"):
                _ids_df = query_ids_bulk(
                    iso3_list=_ids_iso3s,
                    series_codes=_ids_codes_final,
                    start=_ids_yr[0],
                    end=_ids_yr[1],
                    name_map=_ids_nm_map,
                    series_labels=IDS_BULK_CATALOG,
                )

            # Build metadata rows
            _ids_meta = [
                {
                    "Series Code": c,
                    "Description": IDS_BULK_CATALOG.get(c, c),
                    "Source": "World Bank IDS DataBank bulk download (databank.worldbank.org)",
                    "Year range": f"{_ids_yr[0]}–{_ids_yr[1]}",
                    "Extracted": pd.Timestamp.now().strftime("%Y-%m-%d"),
                }
                for c in _ids_codes_final
            ]
            st.session_state["ids_expl_df"]   = _ids_df
            st.session_state["ids_expl_meta"] = _ids_meta
            st.session_state["ids_expl_codes"]= _ids_codes_final
            st.session_state["ids_expl_yr"]   = _ids_yr

        if st.session_state.get("ids_expl_df") is not None:
            _df      = st.session_state["ids_expl_df"]
            _meta    = st.session_state.get("ids_expl_meta", [])
            _idscodes= st.session_state.get("ids_expl_codes", [])
            _yr      = st.session_state.get("ids_expl_yr", (2005, 2023))

            if _df is not None and not _df.empty:
                _title = "World Bank IDS  ·  " + ", ".join(
                    IDS_BULK_CATALOG.get(c, c).split("(")[0].strip() for c in _idscodes
                )
                _fig = px.line(
                    _df.reset_index(), x="Year", y=_df.columns.tolist(),
                    title=_title,
                    labels={"value": "Value (current USD or %)", "variable": "Series"},
                )
                _fig.update_layout(
                    height=460, hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                )
                st.plotly_chart(_fig, use_container_width=True)

                st.markdown("**Data table** — columns: `Country` (single indicator) or `Country — Indicator`")
                st.dataframe(_df.round(2), use_container_width=True)

                _buf = io.BytesIO()
                with pd.ExcelWriter(_buf, engine="xlsxwriter") as _xw:
                    _df.to_excel(_xw, sheet_name="IDS Data")
                    if _meta:
                        pd.DataFrame(_meta).to_excel(_xw, sheet_name="Metadata", index=False)
                _fname = f"IDS_{'_'.join(c.replace('.','') for c in _idscodes[:3])}_{_yr[0]}-{_yr[1]}.xlsx"
                st.download_button(
                    "⬇️  Download Excel",
                    data=_buf.getvalue(),
                    file_name=_fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="ids_dl_btn",
                )
            else:
                st.warning(
                    "No IDS data found for the selected indicators and countries. "
                    "Try a broader year range, or check that the country reports to the World Bank IDS system."
                )
