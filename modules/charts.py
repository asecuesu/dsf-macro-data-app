"""
Chart generators for the LIC DSF Tool using Plotly.
"""

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

# ── Color palette ─────────────────────────────────────────────────────────────
COLORS = {
    "baseline":  "#003087",   # IMF Navy
    "stressed":  "#E05206",   # IMF Orange
    "threshold": "#CC0000",   # Red for threshold lines
    "historical":"#595959",   # Gray for historical
    "weak":      "#E05206",
    "medium":    "#F5A623",
    "strong":    "#2E7D32",
    "low":       "#2E7D32",
    "moderate":  "#F5A623",
    "high":      "#E05206",
    "distress":  "#CC0000",
}

TEMPLATE = "plotly_white"


def _add_threshold_line(fig, threshold: float, label: str, row: int = 1, col: int = 1):
    fig.add_hline(
        y=threshold,
        line_dash="dash",
        line_color=COLORS["threshold"],
        line_width=1.5,
        annotation_text=f"  Threshold: {threshold}%",
        annotation_position="top left",
        annotation_font_size=11,
        row=row, col=col,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Composite Indicator chart
# ─────────────────────────────────────────────────────────────────────────────

def plot_ci_gauge(ci_score: float, classification: str, contributions: dict) -> go.Figure:
    """
    Gauge (left) + contribution bar chart (right) for the CI score.
    Uses explicit domain positioning instead of make_subplots to avoid
    Plotly 6.x incompatibility between Indicator and add_hline.
    """
    color = COLORS.get(classification.lower(), COLORS["medium"])

    fig = go.Figure()

    # ── Left half: Indicator gauge ────────────────────────────────────────────
    fig.add_trace(go.Indicator(
        mode="gauge+number",
        value=ci_score,
        domain={"x": [0.0, 0.42], "y": [0.05, 0.95]},
        title={"text": f"<b>{classification}</b><br><span style='font-size:12px'>CI Score</span>",
               "font": {"size": 16}},
        number={"font": {"size": 34, "color": color}, "valueformat": ".3f"},
        gauge={
            "axis": {"range": [0, 4.5], "tickwidth": 1, "tickvals": [0, 2.69, 3.05, 4.5]},
            "bar":  {"color": color, "thickness": 0.25},
            "bgcolor": "white",
            "steps": [
                {"range": [0,    2.69], "color": "#FFE0CC"},   # Weak
                {"range": [2.69, 3.05], "color": "#FFF3CC"},   # Medium
                {"range": [3.05, 4.5],  "color": "#D4EDDA"},   # Strong
            ],
            "threshold": {
                "line": {"color": "black", "width": 2},
                "thickness": 0.75,
                "value": ci_score,
            },
        },
    ))

    # ── Right half: Contribution bar chart ───────────────────────────────────
    labels = list(contributions.keys())
    values = [round(v, 3) for v in contributions.values()]
    bar_colors = [COLORS["baseline"] if v >= 0 else COLORS["stressed"] for v in values]

    fig.add_trace(go.Bar(
        x=labels,
        y=values,
        marker_color=bar_colors,
        text=[f"{v:+.3f}" for v in values],
        textposition="outside",
        name="CI Contribution",
        showlegend=False,
        xaxis="x",
        yaxis="y",
    ))

    # Zero line via shape (avoids add_hline Indicator conflict in Plotly 6)
    fig.add_shape(
        type="line",
        x0=-0.5, x1=len(labels) - 0.5,
        y0=0, y1=0,
        xref="x", yref="y",
        line=dict(color="black", width=0.8),
    )

    # Classification band annotations on bar chart
    fig.add_shape(
        type="line",
        x0=-0.5, x1=len(labels) - 0.5,
        y0=ci_score, y1=ci_score,
        xref="x", yref="y",
        line=dict(color=color, width=1.5, dash="dot"),
    )
    fig.add_annotation(
        text=f"CI = {ci_score:.3f}",
        x=len(labels) - 1, y=ci_score,
        xref="x", yref="y",
        showarrow=False, font={"size": 10, "color": color},
        yshift=8,
    )

    fig.update_layout(
        template=TEMPLATE,
        height=360,
        margin={"t": 60, "b": 40, "l": 40, "r": 20},
        xaxis={"domain": [0.48, 1.0], "title": ""},
        yaxis={"anchor": "x", "title": "Contribution to CI score"},
        title={
            "text": "Composite Indicator & Debt-Carrying Capacity — " + classification,
            "font": {"size": 14},
            "x": 0.5,
        },
        annotations=[
            dict(text="CI Score (Gauge)", x=0.21, y=1.02,
                 xref="paper", yref="paper", showarrow=False,
                 font=dict(size=12, color="#555")),
            dict(text="Component Contributions", x=0.74, y=1.02,
                 xref="paper", yref="paper", showarrow=False,
                 font=dict(size=12, color="#555")),
        ],
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 2. External Debt Indicators Fan Chart
# ─────────────────────────────────────────────────────────────────────────────

def plot_external_indicators(
    ext_baseline: pd.DataFrame,
    thresholds:   dict,
    stress_bands: dict[str, pd.DataFrame] | None = None,
    base_year:    int = 2024,
) -> go.Figure:
    """
    4-panel chart: one subplot per external indicator with threshold lines.
    Optional stress bands (dict of {scenario_name: DataFrame}).
    """
    indicators = [
        ("pv_debt_gdp",     "PV of Debt / GDP",      thresholds["pv_gdp"],      "%"),
        ("pv_debt_exports", "PV of Debt / Exports",  thresholds["pv_exports"],  "%"),
        ("ds_exports",      "Debt Service / Exports",thresholds["ds_exports"],  "%"),
        ("ds_revenues",     "Debt Service / Revenue",thresholds["ds_revenues"], "%"),
    ]

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[i[1] for i in indicators],
        vertical_spacing=0.18,
        horizontal_spacing=0.12,
    )

    positions = [(1, 1), (1, 2), (2, 1), (2, 2)]

    for idx, (col, title, thresh, unit) in enumerate(indicators):
        r, c = positions[idx]

        # Stress bands (envelope)
        if stress_bands:
            all_stress = pd.DataFrame()
            for sc_name, sc_df in stress_bands.items():
                if col in sc_df.columns:
                    all_stress = pd.concat([all_stress, sc_df[[col]].rename(columns={col: sc_name})], axis=1)
            if not all_stress.empty:
                upper = all_stress.max(axis=1)
                lower = all_stress.min(axis=1)
                x_vals  = list(upper.index)
                x_fill  = x_vals + x_vals[::-1]
                y_fill  = list(upper.values) + list(lower.values[::-1])
                fig.add_trace(go.Scatter(
                    x=x_fill, y=y_fill,
                    fill="toself",
                    fillcolor="rgba(224,82,6,0.15)",
                    line={"color": "rgba(255,255,255,0)"},
                    name="Stress Range",
                    showlegend=(idx == 0),
                    legendgroup="stress",
                    hovertemplate="%{y:.1f}%",
                ), row=r, col=c)

            # Most extreme stress line
            if not all_stress.empty:
                worst = all_stress.max(axis=1)
                fig.add_trace(go.Scatter(
                    x=worst.index,
                    y=worst.values,
                    mode="lines",
                    line={"color": COLORS["stressed"], "width": 1.5, "dash": "dot"},
                    name="Most Extreme Stress",
                    showlegend=(idx == 0),
                    legendgroup="worst_stress",
                ), row=r, col=c)

        # Baseline
        if col in ext_baseline.columns:
            series = ext_baseline[col].dropna()
            fig.add_trace(go.Scatter(
                x=series.index,
                y=series.values,
                mode="lines+markers",
                line={"color": COLORS["baseline"], "width": 2.5},
                marker={"size": 6},
                name="Baseline",
                showlegend=(idx == 0),
                legendgroup="baseline",
                hovertemplate=f"%{{y:.1f}}{unit}<extra></extra>",
            ), row=r, col=c)

        # Threshold line
        fig.add_hline(
            y=thresh,
            line_dash="dash",
            line_color=COLORS["threshold"],
            line_width=2,
            row=r, col=c,
            annotation_text=f"  {thresh}%",
            annotation_font_size=10,
            annotation_position="top left",
        )

        # Base year vertical line
        fig.add_vline(
            x=base_year,
            line_dash="dot",
            line_color="gray",
            line_width=1,
            row=r, col=c,
        )

        fig.update_yaxes(ticksuffix="%", row=r, col=c)

    fig.update_layout(
        template=TEMPLATE,
        height=560,
        legend={"orientation": "h", "y": -0.12, "x": 0.5, "xanchor": "center"},
        margin={"t": 60, "b": 80, "l": 50, "r": 20},
        title_text="<b>External PPG Debt Sustainability Indicators</b>",
        title_x=0.5,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 3. Public Debt Chart
# ─────────────────────────────────────────────────────────────────────────────

def plot_public_debt(
    pub_debt_series:  pd.Series,
    pub_benchmark:    float,
    hist_series:      pd.Series | None = None,
    base_year:        int = 2024,
    stressed_series:  pd.Series | None = None,
) -> go.Figure:
    """Line chart of total public debt (% GDP) vs benchmark."""
    fig = go.Figure()

    # Historical
    if hist_series is not None and not hist_series.empty:
        fig.add_trace(go.Scatter(
            x=hist_series.index, y=hist_series.values,
            mode="lines+markers",
            line={"color": COLORS["historical"], "width": 2, "dash": "solid"},
            marker={"size": 5},
            name="Historical",
        ))

    # Projection baseline
    fig.add_trace(go.Scatter(
        x=pub_debt_series.index, y=pub_debt_series.values,
        mode="lines+markers",
        line={"color": COLORS["baseline"], "width": 2.5},
        marker={"size": 7},
        name="Baseline Projection",
    ))

    # Stressed
    if stressed_series is not None and not stressed_series.empty:
        fig.add_trace(go.Scatter(
            x=stressed_series.index, y=stressed_series.values,
            mode="lines",
            line={"color": COLORS["stressed"], "width": 1.5, "dash": "dot"},
            name="Most Extreme Stress",
        ))

    # Benchmark line
    fig.add_hline(
        y=pub_benchmark,
        line_dash="dash",
        line_color=COLORS["threshold"],
        line_width=2,
        annotation_text=f"  Benchmark: {pub_benchmark}% of GDP",
        annotation_position="top left",
        annotation_font_size=11,
    )

    fig.add_vline(
        x=base_year,
        line_dash="dot",
        line_color="gray",
        line_width=1,
        annotation_text="Base Year",
        annotation_position="top right",
        annotation_font_size=10,
    )

    fig.update_layout(
        template=TEMPLATE,
        height=380,
        title="<b>Total Public Debt (% GDP)</b>",
        title_x=0.5,
        yaxis_ticksuffix="%",
        legend={"orientation": "h", "y": -0.18},
        margin={"t": 60, "b": 80, "l": 50, "r": 20},
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 4. Threshold Breach Summary (heat-map bar chart)
# ─────────────────────────────────────────────────────────────────────────────

def plot_threshold_summary(
    baseline_thresholds: list,
    classification:      str,
    stress_tests:        list,
) -> go.Figure:
    """
    Bar chart showing each indicator's value as % of its threshold,
    grouped by Baseline + each stress scenario.
    """
    from modules.country_meta import EXTERNAL_THRESHOLDS

    indicators = ["PV Debt / GDP (%)", "PV Debt / Exports (%)",
                  "Debt Service / Exports (%)", "Debt Service / Revenue (%)"]
    ind_short = ["PV/GDP", "PV/Exp", "DS/Exp", "DS/Rev"]

    # Build matrix: scenarios × indicators
    scenarios = ["Baseline"] + [st.name for st in stress_tests if st.scenario != "historical"]
    matrix    = pd.DataFrame(index=scenarios, columns=ind_short, dtype=float)

    def _fill_row(thresholds, label):
        for t in thresholds:
            for full, short in zip(indicators, ind_short):
                if full == t.indicator:
                    matrix.loc[label, short] = t.pct_of_thresh

    _fill_row(baseline_thresholds, "Baseline")
    for st in stress_tests:
        if st.scenario != "historical":
            _fill_row(st.indicators, st.name)

    fig = go.Figure()
    colors_sc = px.colors.qualitative.Set2
    for i, sc in enumerate(scenarios):
        y_vals = [matrix.loc[sc, col] if not pd.isna(matrix.loc[sc, col]) else 0 for col in ind_short]
        fig.add_trace(go.Bar(
            name=sc,
            x=ind_short,
            y=y_vals,
            marker_color=colors_sc[i % len(colors_sc)],
            text=[f"{v:.0f}%" if v > 0 else "" for v in y_vals],
            textposition="auto",
        ))

    # Reference line at 100%
    fig.add_hline(
        y=100,
        line_dash="dash",
        line_color=COLORS["threshold"],
        line_width=2,
        annotation_text="  100% = Threshold",
        annotation_font_size=11,
    )

    fig.update_layout(
        template=TEMPLATE,
        barmode="group",
        height=400,
        title="<b>Debt Indicators as % of Applicable Threshold</b><br>"
              "<sup>(values above 100% = threshold breached)</sup>",
        title_x=0.5,
        yaxis_ticksuffix="%",
        legend={"orientation": "h", "y": -0.22, "x": 0.5, "xanchor": "center",
                "font": {"size": 10}},
        margin={"t": 80, "b": 100, "l": 50, "r": 20},
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 5. Macro overview charts
# ─────────────────────────────────────────────────────────────────────────────

def plot_macro_overview(df: pd.DataFrame, base_year: int, country: str) -> go.Figure:
    """4-panel macro dashboard: GDP growth, revenue, CA balance, debt."""
    panels = [
        ("gdp_growth",   "Real GDP Growth (%)",         "%"),
        ("gov_rev_gdp",  "Government Revenue (% GDP)", "%"),
        ("ca_gdp",       "Current Account (% GDP)",    "%"),
        ("pub_debt_gdp", "Public Debt (% GDP)",         "%"),
    ]
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[p[1] for p in panels],
        vertical_spacing=0.18,
        horizontal_spacing=0.12,
    )
    positions = [(1,1),(1,2),(2,1),(2,2)]
    for idx, (col, title, unit) in enumerate(panels):
        r, c = positions[idx]
        if col not in df.columns:
            continue
        data = df[col].dropna()
        hist = data[data.index <= base_year]
        proj = data[data.index > base_year]

        if not hist.empty:
            fig.add_trace(go.Bar(
                x=hist.index, y=hist.values,
                name="Historical" if idx == 0 else None,
                showlegend=(idx == 0),
                legendgroup="hist",
                marker_color=COLORS["historical"],
                opacity=0.7,
            ), row=r, col=c)

        if not proj.empty:
            fig.add_trace(go.Scatter(
                x=proj.index, y=proj.values,
                mode="lines+markers",
                name="WEO Projection" if idx == 0 else None,
                showlegend=(idx == 0),
                legendgroup="proj",
                line={"color": COLORS["baseline"], "width": 2},
                marker={"size": 7},
            ), row=r, col=c)

        if col == "ca_gdp":
            fig.add_hline(y=0, line_color="black", line_width=0.5, row=r, col=c)

        fig.update_yaxes(ticksuffix=unit, row=r, col=c)

    fig.update_layout(
        template=TEMPLATE,
        height=520,
        title_text=f"<b>{country} — Macroeconomic Overview</b>",
        title_x=0.5,
        legend={"orientation": "h", "y": -0.12},
        margin={"t": 70, "b": 80, "l": 50, "r": 20},
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# 6. Risk Rating Summary Card (HTML-styled table)
# ─────────────────────────────────────────────────────────────────────────────

def risk_color(rating: str) -> str:
    mapping = {
        "Low": "#2E7D32",
        "Moderate": "#F57F17",
        "High": "#BF360C",
        "In Debt Distress": "#880E4F",
    }
    return mapping.get(rating, "#333333")


def plot_stress_heatmap(stress_tests: list) -> go.Figure:
    """Heat-map of stress test results by indicator."""
    scenario_names = [st.name for st in stress_tests if st.scenario != "historical"]
    all_inds = ["PV Debt / GDP (%)", "PV Debt / Exports (%)",
                "Debt Service / Exports (%)", "Debt Service / Revenue (%)"]

    z_vals  = []
    z_text  = []
    for st in stress_tests:
        if st.scenario == "historical":
            continue
        row_z, row_t = [], []
        for ind_name in all_inds:
            matched = [t for t in st.indicators if t.indicator == ind_name]
            if matched:
                pct = matched[0].pct_of_thresh
                row_z.append(pct)
                row_t.append(f"{pct:.0f}%")
            else:
                row_z.append(0)
                row_t.append("N/A")
        z_vals.append(row_z)
        z_text.append(row_t)

    if not z_vals:
        return go.Figure()

    fig = go.Figure(go.Heatmap(
        z=z_vals,
        x=["PV/GDP", "PV/Exp", "DS/Exp", "DS/Rev"],
        y=scenario_names,
        text=z_text,
        texttemplate="%{text}",
        colorscale=[
            [0,    "#D4EDDA"],
            [0.7,  "#FFF3CD"],
            [1.0,  "#F8D7DA"],
        ],
        zmin=0, zmax=150,
        showscale=True,
        colorbar={"title": "% of Threshold", "ticksuffix": "%"},
    ))

    fig.add_vline(x=2.5, line_color="gray", line_width=0.5, line_dash="dot")

    fig.update_layout(
        template=TEMPLATE,
        height=40 * max(len(scenario_names), 3) + 120,
        title="<b>Stress Test Heat Map (% of Threshold)</b><br>"
              "<sup>Red shading = threshold breached</sup>",
        title_x=0.5,
        margin={"t": 80, "b": 60, "l": 20, "r": 20},
    )
    return fig
