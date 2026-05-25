"""
Country metadata for LIC DSF Tool.
Includes IDA/PRGT-eligible countries with ISO codes and regional groupings.
CPIA scores are the latest available published values (World Bank, 2022–2023).
"""

# ─────────────────────────────────────────────────────────────────────────────
# LIC / IDA-eligible countries with ISO codes
# Format: {"Name": {"iso2": ..., "iso3": ..., "region": ..., "cpia": ...}}
# CPIA: latest available; None = fetch from API or user-specified
# ─────────────────────────────────────────────────────────────────────────────

LIC_COUNTRIES = {
    # Sub-Saharan Africa
    "Benin":                    {"iso2": "BJ", "iso3": "BEN", "region": "SSA",  "cpia": 3.4},
    "Burkina Faso":             {"iso2": "BF", "iso3": "BFA", "region": "SSA",  "cpia": 3.2},
    "Burundi":                  {"iso2": "BI", "iso3": "BDI", "region": "SSA",  "cpia": 2.5},
    "Cameroon":                 {"iso2": "CM", "iso3": "CMR", "region": "SSA",  "cpia": 3.0},
    "Central African Republic": {"iso2": "CF", "iso3": "CAF", "region": "SSA",  "cpia": 2.3},
    "Chad":                     {"iso2": "TD", "iso3": "TCD", "region": "SSA",  "cpia": 2.5},
    "Comoros":                  {"iso2": "KM", "iso3": "COM", "region": "SSA",  "cpia": 2.8},
    "Congo, Dem. Rep.":         {"iso2": "CD", "iso3": "COD", "region": "SSA",  "cpia": 2.5},
    "Congo, Rep.":              {"iso2": "CG", "iso3": "COG", "region": "SSA",  "cpia": 2.4},
    "Cote d'Ivoire":            {"iso2": "CI", "iso3": "CIV", "region": "SSA",  "cpia": 3.4},
    "Eritrea":                  {"iso2": "ER", "iso3": "ERI", "region": "SSA",  "cpia": None},
    "Ethiopia":                 {"iso2": "ET", "iso3": "ETH", "region": "SSA",  "cpia": 3.0},
    "Gambia":                   {"iso2": "GM", "iso3": "GMB", "region": "SSA",  "cpia": 3.1},
    "Ghana":                    {"iso2": "GH", "iso3": "GHA", "region": "SSA",  "cpia": 3.4},
    "Guinea":                   {"iso2": "GN", "iso3": "GIN", "region": "SSA",  "cpia": 2.8},
    "Guinea-Bissau":            {"iso2": "GW", "iso3": "GNB", "region": "SSA",  "cpia": 2.8},
    "Kenya":                    {"iso2": "KE", "iso3": "KEN", "region": "SSA",  "cpia": 3.6},
    "Lesotho":                  {"iso2": "LS", "iso3": "LSO", "region": "SSA",  "cpia": 3.3},
    "Liberia":                  {"iso2": "LR", "iso3": "LBR", "region": "SSA",  "cpia": 3.0},
    "Madagascar":               {"iso2": "MG", "iso3": "MDG", "region": "SSA",  "cpia": 3.0},
    "Malawi":                   {"iso2": "MW", "iso3": "MWI", "region": "SSA",  "cpia": 3.1},
    "Mali":                     {"iso2": "ML", "iso3": "MLI", "region": "SSA",  "cpia": 2.9},
    "Mauritania":               {"iso2": "MR", "iso3": "MRT", "region": "SSA",  "cpia": 3.0},
    "Mozambique":               {"iso2": "MZ", "iso3": "MOZ", "region": "SSA",  "cpia": 2.8},
    "Niger":                    {"iso2": "NE", "iso3": "NER", "region": "SSA",  "cpia": 3.0},
    "Nigeria":                  {"iso2": "NG", "iso3": "NGA", "region": "SSA",  "cpia": 2.8},
    "Rwanda":                   {"iso2": "RW", "iso3": "RWA", "region": "SSA",  "cpia": 3.9},
    "Senegal":                  {"iso2": "SN", "iso3": "SEN", "region": "SSA",  "cpia": 3.7},
    "Sierra Leone":             {"iso2": "SL", "iso3": "SLE", "region": "SSA",  "cpia": 3.0},
    "Somalia":                  {"iso2": "SO", "iso3": "SOM", "region": "SSA",  "cpia": 2.2},
    "South Sudan":              {"iso2": "SS", "iso3": "SSD", "region": "SSA",  "cpia": 1.9},
    "Sudan":                    {"iso2": "SD", "iso3": "SDN", "region": "SSA",  "cpia": 2.1},
    "Tanzania":                 {"iso2": "TZ", "iso3": "TZA", "region": "SSA",  "cpia": 3.4},
    "Togo":                     {"iso2": "TG", "iso3": "TGO", "region": "SSA",  "cpia": 3.2},
    "Uganda":                   {"iso2": "UG", "iso3": "UGA", "region": "SSA",  "cpia": 3.3},
    "Zambia":                   {"iso2": "ZM", "iso3": "ZMB", "region": "SSA",  "cpia": 3.1},
    "Zimbabwe":                 {"iso2": "ZW", "iso3": "ZWE", "region": "SSA",  "cpia": 2.5},

    # South Asia
    "Afghanistan":              {"iso2": "AF", "iso3": "AFG", "region": "SA",   "cpia": 2.2},
    "Bangladesh":               {"iso2": "BD", "iso3": "BGD", "region": "SA",   "cpia": 3.5},
    "Bhutan":                   {"iso2": "BT", "iso3": "BTN", "region": "SA",   "cpia": 4.0},
    "Nepal":                    {"iso2": "NP", "iso3": "NPL", "region": "SA",   "cpia": 3.4},
    "Pakistan":                 {"iso2": "PK", "iso3": "PAK", "region": "SA",   "cpia": 3.0},

    # East Asia & Pacific
    "Cambodia":                 {"iso2": "KH", "iso3": "KHM", "region": "EAP",  "cpia": 3.2},
    "Kiribati":                 {"iso2": "KI", "iso3": "KIR", "region": "EAP",  "cpia": 3.1},
    "Lao PDR":                  {"iso2": "LA", "iso3": "LAO", "region": "EAP",  "cpia": 3.2},
    "Marshall Islands":         {"iso2": "MH", "iso3": "MHL", "region": "EAP",  "cpia": 3.1},
    "Micronesia, Fed. Sts.":    {"iso2": "FM", "iso3": "FSM", "region": "EAP",  "cpia": 3.0},
    "Myanmar":                  {"iso2": "MM", "iso3": "MMR", "region": "EAP",  "cpia": 2.8},
    "Papua New Guinea":         {"iso2": "PG", "iso3": "PNG", "region": "EAP",  "cpia": 3.2},
    "Samoa":                    {"iso2": "WS", "iso3": "WSM", "region": "EAP",  "cpia": 3.5},
    "Solomon Islands":          {"iso2": "SB", "iso3": "SLB", "region": "EAP",  "cpia": 3.2},
    "Timor-Leste":              {"iso2": "TL", "iso3": "TLS", "region": "EAP",  "cpia": 3.0},
    "Tonga":                    {"iso2": "TO", "iso3": "TON", "region": "EAP",  "cpia": 3.5},
    "Tuvalu":                   {"iso2": "TV", "iso3": "TUV", "region": "EAP",  "cpia": 3.2},
    "Vanuatu":                  {"iso2": "VU", "iso3": "VUT", "region": "EAP",  "cpia": 3.3},
    "Vietnam":                  {"iso2": "VN", "iso3": "VNM", "region": "EAP",  "cpia": 3.6},

    # Middle East & North Africa
    "Djibouti":                 {"iso2": "DJ", "iso3": "DJI", "region": "MENA", "cpia": 3.0},
    "Yemen, Rep.":              {"iso2": "YE", "iso3": "YEM", "region": "MENA", "cpia": 2.3},

    # Latin America & Caribbean
    "Bolivia":                  {"iso2": "BO", "iso3": "BOL", "region": "LAC",  "cpia": 3.4},
    "Dominica":                 {"iso2": "DM", "iso3": "DMA", "region": "LAC",  "cpia": 3.5},
    "Grenada":                  {"iso2": "GD", "iso3": "GRD", "region": "LAC",  "cpia": 3.5},
    "Guyana":                   {"iso2": "GY", "iso3": "GUY", "region": "LAC",  "cpia": 3.5},
    "Haiti":                    {"iso2": "HT", "iso3": "HTI", "region": "LAC",  "cpia": 2.5},
    "Honduras":                 {"iso2": "HN", "iso3": "HND", "region": "LAC",  "cpia": 3.3},
    "Nicaragua":                {"iso2": "NI", "iso3": "NIC", "region": "LAC",  "cpia": 3.1},
    "St. Lucia":                {"iso2": "LC", "iso3": "LCA", "region": "LAC",  "cpia": 3.5},
    "St. Vincent & Grenadines": {"iso2": "VC", "iso3": "VCT", "region": "LAC",  "cpia": 3.5},

    # Europe & Central Asia
    "Kosovo":                   {"iso2": "XK", "iso3": "XKX", "region": "ECA",  "cpia": 3.5},
    "Kyrgyz Republic":          {"iso2": "KG", "iso3": "KGZ", "region": "ECA",  "cpia": 3.3},
    "Moldova":                  {"iso2": "MD", "iso3": "MDA", "region": "ECA",  "cpia": 3.5},
    "Tajikistan":               {"iso2": "TJ", "iso3": "TJK", "region": "ECA",  "cpia": 3.0},
    "Uzbekistan":               {"iso2": "UZ", "iso3": "UZB", "region": "ECA",  "cpia": 3.5},
}

# ─────────────────────────────────────────────────────────────────────────────
# Monetary union members — reserves are pooled regionally, not held nationally.
# Country-level reserve data (FI.RES.TOTL.MO) is not available/meaningful.
# ─────────────────────────────────────────────────────────────────────────────

# WAEMU (West African Economic and Monetary Union) — central bank: BCEAO
# Currency: CFA franc (XOF).  All reserves held at BCEAO, Dakar.
WAEMU_ISO3 = {"BEN", "BFA", "CIV", "GNB", "MLI", "NER", "SEN", "TGO"}

# CEMAC (Economic and Monetary Community of Central Africa) — central bank: BEAC
# Currency: CFA franc (XAF).  All reserves held at BEAC, Yaoundé.
CEMAC_ISO3 = {"CMR", "CAF", "TCD", "COG", "GNQ", "GAB"}

# Combined set for any pooled-reserves check
POOLED_RESERVES_ISO3 = WAEMU_ISO3 | CEMAC_ISO3

POOLED_RESERVES_NOTE = {
    "WAEMU": (
        "WAEMU member — reserves are pooled at the BCEAO (Banque Centrale des États "
        "de l'Afrique de l'Ouest) and not held at country level. "
        "Country-specific import-coverage data is not reported."
    ),
    "CEMAC": (
        "CEMAC member — reserves are pooled at the BEAC (Banque des États de "
        "l'Afrique Centrale) and not held at country level. "
        "Country-specific import-coverage data is not reported."
    ),
}

# Classification cutoffs from LIC DSF 2017
CI_CUTOFF_WEAK_MEDIUM = 2.69
CI_CUTOFF_MEDIUM_STRONG = 3.05

# LIC DSF Thresholds by classification (2017 revised framework)
# External PPG debt thresholds
EXTERNAL_THRESHOLDS = {
    "Weak":   {"pv_gdp": 30,  "pv_exports": 140, "ds_exports": 10, "ds_revenues": 14},
    "Medium": {"pv_gdp": 40,  "pv_exports": 180, "ds_exports": 15, "ds_revenues": 18},
    "Strong": {"pv_gdp": 55,  "pv_exports": 240, "ds_exports": 21, "ds_revenues": 23},
}

# Total public debt benchmark (% of GDP) — informational, not binding threshold
PUBLIC_BENCHMARKS = {
    "Weak":   35,
    "Medium": 55,
    "Strong": 70,
}

# CI formula coefficients (from 2017 LIC DSF probit regressions)
CI_COEFFICIENTS = {
    "cpia":          0.385,
    "gdp_growth":    0.02719,    # real GDP growth (%)
    "reserves":      0.04052,    # import coverage of reserves (months)
    "reserves_sq":  -0.03990,    # reserves squared
    "remittances":   0.02022,    # remittances (% GDP)
    "world_growth":  0.13520,    # world real GDP growth (%)
}

# Stress test parameters
STRESS_TESTS = {
    "gdp_shock": {
        "name": "Real GDP Growth Shock",
        "description": "GDP growth set to min(hist avg − 1SD, proj avg − 1SD) in years 2–3",
        "years": [1, 2],    # 0-indexed projection years
        "type": "external+public",
    },
    "exports_shock": {
        "name": "Exports Shock",
        "description": "Export growth set to min(hist avg − 1SD, proj avg − 1SD) in years 2–3",
        "years": [1, 2],
        "type": "external",
    },
    "other_flows": {
        "name": "Other Flows Shock",
        "description": "Transfers and FDI set to min(hist avg − 1SD, proj avg − 1SD) in years 2–3",
        "years": [1, 2],
        "type": "external",
    },
    "depreciation": {
        "name": "Exchange Rate Depreciation",
        "description": "One-time 30% nominal depreciation in year 2",
        "years": [1],
        "type": "external",
    },
    "pb_shock": {
        "name": "Primary Balance Shock",
        "description": "Primary balance set to min(hist avg − 1SD, proj avg − 1SD) in years 2–3",
        "years": [1, 2],
        "type": "public",
    },
    "combination": {
        "name": "Combination Shock",
        "description": "All shocks at half magnitude simultaneously",
        "years": [1, 2],
        "type": "external+public",
    },
    "contingent": {
        "name": "Contingent Liability Shock",
        "description": "One-off addition of ≥5% of GDP to public debt",
        "years": [0],
        "type": "public",
    },
}

# IMF DataMapper indicators needed
WEO_INDICATORS = {
    "NGDPD":         "GDP, Current Prices (USD Billions)",
    "NGDP_RPCH":     "Real GDP Growth (%)",
    "NGDP_D":        "GDP Deflator (% change)",
    "GGR_NGDP":      "General Gov. Revenue (% GDP)",
    "GGXONLB_NGDP":  "Primary Balance (% GDP)",
    "GGXWDG_NGDP":   "General Gov. Gross Debt (% GDP)",
    "BCA_NGDPD":     "Current Account Balance (% GDP)",
    "BM":            "Imports of Goods & Services (USD Billions)",
    "BX":            "Exports of Goods & Services (USD Billions)",
    "NID_NGDP":      "Total Investment (% GDP)",
}

# World Bank / IDS indicators needed
WB_INDICATORS = {
    "DT.DOD.DPPG.CD":       "PPG External Debt Stocks (current USD)",
    "DT.DOD.PVLX.CD":       "PV of External Debt (current USD)",
    "DT.DOD.PVLX.EX.ZS":   "PV of Debt / Exports (%)",
    "DT.DOD.PVLX.GN.ZS":   "PV of Debt / GNI (%)",
    "DT.TDS.DPPG.CD":       "PPG Debt Service (current USD)",
    "DT.TDS.DPPG.EX.ZS":   "Debt Service / Exports (%)",
    "DT.INT.DPPG.CD":       "PPG Interest Payments (current USD)",
    "DT.AMT.DPPG.CD":       "PPG Principal Repayments (current USD)",
    "BX.TRF.PWKR.DT.GD.ZS": "Remittances (% GDP)",
    "FI.RES.TOTL.MO":       "Reserves (months of imports)",
    "BX.GSR.GNFS.CD":       "Exports of Goods & Services (current USD)",
    "BM.GSR.GNFS.CD":       "Imports of Goods & Services (current USD)",
    "IQ.CPA.ECON.XQ":       "CPIA - Economic Management",
    "IQ.CPA.STRC.XQ":       "CPIA - Structural Policies",
    "IQ.CPA.POLS.XQ":       "CPIA - Social Inclusion/Equity",
    "IQ.CPA.PUBS.XQ":       "CPIA - Public Sector Management",
    "NY.GDP.MKTP.CD":       "GDP (current USD)",
    "GC.REV.XGRT.GD.ZS":   "Government Revenue (% GDP)",
}
