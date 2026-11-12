"""
Part 5 - Export data for the Streamlit app.

Fits the final RQ1 model (performance + age + team strength) separately for the end of
a driver's 1st, 2nd and 3rd GP2/F2 season, the design validated in Part 4b, and writes
small CSV files to app/data/ so the app runs without a database.

Predictions:
  historical (out-of-fold)  drivers the model is trained on get the probability from a model
                            that never saw them (5-fold CV x 20 repeats), never an in-sample fit
  model estimate            everyone else (pending, excluded, the season in progress) gets the
                            full model's probability, with a 90% interval from refitting the
                            model on 300 bootstrap resamples of the training drivers
  current                   a pending driver's latest season within the model's range

Usage: python3 src/run_part5.py   (run Parts 1-4b first)
"""

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from run_part1 import CURRENT_SEASON, DB, ROOT, query_df

SQL_PATH = Path(__file__).resolve().parent / "part5_app_data.sql"
RESULTS = ROOT / "data" / "results"
APP_DATA = ROOT / "app" / "data"

FEATURES = ["rating_ts_raw", "teammate_gap", "age", "team_strength"]
STAGES = [1, 2, 3]
SEED = 42
REPEATS = 20
FOLDS = 5
BOOTSTRAPS = 300


def pipeline():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LogisticRegression(max_iter=1000))


def numeric(df, cols):
    return df[cols].apply(pd.to_numeric, errors="coerce").astype(float)


def out_of_fold(X, y):
    probs = np.zeros(len(y))
    for r in range(REPEATS):
        cv = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=SEED + r)
        for tr, te in cv.split(X, y):
            probs[te] += pipeline().fit(X.iloc[tr], y[tr]).predict_proba(X.iloc[te])[:, 1]
    return probs / REPEATS


def bootstrap_intervals(X_train, y_train, X_new, rng):
    draws = []
    n = len(y_train)
    while len(draws) < BOOTSTRAPS:
        idx = rng.integers(0, n, n)
        if len(np.unique(y_train[idx])) < 2:
            continue
        draws.append(pipeline().fit(X_train.iloc[idx], y_train[idx]).predict_proba(X_new)[:, 1])
    draws = np.vstack(draws)
    return np.percentile(draws, 5, axis=0), np.percentile(draws, 95, axis=0)


def build_predictions(rows, rng):
    rows = rows.copy()
    rows["k"] = pd.to_numeric(rows["k"]).astype(int)
    rows["season"] = pd.to_numeric(rows["season"]).astype(int)
    rows["in_rq1"] = rows["in_rq1"].astype(bool)
    rows["season_in_progress"] = rows["season_in_progress"].astype(bool)

    out, stage_info = [], []
    for k in STAGES:
        stage = rows[rows["k"] == k]
        is_train = (stage["in_rq1"] & ~stage["season_in_progress"]).to_numpy()
        train, other = stage[is_train], stage[~is_train]
        X_train, y_train = numeric(train, FEATURES), train["rq1_reached_f1"].astype(bool).to_numpy()

        hist = train.assign(probability=out_of_fold(X_train, y_train), prob_low=np.nan,
                            prob_high=np.nan, kind="historical (out-of-fold)", reached_f1=y_train)
        out.append(hist)

        if len(other):
            X_other = numeric(other, FEATURES)
            model = pipeline().fit(X_train, y_train)
            low, high = bootstrap_intervals(X_train, y_train, X_other, rng)
            out.append(other.assign(probability=model.predict_proba(X_other)[:, 1],
                                    prob_low=low, prob_high=high, kind="model estimate",
                                    reached_f1=pd.NA))

        stage_info.append({"k": k, "training_drivers": int(len(train)),
                           "reached_f1": int(y_train.sum()),
                           "base_rate": round(float(y_train.mean()), 3)})

    preds = pd.concat(out, ignore_index=True)

    # A pending driver's latest season inside the model's range is their current estimate
    pending = preds[preds["outcome"] == "Pending"]
    latest = pending.sort_values("season").groupby("driver_key").tail(1).index
    preds.loc[latest, "kind"] = "current"

    keep = ["driver_key", "driver_name", "season", "k", "team", "age", "outcome",
            "season_in_progress", "probability", "prob_low", "prob_high", "kind", "reached_f1"]
    preds = preds[keep].sort_values(["driver_name", "season"])
    for c in ["probability", "prob_low", "prob_high"]:
        preds[c] = preds[c].round(3)
    return preds, pd.DataFrame(stage_info)


def copy_results():
    """Experiment summaries from Part 4b, for the app's method page."""
    files = ["experiment_results.csv", "experiment_chronological.csv", "experiment_composition.csv",
             "experiment_sensitivity.csv"]
    for name in files:
        path = RESULTS / name
        if path.exists():
            pd.read_csv(path).to_csv(APP_DATA / name, index=False)
        else:
            print(f"  ! {name} not found - run Part 4b first")


def main():
    APP_DATA.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    with psycopg.connect(**DB) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_PATH.read_text(encoding="utf-8"))
        conn.commit()
        rows = query_df(conn, "SELECT * FROM f1.app_prediction_rows")
        drivers = query_df(conn, "SELECT * FROM f1.app_drivers ORDER BY driver_name")
        seasons = query_df(conn, "SELECT * FROM f1.app_driver_seasons ORDER BY driver_name, season")

    print("Fitting stage models and predictions ...")
    preds, stages = build_predictions(rows, rng)

    drivers.to_csv(APP_DATA / "drivers.csv", index=False)
    seasons.to_csv(APP_DATA / "junior_seasons.csv", index=False)
    preds.to_csv(APP_DATA / "predictions.csv", index=False)
    stages.to_csv(APP_DATA / "stages.csv", index=False)
    copy_results()
    meta = {"built": date.today().isoformat(), "current_season": CURRENT_SEASON,
            "features": FEATURES, "bootstrap_interval": "90%"}
    (APP_DATA / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print("\nTraining data per stage:")
    print(stages.to_string(index=False))
    current = preds[preds["kind"] == "current"].sort_values("probability", ascending=False)
    print(f"\nCurrent estimates ({len(current)} pending drivers within the model's range):")
    print(current[["driver_name", "season", "k", "team", "probability", "prob_low", "prob_high",
                   "season_in_progress"]].head(15).to_string(index=False))


if __name__ == "__main__":
    main()