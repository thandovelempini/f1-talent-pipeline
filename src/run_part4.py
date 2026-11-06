"""
Part 4 - Driver Potential Rating (v2) and the two models.

Runs part4_potential.sql, then:
  1. Validates both potential versions on next season's rating.
  2. Model 1 (reaching F1) and Model 2 (Established or Star, among those who reached F1),
     comparing each feature set with performance alone.

Leakage controls:
  - The development curve behind potential v2b is re-fitted inside every fold,
    using only drivers outside the test fold.
  - All splits and bootstrap resamples are by driver.
  - The rookie snapshot carries the predictive claims. The final snapshot is
    descriptive: which season it is depends on the outcome (the season before an
    F1 debut, or the last season of a career that never reached F1).
  - The rating scale and age-peer averages use all completed seasons 2005-2025
    (no outcome information).

AUCs and R² come from out-of-fold predictions (5 folds x 20 repeats). 95% intervals
bootstrap those predictions by driver; the models are not re-fitted per resample, so
the intervals are slightly narrow. "delta" is the gain over performance alone on the
same resamples; "helps: yes" means its interval is above 0, "hurts" means below 0.

Usage: python3 src/run_part4.py   (run Parts 1-3 first; needs scikit-learn)
"""

from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import r2_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from run_part1 import DB, ROOT, query_df

SQL_PATH = Path(__file__).resolve().parent / "part4_potential.sql"
OUT = ROOT / "data" / "results"

PERFORMANCE = ["performance_raw", "teammate_gap"]
FEATURE_SETS = {
    "performance": PERFORMANCE,
    "+ age": PERFORMANCE + ["age"],
    "+ potential v2a (age peers)": PERFORMANCE + ["potential_peer_raw"],
    "+ potential v2b (development)": PERFORMANCE + ["projected_raw"],
    "+ age + progression speed": PERFORMANCE + ["age", "seasons_so_far"],
}
SINGLE_FEATURES = ["performance_raw", "teammate_gap", "pts_vs_leader", "potential_peer_raw",
                   "age", "best_raw_so_far", "seasons_so_far"]

MODELS = {
    "Model 1: reached F1": ("in_model1", "model1_reached_f1"),
    "Model 2: Established or Star": ("in_model2", "model2_succeeded"),
}
SNAPSHOT_USE = {"rookie": "predictive", "final": "descriptive"}
SEED = 42
REPEATS = 20
FOLDS = 5
BOOTSTRAPS = 1000


def verdict(delta):
    low, high = np.percentile(delta, [2.5, 97.5])
    return "yes" if low > 0 else "hurts" if high < 0 else "not clearly"


def pipeline(estimator):
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), estimator)


def age_band(age):
    return np.clip(np.floor(pd.to_numeric(age, errors="coerce")), 18, 25)


# ---------------------------------------------------------------------------
# Development curve, fitted only on the pairs it is given
# ---------------------------------------------------------------------------
def fit_development_curve(pairs):
    x = pairs["current_raw"].to_numpy(float)
    y = pairs["change"].to_numpy(float)
    slope, intercept = np.polyfit(x, y, 1)
    drift = intercept + slope * x.mean()
    residual = pd.Series(y - (intercept + slope * x), index=pairs.index)
    by_band = residual.groupby(pairs["age_band"].to_numpy()).mean() + drift
    return by_band.to_dict(), drift


def projected(performance, bands, curve):
    by_band, drift = curve
    dev = pd.Series(bands).map(by_band).fillna(drift).to_numpy(float)
    return pd.to_numeric(performance, errors="coerce").to_numpy(float) + dev


def build_features(df, cols, curve=None):
    X = df[[c for c in cols if c != "projected_raw"]].apply(pd.to_numeric, errors="coerce").astype(float)
    if "projected_raw" in cols:
        X["projected_raw"] = projected(df["performance_raw"], age_band(df["age"]), curve)
    return X[cols]


# ---------------------------------------------------------------------------
# Sanity output
# ---------------------------------------------------------------------------
def print_sanity(conn):
    print("\nDevelopment curve on all pairs (descriptive; the models re-fit it per fold):")
    print(query_df(conn, """
        SELECT age_band, n, ROUND(expected_development::numeric, 3) AS expected_development
        FROM f1.development_curve ORDER BY age_band
    """).to_string(index=False))


# ---------------------------------------------------------------------------
# 1. Next-season validation, split and bootstrapped by driver
# ---------------------------------------------------------------------------
def driver_folds(drivers, rng):
    unique = rng.permutation(np.unique(drivers))
    fold_of = {d: i % FOLDS for i, d in enumerate(unique)}
    return np.array([fold_of[d] for d in drivers])


def validate_next_season(conn, rng):
    pairs = query_df(conn, """
        SELECT dp.driver_key, dp.age_band, dp.current_raw, dp.next_raw, dp.change,
               p.potential_peer_raw
        FROM f1.development_pairs dp
        JOIN f1.junior_season_potential p ON p.driver_key = dp.driver_key AND p.season = dp.season
    """)
    for c in ["age_band", "current_raw", "next_raw", "change", "potential_peer_raw"]:
        pairs[c] = pd.to_numeric(pairs[c], errors="coerce").astype(float)
    y = pairs["next_raw"].to_numpy()
    drivers = pairs["driver_key"].to_numpy()

    sets = ["performance only", "+ potential v2a (age peers)", "+ potential v2b (development)"]
    preds = {s: np.zeros(len(pairs)) for s in sets}
    for _ in range(REPEATS):
        folds = driver_folds(drivers, rng)
        for f in range(FOLDS):
            tr, te = folds != f, folds == f
            curve = fit_development_curve(pairs[tr])
            feats = {
                "performance only": lambda d: d[["current_raw"]],
                "+ potential v2a (age peers)": lambda d: d[["current_raw", "potential_peer_raw"]],
                "+ potential v2b (development)": lambda d: pd.DataFrame({
                    "current_raw": d["current_raw"],
                    "projected": projected(d["current_raw"], d["age_band"], curve)}),
            }
            for s in sets:
                model = pipeline(LinearRegression()).fit(feats[s](pairs[tr]), y[tr])
                preds[s][te] += model.predict(feats[s](pairs[te]))
    preds = {s: p / REPEATS for s, p in preds.items()}

    # bootstrap by driver: resample drivers, keep all of each driver's pairs
    unique = np.unique(drivers)
    rows_of = {d: np.flatnonzero(drivers == d) for d in unique}
    boots = {s: [] for s in sets}
    for _ in range(BOOTSTRAPS):
        idx = np.concatenate([rows_of[d] for d in rng.choice(unique, len(unique))])
        for s in sets:
            boots[s].append(r2_score(y[idx], preds[s][idx]))
    boots = {s: np.array(v) for s, v in boots.items()}

    rows = []
    for s in sets:
        row = {"features": s, "r2": round(r2_score(y, preds[s]), 3),
               "ci_low": round(np.percentile(boots[s], 2.5), 3),
               "ci_high": round(np.percentile(boots[s], 97.5), 3)}
        if s != "performance only":
            d = boots[s] - boots["performance only"]
            row.update(delta=round(d.mean(), 3), delta_ci_low=round(np.percentile(d, 2.5), 3),
                       delta_ci_high=round(np.percentile(d, 97.5), 3),
                       helps=verdict(d))
        rows.append(row)
    result = pd.DataFrame(rows)
    print(f"\nValidation - predicting next season's rating "
          f"({len(pairs)} pairs from {len(unique)} drivers, split by driver):")
    print(result.astype(object).fillna("").to_string(index=False))
    return result


# ---------------------------------------------------------------------------
# 2. F1 models
# ---------------------------------------------------------------------------
def usable_sets(model_name, snapshot):
    """Progression speed is only fair in Model 2: in Model 1, reaching F1 itself
    ends a junior career early. In the rookie snapshot it is always 1."""
    sets = dict(FEATURE_SETS)
    if model_name.startswith("Model 1") or snapshot == "rookie":
        sets.pop("+ age + progression speed")
    return sets


def oof_probabilities(df, y, sets, pairs):
    probs = {name: np.zeros(len(df)) for name in sets}
    for r in range(REPEATS):
        cv = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=SEED + r)
        for tr, te in cv.split(df, y):
            test_drivers = set(df["driver_key"].iloc[te])
            curve = fit_development_curve(pairs[~pairs["driver_key"].isin(test_drivers)])
            for name, cols in sets.items():
                model = pipeline(LogisticRegression(max_iter=1000))
                model.fit(build_features(df.iloc[tr], cols, curve), y[tr])
                probs[name][te] += model.predict_proba(build_features(df.iloc[te], cols, curve))[:, 1]
    return {name: p / REPEATS for name, p in probs.items()}


def bootstrap_aucs(y, probs, rng):
    results = {name: [] for name in probs}
    for _ in range(BOOTSTRAPS):
        idx = rng.integers(0, len(y), len(y))
        if len(np.unique(y[idx])) < 2:
            continue
        for name, p in probs.items():
            results[name].append(roc_auc_score(y[idx], p[idx]))
    return {name: np.array(v) for name, v in results.items()}


def single_feature_auc(df, target):
    rows = []
    y = df[target].astype(bool)
    for col in SINGLE_FEATURES:
        x = pd.to_numeric(df[col], errors="coerce")
        mask = x.notna()
        if mask.sum() < 10 or y[mask].nunique() < 2 or x[mask].nunique() < 2:
            continue
        rows.append({"feature": col, "auc": round(roc_auc_score(y[mask], x[mask]), 3)})
    return pd.DataFrame(rows)


def run_models(conn, rng):
    snapshots = query_df(conn, "SELECT * FROM f1.model_snapshots")
    pairs = query_df(conn, "SELECT driver_key, age_band, current_raw, change FROM f1.development_pairs")
    for c in ["age_band", "current_raw", "change"]:
        pairs[c] = pd.to_numeric(pairs[c], errors="coerce").astype(float)

    summary, singles = [], []
    for model_name, (in_col, target) in MODELS.items():
        for snapshot in ["rookie", "final"]:
            df = snapshots[(snapshots["snapshot"] == snapshot) & snapshots[in_col].astype(bool)]
            df = df.reset_index(drop=True)
            y = df[target].astype(bool).to_numpy()

            sets = usable_sets(model_name, snapshot)
            probs = oof_probabilities(df, y, sets, pairs)
            boots = bootstrap_aucs(y, probs, rng)

            for name in sets:
                b = boots[name]
                row = {"model": model_name, "snapshot": snapshot, "use": SNAPSHOT_USE[snapshot],
                       "features": name, "drivers": len(df), "positives": int(y.sum()),
                       "auc": round(roc_auc_score(y, probs[name]), 3),
                       "ci_low": round(np.percentile(b, 2.5), 3),
                       "ci_high": round(np.percentile(b, 97.5), 3)}
                if name != "performance":
                    d = b - boots["performance"]
                    row.update(delta=round(d.mean(), 3), delta_ci_low=round(np.percentile(d, 2.5), 3),
                               delta_ci_high=round(np.percentile(d, 97.5), 3),
                               helps=verdict(d))
                summary.append(row)

            s = single_feature_auc(df, target)
            s.insert(0, "snapshot", snapshot)
            s.insert(0, "model", model_name)
            singles.append(s)

    summary = pd.DataFrame(summary)
    singles = pd.concat(singles, ignore_index=True)

    for model_name in MODELS:
        print(f"\n{model_name} - AUC with 95% interval; delta = gain over performance alone:")
        view = summary[summary["model"] == model_name].drop(columns=["model"])
        print(view.astype(object).fillna("").to_string(index=False))

    for model_name in MODELS:
        print(f"\nSingle characteristics - {model_name} (AUC; below 0.5 means lower values go with success):")
        view = singles[singles["model"] == model_name].pivot(index="feature", columns="snapshot", values="auc")
        print(view.reindex(columns=["rookie", "final"]).to_string())

    return summary, singles


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    with psycopg.connect(**DB) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_PATH.read_text(encoding="utf-8"))
        conn.commit()

        print_sanity(conn)
        validation = validate_next_season(conn, rng)
        summary, singles = run_models(conn, rng)

    validation.to_csv(OUT / "potential_validation.csv", index=False)
    summary.to_csv(OUT / "model_results.csv", index=False)
    singles.to_csv(OUT / "single_feature_auc.csv", index=False)


if __name__ == "__main__":
    main()