
import re
from pathlib import Path

import pandas as pd
import psycopg

from run_part1 import DB, ROOT, query_df

SQL_PATH = Path(__file__).resolve().parent / "data_checks.sql"
OUT = ROOT / "data" / "checks"

CHECK_RE = re.compile(r"^-- check: (\S+) \[(issue|review)\]\s*$", re.MULTILINE)


def load_checks():
    text = SQL_PATH.read_text(encoding="utf-8")
    parts = CHECK_RE.split(text)
    setup, checks = parts[0], []
    for i in range(1, len(parts), 3):
        checks.append((parts[i], parts[i + 1], parts[i + 2].strip()))
    return setup, checks


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    setup, checks = load_checks()
    summary = []

    with psycopg.connect(**DB) as conn:
        with conn.cursor() as cur:
            cur.execute(setup)
        conn.commit()

        for name, kind, query in checks:
            df = query_df(conn, query)
            df.to_csv(OUT / f"{name}.csv", index=False)
            status = ("OK" if df.empty else "CHECK") if kind == "issue" else "review"
            summary.append({"check": name, "type": kind, "rows": len(df), "status": status})

    summary = pd.DataFrame(summary)
    print(summary.to_string(index=False))
    flagged = summary[(summary["type"] == "issue") & (summary["rows"] > 0)]
    print(f"\n{len(flagged)} issue check(s) returned rows. Results saved to {OUT}")


if __name__ == "__main__":
    main()