"""
Part 2 - Define "making it".

Downloads race-by-race F1 results (Jolpica), loads them into PostgreSQL and runs
part2_outcomes.sql to classify every junior driver into an outcome tier.

Usage: python3 src/run_part2.py [--refresh]   (run Part 1 first)
"""

import argparse
from pathlib import Path

import pandas as pd
import psycopg

from run_part1 import (CURRENT_SEASON, DB, F1_FIRST_SEASON, INTERIM, JOLPICA, RAW,
                       _request, load_raw_table, query_df)

SQL_PATH = Path(__file__).resolve().parent / "part2_outcomes.sql"


def fetch_season_results(season, refresh):
    rows, offset = [], 0
    while True:
        data = _request(
            "GET", f"{JOLPICA}/{season}/results.json",
            cache_file=RAW / "jolpica" / "results" / f"{season}_{offset}.json",
            refresh=refresh or season == CURRENT_SEASON, pause=0.4,
            params={"limit": 100, "offset": offset},
        )
        mr = data["MRData"]
        for race in mr["RaceTable"]["Races"]:
            for res in race.get("Results", []):
                d = res["Driver"]
                rows.append({
                    "season": season,
                    "round": race["round"],
                    "race_name": race.get("raceName"),
                    "race_date": race.get("date"),
                    "jolpica_id": d["driverId"],
                    "driver_name": f"{d.get('givenName', '')} {d.get('familyName', '')}".strip(),
                    "constructor": res.get("Constructor", {}).get("name"),
                    "grid": res.get("grid"),
                    "position": res.get("position"),
                    "position_text": res.get("positionText"),
                    "points": res.get("points"),
                    "status": res.get("status"),
                })
        offset += int(mr["limit"])
        if offset >= int(mr["total"]):
            break
    return rows


def collect_results(refresh):
    rows = []
    for season in range(F1_FIRST_SEASON, CURRENT_SEASON + 1):
        season_rows = fetch_season_results(season, refresh)
        races = len({r["round"] for r in season_rows})
        print(f"  F1 {season}: {races} races, {len(season_rows)} results")
        rows += season_rows
    return pd.DataFrame(rows)


def print_checks(conn):
    print("\nOutcome tiers:")
    print(query_df(conn, """
        SELECT outcome, COUNT(*) AS drivers
        FROM f1.driver_outcomes
        GROUP BY outcome, outcome_order
        ORDER BY outcome_order
    """).to_string(index=False))

    print("\nDrivers in each F1 tier:")
    tiers = query_df(conn, """
        SELECT outcome, string_agg(driver_name, ', ' ORDER BY f1_debut_season, driver_name) AS drivers
        FROM f1.driver_outcomes
        WHERE outcome NOT IN ('Didn''t reach F1', 'Pending')
        GROUP BY outcome, outcome_order
        ORDER BY outcome_order
    """)
    for _, row in tiers.iterrows():
        print(f"\n  {row['outcome']}:\n    {row['drivers']}")

    print("\nModelling samples:")
    print(query_df(conn, """
        SELECT
            COUNT(*) FILTER (WHERE in_model1)                       AS model1_drivers,
            COUNT(*) FILTER (WHERE in_model1 AND model1_reached_f1) AS model1_reached_f1,
            COUNT(*) FILTER (WHERE in_model2)                       AS model2_drivers,
            COUNT(*) FILTER (WHERE in_model2 AND model2_succeeded)  AS model2_succeeded
        FROM f1.driver_outcomes
    """).to_string(index=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="re-download everything")
    args = parser.parse_args()

    with psycopg.connect(**DB):
        pass

    print("1/2 F1 race results (Jolpica)")
    results = collect_results(args.refresh)
    results.to_csv(INTERIM / "raw_f1_results.csv", index=False)

    print("2/2 Classifying outcomes in PostgreSQL")
    with psycopg.connect(**DB) as conn:
        with conn.cursor() as cur:
            load_raw_table(cur, "raw_f1_results", results)
            cur.execute(SQL_PATH.read_text(encoding="utf-8"))
        conn.commit()
        print_checks(conn)


if __name__ == "__main__":
    main()