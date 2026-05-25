"""
Excel report generator for LIC DSF assessments.
Produces a structured workbook matching IMF/WB DSA report conventions.
"""

import io
import pandas as pd
import numpy as np
from datetime import datetime

try:
    import xlsxwriter
    HAS_XLSX = True
except ImportError:
    HAS_XLSX = False


def _write_header(ws, row: int, text: str, fmt) -> int:
    ws.write(row, 0, text, fmt)
    return row + 1


def generate_excel_report(
    country_name:     str,
    ci_result,
    dsa_results:      dict,
    df_macro:         pd.DataFrame,
    base_year:        int,
    analyst:          str = "",
) -> bytes:
    """
    Generate a multi-sheet Excel DSA report.
    Returns bytes (file contents) for st.download_button.
    """
    if not HAS_XLSX:
        raise ImportError("xlsxwriter not installed")

    output = io.BytesIO()
    wb     = xlsxwriter.Workbook(output, {"in_memory": True})

    # ── Formats ──────────────────────────────────────────────────────────────
    title_fmt = wb.add_format({
        "bold": True, "font_size": 14, "font_color": "#003087",
        "align": "left", "valign": "vcenter", "border": 0,
    })
    header_fmt = wb.add_format({
        "bold": True, "bg_color": "#003087", "font_color": "white",
        "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True,
    })
    sub_fmt = wb.add_format({
        "bold": True, "bg_color": "#E8EAF6", "font_color": "#003087",
        "border": 1, "align": "left",
    })
    num_fmt   = wb.add_format({"num_format": "#,##0.0",  "border": 1, "align": "right"})
    pct_fmt   = wb.add_format({"num_format": "0.0\"%\"", "border": 1, "align": "right"})
    txt_fmt   = wb.add_format({"border": 1, "align": "left"})
    red_fmt   = wb.add_format({"bg_color": "#FFCCCC", "bold": True, "border": 1, "align": "right", "num_format": "0.0"})
    green_fmt = wb.add_format({"bg_color": "#CCFFCC", "border": 1, "align": "right", "num_format": "0.0"})
    orange_fmt= wb.add_format({"bg_color": "#FFE4B5", "border": 1, "align": "right", "num_format": "0.0"})

    def _cell_fmt(value, threshold, higher_is_worse=True):
        if pd.isna(value):
            return num_fmt
        if higher_is_worse:
            ratio = value / threshold
            if ratio >= 1.0:
                return red_fmt
            elif ratio >= 0.8:
                return orange_fmt
            return green_fmt
        return num_fmt

    today = datetime.today().strftime("%B %d, %Y")

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 1: Cover / Summary
    # ════════════════════════════════════════════════════════════════════════
    ws_cov = wb.add_worksheet("Summary")
    ws_cov.set_column(0, 0, 38)
    ws_cov.set_column(1, 5, 18)

    ws_cov.write(0, 0, f"LIC DSF ASSESSMENT — {country_name.upper()}", title_fmt)
    ws_cov.write(1, 0, f"Date: {today}  |  Analyst: {analyst or 'Auto-generated'}  |  Base Year: {base_year}")
    ws_cov.write(2, 0, "Framework: IMF/World Bank LIC DSF (2017 Revised)", wb.add_format({"italic": True}))

    # Rating box
    rating     = dsa_results["rating"]
    ci         = dsa_results["ci"]
    r_color    = {"Low": "#C8E6C9", "Moderate": "#FFF9C4", "High": "#FFCCBC", "In Debt Distress": "#F8BBD0"}
    r_fmt_cell = wb.add_format({
        "bg_color": r_color.get(rating.final_rating, "#FFFFFF"),
        "bold": True, "font_size": 16, "align": "center", "valign": "vcenter",
        "border": 2,
    })
    ws_cov.merge_range(4, 0, 6, 2, f"Risk Rating: {rating.final_rating}", r_fmt_cell)

    ci_cls_fmt = wb.add_format({
        "bg_color": "#E8EAF6", "bold": True, "font_size": 13,
        "align": "center", "valign": "vcenter", "border": 2,
    })
    ws_cov.merge_range(4, 3, 6, 5, f"Classification: {ci.classification}\nCI Score: {ci.ci_score:.3f}", ci_cls_fmt)

    # Key indicators table
    row = 8
    ws_cov.write_row(row, 0, ["Indicator", "Peak Value", "Threshold", "% of Threshold", "Breached?"], header_fmt)
    row += 1
    for t in dsa_results["baseline_thresholds"]:
        cols = [t.indicator, t.value, t.threshold, t.pct_of_thresh, "YES" if t.breached else "NO"]
        fmt_v = _cell_fmt(t.value, t.threshold)
        ws_cov.write(row, 0, t.indicator, txt_fmt)
        ws_cov.write(row, 1, t.value,        fmt_v)
        ws_cov.write(row, 2, t.threshold,    num_fmt)
        ws_cov.write(row, 3, t.pct_of_thresh,fmt_v)
        ws_cov.write(row, 4, "YES" if t.breached else "NO",
                     red_fmt if t.breached else green_fmt)
        row += 1

    # Public debt
    pt = dsa_results["pub_threshold"]
    ws_cov.write(row, 0, pt.indicator, txt_fmt)
    ws_cov.write(row, 1, pt.value,    _cell_fmt(pt.value, pt.threshold))
    ws_cov.write(row, 2, pt.threshold, num_fmt)
    ws_cov.write(row, 3, pt.pct_of_thresh, _cell_fmt(pt.value, pt.threshold))
    ws_cov.write(row, 4, "YES" if pt.breached else "NO",
                 red_fmt if pt.breached else green_fmt)
    row += 2

    # Key drivers
    ws_cov.write(row, 0, "Key Risk Drivers:", sub_fmt)
    row += 1
    for driver in rating.key_drivers:
        ws_cov.write(row, 0, f"• {driver}", txt_fmt)
        row += 1

    if rating.granularity:
        ws_cov.write(row + 1, 0, f"Moderate Risk Granularity: {rating.granularity}", sub_fmt)

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 2: Composite Indicator
    # ════════════════════════════════════════════════════════════════════════
    ws_ci = wb.add_worksheet("Composite Indicator")
    ws_ci.set_column(0, 0, 35)
    ws_ci.set_column(1, 3, 20)

    ws_ci.write(0, 0, "COMPOSITE INDICATOR (CI) CALCULATION", title_fmt)
    ws_ci.write_row(2, 0, ["Parameter", "Value", "Coefficient", "Contribution"], header_fmt)

    rows_ci = [
        ("CPIA Score",                  ci.cpia,          0.385,   ci.contributions.get("CPIA", 0)),
        ("10yr Avg Real GDP Growth (%)", ci.avg_growth,    0.02719, ci.contributions.get("GDP Growth", 0)),
        ("10yr Avg Reserves (months)",  ci.avg_reserves,  0.04052, ci.contributions.get("Reserves", 0)),
        ("10yr Avg Remittances (% GDP)",ci.avg_remit,     0.02022, ci.contributions.get("Remittances", 0)),
        ("10yr Avg World Growth (%)",   ci.avg_world_g,   0.13520, ci.contributions.get("World Growth", 0)),
    ]
    for i, (param, val, coeff, contrib) in enumerate(rows_ci):
        ws_ci.write(3 + i, 0, param,   txt_fmt)
        ws_ci.write(3 + i, 1, round(val, 3) if val else "N/A",  num_fmt)
        ws_ci.write(3 + i, 2, coeff,   num_fmt)
        ws_ci.write(3 + i, 3, round(contrib, 3), num_fmt)

    ws_ci.write(9,  0, "CI SCORE",      sub_fmt)
    ws_ci.write(9,  1, ci.ci_score,     num_fmt)
    ws_ci.write(10, 0, "Classification",sub_fmt)
    ws_ci.write(10, 1, ci.classification, txt_fmt)
    ws_ci.write(12, 0, "Cutoffs: Weak < 2.69 ≤ Medium ≤ 3.05 < Strong", wb.add_format({"italic": True}))

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 3: Macro Data
    # ════════════════════════════════════════════════════════════════════════
    ws_mac = wb.add_worksheet("Macro Data")
    ws_mac.write(0, 0, f"MACROECONOMIC DATA — {country_name}", title_fmt)

    macro_cols = [
        ("gdp_usd",       "GDP (USD bn)"),
        ("gdp_growth",    "Real GDP Growth (%)"),
        ("gdp_deflator",  "GDP Deflator (% chg)"),
        ("gov_rev_gdp",   "Govt Revenue (% GDP)"),
        ("pbal_gdp",      "Primary Balance (% GDP)"),
        ("pub_debt_gdp",  "Public Debt (% GDP)"),
        ("ca_gdp",        "Current Account (% GDP)"),
        ("reserves_months","Reserves (months imports)"),
        ("remittances_gdp","Remittances (% GDP)"),
    ]
    display_df = df_macro[[c for c, _ in macro_cols if c in df_macro.columns]].copy()
    display_df.columns = [lbl for c, lbl in macro_cols if c in df_macro.columns]

    # Write header
    ws_mac.write(2, 0, "Year", header_fmt)
    for j, col in enumerate(display_df.columns):
        ws_mac.write(2, j + 1, col, header_fmt)
        ws_mac.set_column(j + 1, j + 1, 18)

    for i, (yr, row_data) in enumerate(display_df.iterrows()):
        is_proj = yr > base_year
        yr_fmt  = wb.add_format({"bold": True, "bg_color": "#F0F4FF" if is_proj else "#FFFFFF", "border": 1})
        ws_mac.write(3 + i, 0, yr, yr_fmt)
        for j, val in enumerate(row_data.values):
            ws_mac.write(3 + i, j + 1,
                         round(float(val), 2) if not pd.isna(val) else "",
                         wb.add_format({"num_format": "0.00", "border": 1,
                                        "bg_color": "#F0F4FF" if is_proj else "#FFFFFF"}))

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 4: External DSA
    # ════════════════════════════════════════════════════════════════════════
    ws_ext = wb.add_worksheet("External DSA")
    ws_ext.set_column(0, 0, 8)
    ws_ext.set_column(1, 4, 22)

    ws_ext.write(0, 0, "EXTERNAL PPG DEBT INDICATORS", title_fmt)
    thresh = dsa_results["thresholds"]
    ws_ext.write(2, 0, f"Classification: {ci.classification}", sub_fmt)
    ws_ext.write_row(3, 0, ["PV Debt/GDP threshold:", thresh["pv_gdp"], "% of GDP"])
    ws_ext.write_row(4, 0, ["PV Debt/Exports threshold:", thresh["pv_exports"], "%"])
    ws_ext.write_row(5, 0, ["DS/Exports threshold:", thresh["ds_exports"], "%"])
    ws_ext.write_row(6, 0, ["DS/Revenues threshold:", thresh["ds_revenues"], "%"])

    ext_df = dsa_results["ext_indicators"]
    if not ext_df.empty:
        ws_ext.write_row(8, 0, ["Year", "PV Debt/GDP (%)", "PV Debt/Exports (%)",
                                  "DS/Exports (%)", "DS/Revenue (%)"], header_fmt)
        for i, (yr, row_data) in enumerate(ext_df.iterrows()):
            ws_ext.write(9 + i, 0, yr, txt_fmt)
            for j, (col, lim_key) in enumerate(
                [("pv_debt_gdp","pv_gdp"),("pv_debt_exports","pv_exports"),
                 ("ds_exports","ds_exports"),("ds_revenues","ds_revenues")]
            ):
                val = row_data.get(col, np.nan)
                lim = thresh[lim_key]
                fmt = _cell_fmt(val if not pd.isna(val) else 0, lim)
                ws_ext.write(9 + i, j + 1, round(float(val), 1) if not pd.isna(val) else "", fmt)

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 5: Stress Tests
    # ════════════════════════════════════════════════════════════════════════
    ws_st = wb.add_worksheet("Stress Tests")
    ws_st.set_column(0, 0, 30)
    ws_st.set_column(1, 5, 20)

    ws_st.write(0, 0, "STRESS TEST RESULTS", title_fmt)
    ws_st.write_row(2, 0, [
        "Scenario", "PV/GDP (% thresh)", "PV/Exp (% thresh)",
        "DS/Exp (% thresh)", "DS/Rev (% thresh)", "Any Breach?",
    ], header_fmt)

    ind_keys = {
        "PV Debt / GDP (%)":       1,
        "PV Debt / Exports (%)":   2,
        "Debt Service / Exports (%)": 3,
        "Debt Service / Revenue (%)": 4,
    }
    for i, st in enumerate(dsa_results["stress_tests"]):
        ws_st.write(3 + i, 0, st.name, txt_fmt)
        for t in st.indicators:
            col_idx = ind_keys.get(t.indicator)
            if col_idx:
                fmt = red_fmt if t.breached else green_fmt
                ws_st.write(3 + i, col_idx, round(t.pct_of_thresh, 1), fmt)
        ws_st.write(3 + i, 5, "YES" if st.any_breach else "NO",
                    red_fmt if st.any_breach else green_fmt)

    # ════════════════════════════════════════════════════════════════════════
    # Sheet 6: Notes & Methodology
    # ════════════════════════════════════════════════════════════════════════
    ws_notes = wb.add_worksheet("Methodology")
    ws_notes.set_column(0, 0, 100)
    notes = [
        "LIC DSF METHODOLOGY NOTES",
        "",
        "Framework: IMF/World Bank Debt Sustainability Framework for Low-Income Countries (2017 revised)",
        "Document reference: IMF Policy Paper SM/17/292 and World Bank companion paper",
        "",
        "COMPOSITE INDICATOR (CI):",
        "  CI = 0.385×CPIA + 0.02719×g + 0.04052×reserves − 0.03990×reserves² + 0.02022×remittances + 0.13520×gw",
        "  Window: 5-year historical + 5-year WEO projection (10-year average)",
        "  Cutoffs: Weak < 2.69 ≤ Medium ≤ 3.05 < Strong",
        "",
        "EXTERNAL PPG DEBT THRESHOLDS:",
        "  Indicator             | Weak | Medium | Strong",
        "  PV Debt / GDP         |  30% |   40%  |  55%",
        "  PV Debt / Exports     | 140% |  180%  | 240%",
        "  DS / Exports          |  10% |   15%  |  21%",
        "  DS / Revenue          |  14% |   18%  |  23%",
        "",
        "PUBLIC DEBT BENCHMARK (total public debt/GDP):",
        "  Weak: 35% | Medium: 55% | Strong: 70%",
        "",
        "RISK RATING LOGIC:",
        "  Low         = No threshold breach under baseline or any stress test",
        "  Moderate    = No breach under baseline; breach(es) only under stress",
        "  High        = Breach under baseline",
        "  In Distress = Active restructuring/arrears or significant sustained breach",
        "",
        "STRESS TESTS (standardized):",
        "  1. Historical Scenario — all key variables set to 10yr historical averages",
        "  2. Real GDP Growth Shock — growth set to min(hist avg − 1SD, proj avg − 1SD) in years 2–3",
        "  3. Export Growth Shock — export growth set to min(hist avg − 1SD, proj avg − 1SD) in years 2–3",
        "  4. Other Flows Shock — remittances/FDI set to min(hist avg − 1SD) in years 2–3",
        "  5. Exchange Rate Depreciation — one-time 30% nominal depreciation in year 2",
        "  6. Combination Shock — all shocks at 50% magnitude simultaneously",
        "  7. Contingent Liability Shock — one-off addition of ≥5% of GDP to public debt",
        "",
        "DATA SOURCES:",
        "  - IMF World Economic Outlook (WEO) DataMapper API: www.imf.org/external/datamapper/api/v1",
        "  - World Bank International Debt Statistics (IDS/DSSI): api.worldbank.org/v2",
        "  - CPIA scores: World Bank CPIA database (annual, published July)",
        "",
        f"Report generated: {datetime.today().strftime('%Y-%m-%d %H:%M')}",
        "Tool: LIC DSF Assessment Tool v1.0 (Streamlit/Python)",
    ]
    for i, line in enumerate(notes):
        ws_notes.write(i, 0, line,
                       title_fmt if i == 0 else wb.add_format({"font_name": "Courier New", "font_size": 9}))

    wb.close()
    output.seek(0)
    return output.read()
