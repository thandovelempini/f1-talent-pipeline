"""
Part 3 - Driver Performance Rating.

Runs part3_performance.sql on the tables from Parts 1-2 and prints checks.
No downloads.

Usage: python3 src/run_part3.py   (run Parts 1 and 2 first)
"""

from pathlib import Path

import psycopg

from run_part1 import DB, query_df

SQL_PATH = Path(__file__).resolve().parent / "part3_performance.sql"


def print_checks(conn):
    print("\nCoverage per season:")
    print(query_df(conn, """
        SELECT
            season,
            COUNT(*) AS drivers,
            COUNT(teammate_gap) AS with_teammate,
            COUNT(*) FILTER (WHERE confidence = 'Low') AS low_confidence,
            COUNT(*) FILTER (WHERE confidence = 'Medium') AS switched_team
        FROM f1.junior_season_ratings
        GROUP BY season
        ORDER BY season
    """).to_string(index=False))

    print("\nCar adjustment (finishing percentile ~ team strength):")
    print(query_df(conn, """
        SELECT ROUND(slope::numeric, 3) AS slope, ROUND(intercept::numeric, 3) AS intercept,
               ROUND(r2::numeric, 3) AS r2, n
        FROM f1.car_adjustment_fit
    """).to_string(index=False))

    print("\nTop 15 junior seasons:")
    print(query_df(conn, """
        SELECT season, driver_name, team, final_pos, teammate_share, teammate_gap, team_strength, rating, confidence
        FROM f1.junior_season_ratings
        ORDER BY rating_raw DESC
        LIMIT 15
    """).to_string(index=False))

    print("\nFirst look - average ratings by outcome:")
    print(query_df(conn, """
        SELECT
            outcome,
            COUNT(*) AS drivers,
            ROUND(AVG(best_rating)) AS avg_best,
            ROUND(AVG(last_rating)) AS avg_last,
            ROUND(AVG(rookie_rating)) AS avg_rookie,
            ROUND(AVG(avg_teammate_gap), 3) AS avg_teammate_gap
        FROM f1.driver_performance
        GROUP BY outcome, outcome_order
        ORDER BY outcome_order
    """).to_string(index=False))


def main():
    with psycopg.connect(**DB) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_PATH.read_text(encoding="utf-8"))
        conn.commit()
        print_checks(conn)


if __name__ == "__main__":
    main()