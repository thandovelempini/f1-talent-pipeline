"""
Part 4 - Driver Potential Rating and the two models.

Runs part4_potential.sql, then:
  1. Validates the potential rating: does it predict next season's rating
     beyond what current performance already tells you?
  2. Model 1 (reaching F1) and Model 2 (Established or Star, among those who reached F1),
     each on two snapshots (rookie season, final season before F1), comparing
     performance-only features with performance + potential.

Models are logistic regressions scored by cross-validated AUC
(0.5 = coin flip, 1.0 = perfect)
"""

from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import (RepeatedKFold, RepeatedStratifiedKFold,
                                     cross_val_score)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from run_part1 import DB, ROOT, query_df

SQL_PATH = Path(__file__).resolve().parent / "part4_potential.sql"
OUT = ROOT / "data" / "results"

PERFORMANCE = ["performance_raw", "teammate_gap"]
PERFORMANCE_POTENTIAL = PERFORMANCE + ["potential_raw", "age"]
SINGLE_FEATURES = ["performance_raw", "teammate_gap", "pts_vs_leader", "potential_raw",
                   "ahead_of_schedule", "age", "best_raw_so_far", "seasons_so_far"]

MODELS = {
    "Model 1: reached F1": ("in_model1", "model1_reached_f1"),
    "Model 2: Established or Star": ("in_model2", "model2_succeeded"),
}
SEED = 42


def pipeline(estimator):
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), estimator)


def to_float(df, columns):
    return df[columns].apply(pd.to_numeric, errors="coerce").astype(float)


def print_sanity(conn):
    print("\nAge curve (expected rating by age, per season in the category):")
    print(query_df(conn, """
        SELECT experience, ROUND(slope::numeric, 3) AS slope_per_year,
               ROUND(r2::numeric, 3) AS r2, n
        FROM f1.age_curve_fit ORDER BY experience
    """).to_string(index=False))

    print("\nTop 15 potential seasons (excluding low confidence):")
    print(query_df(conn, """
        SELECT season, driver_name, age_at_season_start AS age, season_in_category AS yr,
               performance_rating AS perf, potential_rating AS potential
        FROM f1.junior_season_potential
        WHERE confidence <> 'Low'
        ORDER BY potential_raw DESC NULLS LAST
        LIMIT 15
    """).to_string(index=False))


def validate_next_season(conn):
    """Does potential predict next season's rating beyond current performance?"""
    df = query_df(conn, """
        SELECT a.performance_raw, a.potential_raw, b.performance_raw AS next_raw
        FROM f1.junior_season_potential a
        JOIN f1.junior_season_potential b
            ON b.driver_key = a.driver_key AND b.season = a.season + 1
        WHERE a.confidence <> 'Low' AND b.confidence <> 'Low' AND NOT b.season_in_progress
    """)
    X = to_float(df, ["performance_raw", "potential_raw"])
    y = pd.to_numeric(df["next_raw"]).astype(float)
    cv = RepeatedKFold(n_splits=5, n_repeats=20, random_state=SEED)

    rows = []
    for name, cols in [("performance only", ["performance_raw"]),
                       ("performance + potential", ["performance_raw", "potential_raw"])]:
        r2 = cross_val_score(pipeline(LinearRegression()), X[cols], y, cv=cv, scoring="r2")
        rows.append({"features": name, "cv_r2": round(r2.mean(), 3), "sd": round(r2.std(), 3)})

    fit = pipeline(LinearRegression()).fit(X, y)
    coefs = dict(zip(X.columns, fit[-1].coef_.round(3)))
    result = pd.DataFrame(rows)
    print(f"\nValidation - predicting next season's rating ({len(df)} driver-season pairs):")
    print(result.to_string(index=False))
    print(f"  standardised coefficients: {coefs}")
    print("  (a positive potential coefficient = high-potential drivers improve more than "
          "their current rating suggests)")
    return result


def single_feature_auc(df, target):
    rows = []
    y = df[target].astype(bool)
    for col in SINGLE_FEATURES:
        x = pd.to_numeric(df[col], errors="coerce")
        mask = x.notna()
        if mask.sum() < 10 or y[mask].nunique() < 2:
            continue
        auc = roc_auc_score(y[mask], x[mask])
        rows.append({"feature": col, "auc": round(auc, 3),
                     "direction": "higher is better" if auc >= 0.5 else "lower is better",
                     "strength": round(abs(auc - 0.5) + 0.5, 3)})
    return pd.DataFrame(rows).sort_values("strength", ascending=False)


def run_models(conn):
    snapshots = query_df(conn, "SELECT * FROM f1.model_snapshots")
    cv = RepeatedStratifiedKFold(n_splits=5, n_repeats=20, random_state=SEED)
    summary, singles, coefs = [], [], []

    for model_name, (in_col, target) in MODELS.items():
        for snapshot in ["rookie", "final"]:
            df = snapshots[(snapshots["snapshot"] == snapshot) & snapshots[in_col].astype(bool)].copy()
            y = df[target].astype(bool)
            label = f"{model_name} | {snapshot}"

            for set_name, cols in [("performance", PERFORMANCE),
                                   ("performance + potential", PERFORMANCE_POTENTIAL)]:
                auc = cross_val_score(pipeline(LogisticRegression(max_iter=1000)),
                                      to_float(df, cols), y, cv=cv, scoring="roc_auc")
                summary.append({"model": model_name, "snapshot": snapshot, "features": set_name,
                                "drivers": len(df), "positives": int(y.sum()),
                                "cv_auc": round(auc.mean(), 3), "sd": round(auc.std(), 3)})

            fit = pipeline(LogisticRegression(max_iter=1000)).fit(to_float(df, PERFORMANCE_POTENTIAL), y)
            for col, c in zip(PERFORMANCE_POTENTIAL, fit[-1].coef_[0]):
                coefs.append({"model": model_name, "snapshot": snapshot, "feature": col,
                              "std_coefficient": round(c, 3)})

            s = single_feature_auc(df, target)
            s.insert(0, "snapshot", snapshot)
            s.insert(0, "model", model_name)
            singles.append(s)

    summary = pd.DataFrame(summary)
    singles = pd.concat(singles, ignore_index=True)
    coefs = pd.DataFrame(coefs)

    print("\nModel results (cross-validated AUC, 5 folds x 20 repeats):")
    print(summary.to_string(index=False))

    for model_name in MODELS:
        print(f"\nWhich single characteristics separate outcomes - {model_name}:")
        view = singles[singles["model"] == model_name].pivot(index="feature", columns="snapshot", values="auc")
        print(view.reindex(columns=["rookie", "final"]).to_string())
    print("  (AUC above 0.5: higher values go with success; below 0.5: lower values do, e.g. younger age)")

    print("\nStandardised coefficients, performance + potential model:")
    print(coefs.pivot_table(index="feature", columns=["model", "snapshot"], values="std_coefficient").to_string())

    return summary, singles, coefs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(**DB) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_PATH.read_text(encoding="utf-8"))
        conn.commit()

        print_sanity(conn)
        validation = validate_next_season(conn)
        summary, singles, coefs = run_models(conn)

    validation.to_csv(OUT / "potential_validation.csv", index=False)
    summary.to_csv(OUT / "model_results.csv", index=False)
    singles.to_csv(OUT / "single_feature_auc.csv", index=False)
    coefs.to_csv(OUT / "model_coefficients.csv", index=False)


if __name__ == "__main__":
    main()