"""
Who Makes It to Formula 1? - Streamlit app

"""

import json
from pathlib import Path
from datetime import date

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import design as D

DATA = Path(__file__).resolve().parent / "data"
REPO_URL = "https://github.com/thandovelempini/f1-talent-pipeline.git"

RQ1_COLOUR = D.RQ1
RQ2_COLOUR = D.RQ2
GREY = "#9ca3af"

STRICT = "strict 5-year horizon"
REACHED_TIERS = ["Star", "Established", "Reached, didn't stick", "Too early to tell"]
ENTRANT_TIERS = ["Star", "Established", "Reached, didn't stick"]

OUTCOME_LABELS = {
    "Star": "Star",
    "Established": "Established",
    "Reached, didn't stick": "Reached, did not stick",
    "Didn't reach F1": "Did not reach F1",
    "Too early to tell": "Too early to classify",
    "Pending": "Pending",
    "Excluded: career cut short": "Excluded: Career cut short",
    "Excluded: f1 before junior": "Excluded: F1 before junior",
}
FEATURE_LABELS = {
    "performance": "Performance only",
    "+ age": "+ Age",
    "+ team strength": "+ Team strength",
    "+ age + team strength": "+ Age + Team strength",
    "team strength only": "Team strength only",
}
COMPARISON_LABELS = {
    "team strength beyond performance + age": "Team strength beyond performance + Age",
    "age beyond performance + team strength": "Age beyond performance + Team strength",
    "team strength alone vs performance alone": "Team strength alone vs Performance alone",
}


def outcome_label(outcome):
    if not isinstance(outcome, str):
        return ""
    return OUTCOME_LABELS.get(outcome, outcome)

st.set_page_config(page_title="Who Makes It to F1?", page_icon="🏁", layout="wide")


# Data
def to_bool(series):
    return series.astype(str).str.lower().isin(["true", "1", "1.0", "t"])


@st.cache_data
def load():
    drivers = pd.read_csv(DATA / "drivers.csv")
    seasons = pd.read_csv(DATA / "junior_seasons.csv")
    preds = pd.read_csv(DATA / "predictions.csv")
    stages = pd.read_csv(DATA / "stages.csv")
    meta = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
    res = {}
    for name in ["experiment_results", "experiment_chronological",
                 "experiment_composition", "experiment_sensitivity"]:
        path = DATA / f"{name}.csv"
        res[name] = pd.read_csv(path) if path.exists() else pd.DataFrame()

    drivers["reached_f1"] = drivers["f1_starts"].fillna(0) > 0
    seasons["season_in_progress"] = to_bool(seasons["season_in_progress"])
    seasons = seasons.merge(drivers[["driver_key", "outcome", "reached_f1"]], on="driver_key", how="left")
    preds["season_in_progress"] = to_bool(preds["season_in_progress"])
    preds["known_reached"] = to_bool(preds["reached_f1"])
    return drivers, seasons, preds, stages, meta, res


drivers, seasons, preds, stages, meta, R = load()
CURRENT = meta["current_season"]


# Helpers
def show_table(df, **kwargs):
    try:
        st.dataframe(df, hide_index=True, width="stretch", **kwargs)
    except Exception:
        st.dataframe(df, hide_index=True, use_container_width=True, **kwargs)


def show_chart(chart):
    chart = (chart.configure(font="Barlow", background="transparent")
             .configure_view(strokeWidth=0)
             .configure_axis(gridColor="#24242E", domainColor=D.LINE, tickColor=D.LINE, labelColor=D.MUTED,
                             titleColor=D.MUTED, labelFontSize=12, titleFontSize=13, titleFontWeight=500)
             .configure_axisX(labelAngle=0, labelLimit=200, labelFlush=False, labelAlign="center")
             .configure_axisY(labelLimit=320, labelFlush=False, labelBaseline="middle")
             .configure_legend(labelColor=D.MUTED, titleColor=D.TEXT, labelFontSize=12, titleFontSize=13))
    try:
        st.altair_chart(chart, width="stretch")
    except Exception:
        st.altair_chart(chart, use_container_width=True)


def table_height(n_rows):
    return 38 + 35 * n_rows


def blank_missing(df):
    out = df.copy()
    for col in out.columns:
        if out[col].isna().any():
            out[col] = out[col].astype(object).map(
                lambda v: "–" if pd.isna(v) else str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))
    return out


def share_histogram(df, field, colours, step=10, height=280, padding=None):
    d = df.dropna(subset=[field]).copy()

    edges = list(range(0, 100 + step, step))
    labels = [f"{a}–{a + step}" for a in edges[:-1]]

    d["band"] = pd.cut(
        d[field],
        bins=edges,
        labels=labels,
        include_lowest=True
    )

    counts = (
        d.groupby(["Group", "band"], observed=False)
        .size()
        .rename("n")
        .reset_index()
    )

    counts["share"] = counts["n"] / counts.groupby("Group")["n"].transform("sum")
    counts["band"] = counts["band"].astype(str)

    chart = alt.Chart(counts).mark_bar().encode(
        x=alt.X("band:N", sort=labels, title="Performance rating"),
        xOffset=alt.XOffset("Group:N"),
        y=alt.Y("share:Q", title="Share of group", axis=alt.Axis(format="%")),
        color=alt.Color("Group:N", scale=colours, title=None),
        tooltip=[alt.Tooltip("Group:N", title="Group"), alt.Tooltip("band:N", title="Rating band"),
                 alt.Tooltip("share:Q", format=".0%", title="Share of group"), alt.Tooltip("n:Q", title="Seasons")],
    )

    properties = {"height": height}

    if padding is not None:
        properties["padding"] = padding

    return chart.properties(**properties)

NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


def words(n):
    return NUMBER_WORDS[n] if 0 <= n < len(NUMBER_WORDS) else str(n)


def pct(x):
    return "" if pd.isna(x) else f"{x:.0%}"


def interval(low, high):
    return "" if pd.isna(low) else f"{low:.0%} – {high:.0%}"


def stage_label(k):
    return {1: "Rookie season", 2: "Second season", 3: "Third season"}.get(int(k), f"Season {int(k)}")


def result_row(table, **match):
    if table.empty:
        return None
    mask = pd.Series(True, index=table.index)
    for col, val in match.items():
        if col not in table.columns:
            return None
        mask &= table[col] == val
    rows = table[mask]
    return None if rows.empty else rows.iloc[0]


def auc_text(row, low="ci_low", high="ci_high"):
    if row is None:
        return "n/a"
    return f"{row['auc']:.2f} ({row[low]:.2f}–{row[high]:.2f})"


def dot_whisker(df, y, colour_field=None, colour_scale=None, low="ci_low", high="ci_high", height=260,
                domain=(0.3, 1), offset=True):
    base = alt.Chart(df).encode(y=alt.Y(f"{y}:N", title=None, sort=None))
    enc = {}
    if colour_field:
        enc["color"] = alt.Color(f"{colour_field}:N", title=None, scale=colour_scale)
        if offset:
            enc["yOffset"] = alt.YOffset(f"{colour_field}:N")
    rules = base.mark_rule(strokeWidth=2, clip=True).encode(
        x=alt.X(f"{low}:Q", title="AUC (0.5 = chance)", scale=alt.Scale(domain=list(domain)),
                axis=alt.Axis(tickCount=8)),
        x2=f"{high}:Q", **enc)
    dots = base.mark_circle(size=110, opacity=1, clip=True).encode(
        x="auc:Q", tooltip=[alt.Tooltip(f"{y}:N", title="Model"), alt.Tooltip("auc:Q", format=".3f", title="AUC"),
                            alt.Tooltip(f"{low}:Q", format=".3f", title="Lower 95% bound"),
                            alt.Tooltip(f"{high}:Q", format=".3f", title="Upper 95% bound")],
        **enc)
    chance = alt.Chart(pd.DataFrame({"x": [0.5]})).mark_rule(strokeDash=[4, 4], color=GREY).encode(x="x:Q")
    return (rules + dots + chance).properties(height=height)


# Navigation
PAGES = ["Overview", "Reaching F1", "Establishing in F1", "Driver Explorer",
         "Junior Performance", "Methodology"]
ACTIVE = {"Reaching F1": (D.RQ1_HERO, "#FFFFFF"), "Establishing in F1": (D.RQ2, "#1A1206")}
asked = st.query_params.get("page")
if asked in PAGES:
    st.session_state.page = asked
    del st.query_params["page"]
if "page" not in st.session_state:
    st.session_state.page = "Overview"
st.markdown(D.page_css(*ACTIVE.get(st.session_state.page, (D.TEXT, D.BG))), unsafe_allow_html=True)
brand, nav = st.columns([1.3, 6], vertical_alignment="center")
brand.markdown('<div class="brand">WHO MAKES IT?</div>', unsafe_allow_html=True)
nav.radio("Go to", PAGES, key="page", horizontal=True, label_visibility="collapsed")


def footer():
    st.divider()
    st.caption(f"**Junior seasons:** GP2 (2005–2016) and Formula 2 (2017–{CURRENT}). "
               f"**F1 seasons:** 2000–{CURRENT}. "
               f"**Data last updated:** {date.today():%d %B %Y}. "
               f"The {CURRENT} season remains provisional until completion.")
    st.caption("**Data sources:** GP2 and Formula 2 standings from [Wikipedia](https://en.wikipedia.org) (CC BY-SA 4.0), "
               "F1 results from the [Jolpica-F1 API](https://github.com/jolpica/jolpica-f1), "
               "and dates of birth and nationalities from [Wikidata](https://www.wikidata.org) (CC0). "
               "Flags from [flagcdn.com](https://flagcdn.com). \n\n"
               f"**Built by Thando Velempini**")


def num(row, col):
    if row is None or col not in row.index or pd.isna(row[col]):
        return None
    return float(row[col])


def gain_of(row, base):
    delta = num(row, "delta")
    if delta is None:
        delta = row["auc"] - base["auc"]
    verdict = row["helps"] if "helps" in row.index and isinstance(row["helps"], str) else ""
    return D.gain_chip(delta, verdict)


def whole_age(ages):
    return np.floor(ages).astype("Int64")


def pos_label(x):
    text = "" if pd.isna(x) else str(x)
    return D.escape(f"P{text}" if text.isdigit() else text)


STAGE_NAMES = {"end of season 1": "Rookie season", "end of season 2": "Second season",
               "end of season 3": "Third season"}


def stage_name(point):
    return STAGE_NAMES.get(point, point.replace("end of ", "").capitalize())


def point_label(point):
    return "End of " + stage_name(point).lower()


def model_name(features):
    label = FEATURE_LABELS.get(features, features.capitalize())
    return "Performance " + label if features.startswith("+") else label


def place_labels(pts, top, plot_w=780, plot_h=340):
    lo, hi = np.floor(pts["age"].min()), np.ceil(pts["age"].max())
    ux, uy = max(hi - lo, 1) / plot_w, 100 / plot_h
    rx, ry = 8 * ux, 8 * uy
    dots = list(zip(pts["age"], pts["performance_rating"]))
    boxes, out = [], top.copy()
    out["label_y"], out["side"] = out["performance_rating"].astype(float), "right"
    for i, row in out.iterrows():
        x, y, name = row["age"], row["performance_rating"], str(row["driver_name"])
        w, h = (len(name) * 6.6 + 4) * ux, 16 * uy
        best = None
        for shift in [0, 1, -1, 2, -2, 3, -3]:
            ly = min(max(y + shift * 18 * uy, 2), 98)
            for side in ["right", "left"]:
                x0 = x + 10 * ux if side == "right" else x - 10 * ux - w
                box = (x0, ly - h / 2, x0 + w, ly + h / 2)
                hits_dot = any(box[0] - rx < dx < box[2] + rx and box[1] - ry < dy < box[3] + ry
                               for dx, dy in dots if (dx, dy) != (x, y))
                hits_box = any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in boxes)
                if not hits_dot and not hits_box:
                    best = (ly, side, box)
                    break
            if best:
                break
        if best is None:
            x0 = x + 10 * ux
            best = (float(y), "right", (x0, y - h / 2, x0 + w, y + h / 2))
        out.at[i, "label_y"], out.at[i, "side"] = best[0], best[1]
        boxes.append(best[2])
    return out


# 1. Overview
def page_overview():
    chrono, exp = R["experiment_chronological"], R["experiment_results"]
    strict = result_row(chrono, version=STRICT, features="+ age + team strength")
    age = result_row(chrono, version="eventual outcome", features="+ age")
    age_base = result_row(chrono, version="eventual outcome", features="performance")
    cv_base = result_row(exp, question="RQ1 progression", prediction_point="end of season 1", features="performance")
    rq2 = exp[(exp["question"] == "RQ2 establishment") & (exp["prediction_point"] == "end of season 1")] \
        if not exp.empty else exp
    rq2_best = rq2.loc[rq2["auc"].idxmax()] if not rq2.empty else None
    rq2_unclear = rq2_best is not None and bool((rq2["oob_ci_low"] <= 0.5).all())
    n, reached = len(drivers), int(drivers["reached_f1"].sum())
    first, last = int(seasons["season"].min()), int(seasons["season"].max())

    cards = [
        f'<div class="solid" style="grid-column:1 / span 4;grid-row:1 / span 2;background:{D.TEAL};color:#0B1416;'
        'min-height:500px"><span class="wide" style="font-size:13px;opacity:0.75">'
        f'GP2 &amp; F2 · {first}–{last}</span><span style="font-family:\'Barlow Condensed\',sans-serif;font-weight:700;'
        'font-size:46px;line-height:1">Who makes it to Formula 1?</span><span style="font-size:16px;line-height:1.5">'
        'F1 teams make expensive bets on young drivers with limited evidence. '
        'How much can a GP2 or Formula 2 career tell us about reaching F1, and about staying there?</span>'
        '<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:auto">'
        f'<div style="display:flex;flex-direction:column"><span class="wide" style="font-size:40px">{n}</span>'
        '<span style="font-weight:600;font-size:14px">Junior drivers</span></div>'
        f'<div style="display:flex;flex-direction:column"><span class="wide" style="font-size:40px">{reached}</span>'
        '<span style="font-weight:600;font-size:14px">Reached F1</span></div></div>'
        '<div style="display:flex;height:12px;border-radius:6px;overflow:hidden;background:rgba(11,20,22,0.15)">'
        f'<span style="width:{reached / n * 100:.1f}%;background:#0B1416"></span></div>'
        f'<span style="font-size:13px;opacity:0.8">{reached / n:.0%} of the field</span></div>']

    if strict is not None:
        cards.append(
            f'<div class="solid" style="grid-column:5 / span 4;grid-row:1;background:{D.RQ1_HERO};color:#FFFFFF;'
            'min-height:240px"><span class="wide" style="font-size:13px;opacity:0.8">RQ1 · REACHING F1</span>'
            '<span style="font-size:17px;line-height:1.4">Can performance, age and team context predict who reaches '
            'F1?</span><div class="row" style="margin-top:auto;align-items:flex-end"><div style="display:flex;'
            f'flex-direction:column"><span class="wide" style="font-size:44px;line-height:1">{D.f2(strict["auc"])}</span>'
            f'<span style="font-size:13px;opacity:0.85">AUC · {"Answer: Yes" if strict["ci_low"] > 0.5 else "Unclear"}'
            '</span></div>' + D.link("Explore →", "Reaching F1", "#FFFFFF", D.RQ1_HERO) + '</div></div>')
    if rq2_best is not None:
        cards.append(
            f'<div class="solid" style="grid-column:9 / span 4;grid-row:1;background:{D.RQ2};color:#1A1206;'
            'min-height:240px"><span class="wide" style="font-size:13px;opacity:0.75">RQ2 · ESTABLISHING IN F1</span>'
            '<span style="font-size:17px;line-height:1.4">Among F1 entrants, can a junior career tell us which drivers '
            'will last?</span>'
            '<div class="row" style="margin-top:auto;align-items:flex-end"><div style="display:flex;'
            f'flex-direction:column"><span class="wide" style="font-size:44px;line-height:1">{D.f2(rq2_best["auc"])}'
            f'</span><span style="font-size:13px">AUC · {"Interval includes chance" if rq2_unclear else "Clear signal"}'
            '</span></div>' + D.link("Explore →", "Establishing in F1", "#1A1206", D.RQ2) + '</div></div>')

    def stage(n_, title, sub, border, fill):
        return (f'<div style="border:1px solid {border};border-radius:18px;padding:16px 18px;display:flex;'
                f'flex-direction:column;gap:4px;background:{fill}"><span class="wide" style="font-size:11px">STAGE {n_}'
                f'</span><span style="font-weight:600">{title}</span><span class="muted" style="font-size:13px">{sub}'
                '</span></div>')

    def arrow(label, colour):
        return (f'<div class="arrow" style="display:flex;flex-direction:column;align-items:center;gap:4px"><span class="wide" '
                f'style="font-size:10px;color:{colour}">{label}</span><span style="width:100%;height:2px;'
                f'background:{colour}"></span></div>')

    cards.append(
        '<div class="card" style="grid-column:5 / span 8;grid-row:2">' + D.card_head("The pathway")
        + '<div class="path" style="display:grid;grid-template-columns:minmax(0,1fr) 60px minmax(0,1fr) 60px minmax(0,1fr);'
        'align-items:center">' + stage(1, "Junior career", "GP2 / F2 results, age and team", D.LINE, D.PANEL)
        + arrow("RQ1", D.RQ1) + stage(2, "F1 entry", "Has the driver started an F1 race?", D.RQ1, "#161C40")
        + arrow("RQ2", D.RQ2) + stage(3, "F1 progression", "Established or a Star?", D.RQ2, "#2E1E0E")
        + '</div><span class="muted" style="font-size:13px;margin-top:auto">AUC measures how well a model ranks '
        'drivers: <strong>0.5</strong> is a coin flip, <strong>1.0</strong> is perfect</span></div>')

    findings = []
    if cv_base is not None:
        findings.append((D.f2(cv_base["auc"]), D.TEXT, "Junior results carry real signal",
                         "Rookie-season results alone rank future F1 entrants "
                         + ("clearly better than chance" if cv_base["oob_ci_low"] > 0.5 else "only loosely.")))
    if age is not None and age_base is not None:
        delta = num(age, "delta")
        delta = age["auc"] - age_base["auc"] if delta is None else delta
        findings.append((f"+{delta:.2f}", "#6F86FF", "Age adds information",
                         "Adding age improves predictions on later generations of drivers"))
    if strict is not None:
        findings.append((D.f2(strict["auc"]), D.RQ1, "The combination works best",
                         "Combining performance, age and team strength works best on cohorts the model has never seen"))
    if rq2_best is not None:
        findings.append((D.f2(rq2_best["auc"]), D.RQ2, "Lasting in F1 is far harder",
                         f"With {int(rq2_best['drivers'])} drivers, "
                         + ("no model clearly beats a coin flip" if rq2_unclear else "the signal is weaker.")))
    span = 12 // max(len(findings), 1)
    for i, (value, colour, title, body) in enumerate(findings, 1):
        cards.append(
            f'<div class="card" style="grid-column:span {span};grid-row:3"><div class="row" style="align-items:center">'
            '<span class="wide" style="font-size:13px;width:32px;height:32px;border-radius:50%;border:1px solid #4A4A57;'
            f'display:flex;align-items:center;justify-content:center">{i}</span><span class="wide" '
            f'style="font-size:24px;color:{colour}">{value}</span></div><span style="font-weight:600;font-size:16px;'
            f'line-height:1.35">{title}</span><span class="muted" style="font-size:14px;line-height:1.45">{body}</span></div>')

    cards.append(
        '<div class="card" style="grid-column:1 / span 7;grid-row:4">'
        + D.card_head("How the performance rating is calculated", "Performance rating, 0–100") + D.recipe_bar()
        + '<span class="muted" style="font-size:13px;margin-top:auto">Models then predict at the end of a driver\'s '
        'rookie, second and third seasons, using only what was known at the time</span></div>')

    now = preds[(preds["kind"] == "current") & (preds["season"] == CURRENT)].sort_values("probability", ascending=False)
    if not now.empty:
        lead = now.iloc[0]
        rest = "".join(
            '<div style="display:grid;grid-template-columns:46px minmax(0,1fr) 46px;align-items:center;gap:12px">'
            f'<span class="wide" style="font-size:11px">{D.escape(D.driver_code(r["driver_name"]))}</span>'
            '<div style="height:8px;border-radius:4px;background:#24242E"><div style="height:100%;border-radius:4px;'
            f'background:#6F86FF;width:{r["probability"] * 100:.0f}%"></div></div><span class="wide" '
            f'style="font-size:12px;text-align:right">{D.pc(pct(r["probability"]))}</span></div>'
            for _, r in now.iloc[1:4].iterrows())
        cards.append(
            '<div class="card" style="grid-column:8 / span 5;grid-row:4">'
            + D.card_head("Today's highest predicted chances of reaching F1", f"{CURRENT} Grid")
            + '<div style="display:flex;align-items:center;gap:16px">' + D.code_tile(D.driver_code(lead["driver_name"]),
                                                                                       D.RQ1, 64)
            + f'<div style="display:flex;flex-direction:column;flex-grow:1;min-width:0"><span style="font-weight:600;'
            f'font-size:17px">{D.escape(lead["driver_name"])}</span><span class="muted" style="font-size:13px">'
            f'{stage_label(lead["k"])} · {D.escape(str(lead["team"]))}</span></div><span class="wide" '
            f'style="font-size:30px">{D.pc(pct(lead["probability"]))}</span></div>' + rest
            + D.link("View all predictions →", "Reaching F1", "transparent", D.TEXT).replace(
                'style="', 'style="border:1px solid #34343F;margin-top:auto;', 1) + '</div>')

    st.markdown(f'<div class="bento">{"".join(cards)}</div>', unsafe_allow_html=True)


# 2. Reaching F1 (RQ1)
def rq1_cards():
    chrono, exp, comp = R["experiment_chronological"], R["experiment_results"], R["experiment_composition"]
    strict = result_row(chrono, version=STRICT, features="+ age + team strength")
    strict_base = result_row(chrono, version=STRICT, features="performance")
    eventual = result_row(chrono, version="eventual outcome", features="+ age + team strength")
    eventual_base = result_row(chrono, version="eventual outcome", features="performance")
    s1 = dict(question="RQ1 progression", prediction_point="end of season 1")
    cv = result_row(exp, features="+ age + team strength", **s1)
    cv_base = result_row(exp, features="performance", **s1)
    cv_team = result_row(exp, features="team strength only", **s1)
    if strict is None or strict_base is None:
        return

    cards = [D.hero(
        D.RQ1_HERO, "#FFFFFF", "RESEARCH QUESTION 1",
        "Can performance, age and team context predict who reaches F1?",
        D.f2(strict["auc"]), "AUC on unseen cohorts", f"95% CI <strong>{D.f2(strict['ci_low'])}–{D.f2(strict['ci_high'])}</strong>",
        f"Junior performance alone achieves {D.f2(strict_base['auc'])}. Adding age and team "
        f"strength increases this to {D.f2(strict['auc'])}.",
        ["Answer: yes" if strict["ci_low"] > 0.5 else "Answer: unclear", "Strict five-year test",
         f"{int(strict['test_drivers'])} test drivers"],
        "RQ1", "rgba(255,255,255,0.18)", "1 / span 5")]

    order = ["performance", "+ age", "+ team strength", "team strength only", "+ age + team strength"]
    rows = []
    for f in order:
        r = result_row(chrono, version=STRICT, features=f)
        if r is not None:
            best = f == "+ age + team strength"
            rows.append(dict(name=FEATURE_LABELS[f], auc=r["auc"], low=r["ci_low"], high=r["ci_high"],
                             colour=D.RQ1 if best else (D.MUTED if f == "performance" else D.TEXT), strong=best))
    cards.append(
        '<div class="card" style="grid-column:6 / span 7;grid-row:1"><div class="row"><span class="lbl">'
        'What each factor adds</span><span class="muted" style="font-size:13px">AUC with 95% interval · '
        'Strict five-year test</span></div>' + D.range_chart(rows) + '</div>')

    trio = []
    if cv is not None and cv_base is not None:
        trio.append(D.stat_card("Cross-validation", D.f2(cv["auc"]),
                                f"95% CI <strong>{D.f2(cv['oob_ci_low'])}–{D.f2(cv['oob_ci_high'])}</strong>", gain_of(cv, cv_base),
                                f"{int(cv['drivers'])} drivers · {int(cv['positives'])} reached F1"))
    for label, row, base in [("Later cohorts", eventual, eventual_base), ("Strict five-year", strict, strict_base)]:
        if row is not None and base is not None:
            trio.append(D.stat_card(label, D.f2(row["auc"]), f"95% CI <strong>{D.f2(row['ci_low'])}–{D.f2(row['ci_high'])}</strong>",
                                    gain_of(row, base), f"{int(row['test_drivers'])} test drivers"))
    cards.append(f'<div class="sub3" style="grid-column:6 / span 7;grid-row:2">{"".join(trio)}</div>')

    rq1_comp = comp[comp["question"] == "RQ1 progression"] if not comp.empty else comp
    if not rq1_comp.empty:
        first = rq1_comp.iloc[0]
        n, pos = int(first["drivers"]), int(first["positives"])
        cards.append(
            '<div class="card" style="grid-column:1 / span 5;grid-row:3"><div class="row"><span class="lbl">'
            f'Who was included in the test</span><span class="wide" style="font-size:26px">{D.pc(f"{pos / n:.0%}")}</span></div>'
            + D.waffle(n, pos, D.RQ1)
            + '<div style="display:flex;gap:20px;font-size:14px;flex-wrap:wrap">'
            + D.legend_item(D.RQ1, f"{pos} reached F1") + D.legend_item(D.LINE, f"{n - pos} did not")
            + f'<span class="muted">{n} drivers after their rookie season</span></div></div>')

        biggest = rq1_comp["drivers"].max()
        stage_html, bests = [], []
        for _, c in rq1_comp.iterrows():
            point = dict(question="RQ1 progression", prediction_point=c["prediction_point"])
            at = exp[(exp["question"] == point["question"]) & (exp["prediction_point"] == point["prediction_point"])]
            base = result_row(exp, features="performance", **point)
            if at.empty or base is None:
                continue
            best = at.loc[at["auc"].idxmax()]
            bests.append(best["auc"])
            stage_html.append(
                '<div style="display:flex;flex-direction:column;gap:6px">'
                '<div class="row" style="font-size:13px">'
                f'<span class="wide" style="font-size:12px;white-space:nowrap">{stage_name(c["prediction_point"])}</span>'
                f'<span class="muted">{int(c["drivers"])} drivers · {int(c["positives"])} reached F1</span></div>'
                f'<div style="display:flex;height:10px;border-radius:5px;overflow:hidden;'
                f'width:{c["drivers"] / biggest * 100:.0f}%;background:{D.LINE}">'
                f'<span style="width:{c["positive_rate"] * 100:.0f}%;background:{D.RQ1}"></span></div>'
                '<div style="display:flex;gap:6px 18px;align-items:baseline;font-size:13px;flex-wrap:wrap">'
                f'<span class="muted">Performance only {D.f2(base["auc"])}</span>'
                f'<span style="font-weight:600">Best model {D.f2(best["auc"])}</span></div>'
                f'<span class="muted" style="font-size:12px">{model_name(best["features"])}</span></div>')
        fades = len(bests) > 1 and bests[-1] < bests[0]
        key = ('<span class="muted" style="font-size:12px;line-height:1.5">Bar length = Drivers remaining in GP2/F2 · '
               f'<span style="color:{D.RQ1}">Blue</span> = Eventually reached F1 · AUC measures how well models rank '
               'drivers (0.5 = chance)</span>')
        cards.append('<div class="card" style="grid-column:6 / span 4;grid-row:3"><span class="lbl">'
                     + ("Predictive power across junior seasons" if fades else "Predictions by season")
                     + '</span>' + key + "".join(stage_html) + '</div>')

    if cv_team is not None and cv_base is not None:
        cards.append(
            f'<div class="solid" style="grid-column:10 / span 3;grid-row:3;background:{D.TEAL};color:#0B1416;padding:26px">'
            '<span class="lbl">Team strength vs results</span><div style="display:flex;flex-direction:column;gap:10px;'
            'margin-top:6px">' + D.meter("Team strength", cv_team["auc"]) + D.meter("Results", cv_base["auc"])
            + '</div><span style="font-size:14px;line-height:1.45;margin-top:auto">Top teams sign drivers already rated '
            'as prospects, so a team reflects talent, backing and opportunity</span></div>')

    st.markdown(f'<div class="bento">{"".join(cards)}</div>', unsafe_allow_html=True)


def page_rq1():
    rq1_cards()

    st.header("A. The prediction problem")
    st.markdown("""
- **Outcome:** The driver starts at least one F1 race after the prediction point.
- **Who is included:** GP2/F2 drivers from 2007 onwards who had not yet raced in F1. Drivers still waiting
  for an opportunity (**pending**) are excluded because their outcomes are not yet known. They are not counted
  as failures.
- **When predictions are made:** At the end of a driver's rookie, second and third junior seasons.
  Each successive prediction point asks a narrower question: *Among drivers still competing in GP2/F2, who goes
  on to reach F1?*
""")
    comp = R["experiment_composition"]
    if not comp.empty:
        view = comp[comp["question"] == "RQ1 progression"].drop(columns=["question"])
        count_cols = [c for c in view.columns if c not in ("prediction_point", "positive_rate")]
        view[count_cols] = view[count_cols].astype("Int64")
        view["positive_rate"] = view["positive_rate"].map("{:.0%}".format)
        view["prediction_point"] = view["prediction_point"].map(point_label)
        show_table(blank_missing(view).rename(columns=lambda c: c.replace("_", " ").capitalize()))

    st.header("B. Junior performance and F1 progression")
    hist = preds[preds["kind"] == "historical (out-of-fold)"].merge(
        seasons[["driver_key", "season", "performance_rating", "team_strength"]],
        on=["driver_key", "season"], how="left")
    hist["Group"] = hist["known_reached"].map({True: "Reached F1", False: "Did not reach F1"})
    colours = alt.Scale(domain=["Reached F1", "Did not reach F1"], range=[RQ1_COLOUR, GREY])
    rookies = hist[hist["k"] == 1]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Rookie performance rating by eventual outcome**")
        show_chart(share_histogram(rookies, "performance_rating", colours))
    with c2:
        st.markdown("**Performance across the first three seasons**")
        prog = hist.groupby(["k", "Group"], as_index=False)["performance_rating"].mean()
        prog["Stage"] = prog["k"].map(stage_label)
        show_chart(alt.Chart(prog).mark_line(point=True).encode(
            x=alt.X("Stage:N", sort=["Rookie season", "Second season", "Third season"], title=None),
            y=alt.Y("performance_rating:Q", title="Average performance rating"),
            color=alt.Color("Group:N", scale=colours, title=None)).properties(height=280))

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**Age during rookie season**")
        show_chart(alt.Chart(rookies).mark_boxplot(extent="min-max", rule={"color": D.MUTED},
                                                   median={"color": "#FFFFFF"}, size=40).encode(
            x=alt.X("Group:N", title=None), y=alt.Y("age:Q", title="Age", scale=alt.Scale(zero=False)),
            color=alt.Color("Group:N", scale=colours, legend=None)).properties(height=260))
    with c4:
        st.markdown("**Team strength during rookie season**")
        show_chart(alt.Chart(rookies).mark_boxplot(extent="min-max", rule={"color": D.MUTED},
                                                   median={"color": "#FFFFFF"}, size=40).encode(
            x=alt.X("Group:N", title=None), y=alt.Y("team_strength:Q", title="Team strength (1 = strongest)"),
            color=alt.Color("Group:N", scale=colours, legend=None)).properties(height=260))

    st.header("C. Model performance")
    chrono = R["experiment_chronological"]
    if not chrono.empty:
        st.markdown("**Chronological validation using rookie-season data.** Models were trained on earlier cohorts "
                    "and tested on later cohorts. The five-year horizon version only includes outcomes that were "
                    "known at the time of each prediction.")
        order = ["performance", "+ age", "+ team strength", "+ age + team strength", "team strength only"]
        cview = chrono[chrono["features"].isin(order)].copy()
        cview["version"] = cview["version"].replace({"eventual outcome": "Main evaluation",
                                                     STRICT: "Five-year horizon"})
        cview["features"] = pd.Categorical(cview["features"], order, ordered=True)
        cview = cview.sort_values("features")
        cview["features"] = cview["features"].map(FEATURE_LABELS)
        show_chart(dot_whisker(cview, "features", "version",
                               alt.Scale(range=[RQ1_COLOUR, "#93c5fd"]), height=320))
        table = cview.pivot_table(index="features", columns="version", values="auc", sort=False).round(3)
        show_table(table.reset_index().rename(columns={"features": "Model"}))

    exp = R["experiment_results"]
    if not exp.empty:
        st.markdown("**Prediction-stage validation** (out-of-bag 95% intervals)")
        sv = exp[(exp["question"] == "RQ1 progression") &
                 exp["features"].isin(["performance", "+ age + team strength"])].copy()
        sv["features"] = sv["features"].map(FEATURE_LABELS)
        sv["label"] = sv["prediction_point"].map(stage_name) + " · " + sv["features"]
        show_chart(dot_whisker(sv, "label", "features",
                               alt.Scale(domain=[FEATURE_LABELS["performance"], FEATURE_LABELS["+ age + team strength"]],
                                         range=[GREY, RQ1_COLOUR]),
                               low="oob_ci_low", high="oob_ci_high", height=260, offset=False))

    st.markdown("**Calibration (rookie season, out-of-fold).** Drivers are grouped by predicted probability. "
                "Well-calibrated models produce predictions that closely match the observed share of drivers who "
                "reached F1.")
    r1 = hist[hist["k"] == 1].copy()
    if len(r1) < 10:
        st.info("Not enough rookie-season estimates for a calibration chart.")
        r1 = None
    if r1 is not None:
        _calibration(r1)

    _rq1_rest(chrono)


def _calibration(r1):
    r1["band"] = pd.qcut(r1["probability"], q=5, duplicates="drop")
    calib = (r1.groupby("band", observed=True)
             .agg(predicted=("probability", "mean"), actual=("known_reached", "mean"), drivers=("driver_key", "size"))
             .reset_index(drop=True))
    diag = alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]})).mark_line(strokeDash=[4, 4], color=GREY).encode(x="x", y="y")
    dots = alt.Chart(calib).mark_circle(size=160, color=RQ1_COLOUR).encode(
        x=alt.X("predicted:Q", title="Predicted chance", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
        y=alt.Y("actual:Q", title="Share who reached F1", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
        tooltip=[alt.Tooltip("predicted:Q", title="Predicted chance", format=".0%"),
                 alt.Tooltip("actual:Q", title="Share who reached F1", format=".0%"),
                 alt.Tooltip("drivers:Q", title="Drivers")])
    show_chart((diag + dots).properties(height=320))


def ci_text(row):
    if row is None:
        return "n/a"
    return f"**{row['auc']:.2f}** [95% CI **{row['ci_low']:.2f}–{row['ci_high']:.2f}**]"


def _rq1_rest(chrono):
    st.header("D. What does this tell us?")
    eventual = result_row(chrono, version="eventual outcome", features="+ age + team strength")
    base = result_row(chrono, version="eventual outcome", features="performance")
    st.markdown(f"""
Combining performance, age and team strength improved chronological predictive performance over junior
performance alone ({ci_text(base)} to {ci_text(eventual)}) in the main evaluation. The improvement
also held when only outcomes known at the time of prediction were considered.

However, the analysis could not establish how much age and team strength each contribute independently.
In the sensitivity analysis, neither feature's contribution beyond the other was conclusive.

Team strength requires careful interpretation. Top junior teams often recruit drivers who are already
considered promising, while academy-backed drivers may receive opportunities in stronger seats. A driver's
team therefore reflects a mixture of talent, backing and opportunity. It predicts progression to F1, but the
data cannot establish why.
""")

    sens = R["experiment_sensitivity"]
    if not sens.empty:
        with st.expander("Sensitivity analysis (paired out-of-bag deltas)"):
            sv = sens[sens["question"] == "RQ1 progression"].drop(columns=["question", "drivers", "positives"],
                                                                   errors="ignore")
            sv["prediction_point"] = sv["prediction_point"].map(point_label)
            sv["comparison"] = sv["comparison"].map(COMPARISON_LABELS).fillna(sv["comparison"])
            sv["verdict"] = sv["verdict"].str.capitalize()
            show_table(sv.rename(columns={"prediction_point": "Prediction point", "comparison": "Comparison",
                                          "delta": "Gain in AUC", "delta_ci_low": "95% low",
                                          "delta_ci_high": "95% high", "verdict": "Clear gain?"}))

    st.header("E. Limitations")
    st.markdown("""
- **Few F1 entrants:** Only around 45 drivers in the rookie population reached F1, resulting in wide confidence
  intervals.
- **Changing populations:** Later prediction points exclude drivers who have already reached F1, including many
  future stars.
- **Unresolved careers:** Recent cohorts still contain Pending drivers, which the five-year horizon evaluation avoids.
- **Uncertainty:** Chronological intervals resample test drivers around fixed models, so they understate the full
  training-pipeline uncertainty.
""")

    st.header("F. Applying the model to today's drivers")
    st.write("Drivers still awaiting an F1 opportunity, scored using the model for their current stage. "
             "Each probability reflects how often similar drivers reached F1, not a prediction of an "
             "individual's future.")
    current = preds[preds["kind"] == "current"].merge(
        seasons[["driver_key", "season", "performance_rating", "pos_text"]], on=["driver_key", "season"], how="left")
    if st.toggle(f"{CURRENT} grid only", value=True):
        current = current[current["season"] == CURRENT]
    current = current.sort_values("probability", ascending=False)
    show_table(pd.DataFrame({
        "Driver": current["driver_name"], "Team": current["team"], "Season": current["season"],
        "Stage": current["k"].map(stage_label), "Age": whole_age(current["age"]),
        "Position": current["pos_text"], "Performance rating": current["performance_rating"],
        "Chance of reaching F1": current["probability"],
        "90% uncertainty range": [interval(lo, hi) for lo, hi in zip(current["prob_low"], current["prob_high"])],
        "Note": current["season_in_progress"].map({True: "Season in progress", False: ""}),
    }), height=table_height(len(current)), column_config={"Chance of reaching F1": st.column_config.ProgressColumn(
        format="percent", min_value=0, max_value=1)})
    rates = [f"{pct(v)} after the {stage_label(k).lower()}" for k, v in zip(stages["k"], stages["base_rate"])]
    rates_text = ", ".join(rates[:-1]) + " and " + rates[-1] if len(rates) > 1 else "".join(rates)
    st.caption(f"**Historical share reaching F1:** {rates_text}. "
               "The 90% ranges are based on refitting the model on resampled drivers. Drivers in their fourth season "
               "or later are not scored because the model was only validated for the first three seasons.")
    if not current.empty:
        pts = current.dropna(subset=["performance_rating"])
        base = alt.Chart(pts).encode(
            x=alt.X("age:Q", title="Age (start of season)", scale=alt.Scale(zero=False), axis=alt.Axis(tickCount=10)),
            y=alt.Y("performance_rating:Q", title="Performance rating (0–100)"))
        dots = base.mark_circle(size=150, opacity=1, stroke=D.BG, strokeWidth=1.5).encode(
            color=alt.Color("probability:Q", title="Chance",
                            scale=alt.Scale(domain=[0, 1], range=["#3A3A48", "#4A5BC4", D.RQ1, "#9DB0FF"]),
                            legend=alt.Legend(format="%", gradientLength=180)),
            tooltip=[alt.Tooltip("driver_name:N", title="Driver"),
                     alt.Tooltip("team:N", title="Team"),
                     alt.Tooltip("probability:Q", title="Chance", format=".0%")])
        top = place_labels(pts, pts.nlargest(6, "probability"))
        moved = top[top["label_y"] != top["performance_rating"]]
        leaders = alt.Chart(moved).mark_rule(color=D.MUTED, strokeWidth=1).encode(
            x=alt.X("age:Q", title="Age (start of season)"),
            y=alt.Y("performance_rating:Q", title="Performance rating (0–100)"),
            y2="label_y:Q")
        text = dict(fontSize=12, fontWeight=500, color=D.TEXT, opacity=0.6)
        enc = dict(x="age:Q", y=alt.Y("label_y:Q", title="Performance rating (0–100)"), text="driver_name:N")
        labels = (alt.Chart(top[top["side"] == "right"]).mark_text(align="left", dx=10, **text).encode(**enc) +
                  alt.Chart(top[top["side"] == "left"]).mark_text(align="right", dx=-10, **text).encode(**enc))
        show_chart((leaders + dots + labels).properties(height=400))
        st.caption("The six highest chances are labelled")


# 3. Establishing in F1 (RQ2)
OUTCOME_AFTER = {"Star": "Became a Star", "Established": "Established in F1",
                 "Reached, didn't stick": "Reached F1, did not stick", "Didn't reach F1": "Never reached F1",
                 "Too early to tell": "In F1, too early to tell", "Pending": "Still waiting for a chance"}


def rq2_cards():
    exp = R["experiment_results"]
    if exp.empty:
        return
    rq2 = exp[exp["question"] == "RQ2 establishment"]
    s1 = rq2[rq2["prediction_point"] == "end of season 1"]
    base = result_row(rq2, prediction_point="end of season 1", features="performance")
    if s1.empty or base is None:
        return
    best = s1.loc[s1["auc"].idxmax()]
    n = int(best["drivers"])
    unclear = bool((s1["oob_ci_low"] <= 0.5).all())

    cards = [D.hero(
        D.RQ2, "#1A1206", "RESEARCH QUESTION 2", "Once in F1, can a junior career tell us which drivers will last?",
        D.f2(base["auc"]), "Performance alone", "A coin flip is 0.50",
        f"Rookie-season performance alone achieved an AUC of {D.f2(base['auc'])}. The best model reached "
        f"{D.f2(best['auc'])}, "
        + ("but its confidence interval still includes chance." if unclear
           else "and its interval excludes chance."),
        ["Answer: Not with this data" if unclear else "Answer: partly", f"{n} drivers"],
        "RQ2", "rgba(26,18,6,0.22)", "1 / span 5")]

    rows = []
    for f in ["performance", "+ age", "+ team strength", "team strength only", "+ age + team strength"]:
        r = result_row(s1, features=f)
        if r is not None:
            top = f == best["features"]
            rows.append(dict(name=FEATURE_LABELS[f], auc=r["auc"], low=r["oob_ci_low"], high=r["oob_ci_high"],
                             colour=D.RQ2 if top else (D.MUTED if f == "performance" else D.TEXT), strong=top))
    title = "Every interval crosses chance" if unclear else "Model results"
    cards.append(
        f'<div class="card" style="grid-column:6 / span 7;grid-row:1"><div class="row"><span class="lbl">{title}</span>'
        '<span class="muted" style="font-size:13px">AUC with 95% confidence interval · Rookie-season predictions</span></div>'
        + D.range_chart(rows, lo=0.0, hi=1.0, chance=0.5) + '</div>')

    trio = []
    for point in ["end of season 1", "end of season 2"]:
        at = rq2[rq2["prediction_point"] == point]
        b = result_row(at, features="performance")
        if at.empty or b is None:
            continue
        top = at.loc[at["auc"].idxmax()]
        trio.append(D.stat_card(f"<strong>{point_label(point)}</strong>", int(top["drivers"]), f"Drivers · {int(top['positives'])} lasted",
                                "", f"<span style='white-space:nowrap'>Performance only <strong>{D.f2(b['auc'])}</strong> · Best model <strong>{D.f2(top['auc'])}</strong></span>",
                                style="padding-left:15px;padding-right:15px"))
        verdict_bg, verdict_fg, verdict = ("#3A2F0B", "#FACC15", "NOT CLEARLY") if unclear else ("#15803D", "#FFFFFF", "YES")
    trio.append(
        f'<div class="solid" style="background:{verdict_bg};color:{verdict_fg};padding:22px;gap:8px">'
        f'<span style="font-size:13px"><strong>Verdict</strong></span><span class="wide" style="font-size:20px;line-height:1.35">{verdict}</span>'
        f'<span style="font-size:14px;line-height:1.45;opacity:0.85">With only {n} drivers, the analysis cannot reliably '
        'distinguish a moderate effect from no effect. More data is needed.</span></div>' if unclear else
        f'<div class="solid" style="background:{verdict_bg};color:{verdict_fg};padding:22px;gap:8px">'
        f'<span style="font-size:13px">Verdict</span><span class="wide" style="font-size:20px">{verdict}</span></div>')
    cards.append(f'<div class="sub3" style="grid-column:6 / span 7;grid-row:2">{"".join(trio)}</div>')

    tiers = ENTRANT_TIERS + ["Too early to tell"]
    counts = drivers["outcome"].value_counts().reindex(tiers).fillna(0).astype(int)
    fills = {"Star": (D.RQ2, "#1A1206"), "Established": ("#FFC48A", "#1A1206"),
             "Reached, didn't stick": (D.LINE, D.TEXT), "Too early to tell": (D.PANEL, D.MUTED)}
    segments = "".join(
        f'<div style="flex-grow:{c};background:{fills[t][0]};color:{fills[t][1]};display:flex;align-items:center;'
        f'justify-content:center;font-family:\'Michroma\',sans-serif;font-size:15px">{c}</div>'
        for t, c in counts.items() if c > 0)
    cards.append(
        '<div class="card" style="grid-column:1 / span 5;grid-row:3"><div class="row"><span class="lbl">'
        f'F1 career outcomes</span><span class="wide" style="font-size:26px">{counts.sum()}</span></div>'
        f'<div style="display:flex;height:54px;border-radius:14px;overflow:hidden;gap:3px">{segments}</div>'
        '<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 18px;font-size:14px">'
        + "".join(D.legend_item(fills[t][0], outcome_label(t)) for t in tiers)
        + '</div><span class="muted" style="font-size:13px">Drivers whose careers are still too early to classify '
        'are excluded from RQ2</span></div>')

    rated = seasons[seasons["performance_rating"].notna() & (seasons["confidence"] != "Low")
                    & ~seasons["season_in_progress"]]
    peaks = (rated.sort_values(["performance_rating", "season"], ascending=[False, True])
             .drop_duplicates("driver_key").head(5))
    if not peaks.empty:
        lines = []
        for _, p in peaks.iterrows():
            o = p["outcome"] if isinstance(p["outcome"], str) else ""
            colour = D.RQ2 if o in ("Star", "Established") else (D.RQ1 if p["reached_f1"] else D.LINE)
            after = OUTCOME_AFTER.get(o, outcome_label(o))
            lines.append(
                f'<div style="display:flex;align-items:center;gap:14px">{D.code_tile(D.driver_code(p["driver_name"]), colour)}'
                f'<div style="display:flex;flex-direction:column;min-width:0"><span style="font-weight:600;font-size:15px">'
                f'{D.escape(p["driver_name"])}</span><span class="muted" style="font-size:12px">{int(p["season"])} · Rating '
                f'{int(p["performance_rating"])} · {after}</span></div></div>')
        lasted = int(peaks["outcome"].isin(["Star", "Established"]).sum())
        cards.append(
            '<div class="card" style="grid-column:6 / span 4;grid-row:3"><span class="lbl">Highest-rated individual junior '
            'seasons</span>' + "".join(lines)
            + f'<span class="muted" style="font-size:13px;margin-top:auto">{words(len(peaks) - lasted).capitalize()} '
            f'of these {words(len(peaks))} drivers never established themselves in F1</span></div>')

    team1 = result_row(exp, question="RQ1 progression", prediction_point="end of season 1", features="team strength only")
    team2 = result_row(s1, features="team strength only")
    if team1 is not None and team2 is not None:
        faded = team2["oob_ci_low"] <= 0.5
        cards.append(
            f'<div class="solid" style="grid-column:10 / span 3;grid-row:3;background:{D.RQ1_HERO};color:#FFFFFF;padding:26px">'
            f'<span class="lbl">{"Team strength predicts entry, not establishment" if faded else "Team strength in both questions"}'
            '</span><div style="display:flex;flex-direction:column;gap:4px;margin-top:8px">'
            '<span style="font-size:13px;opacity:0.8"><strong>Reaching F1</strong></span>'
            f'<span class="wide" style="font-size:22px">{D.f2(team1["auc"])}</span></div>'
            '<div style="display:flex;flex-direction:column;gap:4px"><span style="font-size:13px;opacity:0.8"><strong>Lasting in F1</strong>'
            f'</span><span class="wide" style="font-size:22px">{D.f2(team2["auc"])}</span></div>'
            '<span style="font-size:14px;line-height:1.45;margin-top:12px">'
            + ("Team strength is associated with reaching F1, but provides much less separation between "
               "established and short-career entrants" if faded else "It carries signal for both.")
            + '</span></div>')

    st.markdown(f'<div class="bento">{"".join(cards)}</div>', unsafe_allow_html=True)


def page_rq2():
    rq2_cards()

    st.header("Outcome categories")
    show_table(pd.DataFrame({
           "Category": ["Star", "Established", "Reached, did not stick"],
           "Rule": ["Top-five F1 championship finish, or three or more race wins",
                    "Three or more full F1 seasons (started at least half the races)",
                    "F1 starts, but fewer than three full seasons"],
       }), column_config={"Category": st.column_config.TextColumn("Category", width="medium")})
    st.markdown("""

**Established or Star** counts as success. Drivers still early in their F1 careers **(too early to tell)**
are left out, because their outcome is not known yet.
""")
    entrants = drivers[drivers["outcome"].isin(ENTRANT_TIERS + ["Too early to tell"])]
    counts = entrants["outcome"].value_counts().reindex(ENTRANT_TIERS + ["Too early to tell"]).fillna(0).reset_index()
    counts.columns = ["Outcome", "Drivers"]
    counts["Outcome"] = counts["Outcome"].map(outcome_label)
    left, _ = st.columns([3, 2])
    with left:
        bars = alt.Chart(counts).encode(
        x=alt.X("Drivers:Q", axis=alt.Axis(tickMinStep=1, format="d")),
        y=alt.Y("Outcome:N", sort=None, title=None))
    show_chart((bars.mark_bar(color=RQ2_COLOUR) +
                bars.mark_text(align="left", dx=4, color=D.TEXT).encode(text="Drivers:Q"))
               .properties(height=200))

    st.header("Junior profiles of F1 entrants")
    rookie = seasons[(seasons["k"] == 1) & seasons["outcome"].isin(ENTRANT_TIERS)].copy()
    rookie["Group"] = rookie["outcome"].map(lambda o: "Established or Star" if o in ["Star", "Established"]
                                            else "Did not stick")
    colours = alt.Scale(domain=["Established or Star", "Did not stick"], range=[RQ2_COLOUR, GREY])
    c1, c2, c3 = st.columns(3)
    for col, field, title in [(c1, "performance_rating", "Rookie performance rating"),
                              (c2, "age", "Age at rookie season"),
                              (c3, "team_strength", "Rookie team strength")]:
        with col:
            st.markdown(f"**{title}**")
            show_chart(alt.Chart(rookie).mark_boxplot(extent="min-max", rule={"color": D.MUTED},
                                                      median={"color": "#FFFFFF"}, size=36).encode(
                x=alt.X("Group:N", title=None), y=alt.Y(f"{field}:Q", title=None, scale=alt.Scale(zero=False)),
                color=alt.Color("Group:N", scale=colours, legend=None)).properties(height=260))
    st.caption("Includes all F1 entrants with settled careers, including 2005–2006 rookies. The sample is therefore " \
    "slightly larger than the modelling population.")

    st.header("Model results")
    exp = R["experiment_results"]
    rq2 = exp[exp["question"] == "RQ2 establishment"] if not exp.empty else exp
    first = rq2[rq2["prediction_point"] == "end of season 1"] if not rq2.empty else rq2
    if not first.empty:
        best = first.loc[first["auc"].idxmax()]
        k1, k2, k3 = st.columns(3)
        k1.metric("F1 entrants (rookie snapshot)", int(best["drivers"]))
        k2.metric("Established or Star", int(best["positives"]))
        k3.metric("Best model AUC", f"{best['auc']:.3f}", help=model_name(best["features"]))
        st.markdown(f"**Best model:** {model_name(best['features'])} "
                    f"(95% CI **{best['oob_ci_low']:.3f}–{best['oob_ci_high']:.3f}**). "
                    "The interval includes chance, so there is insufficient evidence to "
                    "conclude that the model reliably distinguishes established from short-career F1 entrants.")
        rv = rq2.copy()
        rv["label"] = rv["prediction_point"].map(stage_name) + " · " + rv["features"].map(FEATURE_LABELS)
        rv["Prediction point"] = rv["prediction_point"].map(point_label)
        show_chart(dot_whisker(rv, "label", "Prediction point", alt.Scale(range=[RQ2_COLOUR, "#fdba74"]),
                               low="oob_ci_low", high="oob_ci_high", height=380, domain=(0, 1), offset=False))

    st.header("Why is this harder?")
    st.markdown("""
- **Small sample:** Around 40 F1 entrants with settled careers is too few to reliably detect moderate effects.
- **A different filter:** Reaching F1 depends on results, backing and opportunity. Establishing a career depends 
on performance against other F1 drivers, which junior standings measure imperfectly.
- **Missing stars at later stages:** Many future stars were promoted after one season, so second-season comparisons 
exclude some of the drivers we most want to identify.
- **Age points in the expected direction:** Younger entrants tended to establish themselves more often, but the confidence 
intervals still include chance.
""")


# 4. Driver Explorer
LIST_LIMIT = 80
LIST_ADJUST = 0  # add or subtract pixels if the list ends up a little longer or shorter than the profile


def list_height(s, p):
    """Rough height of the profile column, so the driver list can end level with it."""
    has_chart = s["performance_rating"].notna().any()
    profile = 640 if has_chart else 310
    season_rows = -(-len(s) // 5)
    seasons_block = 175 * season_rows + 40
    predictions = 150 if p.empty else 175 + 36 * len(p)
    total = profile + seasons_block + predictions + 55 + 4 * 16
    return max(500, int(total - 130 + LIST_ADJUST))


def choose(key):
    st.session_state.pick = key


def series_span(first, last):
    if last <= 2016:
        return "GP2"
    if first >= 2017:
        return "F2"
    return "GP2/F2"


def driver_row(r, selected):
    o = r["outcome"]
    tile_bg, tile_fg = D.outcome_style(o)
    tag_bg, tag_fg = D.outcome_tag_style(o)
    best = r["best_junior_pos"]
    bits = []
    if not pd.isna(r["first"]):
        bits.append(f"{series_span(r['first'], r['last'])} {int(r['first'])}–{int(r['last'])}")
    if not pd.isna(best):
        bits.append("Champion" if int(best) == 1 else f"Best P{int(best)}")
    style = f"background:{D.PANEL};border-color:#4A4A57" if selected else ""
    return (f'<div class="drow" style="{style}">'
            + D.code_tile(D.driver_code(r["driver_name"]), tile_bg, 56, tile_fg)
            + f'<div class="dtext"><b>{D.escape(r["driver_name"])}</b><span>{D.escape(" · ".join(bits))}</span></div>'
            + f'<span class="tag" style="background:{tag_bg};color:{tag_fg}">{D.escape(outcome_label(o))}</span></div>')


def pill_text(chosen, fmt=str):
    if not chosen:
        return "All"
    return fmt(chosen[0]) if len(chosen) == 1 else f"{len(chosen)} selected"


COUNTRY_CODES = {
    "Argentina": "ARG", "Australia": "AUS", "Austria": "AUT", "Belgium": "BEL", "Brazil": "BRA",
    "Bulgaria": "BUL", "Canada": "CAN", "Chile": "CHI", "China": "CHN", "Colombia": "COL", "Croatia": "CRO",
    "Czech Republic": "CZE", "Czechia": "CZE", "Denmark": "DEN", "Estonia": "EST", "Finland": "FIN",
    "France": "FRA", "Germany": "GER", "Greece": "GRE", "Hong Kong": "HKG", "Hungary": "HUN", "India": "IND",
    "Indonesia": "INA", "Ireland": "IRL", "Israel": "ISR", "Italy": "ITA", "Japan": "JPN", "Latvia": "LAT",
    "Lithuania": "LTU", "Malaysia": "MAS", "Mexico": "MEX", "Monaco": "MON", "Netherlands": "NED",
    "Kingdom of the Netherlands": "NED", "New Zealand": "NZL", "Norway": "NOR", "Paraguay": "PAR",
    "Peru": "PER", "Philippines": "PHI", "Poland": "POL", "Portugal": "POR", "Romania": "ROU", "Russia": "RUS",
    "Saudi Arabia": "KSA", "Serbia": "SRB", "Singapore": "SGP", "Slovakia": "SVK", "South Africa": "RSA",
    "South Korea": "KOR", "Spain": "ESP", "Sweden": "SWE", "Switzerland": "SUI", "Taiwan": "TPE",
    "Thailand": "THA", "Turkey": "TUR", "Türkiye": "TUR", "Ukraine": "UKR", "United Arab Emirates": "UAE",
    "United Kingdom": "GBR", "United States": "USA", "United States of America": "USA", "Uruguay": "URU",
    "Venezuela": "VEN",
}
SNAPSHOT_NOTES = {
    "historical (out-of-fold)": ("back-test", "Predicted by a model trained without this driver"),
    "current": ("live estimate", "Latest season; the outcome is not known yet"),
    "model estimate": ("estimate", "This driver's outcome was not used in training"),
}

FLAG_CODES = {
    "Argentina": "ar", "Australia": "au", "Austria": "at", "Belgium": "be", "Brazil": "br", "Bulgaria": "bg",
    "Canada": "ca", "Chile": "cl", "China": "cn", "Colombia": "co", "Croatia": "hr", "Czech Republic": "cz",
    "Czechia": "cz", "Denmark": "dk", "Estonia": "ee", "Finland": "fi", "France": "fr", "Germany": "de",
    "Greece": "gr", "Hong Kong": "hk", "Hungary": "hu", "India": "in", "Indonesia": "id", "Ireland": "ie",
    "Israel": "il", "Italy": "it", "Japan": "jp", "Latvia": "lv", "Lithuania": "lt", "Malaysia": "my",
    "Mexico": "mx", "Monaco": "mc", "Netherlands": "nl", "Kingdom of the Netherlands": "nl", "New Zealand": "nz",
    "Norway": "no", "Paraguay": "py", "Peru": "pe", "Philippines": "ph", "Poland": "pl", "Portugal": "pt",
    "Romania": "ro", "Russia": "ru", "Saudi Arabia": "sa", "Serbia": "rs", "Singapore": "sg", "Slovakia": "sk",
    "South Africa": "za", "South Korea": "kr", "Spain": "es", "Sweden": "se", "Switzerland": "ch", "Taiwan": "tw",
    "Thailand": "th", "Turkey": "tr", "Türkiye": "tr", "Ukraine": "ua", "United Arab Emirates": "ae",
    "United Kingdom": "gb", "United States": "us", "United States of America": "us", "Uruguay": "uy",
    "Venezuela": "ve",
}


def flag_img(nationality, height=12):
    iso = FLAG_CODES.get(nationality) if isinstance(nationality, str) else None
    if not iso:
        return ""
    return (f'<img src="https://flagcdn.com/h20/{iso}.png" alt="" '
            f'style="height:{height}px;width:auto;border-radius:2px;display:block">')

def country_code(nationality):
    if not isinstance(nationality, str) or not nationality:
        return ""
    return COUNTRY_CODES.get(nationality, nationality[:3].upper())

def format_dob(dob):
    try:
        return f"{date.fromisoformat(dob):%d/%m/%Y}"
    except (TypeError, ValueError):
        return dob
    
def driver_profile(d, s, p):
    bg, fg = D.outcome_tag_style(d["outcome"])
    years = f"{series_span(s['season'].min(), s['season'].max())} {int(s['season'].min())}–{int(s['season'].max())}" \
        if not s.empty else ""
    debut_age = s["age"].dropna()
    debut = f"Debut at {int(debut_age.iloc[0])}" if not debut_age.empty else ""
    bits = [b for b in [f"Born {format_dob(d['dob'])}" if isinstance(d["dob"], str) else "", years, debut,                        
                        f"{0 if pd.isna(d['f1_starts']) else int(d['f1_starts'])} starts"] if b]
    peak = s["performance_rating"].max()
    stats = [("GP2/F2 seasons", int(d["junior_seasons"]), D.PANEL, D.TEXT, ""),
             ("Best championship finish", "–" if pd.isna(d["best_junior_pos"]) else f"P{int(d['best_junior_pos'])}", D.PANEL, D.TEXT, ""),
             ("Highest performance rating", "–" if pd.isna(peak) else int(peak), D.PANEL, D.TEXT, "")]
    if not p.empty:
        first = p.iloc[0]
        kind, note = SNAPSHOT_NOTES.get(first["kind"], ("estimate", ""))
        stats.append((f"{int(first['season'])} {kind}", pct(first["probability"]), D.RQ1_HERO, "#FFFFFF", note))
    tiles = "".join(
        f'<div title="{D.escape(note)}" style="border-radius:18px;padding:14px 16px;background:{b};color:{f};'
        f'display:flex;flex-direction:column;gap:2px"><span style="font-size:12px;opacity:0.8">{label}</span>'
        f'<span class="wide" style="font-size:24px">{D.pc(value)}</span>'
        + (f'<span style="font-size:11px;line-height:1.3;opacity:0.8;margin-top:2px">{D.escape(note)}</span>' if note else "")
        + '</div>' for label, value, b, f, note in stats)
    code = country_code(d["nationality"])
    flag = (f'<span title="{D.escape(str(d["nationality"]))}" style="display:inline-flex;align-items:center;gap:6px;'
            f'font-family:\'Michroma\',sans-serif;font-size:11px;border:1px solid {D.LINE};border-radius:6px;'
            f'padding:3px 7px;color:{D.MUTED}">{flag_img(d["nationality"])}{D.escape(code)}</span>'
            if code else "")
    st.markdown(
        '<div class="bento" style="display:block;margin:4px 0 6px"><div style="display:flex;flex-direction:column;gap:18px">'
        '<div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap"><span class="wide" style="font-size:52px;'
        f'line-height:1;color:transparent;-webkit-text-stroke:1.5px {D.TEXT}">{D.escape(D.driver_code(d["driver_name"]))}'
        '</span><div style="display:flex;flex-direction:column;gap:4px;flex-grow:1;min-width:0">'
        '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap"><span style="font-family:'
        f'\'Barlow Condensed\',sans-serif;font-weight:600;font-size:30px;line-height:1.1">{D.escape(d["driver_name"])}'
        f'</span>{flag}</div>'
        f'<div style="display:flex">{D.tag(outcome_label(d["outcome"]), bg, fg)}</div>'
        f'<span class="muted" style="font-size:14px">{D.escape(" · ".join(bits))}</span></div></div>'
        '<div class="quad" style="display:grid;'
        f'grid-template-columns:repeat({len(stats)},minmax(0,1fr));gap:12px">{tiles}</div></div></div>',
        unsafe_allow_html=True)


def season_cards(s):
    conf = {"High": D.TEAL, "Medium": "#FACC15"}
    cards = "".join(
        f'<div class="card" style="padding:16px;gap:4px;border-radius:20px"><span class="wide" style="font-size:12px">'
        f'{int(r["season"])}</span><span style="font-weight:600;font-size:14px;line-height:1.3;min-height:2.6em">'
        f'{D.escape(str(r["team"]))}</span>'
        f'<span class="muted" style="font-size:12px">{pos_label(r["pos_text"])} · Rating '
        f'{"–" if pd.isna(r["performance_rating"]) else int(r["performance_rating"])}</span>'
        + (D.tag(str(r["confidence"]), "transparent", conf.get(r["confidence"], D.MUTED))
           .replace('style="', f'style="margin-top:auto;align-self:flex-start;border:1px solid '
                               f'{conf.get(r["confidence"], D.MUTED)};', 1) if isinstance(r["confidence"], str) else "")
        + '</div>' for _, r in s.iterrows())
    st.markdown(f'<div class="bento" style="margin-top:0"><div class="seasons" style="grid-column:1 / -1">{cards}'
                '</div></div>', unsafe_allow_html=True)
    st.caption("Confidence labels reflect data completeness. Low confidence indicates a partial season.")


def page_explorer():
    summary = seasons.groupby("driver_key").agg(
        teams=("team", lambda t: " · ".join(dict.fromkeys(t.dropna()))),
        first=("season", "min"), last=("season", "max")).reset_index()
    table = drivers.merge(summary, on="driver_key", how="left")
    lo, hi = int(seasons["season"].min()), int(seasons["season"].max())
    max_n = int(drivers["junior_seasons"].max())
    outcome_options = sorted(drivers["outcome"].dropna().unique(), key=outcome_label)
    team_options = sorted(seasons["team"].dropna().unique())

    with st.container(border=True):
        bar = st.columns([3.2, 1.3, 1.2, 1.5, 1.6, 1.2], vertical_alignment="center")
        name = bar[0].text_input("Driver name", placeholder="Search for a driver", label_visibility="collapsed")
        with bar[1].popover(f"Outcome: {pill_text(st.session_state.get('f_outcome', []), outcome_label)}",
                            use_container_width=True):
            outcomes = st.multiselect("Outcome", outcome_options, format_func=outcome_label, key="f_outcome")
        with bar[2].popover(f"Team: {pill_text(st.session_state.get('f_team', []))}", use_container_width=True):
            teams = st.multiselect("Team", team_options, key="f_team")
        y0, y1 = st.session_state.get("f_years", (lo, hi))
        with bar[3].popover(f"Years: {y0}–{y1}", use_container_width=True):
            years = st.slider("Raced GP2/F2 between", lo, hi, (lo, hi), key="f_years")
        n0, n1 = st.session_state.get("f_seasons", (1, max_n))
        with bar[4].popover(f"GP2/F2 seasons: {n0}–{n1}", use_container_width=True):
            n_seasons = st.slider("Number of GP2/F2 seasons", 1, max_n, (1, max_n), key="f_seasons")

    view = table
    if name:
        view = view[view["driver_name"].str.contains(name, case=False, na=False)]
    if outcomes:
        view = view[view["outcome"].isin(outcomes)]
    if teams:
        keys = seasons.loc[seasons["team"].isin(teams), "driver_key"]
        view = view[view["driver_key"].isin(keys)]
    view = view[(view["last"] >= years[0]) & (view["first"] <= years[1])]
    view = view[view["junior_seasons"].between(*n_seasons)].sort_values("driver_name").reset_index(drop=True)
    bar[5].markdown(f'<div class="dcount">{len(view)} <span>DRIVERS</span></div>', unsafe_allow_html=True)

    if view.empty:
        st.info("No drivers match these filters.")
        return
    if st.session_state.get("pick") not in set(view["driver_key"]):
        st.session_state.pick = view.iloc[0]["driver_key"]
    picked = st.session_state.pick
    d = drivers[drivers["driver_key"] == picked].iloc[0]
    s = seasons[seasons["driver_key"] == d["driver_key"]].sort_values("season")
    p = preds[preds["driver_key"] == d["driver_key"]].sort_values("season")

    left, right = st.columns([5, 7], gap="large")
    with left:
        with st.container(border=True):
            st.markdown('<div class="bento" style="display:block;margin:0">'
                        + D.card_head("Drivers", "Select a driver to view their profile") + '</div>', unsafe_allow_html=True)
            with st.container(height=list_height(s, p), border=False):
                for _, r in view.head(LIST_LIMIT).iterrows():
                    row, go = st.columns([12, 1], vertical_alignment="center")
                    row.markdown(driver_row(r, r["driver_key"] == picked), unsafe_allow_html=True)
                    go.button("›", key=f"pick_{r['driver_key']}", on_click=choose, args=(r["driver_key"],),
                              help=f"Open {r['driver_name']}")
            if len(view) > LIST_LIMIT:
                st.caption(f"Showing the first {LIST_LIMIT} of {len(view)} drivers. Search or filter to narrow the list.")

    with right:
        with st.container(border=True):
            driver_profile(d, s, p)
            if s["performance_rating"].notna().any():
                st.markdown('<div class="bento" style="display:block;margin:8px 0 0">'
                            + D.card_head("Season-by-season performance", "Performance rating")
                            + '</div>', unsafe_allow_html=True)
                career = s.dropna(subset=["performance_rating"]).assign(
                    pos_label=lambda t: t["pos_text"].map(lambda x: f"P{x}" if str(x).isdigit() else str(x)))
                traj = alt.Chart(career).encode(
                    x=alt.X("season:O", title=None),
                    y=alt.Y("performance_rating:Q", title=None, scale=alt.Scale(domain=[0, 100])))
                show_chart((traj.mark_line(color=RQ1_COLOUR, strokeWidth=3) +
                            traj.mark_circle(size=110, color=RQ1_COLOUR, opacity=1).encode(
                                tooltip=[alt.Tooltip("season:O", title="Season"), alt.Tooltip("team:N", title="Team"),
                                         alt.Tooltip("pos_text:N", title="Position"), alt.Tooltip("points:Q", title="Points"),
                                         alt.Tooltip("performance_rating:Q", format=".0f", title="Performance rating")]) +
                            traj.mark_text(dy=-16, fontSize=12, fontWeight=600, color=D.TEXT).encode(
                                text="pos_label:N")).properties(height=240))
                st.caption("Labels show final championship position **(P1 = champion)**. Ratings "
                           "describe each season retrospectively, not predictively.")
        season_cards(s)
        with st.expander("Season details"):
            show_table(pd.DataFrame({
                "Season": s["season"].astype(str), "Series": s["series"], "Points": s["points"],
                "Age": whole_age(s["age"]), "Team strength": s["team_strength"],
            }), column_config={
                "Season": st.column_config.TextColumn("Season", width="small"),
                "Series": st.column_config.TextColumn("Series", width="small"),
                "Points": st.column_config.NumberColumn("Points", format="%d", width="small"),
                "Age": st.column_config.NumberColumn("Age", format="%d", width="small"),
                "Team strength": st.column_config.NumberColumn("Team strength", format="%.2f", width="small"),
            })
        with st.container(border=True):
            st.markdown('<div class="ctitle">Historical prediction snapshots</div>', unsafe_allow_html=True)
            if p.empty:
                st.write("No prediction snapshot: estimates exist only for seasons from 2007, within a driver's "
                         "first three GP2/F2 seasons and before any F1 debut.")
            else:
                labels = {"historical (out-of-fold)": "Back-test", "current": "Live estimate",
                          "model estimate": "Estimate"}
                meaning = {"historical (out-of-fold)": "**Back-test:** Model never saw this driver.",
                           "current": "**Live estimate:** The latest season, with the outcome not yet known.",
                           "model estimate": "**Estimate:** Outcome not used in training."}
                predictions = pd.DataFrame({
                    "Season": p["season"].astype(str), "Career stage": p["k"].map(stage_label),
                    "Estimated chance of reaching F1": p["probability"],
                    "90% range": [interval(lo, hi) for lo, hi in zip(p["prob_low"], p["prob_high"])],
                    "Prediction type": p["kind"].map(labels),
                })
                if not p["prob_low"].notna().any():
                    predictions = predictions.drop(columns=["90% range"])
                show_table(predictions, column_config={
                    "Season": st.column_config.TextColumn("Season", width="small"),
                    "Career stage": st.column_config.TextColumn("Career stage", width="150"),
                    "Estimated chance of reaching F1": st.column_config.ProgressColumn(
                        "Estimated chance of reaching F1", format="percent", min_value=0, max_value=1, width="medium"),
                    "90% range": st.column_config.TextColumn("90% range", width="small"),
                    "Prediction type": st.column_config.TextColumn("Prediction type"),
                })
                st.caption(" ".join(meaning[k] for k in dict.fromkeys(p["kind"]) if k in meaning)
                           + " Each estimate uses only information available at the end of that season. "
                           "Outcome-dependent final-season scores are excluded.")


# 5. Junior Performance
def record_card(label, row, value):
    bg, _ = D.outcome_style(row["outcome"])
    return (
        '<div class="card" style="grid-column:span 4;flex-direction:row;align-items:center;gap:16px;padding:20px 22px">'
        + D.code_tile(D.driver_code(row["driver_name"]), bg, 60)
        + '<div style="display:flex;flex-direction:column;flex-grow:1;min-width:0">'
        f'<span class="muted" style="font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
        f'{label}</span><span style="font-weight:600;font-size:16px">'
        f'{D.escape(row["driver_name"])}</span><span class="muted" style="font-size:12px">{int(row["season"])} · '
        f'{D.escape(str(row["team"]))} · {pos_label(row["pos_text"])}</span></div>'
        f'<span class="wide" style="font-size:24px">{value}</span></div>')

CHART_CARD_HEIGHT = 480   
CHART_FILL = 340          
CHART_FILL_NOTE = 340     

def chart_card(title, chart, note=None, height=CHART_CARD_HEIGHT, one_line=False):
    if height:
        chart = chart.properties(height=CHART_FILL_NOTE if note else CHART_FILL)
    with st.container(border=True, **({"height": height} if height else {})):
        st.markdown(f'<div class="ctitle" style="padding-bottom:12px">{title}</div>', unsafe_allow_html=True)
        show_chart(chart)
        if note:
            layout = "text-align:left;" if one_line else "text-align:center;"
            st.markdown(f'<div style="{layout}font-size:13px;line-height:1.5;color:{D.MUTED};padding-bottom:16px">'
                        f'{note}</div>', unsafe_allow_html=True)

OUTCOME_ORDER = ["Star", "Established", "Reached, didn't stick", "Too early to tell", "Didn't reach F1", "Pending"]

def page_junior():
    outcome_options = [o for o in OUTCOME_ORDER if o in set(seasons["outcome"].dropna())]
    with st.container(border=True):
        c0, c1, c2, c3 = st.columns([3, 3.1, 1.6, 1.8], vertical_alignment="center")
        c0.markdown('<div class="ctitle bar-title" style="white-space:nowrap">All GP2/F2 seasons, '
                    'outside the predictive models</div>', unsafe_allow_html=True)
        sel = st.session_state.get("j_outcome", [])
        with c1.popover("Outcome: All" if not sel else f"Outcome: {len(sel)} selected",
                        use_container_width=False):
            chosen = st.multiselect("Show only these outcomes", outcome_options, format_func=outcome_label,
                                    key="j_outcome")
        drop_low = c2.toggle("Exclude partial seasons", value=True)
        drop_live = c3.toggle(f"Exclude {CURRENT} (in progress)", value=True)
    s = seasons.dropna(subset=["performance_rating"]).copy()
    if drop_low:
        s = s[s["confidence"] != "Low"]
    if drop_live:
        s = s[~s["season_in_progress"]]
    if chosen:
        s = s[s["outcome"].isin(chosen)]
    if s.empty:
        st.info("No seasons match these settings.")
        return
    s["Group"] = s["reached_f1"].map({True: "Reached F1", False: "Did not reach F1"})
    colours = alt.Scale(domain=["Reached F1", "Did not reach F1"], range=[RQ1_COLOUR, "#6B6B7B"])
    tip = [alt.Tooltip("driver_name:N", title="Driver"), alt.Tooltip("season:O", title="Season"),
           alt.Tooltip("team:N", title="Team"), alt.Tooltip("pos_text:N", title="Position"),
           alt.Tooltip("performance_rating:Q", title="Rating")]

    records = []
    top = s.sort_values(["performance_rating", "season"], ascending=[False, True]).iloc[0]
    records.append(record_card("Highest-rated junior season", top, int(top["performance_rating"])))
    gaps = s.dropna(subset=["teammate_gap"])
    if not gaps.empty:
        g = gaps.sort_values(["teammate_gap", "season"], ascending=[False, True]).iloc[0]
        records.append(record_card("Largest teammate advantage", g, f"{g['teammate_gap']:.2f}"))
    never = s[s["outcome"] == "Didn't reach F1"]
    if not never.empty:
           nv = never.sort_values(["performance_rating", "season"], ascending=[False, True]).iloc[0]
           records.append(record_card("Top-rated, never reached F1", nv, int(nv["performance_rating"])))
    st.markdown(f'<div class="bento" style="margin:4px 0 22px">{"".join(records)}</div>', unsafe_allow_html=True)
    
    c1, c2 = st.columns([7, 5])
    
    with c1:
        chart_card(
            "Rating distribution",
            share_histogram(
                s,
                "performance_rating",
                colours,
                height=260,
                padding={"left": 45, "right": 0, "top": 5, "bottom": 5}
            ),
        "Percentage of seasons in each rating band, allowing comparison between groups of different sizes"
        )
        
    with c2:
        prog = (
            s[s["k"] <= 5]
            .groupby(["k", "Group"], as_index=False)
            .agg(
                rating=("performance_rating", "mean"),
                n=("driver_key", "size")
            )
        )
        
        prog = prog[prog["n"] >= 10]
        
        prog_chart = alt.Chart(prog).mark_line(
            point=True,
            strokeWidth=3
        ).encode(
            x=alt.X(
                "k:O",
                title="Season in GP2/F2"
            ),
            
            y=alt.Y(
                "rating:Q",
                title="Average rating"
            ),
            
            color=alt.Color(
                "Group:N",
                scale=colours,
                title=None,
                legend=alt.Legend(offset=8)
            ),
            tooltip=[
                alt.Tooltip("k:O", title="Season in GP2/F2"),
                alt.Tooltip("Group:N", title="Group"),
                alt.Tooltip("rating:Q", format=".0f", title="Average rating"),
                alt.Tooltip("n:Q", title="Drivers")
            ]
        ).properties(
            height=260,
            padding={"left": 35, "right": 0, "top": 5, "bottom": 5}
    
    )
        
        
        chart_card(
            "Performance by junior season",
            prog_chart,
            "Later seasons include only drivers who remained in GP2/F2. Groups with fewer than 10 drivers are hidden."
        )

    c3, c4, c5 = st.columns(3)
    with c3:
        chart_card("Performance rating vs championship position", alt.Chart(s.dropna(subset=["final_pos"])).mark_circle(
            size=40, opacity=0.7).encode(
            x=alt.X("final_pos:Q", title="Championship position", axis=alt.Axis(tickCount=7)),
            y=alt.Y("performance_rating:Q", title=None, scale=alt.Scale(domain=[0, 100]),
                    axis=alt.Axis(tickCount=5, minExtent=30)),
            color=alt.Color("Group:N", scale=colours, legend=None), tooltip=tip).properties(height=260), 
            "Higher ratings generally correspond to better championship finishes",
                    one_line=True)

    with c4:
        chart_card("Age vs performance rating", alt.Chart(s).mark_circle(size=40, opacity=0.7).encode(
            x=alt.X("age:Q", title="Age at the start of the season",
                    scale=alt.Scale(domain=[np.floor(s["age"].min() / 2) * 2, np.ceil(s["age"].max() / 2) * 2]),
                    axis=alt.Axis(tickCount=7)),
            y=alt.Y("performance_rating:Q", title=None, scale=alt.Scale(domain=[0, 100]),
                    axis=alt.Axis(tickCount=5, minExtent=30)),
            color=alt.Color("Group:N", scale=colours, legend=None), tooltip=tip).properties(height=260),
            "Age alone shows no clear relationship with performance rating",
                    one_line=True)

    with c5:
        chart_card("Team strength vs performance rating", alt.Chart(s).mark_circle(
        size=40, opacity=0.7).encode(
        x=alt.X("team_strength:Q", title="Team strength", axis=alt.Axis(tickCount=6, format=".1f")),
        y=alt.Y("performance_rating:Q", title=None, scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(tickCount=5, minExtent=30)),
        color=alt.Color("Group:N", scale=colours, legend=None), tooltip=tip
    ).properties(height=260, padding={"left": 0, "right": 18}),
        "The performance rating already accounts for team strength, so a weak relationship is expected",
        one_line=True)

    chart_card("Performance ratings by championship season", alt.Chart(s.rename(columns={"season": "Season"})).mark_boxplot(
        extent="min-max", rule={"color": D.MUTED}, median={"color": "#FFFFFF"}, color=RQ1_COLOUR).encode(
        x=alt.X("Season:O", title=None), y=alt.Y("performance_rating:Q", title="Performance rating")
    ).properties(height=240), height=None,

    
        note="Each box shows the distribution of driver ratings within a season. The median is the line inside the box.")
    


# 6. Methodology
METHOD_SECTIONS = ["Research design", "Data sources", "Outcome tiers", "Features and prediction points",
                   "Model development", "Validation", "Limitations"]


def anchor(title):
    return title.lower().replace(" ", "-")


def method_card(i, title, body):
    return (f'<div class="card" id="{anchor(title)}"><div style="display:flex;gap:12px;align-items:baseline">'
            f'<span class="num">{i:02d}</span><span class="lbl">{title}</span></div>{body}</div>')


def note(text):
    return f'<span class="muted" style="font-size:14px;line-height:1.5">{text}</span>'


def page_method():
    left, right = st.columns([1, 3], gap="large")
    links = "".join(f'<a href="#{anchor(t)}" target="_self"><span class="num">{i:02d}</span>{t}</a>'
                    for i, t in enumerate(METHOD_SECTIONS, 1))
    left.markdown(f'<div class="toc"><span class="ctitle" style="padding:0 8px 6px">Methodology</span>{links}'
                  f'<a href="{REPO_URL}" target="_blank" style="margin-top:12px;align-self:flex-start;background:{D.TEXT};'
                  f'color:{D.BG} !important;border-radius:999px;padding:7px 16px">Code on GitHub →</a></div>',
                  unsafe_allow_html=True)

    comp, exp = R["experiment_composition"], R["experiment_results"]
    rq1_n = comp.loc[comp["question"] == "RQ1 progression", "positives"].max() if not comp.empty else None
    rq2_rows = exp[exp["question"] == "RQ2 establishment"] if not exp.empty else exp
    rq2_n = rq2_rows["drivers"].max() if not rq2_rows.empty else None

    rq_box = lambda tag_, colour, fill, q, who: (
        f'<div class="box" style="background:{fill};border:1px solid {colour}"><span class="wide" '
        f'style="font-size:12px;color:{colour}">{tag_}</span><span style="font-size:15px">{q}</span>'
        f'<span class="muted" style="font-size:13px">{who}</span></div>')
    design = ('<div class="duo" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px">'
              + rq_box("RQ1 · PROGRESSION", "#6F86FF", "#161C40", "Does a GP2/F2 driver go on to start an F1 race?",
                       "Drivers not yet in F1 · Target: Started at least one race")
              + rq_box("RQ2 · ESTABLISHMENT", D.RQ2, "#2E1E0E",
                       "Among F1 entrants with a sufficiently mature career, do they become Established or a Star?",
                       "F1 entrants · Target: Established or Star") + '</div>')

    sources = "".join(
        '<div style="display:flex;align-items:center;gap:14px"><span class="wide" style="width:48px;height:40px;'
        'flex-shrink:0;border-radius:12px;background:#1B1B23;border:1px solid #34343F;display:flex;align-items:center;'
        f'justify-content:center;font-size:9px">{code}</span><div style="display:flex;flex-direction:column">'
        f'<span style="font-weight:600;font-size:15px">{name}</span><span class="muted" style="font-size:13px">{what}'
        '</span></div></div>' for code, name, what in [
            ("WIKI", "Wikipedia season pages", f"GP2 2005–2016 and FIA F2 2017–{CURRENT}: standings, teams and rounds"),
            ("API", "Jolpica-F1 API", f"F1 standings and race results, 2000–{CURRENT} (successor to Ergast)"),
            ("DATA", "Wikidata", "Dates of birth and nationality")])
    sources += note("Drivers are linked across sources using their Wikipedia articles, with redirects resolved so name variants "
                    "(<i>Hulkenberg</i> / <i>Hülkenberg</i>) map to a single driver. Nineteen data-quality checks "
                    "cover identity matching, team mappings, standings consistency and career anomalies, plus a manual "
                    "random sample.")

    groups = drivers["outcome"].fillna("").map(lambda o: "Excluded" if o.startswith("Excluded") else o)
    counts = groups.value_counts()
    tier_rules = [("Star", "Top-five championship finish or 3+ wins"),
                  ("Established", "3+ full F1 seasons (started at least half the races)"),
                  ("Reached, didn't stick", "F1 starts, fewer than 3 full seasons"),
                  ("Didn't reach F1", "No starts and no outstanding opportunity"),
                  ("Too early to classify", f"Raced F1 in {CURRENT}, fewer than 3 full seasons"),
                  ("Pending", "No F1 start yet; competed in GP2/F2 within the last two seasons"),
                  ("Excluded", "Raced F1 before GP2/F2, or career ended for reasons unrelated to performance")]
    biggest = max(counts.max(), 1)
    tiers = "".join(
        '<div style="display:grid;grid-template-columns:minmax(0,1fr) 44px;align-items:center;gap:12px">'
        f'<div style="display:flex;flex-direction:column;gap:4px"><span style="font-size:14px"><b>{outcome_label(t)}</b> '
        f'<span class="muted">· {rule}</span></span><div style="height:8px;border-radius:4px;background:#24242E">'
        f'<div style="height:100%;border-radius:4px;width:{max(2, counts.get(t, 0) / biggest * 100):.0f}%;'
        f'background:{D.outcome_style(t)[0] if t != "Excluded" else "#4A4A57"}"></div></div></div>'
        f'<span class="wide" style="font-size:13px;text-align:right">{int(counts.get(t, 0))}</span></div>'
        for t, rule in tier_rules)
    tiers += note("<b>Why pending drivers are not failures:</b> They may still be promoted. Counting them as negatives "
                  "would make recent cohorts look worse than they are, so they are left out until their outcome is "
                  "known.")

    points = "".join(
        f'<span class="wide" style="position:relative;width:40px;height:40px;border-radius:50%;background:{b};'
        f'border:2px solid {c};display:flex;align-items:center;justify-content:center;font-size:10px">{t}</span>'
        for t, b, c in [("S1", D.RQ1, D.RQ1), ("S2", D.RQ1, D.RQ1), ("S3", D.RQ1, D.RQ1), ("F1?", D.BG, D.TEXT)])
    features = (
        '<div class="duo" style="display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:28px">'
        '<div style="display:flex;flex-direction:column;gap:12px">' + D.recipe_bar(44)
        + note("Each season is rated using information available up to that point. A three-season "
               "burn-in is applied, so ratings begin in 2007. Models also use <b>age</b> at the start of the season and "
               "<b>team strength</b>, measured by the team's combined championship points rank that season.")
        + '</div><div style="display:flex;flex-direction:column;gap:12px"><div style="display:flex;align-items:center;'
        'justify-content:space-between;position:relative;padding:4px 6px"><span style="position:absolute;left:20px;'
        f'right:20px;top:50%;height:2px;background:{D.LINE}"></span>{points}</div>'
        + note("Predictions are made at the end of a driver's rookie, second and third seasons, for drivers not yet "
               "in F1. A \"final junior season\" snapshot is selected by the outcome itself (the season before F1 for "
               "promoted drivers, the end of a failed career for the rest), so its high score of around 0.87 is "
               "exploratory only.") + '</div></div>')

    model = (note("Logistic regression with median imputation and standardisation, kept deliberately simple for "
                  "samples this size. Each feature set is compared with performance alone on the same resamples.")
             + note("<b>Why the potential composites were removed:</b> Two \"potential\" scores were tested, one "
                    "comparing drivers with same-age peers and one projecting age-typical development. Neither "
                    "improved predictions once leakage was removed. The apparent improvement disappeared when the development "
                    "curve was fitted without the drivers being evaluated, suggesting that the composites were not providing " \
                    "reliable additional information beyond age and performance."))

    checks = "".join(
        f'<div class="box"><span class="wide" style="font-size:20px">{v}</span><span style="font-weight:600;'
        f'font-size:14px">{n}</span><span class="muted" style="font-size:13px;line-height:1.4">{w}</span></div>'
        for v, n, w in [("5×20", "Cross-validation", "Five folds, repeated 20 times, one row per driver"),
                        ("500", "Out-of-bag bootstrap", "Resample drivers, refit everything and score those left "
                                                        "out. Failed replicates are reported."),
                        ("→", "Chronological", "Train on earlier rookie cohorts and evaluate on later, unseen cohorts"),
                        ("5 YR", "Strict horizon", "Only outcomes that could have been known within five years of each prediction are evaluated")])
    validation = ('<div class="quad" style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px">'
                  + checks + '</div>'
                  + note("<b>Why the chronological intervals understate uncertainty:</b> They resample the test "
                         "drivers around models that are already fitted, so they leave out the variation from refitting "
                         "on different training drivers."))

    limits = [("Sample size", f"About {int(rq1_n) if rq1_n else 45} F1 entrants for RQ1 and "
                              f"{int(rq2_n) if rq2_n else 39} drivers for RQ2"),
              ("Censoring", "Recent careers are unfinished. Drivers who debut more than five years after a prediction point "
              "are classified as not having reached F1 within the evaluation window, even if they eventually debut."),
              ("Selection", "Later prediction points contain fewer drivers because those promoted to F1 earlier are no longer "
              "eligible for prediction. The remaining population is therefore increasingly selected."),
              ("Data depth", "Season standings only, without race-by-race results, qualifying or telemetry."),
              ("Confounding", "Team placement reflects a mixture of driver ability, funding, academy backing and opportunity, "
              "making its independent contribution difficult to isolate.")]
    limitations = ('<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px">'
                   + "".join(
        f'<div style="border:1px solid {D.LINE};border-radius:16px;padding:14px 18px;display:flex;'
        f'flex-direction:column;gap:6px"><b style="font-size:15px">{n}</b>'
        f'<span class="muted" style="font-size:13px;line-height:1.5">{w}</span></div>' for n, w in limits)
                   + '</div>')

    bodies = [design, sources, tiers, features, model, validation, limitations]
    right.markdown('<div class="bento" style="display:block;margin-top:0"><div class="stack">'
                   + "".join(method_card(i, t, b) for i, (t, b) in enumerate(zip(METHOD_SECTIONS, bodies), 1))
                   + '</div></div>', unsafe_allow_html=True)


{"Overview": page_overview, "Reaching F1": page_rq1, "Establishing in F1": page_rq2,
 "Driver Explorer": page_explorer, "Junior Performance": page_junior,
 "Methodology": page_method}[st.session_state.page]()
footer()