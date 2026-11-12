"""Shared look for the app: colours, fonts, navigation pills and the bento cards."""

from html import escape
from urllib.parse import quote_plus

BG = "#101015"
PANEL = "#1B1B23"
LINE = "#34343F"
TEXT = "#ECECF1"
MUTED = "#9A9AAB"
RQ1_HERO = "#2433FF"
RQ1 = "#2F5BFF"
RQ2 = "#FF8A1F"
TEAL = "#5FD4C1"
CHIPS = {
    "yes": ("#15803D", "#FFFFFF", "clear gain"),
    "not clearly": ("#3A2F0B", "#FACC15", "not clearly"),
    "hurts": ("#4A1414", "#FF8A8A", "hurts"),
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Michroma&family=Barlow+Condensed:wght@500;600;700&family=Barlow:wght@400;500;600&display=swap');
html, body, [data-testid="stAppViewContainer"], [data-testid="stMarkdownContainer"], .stApp {font-family: 'Barlow', system-ui, sans-serif;}
[data-testid="stAppViewContainer"], .stApp {background: #101015;}
[data-testid="stHeader"] {background: transparent;}
.block-container {max-width: 1480px; padding-top: 2.2rem;}
h1, h2, h3 {font-family: 'Barlow Condensed', sans-serif !important; font-weight: 600 !important; letter-spacing: 0.01em;}
[data-testid="stMetricValue"] {font-family: 'Michroma', sans-serif; font-size: 1.6rem;}
[data-testid="stMetric"] {border: 1px solid #34343F; border-radius: 20px; padding: 16px 20px;}
.brand {font-family: 'Michroma', sans-serif; font-size: 14px; letter-spacing: 0.06em; color: #ECECF1; padding-top: 8px; white-space: nowrap;}
.pc {font-family: 'Barlow', sans-serif; font-weight: 600;}
[data-testid="stRadio"] [role="radiogroup"] {gap: 8px !important; flex-wrap: wrap;}
[data-testid="stRadio"] label:has(input[type="radio"]) {margin: 0 !important; padding: 6px 16px !important; border-radius: 999px !important; border: 1px solid #34343F !important; background: transparent !important; cursor: pointer;}
[data-testid="stRadio"] label:has(input[type="radio"]) *:not(:has([data-testid="stMarkdownContainer"])):not([data-testid="stMarkdownContainer"]):not([data-testid="stMarkdownContainer"] *) {display: none !important;}
[data-testid="stRadio"] label:has(input[type="radio"]) div {padding-left: 0 !important; margin-left: 0 !important;}
[data-testid="stRadio"] label p {font-weight: 600 !important; font-size: 14px !important; color: #9A9AAB !important; white-space: nowrap;}
[data-testid="stRadio"] label:hover p {color: #ECECF1 !important;}
[data-testid="stRadio"] label:has(input:checked) {background: var(--active) !important; border-color: var(--active) !important;}
[data-testid="stRadio"] label:has(input:checked) p {color: var(--active-fg) !important;}
.bento {display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 20px; margin: 8px 0 28px; color: #ECECF1;}
.bento .card {border: 1px solid #34343F; border-radius: 28px; padding: 26px; display: flex; flex-direction: column; gap: 12px; min-width: 0;}
.bento .solid {border-radius: 28px; padding: 30px; display: flex; flex-direction: column; gap: 12px; position: relative; overflow: hidden; min-width: 0;}
.bento .lbl {font-family: 'Barlow Condensed', sans-serif; font-weight: 600; font-size: 19px;}
.bento .wide {font-family: 'Michroma', sans-serif;}
.bento .muted {color: #9A9AAB;}
.bento .row {display: flex; justify-content: space-between; align-items: baseline; gap: 14px;}
.bento .chip {align-self: flex-start; border-radius: 999px; padding: 4px 12px; font-size: 12px; font-weight: 600;}
.bento .ghost {position: absolute; right: -8px; bottom: -22px; font-family: 'Michroma', sans-serif; font-size: 112px; line-height: 1; color: transparent; pointer-events: none;}
.bento .rng {display: grid; grid-template-columns: 170px minmax(0, 1fr) 50px; align-items: center; gap: 14px;}
.bento .track {position: relative; height: 26px;}
.bento .sub3 {display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px;}
.bento .waffle {display: grid; grid-template-columns: repeat(23, minmax(0, 1fr)); gap: 4px;}
.bento .waffle span {aspect-ratio: 1; border-radius: 3px;}
.bento a.go, .toc a {text-decoration: none;}
.bento a.go {align-self: flex-start; border-radius: 999px; padding: 7px 16px; font-weight: 600; font-size: 14px;}
.bento .tag {font-size: 12px; font-weight: 600; border-radius: 999px; padding: 3px 10px; white-space: nowrap;}
.bento .num {font-family: 'Michroma', sans-serif; font-size: 11px; color: #9A9AAB;}
.bento .box {border-radius: 20px; padding: 16px 18px; background: #1B1B23; display: flex; flex-direction: column; gap: 6px; min-width: 0;}
.bento .seasons {display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 12px;}
.stack {display: flex; flex-direction: column; gap: 20px;}
.stack .card {scroll-margin-top: 80px;}
.toc {display: flex; flex-direction: column; gap: 4px; border: 1px solid #34343F; border-radius: 28px; padding: 22px;}
.toc a {display: flex; gap: 12px; align-items: baseline; padding: 8px; border-radius: 12px; font-weight: 600; font-size: 14px; color: #9A9AAB !important;}
.toc a:hover {background: #1B1B23; color: #ECECF1 !important;}
.toc .num {font-family: 'Michroma', sans-serif; font-size: 11px;}
.drow {display: flex; align-items: center; gap: 14px; padding: 9px 10px; border-radius: 16px; border: 1px solid transparent; color: #ECECF1;}
.drow .dtext {display: flex; flex-direction: column; flex-grow: 1; min-width: 0;}
.drow .dtext b {font-size: 15px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.drow .dtext span {font-size: 12px; color: #9A9AAB;}
.drow .tag {font-size: 12px; font-weight: 600; border-radius: 999px; padding: 3px 10px; white-space: nowrap;}
.dcount {font-family: 'Michroma', sans-serif; font-size: 12px; color: #ECECF1; white-space: nowrap; text-align: right;}
.dcount span {color: #9A9AAB;}
[data-testid="stMarkdown"]:has(.dcount), [data-testid="stMarkdownContainer"]:has(.dcount), [data-testid="stElementContainer"]:has(.dcount) {margin: 0 !important; padding: 0 !important;}
.bar-title {margin: 0 !important; line-height: 1.2;}
[data-testid="stMarkdown"]:has(.bar-title), [data-testid="stMarkdownContainer"]:has(.bar-title), [data-testid="stElementContainer"]:has(.bar-title) {margin: 0 !important; padding: 0 !important;}
[data-testid="stPopover"] button, [data-testid="stPopoverButton"] {border-radius: 999px !important; border: 1px solid #34343F !important; background: transparent !important; white-space: nowrap;}
[data-testid="stHorizontalBlock"]:has(.drow):not(:has([data-testid="stHorizontalBlock"])) {align-items: center !important;}
[data-testid="stHorizontalBlock"]:has(.drow):not(:has([data-testid="stHorizontalBlock"])) [data-testid="stMarkdownContainer"],
[data-testid="stHorizontalBlock"]:has(.drow):not(:has([data-testid="stHorizontalBlock"])) [data-testid="stMarkdown"] {margin: 0 !important; padding: 0 !important;}
[data-testid="stHorizontalBlock"]:has(.drow):not(:has([data-testid="stHorizontalBlock"])) [data-testid="stColumn"] > div {justify-content: center;}
.stButton {display: flex; justify-content: center; align-items: center;}
.stButton button {width: 22px !important; height: 22px !important; min-height: 0 !important; padding: 0 !important; border-radius: 50% !important; border: 1px solid #4A4A57 !important; background: transparent !important; display: flex; align-items: center; justify-content: center;}
.stButton button * {display: none !important;}
.stButton button::after {content: ""; width: 5px; height: 5px; border-top: 1.5px solid #9A9AAB; border-right: 1.5px solid #9A9AAB; transform: translateX(-1px) rotate(45deg);}
.stButton button:hover {border-color: #ECECF1 !important;}
.stButton button:hover::after {border-color: #ECECF1;}
.ctitle {font-family: 'Barlow Condensed', sans-serif; font-weight: 600; font-size: 20px; margin-bottom: 2px;}
[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 28px !important; border-color: #34343F !important;}
[data-baseweb="input"], [data-baseweb="select"] > div {border-radius: 999px !important;}
@media (max-width: 960px) {
  .bento {grid-template-columns: minmax(0, 1fr);}
  .bento > * {grid-column: 1 / -1 !important; grid-row: auto !important;}
  .bento .sub3, .bento .duo, .bento .quad {grid-template-columns: minmax(0, 1fr) !important;}
  .bento .rng {grid-template-columns: minmax(0, 1fr) 44px; gap: 2px 12px;}
  .bento .rng > :first-child {grid-column: 1 / -1;}
  .bento .row {flex-wrap: wrap;}
  .bento .solid {min-height: 0 !important;}
  .bento .question {font-size: 27px !important;}
  .bento .path {grid-template-columns: minmax(0, 1fr) !important; gap: 6px;}
  .bento .path .arrow {flex-direction: row-reverse !important; justify-content: center;}
  .bento .path .arrow > span:last-child {width: 2px !important; height: 18px;}
  .bento .ghost {font-size: 90px;}
}
</style>
"""


def page_css(active, active_fg="#FFFFFF"):
    return CSS + f"<style>:root {{--active: {active}; --active-fg: {active_fg};}}</style>"


def html(*parts):
    return "".join(parts)


def pc(text):
    """The wide font draws % badly, so show the sign in the text font."""
    return str(text).replace("%", '<span class="pc">%</span>')


def f2(x):
    return f"{x:.2f}"


def chip(text, bg, fg):
    return f'<span class="chip" style="background:{bg};color:{fg}">{escape(text)}</span>'


def gain_chip(delta, verdict):
    sign = "+" if delta >= 0 else "−"
    bg, fg, word = CHIPS.get(verdict, (LINE, TEXT, ""))
    text = f"{sign}{abs(delta):.2f}" + (f" · {word}" if word else " vs performance")
    return chip(text, bg, fg)


def place(v, lo, hi):
    return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))


def range_chart(rows, lo=0.5, hi=1.0, chance=None):
    """rows: dicts with name, auc, low, high, colour, strong."""
    out = []
    for r in rows:
        left, right = place(r["low"], lo, hi), place(r["high"], lo, hi)
        at = place(r["auc"], lo, hi)
        line = ""
        if chance is not None:
            line = (f'<span style="position:absolute;left:{place(chance, lo, hi):.1f}%;top:0;bottom:0;'
                    'border-left:2px dashed #FACC15"></span>')
        weight = "#FFFFFF" if r.get("strong") else "#C8C8D4"
        out.append(
            f'<div class="rng"><span style="font-weight:600;font-size:15px;color:{weight}">{escape(r["name"])}</span>'
            f'<div class="track"><span style="position:absolute;left:0;right:0;top:12px;height:2px;background:#24242E"></span>'
            f'{line}<span style="position:absolute;left:{left:.1f}%;width:{right - left:.1f}%;top:11px;height:4px;'
            f'border-radius:2px;background:{r["colour"] if r.get("strong") else "#4A4A57"}"></span>'
            f'<span style="position:absolute;left:{at:.1f}%;top:5px;width:16px;height:16px;margin-left:-8px;'
            f'border-radius:50%;background:{r["colour"]};box-shadow:0 0 0 3px {BG}"></span></div>'
            f'<span class="wide" style="font-size:14px;text-align:right">{f2(r["auc"])}</span></div>')
    mid = (lo + hi) / 2
    mid_text = f'<span style="color:#FACC15">{f2(mid)} CHANCE</span>' if chance == mid else f"<span>{f2(mid)}</span>"
    out.append(f'<div class="rng"><span></span><div class="wide muted" style="display:flex;justify-content:space-between;'
               f'font-size:11px"><span>{f2(lo)}</span>{mid_text}<span>{f2(hi)}</span></div><span></span></div>')
    return "".join(out)


def hero(colour, fg, eyebrow, question, value, value_label, value_note, body, chips, ghost, ghost_stroke, span):
    chip_html = "".join(chip(c, "rgba(255,255,255,0.16)" if fg == "#FFFFFF" else "rgba(26,18,6,0.12)", fg)
                        for c in chips)
    return (
        f'<div class="solid" style="grid-column:{span};grid-row:1 / span 2;background:{colour};color:{fg};min-height:500px">'
        f'<span class="wide" style="font-size:13px;opacity:0.8">{eyebrow}</span>'
        f'<span class="question" style="font-family:\'Barlow Condensed\',sans-serif;font-weight:600;font-size:34px;'
        f'line-height:1.1">{question}</span>'
        f'<div style="display:flex;align-items:flex-end;gap:18px;margin-top:24px;flex-wrap:wrap">'
        f'<span class="wide" style="font-size:80px;line-height:0.9">{value}</span>'
        f'<div style="display:flex;flex-direction:column;padding-bottom:6px"><span style="font-weight:600;font-size:16px">'
        f'{value_label}</span><span style="font-size:14px;opacity:0.85">{value_note}</span></div></div>'
        f'<span style="font-size:16px;line-height:1.5;max-width:440px;opacity:0.92">{body}</span>'
        f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:auto;max-width:56%;position:relative;z-index:1">'
        f'{chip_html}</div>'
        f'<span class="ghost" style="-webkit-text-stroke:2px {ghost_stroke}">{ghost}</span></div>')


def stat_card(kind, value, line, chip_html, note, style=""):
    return (f'<div class="card" style="padding:22px;gap:8px;{style}"><span class="muted" style="font-size:13px">{kind}</span>'
            f'<span class="wide" style="font-size:34px">{value}</span><span style="font-size:14px">{line}</span>'
            f'<div style="margin-top:auto">{chip_html}</div><span class="muted" style="font-size:12px">{note}</span></div>')


def waffle(total, filled, colour):
    cells = "".join(f'<span style="background:{colour if i < filled else LINE}"></span>' for i in range(total))
    return f'<div class="waffle">{cells}</div>'


def legend_item(colour, text):
    return (f'<span style="display:flex;align-items:center;gap:8px"><span style="width:12px;height:12px;'
            f'border-radius:3px;background:{colour};border:1px solid #4A4A57"></span>{escape(text)}</span>')


def meter(label, value, lo=0.5, hi=1.0, ink="#0B1416"):
    return (f'<div class="row"><span style="font-weight:600">{label}</span><span class="wide" style="font-size:22px">'
            f'{f2(value)}</span></div><div style="height:8px;border-radius:4px;background:rgba(11,20,22,0.15)">'
            f'<div style="width:{place(value, lo, hi):.0f}%;height:100%;border-radius:4px;background:{ink}"></div></div>')


def code_tile(code, colour, size=52, fg="#FFFFFF"):
    return (f'<span style="width:{size}px;height:36px;flex-shrink:0;border-radius:10px;background:{colour};color:{fg};'
            f'display:flex;align-items:center;justify-content:center;font-family:\'Michroma\',sans-serif;'
            f'font-size:11px">{escape(code)}</span>')


def driver_code(name):
    rest = name.split(" ", 1)[1] if " " in name else name
    return "".join(ch for ch in rest if ch.isalpha())[:3].upper()


OUTCOME_STYLE = {
    "Star": (RQ2, "#1A1206"),
    "Established": ("#FFC48A", "#1A1206"),
    "Reached, didn't stick": (RQ1, "#FFFFFF"),
    "Too early to tell": (TEAL, "#0B1416"),
    "Pending": (TEAL, "#0B1416"),
    "Didn't reach F1": (LINE, TEXT),
}


OUTCOME_TAG = {
    "Star": (RQ2, "#1A1206"),
    "Established": ("#FFC48A", "#1A1206"),
    "Reached, didn't stick": ("#161C40", "#AFC0FF"),
    "Too early to tell": ("#0F2E2A", TEAL),
    "Pending": ("#0F2E2A", TEAL),
    "Didn't reach F1": ("#24242E", "#C8C8D4"),
}


def outcome_tag_style(outcome):
    return OUTCOME_TAG.get(outcome, ("#24242E", MUTED))


def outcome_style(outcome):
    return OUTCOME_STYLE.get(outcome, ("#24242E", MUTED))


def tag(text, bg, fg):
    return f'<span class="tag" style="background:{bg};color:{fg}">{escape(text)}</span>'


def link(text, page, bg, fg):
    return f'<a class="go" href="?page={quote_plus(page)}" target="_self" style="background:{bg};color:{fg}">{escape(text)}</a>'


def card_head(title, note=""):
    right = f'<span class="muted" style="font-size:13px">{note}</span>' if note else ""
    return f'<div class="row"><span class="lbl">{title}</span>{right}</div>'


def recipe_bar(height=54):
    parts = [
        ("Teammate gap", "Closest available same-car comparison", 50, RQ1, "#FFFFFF"),
        ("Car-adjusted result", "Finishing position relative to team strength", 30, TEAL, "#0B1416"),
        ("Points vs leader", "Points scored relative to the championship leader", 20, RQ2, "#1A1206"),
    ]
    cols = []
    for i, (name, note, w, bg, fg) in enumerate(parts):
        left = "14px" if i == 0 else "0"
        right = "14px" if i == len(parts) - 1 else "0"
        cols.append(
            f'<div style="flex-grow:{w};display:flex;flex-direction:column;gap:12px">'
            f'<div style="height:{height}px;background:{bg};color:{fg};display:flex;align-items:center;padding:0 14px;'
            f'border-radius:{left} {right} {right} {left};font-family:\'Michroma\',sans-serif;font-size:13px">{pc(f"{w}%")}</div>'
            f'<div style="width:0;min-width:100%;display:flex;flex-direction:column;font-size:14px">'
            f'<b>{name}</b><span class="muted" style="font-size:13px">{note}</span></div></div>')
    return f'<div style="display:flex;gap:3px">{"".join(cols)}</div>'