"""
Part 1 - Build the dataset.

Collects GP2/F2 standings and entries (Wikipedia), F1 standings (Jolpica) and
dates of birth (Wikidata), loads them into PostgreSQL and runs part1_build.sql.

export PGPASSWORD="..."

"""

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import psycopg
import requests
from bs4 import BeautifulSoup
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
SQL_PATH = Path(__file__).resolve().parent / "part1_build.sql"
SCHEMA = "f1"

DB = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": os.getenv("PGPORT", "5432"),
    "dbname": os.getenv("PGDATABASE", "f1_talent"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD"),
}

JUNIOR_FIRST_SEASON = 2005
F1_FIRST_SEASON = 2000
CURRENT_SEASON = 2026

HEADERS = {
    "User-Agent": "f1-talent-pipeline/0.1 (portfolio project; contact: contact-removed)"
}

WIKI_API = "https://en.wikipedia.org/w/api.php"
JOLPICA = "https://api.jolpi.ca/ergast/f1"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

session = requests.Session()
session.headers.update(HEADERS)


def _request(method, url, cache_file=None, refresh=False, pause=0.5, **kwargs):
    if cache_file and cache_file.exists() and not refresh:
        return json.loads(cache_file.read_text(encoding="utf-8"))

    for attempt in range(5):
        resp = session.request(method, url, timeout=60, **kwargs)
        if resp.status_code in (429, 500, 502, 503, 504):
            wait = 5 * (attempt + 1)
            print(f"    rate limited, waiting {wait}s ...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        break
    else:
        raise RuntimeError(f"Gave up after repeated rate limits: {url}")

    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data), encoding="utf-8")
    time.sleep(pause)
    return data


def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


FOOTNOTE_RE = re.compile(r"\[[^\]]*\]")
POS_RE = re.compile(r"\d+|NC|DSQ|EX|—|–|-", re.IGNORECASE)


def clean_text(text):
    text = FOOTNOTE_RE.sub("", text or "")
    return re.sub(r"\s+", " ", text).strip()


def wiki_title_from_href(href):
    if not href or not href.startswith("/wiki/"):
        return None
    title = unquote(href[len("/wiki/"):].split("#")[0]).replace("_", " ")
    if ":" in title:
        return None
    return title


def driver_from_cell(cell):
    name = clean_text(cell.get_text(" "))
    for a in cell.find_all("a", href=True):
        if a.find_parent(class_="flagicon") or a.find("img"):
            continue
        title = wiki_title_from_href(a["href"])
        if title:
            return clean_text(a.get_text(" ")) or name, title
    return name, None


def table_to_grid(table):
    """Expand rowspan/colspan so every row has the same column positions."""
    def span(cell, attr):
        m = re.match(r"\d+", str(cell.get(attr, "1")))
        return int(m.group()) if m else 1

    grid, pending = [], {}
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells = iter(tr.find_all(["th", "td"], recursive=False))
        row, col = [], 0
        while True:
            if col in pending:
                cell, left = pending[col]
                row.append(cell)
                if left <= 1:
                    del pending[col]
                else:
                    pending[col][1] = left - 1
                col += 1
                continue
            cell = next(cells, None)
            if cell is None:
                if any(c > col for c in pending):
                    row.append(None)
                    col += 1
                    continue
                break
            rs, cs = span(cell, "rowspan"), span(cell, "colspan")
            for _ in range(cs):
                row.append(cell)
                if rs > 1:
                    pending[col] = [cell, rs - 1]
                col += 1
        if row:
            grid.append(row)
    return grid


def find_table(soup, heading_pattern, header_patterns):
    def header_ok(table):
        own = [th for th in table.find_all("th") if th.find_parent("table") is table]
        text = " ".join(th.get_text(" ", strip=True) for th in own[:20])
        return all(re.search(p, text, re.IGNORECASE) for p in header_patterns)

    for h in soup.find_all(["h2", "h3", "h4"]):
        if re.search(heading_pattern, h.get_text(" ", strip=True), re.IGNORECASE):
            for table in h.find_all_next("table"):
                if header_ok(table):
                    return table
    for table in soup.find_all("table"):
        if header_ok(table):
            return table
    return None


def header_index(grid, patterns):
    for i, row in enumerate(grid):
        texts = [clean_text(c.get_text(" ")) if c is not None else "" for c in row]
        joined = " ".join(texts)
        if all(re.search(p, joined, re.IGNORECASE) for p in patterns.values()):
            idx = {}
            for key, p in patterns.items():
                for j, t in enumerate(texts):
                    if re.search(p, t, re.IGNORECASE):
                        idx[key] = j
                        break
            return i, idx
    return None, None


def junior_page_title(season):
    return f"{season} GP2 Series" if season <= 2016 else f"{season} FIA Formula 2 Championship"


def series_name(season):
    return "GP2" if season <= 2016 else "F2"


def fetch_wiki_page(title, refresh):
    cache = RAW / "wikipedia" / f"{title.replace(' ', '_')}.json"
    data = _request("GET", WIKI_API, cache_file=cache, refresh=refresh, params={
        "action": "parse", "page": title, "prop": "text",
        "format": "json", "formatversion": 2, "redirects": 1,
    })
    if "error" in data:
        raise RuntimeError(f"Wikipedia error for '{title}': {data['error']}")
    return data["parse"]["text"]


def parse_standings(soup, season):
    table = find_table(soup, r"drivers['’]?\s+championship", [r"\bpos", r"driver", r"points"])
    if table is None:
        return []
    rows, seen = [], set()
    for row in table_to_grid(table):
        if len(row) < 3 or row[0] is None or row[1] is None:
            continue
        pos = clean_text(row[0].get_text(" "))
        if not POS_RE.fullmatch(pos):
            continue
        name, title = driver_from_cell(row[1])
        # an unlinked name without a space is a result cell, not a driver
        if not name or (title is None and (" " not in name or re.search(r"\d", name))):
            continue
        if name in seen:
            continue
        seen.add(name)
        rows.append({
            "season": season, "series": series_name(season), "pos_text": pos,
            "driver_name": name, "wiki_title": title,
            "points_text": clean_text(row[-1].get_text(" ")) if row[-1] is not None else "",
        })
    return rows


def parse_entries(soup, season):
    table = find_table(soup, r"teams? and drivers|entries|entry list", [r"driver", r"team|entrant"])
    if table is None:
        return []
    grid = table_to_grid(table)
    h, idx = header_index(grid, {"team": r"team|entrant", "driver": r"driver"})
    if h is None:
        return []
    num_i = next((j for j, c in enumerate(grid[h])
                  if c is not None and re.search(r"^no\.?$|number", clean_text(c.get_text(" ")), re.I)), None)
    rnd_i = next((j for j, c in enumerate(grid[h])
                  if c is not None and re.search(r"round", clean_text(c.get_text(" ")), re.I)), None)

    def cell_text(row, i):
        return clean_text(row[i].get_text(" ")) if i is not None and i < len(row) and row[i] is not None else ""

    rows, seen = [], set()
    for order, row in enumerate(grid[h + 1:]):
        if len(row) <= idx["driver"] or row[idx["driver"]] is None:
            continue
        team_cell, driver_cell = row[idx["team"]], row[idx["driver"]]
        if team_cell is driver_cell:
            continue
        name, title = driver_from_cell(driver_cell)
        if not name or not re.search(r"[A-Za-z]", name):
            continue
        team = clean_text(team_cell.get_text(" ")) if team_cell is not None else ""
        if (team, name) in seen:
            continue
        seen.add((team, name))
        rows.append({
            "season": season, "series": series_name(season), "team": team,
            "car_no": cell_text(row, num_i), "driver_name": name, "wiki_title": title,
            "rounds": cell_text(row, rnd_i), "entry_order": order,
        })
    return rows


def collect_junior(refresh):
    standings, entries = [], []
    for season in range(JUNIOR_FIRST_SEASON, CURRENT_SEASON + 1):
        title = junior_page_title(season)
        try:
            soup = BeautifulSoup(fetch_wiki_page(title, refresh), "lxml")
        except Exception as exc:
            print(f"  ! {title}: {exc}")
            continue
        s, e = parse_standings(soup, season), parse_entries(soup, season)
        print(f"  {title}: {len(s)} classified drivers, {len(e)} entries")
        standings += s
        entries += e
    return pd.DataFrame(standings), pd.DataFrame(entries)


def collect_f1(refresh):
    rows = []
    for season in range(F1_FIRST_SEASON, CURRENT_SEASON + 1):
        data = _request("GET", f"{JOLPICA}/{season}/driverStandings.json",
                        cache_file=RAW / "jolpica" / f"driver_standings_{season}.json",
                        refresh=refresh, pause=0.4, params={"limit": 100})
        lists = data["MRData"]["StandingsTable"]["StandingsLists"]
        if not lists:
            print(f"  F1 {season}: no standings yet")
            continue
        for st in lists[0]["DriverStandings"]:
            d = st["Driver"]
            url = d.get("url", "")
            title = unquote(url.split("/wiki/")[-1].split("#")[0]).replace("_", " ") if "/wiki/" in url else None
            rows.append({
                "season": season,
                "jolpica_id": d["driverId"],
                "driver_name": f"{d.get('givenName', '')} {d.get('familyName', '')}".strip(),
                "wiki_title": title,
                "dob": d.get("dateOfBirth"),
                "constructor": " / ".join(c["name"] for c in st.get("Constructors", [])),
                "position": st.get("position"),
                "points": st.get("points"),
                "wins": st.get("wins"),
            })
        print(f"  F1 {season}: {len(lists[0]['DriverStandings'])} drivers")
    return pd.DataFrame(rows)


def resolve_titles(titles, refresh):
    cache = RAW / "wikipedia_title_map.json"
    mapping = {} if refresh or not cache.exists() else json.loads(cache.read_text(encoding="utf-8"))
    todo = sorted(t for t in set(titles) if t and t not in mapping)
    for batch in chunks(todo, 50):
        data = _request("GET", WIKI_API, params={
            "action": "query", "titles": "|".join(batch), "redirects": 1,
            "format": "json", "formatversion": 2,
        })
        q = data.get("query", {})
        normalized = {n["from"]: n["to"] for n in q.get("normalized", [])}
        redirects = {r["from"]: r["to"] for r in q.get("redirects", [])}
        for t in batch:
            step = normalized.get(t, t)
            mapping[t] = redirects.get(step, step)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    print(f"  resolved {len(todo)} new titles ({len(mapping)} total)")
    return pd.DataFrame(sorted(mapping.items()), columns=["raw_title", "canonical_title"])


def _sparql_literal(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"@en'


def fetch_bios(titles, refresh):
    cache = RAW / "wikidata_bios.json"
    bios = {} if refresh or not cache.exists() else json.loads(cache.read_text(encoding="utf-8"))
    todo = sorted(t for t in set(titles) if t and t not in bios)
    cache.parent.mkdir(parents=True, exist_ok=True)
    for i, batch in enumerate(chunks(todo, 25), start=1):
        query = f"""
        SELECT ?title ?dob ?sportNat ?citizen WHERE {{
          VALUES ?title {{ {' '.join(_sparql_literal(t) for t in batch)} }}
          ?article schema:name ?title ;
                   schema:isPartOf <https://en.wikipedia.org/> ;
                   schema:about ?item .
          OPTIONAL {{ ?item wdt:P569 ?dob . }}
          OPTIONAL {{ ?item wdt:P1532 ?sc . ?sc rdfs:label ?sportNat . FILTER(LANG(?sportNat) = "en") }}
          OPTIONAL {{ ?item wdt:P27 ?cc . ?cc rdfs:label ?citizen . FILTER(LANG(?citizen) = "en") }}
        }}"""
        try:
            data = _request("POST", WIKIDATA_SPARQL, pause=1.0, data={"query": query},
                            headers={"Accept": "application/sparql-results+json"})
        except Exception as exc:
            print(f"    batch {i} failed ({exc}); skipping - re-run later to fill it in")
            continue
        for t in batch:
            bios.setdefault(t, {"dob": None, "nationality": None})
        for b in data["results"]["bindings"]:
            rec = bios[b["title"]["value"]]
            if rec["dob"] is None and "dob" in b:
                rec["dob"] = b["dob"]["value"][:10]
            nat = b.get("sportNat", b.get("citizen", {})).get("value")
            if rec["nationality"] is None and nat:
                rec["nationality"] = nat
        cache.write_text(json.dumps(bios, ensure_ascii=False), encoding="utf-8")
        print(f"    batch {i}: {len(bios)} drivers looked up so far")
    print(f"  looked up {len(todo)} new drivers ({len(bios)} total)")
    return pd.DataFrame([{"title": t, **v} for t, v in sorted(bios.items())],
                        columns=["title", "dob", "nationality"])


def load_raw_table(cur, name, df):
    table = sql.Identifier(SCHEMA, name)
    cur.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(table))
    cur.execute(sql.SQL("CREATE TABLE {} ({})").format(
        table, sql.SQL(", ").join(sql.SQL("{} text").format(sql.Identifier(c)) for c in df.columns)))
    with cur.copy(sql.SQL("COPY {} FROM STDIN").format(table)) as copy:
        for row in df.itertuples(index=False):
            copy.write_row([None if pd.isna(v) else str(v) for v in row])
    print(f"  loaded {SCHEMA}.{name}: {len(df)} rows")


def build_database(conn, raw_tables):
    settings = sql.Identifier(SCHEMA, "project_settings")
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(SCHEMA)))
        for name, df in raw_tables.items():
            load_raw_table(cur, name, df)
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(settings))
        cur.execute(sql.SQL("CREATE TABLE {} (current_season int)").format(settings))
        cur.execute(sql.SQL("INSERT INTO {} VALUES (%s)").format(settings), (CURRENT_SEASON,))
        cur.execute(SQL_PATH.read_text(encoding="utf-8"))
    conn.commit()


def query_df(conn, query):
    with conn.cursor() as cur:
        cur.execute(query)
        return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def print_checks(conn):
    print("\nJunior seasons parsed:")
    print(query_df(conn, """
        SELECT season, series, COUNT(*) AS drivers,
               MAX(CASE WHEN final_pos = 1 THEN driver_name END) AS champion,
               COUNT(*) FILTER (WHERE team IS NULL) AS no_team_match
        FROM f1.junior_seasons
        GROUP BY season, series
        ORDER BY season
    """).to_string(index=False))

    print("\nOverall:")
    print(query_df(conn, """
        SELECT COUNT(*) AS junior_drivers,
               COUNT(*) FILTER (WHERE reached_f1) AS reached_f1,
               COUNT(*) FILTER (WHERE dob IS NULL) AS missing_dob,
               COUNT(*) FILTER (WHERE driver_key LIKE 'unlinked::%') AS no_wiki_article
        FROM f1.driver_summary
    """).to_string(index=False))

    missing = query_df(conn, "SELECT driver_name FROM f1.driver_summary WHERE dob IS NULL ORDER BY driver_name")
    if len(missing):
        print("\nDrivers missing a date of birth:")
        print(", ".join(missing["driver_name"].tolist()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="re-download everything")
    args = parser.parse_args()
    INTERIM.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(**DB):
        pass

    print("1/5 Junior series (Wikipedia)")
    junior_standings, junior_entries = collect_junior(args.refresh)

    print("2/5 F1 standings (Jolpica)")
    f1 = collect_f1(args.refresh)

    print("3/5 Resolving Wikipedia titles")
    all_titles = pd.concat([junior_standings["wiki_title"], junior_entries["wiki_title"],
                            f1["wiki_title"]]).dropna().tolist()
    title_map = resolve_titles(all_titles, args.refresh)

    print("4/5 Dates of birth (Wikidata)")
    bios = fetch_bios(title_map["canonical_title"].tolist(), args.refresh)

    raw_tables = {
        "raw_junior_standings": junior_standings,
        "raw_junior_entries": junior_entries,
        "raw_f1_standings": f1,
        "title_map": title_map,
        "driver_bios": bios,
    }
    for name, df in raw_tables.items():
        df.to_csv(INTERIM / f"{name}.csv", index=False)

    print(f"5/5 Building tables in PostgreSQL ({DB['dbname']}, schema {SCHEMA})")
    with psycopg.connect(**DB) as conn:
        build_database(conn, raw_tables)
        print_checks(conn)


if __name__ == "__main__":
    main()