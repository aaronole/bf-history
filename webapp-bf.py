import html
import re

import pandas as pd
import requests
import streamlit as st


BASE = "https://api.zygarden.gg/api/v2"
SPRITE_URL = "https://cdn.zygarden.gg/sprites/{}.png"

st.set_page_config(page_title="Battle Frontier Usage History", layout="wide")


# ---------------------------------------
# API helpers (cached for 10 minutes so repeat searches are fast
# and Zygarden's servers aren't hit unnecessarily)
# ---------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def get_json(url, params=None):
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def search_trainers(query):
    data = get_json(
        f"{BASE}/trainers",
        params={"filter": f"name=*{query}", "page": 1, "count": 20},
    )
    return data.get("items", [])


def load_tournaments(trainer_id):
    profile = get_json(f"{BASE}/trainer/{trainer_id}")
    tournaments = list(profile["tournaments"]["items"])
    next_page = profile["tournaments"].get("nextPage")
    while next_page:
        page = get_json(next_page)
        tournaments.extend(page.get("items", []))
        next_page = page.get("nextPage")
    return tournaments


# ---------------------------------------
# Cycle name standardization
# ---------------------------------------
def standardize_name(name):
    """Return S#C#, S#BT, or S#WC, or None if the name isn't a recognized BF event."""
    m = (re.search(r"\bS(\d+)\s*C(\d+)\b", name, re.I)
         or re.search(r"Season\s*(\d+)\W+Cycle\s*(\d+)", name, re.I))
    if m:
        return f"S{m[1]}C{m[2]}"

    season = re.search(r"\bS(\d+)\b|Season\s*(\d+)", name, re.I)
    if not season:
        return None
    s = season.group(1) or season.group(2)

    if re.search(r"\bWorlds\b|\bWC\b", name, re.I):
        return f"S{s}WC"

    if re.search(r"Battle Tower|\bBT\b", name, re.I):
        num = re.search(r"(?:Battle Tower|\bBT)\s*[-#]?\s*(\d+)", name, re.I)
        return f"S{s}BT" + (f"-{num[1]}" if num else "")

    return None


# ---------------------------------------
# Build rows
# ---------------------------------------
def fmt_score(score):
    if not score:
        return ""
    return f"{score.get('wins', 0)}-{score.get('losses', 0)}"


def build_rows(tournaments, trainer_name):
    rows = []
    excluded_bf = []

    for tournament in tournaments:
        raw_name = tournament["tournamentName"]

        # Strictly Battle Frontier only: anything else is skipped silently
        if "battle frontier" not in raw_name.lower():
            continue

        # Must also be a cycle, Battle Tower, or Worlds
        cycle = standardize_name(raw_name)
        if cycle is None:
            excluded_bf.append(raw_name)
            continue

        # Only real rounds count: skip placeholder/empty entries
        played = [
            p for p in tournament.get("battleParties", [])
            if "round" in p and p.get("battleParty")
        ]

        # Tournaments stay in API order; rounds within each go last-to-first
        played.sort(key=lambda p: p["round"], reverse=True)

        for party in played:
            score = fmt_score(party.get("score"))

            # Skip rounds that never happened
            if score in ("", "0-0"):
                continue

            rows.append({
                "Trainer": trainer_name,
                "Cycle": cycle,
                "Round": party["round"],
                "Score": score,
                "Wins": party["score"].get("wins", 0),
                "Losses": party["score"].get("losses", 0),
                "Team": [(p["id"], bool(p.get("isShadow")))
                         for p in party["battleParty"]],
            })

    return rows, sorted(set(excluded_bf))

#---------------------------------------
# Sprite URL
#---------------------------------------


def sprite_url(species_id):
    return SPRITE_URL.format(species_id.replace("_", "-"))


# ---------------------------------------
# HTML table
# ---------------------------------------
CSS = """
table.bf-table { border-collapse: collapse; table-layout: fixed;
                 width: 100%; max-width: 1100px; margin: 0 auto; }
table.bf-table th, table.bf-table td {
    padding: 2px 4px; text-align: center; font-size: 14px;
    white-space: nowrap; background: transparent; color: inherit;
    border: none; border-bottom: 1px solid rgba(128,128,128,0.25); }
table.bf-table th { padding-bottom: 6px;
                    border-bottom: 2px solid rgba(128,128,128,0.5); }
table.bf-table td.sprite { padding: 2px; }

table.bf-table .mon { position: relative; width: 100%; max-width: 60px;
                      margin: 0 auto; padding: 0; overflow: hidden; }
table.bf-table .mon::before { content: ""; display: block;
                              padding-top: 100%; }
table.bf-table .mon img { position: absolute !important; top: 0; left: 0;
                          width: 100% !important; height: 100% !important;
                          max-width: none !important; margin: 0 !important;
                          padding: 0 !important; transform: none !important;
                          object-fit: contain; }

table.bf-table .shadow {
    background: radial-gradient(circle, rgba(130,40,200,0.95) 0%,
                rgba(130,40,200,0.6) 55%, rgba(130,40,200,0) 78%); }

@media (max-width: 600px) {
  table.bf-table th, table.bf-table td { font-size: 11px; padding: 2px 1px; }
}
"""


def mon_cell(species_id, is_shadow):
    sid = html.escape(species_id)
    cls = "mon shadow" if is_shadow else "mon"
    return (
        f'<td class="sprite"><div class="{cls}" title="{sid}">'
        f'<img src="{html.escape(sprite_url(species_id))}" alt="{sid}">'
        f"</div></td>"
    )


def build_html(rows):
    header = (
        "<thead><tr><th>Cycle</th><th>Round</th><th>Score</th>"
        '<th colspan="6"></th></tr></thead>'
    )

    html_rows = []
    for r in rows:
        cells = [
            f"<td>{html.escape(r['Cycle'])}</td>",
            f"<td>{r['Round']}</td>",
            f"<td>{html.escape(r['Score'])}</td>",
        ]
        for i in range(6):
            if i < len(r["Team"]):
                cells.append(mon_cell(*r["Team"][i]))
            else:
                cells.append('<td class="sprite"></td>')
        html_rows.append("<tr>" + "".join(cells) + "</tr>")

    colgroup = (
        '<colgroup><col style="width:16%"><col style="width:11%">'
        '<col style="width:11%"></colgroup>'
    )

    # Everything is collapsed to a single line: blank lines or indentation
    # inside HTML can make Streamlit's markdown parser treat it as code.
    css = " ".join(CSS.split())
    return (
        f"<style>{css}</style>"
        f'<table class="bf-table">{colgroup}{header}'
        f"<tbody>{''.join(html_rows)}</tbody></table>"
    )


def build_csv(rows):
    records = []
    for r in rows:
        rec = {k: r[k] for k in ("Trainer", "Cycle", "Round", "Score")}
        for i in range(6):
            if i < len(r["Team"]):
                sid, shadow = r["Team"][i]
                rec[f"P{i+1}"] = sid + (" (S)" if shadow else "")
            else:
                rec[f"P{i+1}"] = ""
        records.append(rec)
    return pd.DataFrame(records).to_csv(index=False).encode("utf-8")


def winrate_text(rows):
    wins = sum(r["Wins"] for r in rows)
    losses = sum(r["Losses"] for r in rows)
    total = wins + losses
    if total == 0:
        return ""
    return f"Overall BF Winrate: {wins / total * 100:.1f}%"


# ---------------------------------------
# Page
# ---------------------------------------
st.title("Battle Frontier Usage History")

query = st.text_input(
    "Trainer name", placeholder="Enter a trainer name and press Enter"
).strip()

if not query:
    st.stop()

try:
    with st.spinner("Searching..."):
        matches = search_trainers(query)
except requests.RequestException:
    st.error("Couldn't reach Zygarden. Please try again in a moment.")
    st.stop()

if not matches:
    st.warning("Trainer not found.")
    st.stop()

# Prefer exact (case-insensitive) matches; otherwise offer all results
exact = [t for t in matches if t["name"].lower() == query.lower()]
candidates = exact or matches

if len(candidates) == 1:
    trainer = candidates[0]
else:
    trainer = st.selectbox(
        "Multiple trainers found. Pick one:",
        candidates,
        format_func=lambda t: t["name"],
    )

try:
    with st.spinner(f"Loading {trainer['name']}'s history..."):
        tournaments = load_tournaments(trainer["id"])
except requests.RequestException:
    st.error("Couldn't load that trainer's history. Please try again.")
    st.stop()

rows, excluded = build_rows(tournaments, trainer["name"])

if not rows:
    st.info(f"No Battle Frontier history found for {trainer['name']}.")
    st.stop()

header_html = (
    '<div style="display:flex; flex-wrap:wrap; justify-content:space-between; '
    'align-items:baseline; column-gap:2rem;">'
    f'<h3 style="margin:0;">{html.escape(trainer["name"])}</h3>'
    f'<h3 style="margin:0;">{html.escape(winrate_text(rows))}</h3>'
    "</div>"
)
st.markdown(header_html, unsafe_allow_html=True)

st.markdown(build_html(rows), unsafe_allow_html=True)


st.download_button(
    "Download as CSV",
    build_csv(rows),
    file_name=f"{trainer['name']}_history.csv",
    mime="text/csv",
)

if excluded:
    with st.expander("Excluded events"):
        st.write("These have \"Battle Frontier\" in the name but aren't a cycle, "
                 "Battle Tower, or Worlds:")
        for n in excluded:
            st.write(f"- {n}")
