"""
Part 4b - Leakage-safe experiment.

Research question 1 (progression): can a driver's performance, age and competitive
context predict whether they will eventually reach F1?
Research question 2 (establishment): among drivers who reach F1, can junior-career
characteristics distinguish those who establish themselves (Established or Star)?

Design:
  - Time-safe ratings (part4b_experiment.sql): each season rated only with information
    available at the end of that season; ratings start in 2007 after a 3-season burn-in.
  - Prediction points: end of a driver's 1st, 2nd and 3rd GP2/F2 season, for drivers who
    had not yet raced in F1. Each later point asks a narrower question: "among drivers
    still in GP2/F2 at this stage...". RQ2 stops at season 2 (too few drivers after).
  - Point estimates: out-of-fold AUC, 5-fold stratified CV x 20 repeats (one row per driver).
  - Intervals: out-of-bag bootstrap of the whole pipeline. Resample drivers, refit
    imputation, scaling and model, score the drivers left out. Replicates where either
    sample lacks one of the classes are counted as failed, not hidden.
  - "delta" compares each feature set with performance alone on the same replicates.
  - Sensitivity: team strength and age are added separately and together, and their
    contributions beyond each other are tested directly.
  - Class composition per prediction point, including who left between stages.
  - Chronological validation (RQ1, rookie season): train on earlier rookie cohorts and
    predict each later cohort in turn. A strict version uses a fixed 5-year horizon so that
    every training label was already known at the prediction date.
  - Risk populations and class counts are written to data/results/risk_populations.md.

"""

from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from run_part1 import DB, ROOT, query_df

SQL_PATH = Path(__file__).resolve().parent / "part4b_experiment.sql"
OUT = ROOT / "data" / "results"

PERFORMANCE = ["rating_ts_raw", "teammate_gap"]
QUESTIONS = {
    "RQ1 progression": ("in_rq1", "rq1_reached_f1", [1, 2, 3]),
    "RQ2 establishment": ("in_rq2", "rq2_established", [1, 2]),
}
SEED = 42
REPEATS = 20
FOLDS = 5
BOOTSTRAPS = 500
MIN_CLASS = 5
CHRONO_FIRST_TEST_YEAR = 2012
HORIZON = 5
LAST_COMPLETE_SEASON = 2025

CONTRASTS = [
    ("+ age + team strength", "+ age", "team strength beyond performance + age"),
    ("+ age + team strength", "+ team strength", "age beyond performance + team strength"),
    ("team strength only", "performance", "team strength alone vs performance alone"),
]


def feature_sets(k):
    sets = {
        "performance": PERFORMANCE,
        "+ age": PERFORMANCE + ["age"],
        "+ team strength": PERFORMANCE + ["team_strength"],
        "+ age + team strength": PERFORMANCE + ["age", "team_strength"],
        "team strength only": ["team_strength"],
    }
    if k >= 2:
        sets["+ age + trajectory"] = PERFORMANCE + ["age", "trajectory"]
    return sets


def pipeline():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LogisticRegression(max_iter=1000))


def verdict(delta):
    low, high = np.percentile(delta, [2.5, 97.5])
    return "yes" if low > 0 else "hurts" if high < 0 else "not clearly"


def cv_auc(X, y):
    probs = np.zeros(len(y))
    for r in range(REPEATS):
        cv = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=SEED + r)
        for tr, te in cv.split(X, y):
            probs[te] += pipeline().fit(X.iloc[tr], y[tr]).predict_proba(X.iloc[te])[:, 1]
    return roc_auc_score(y, probs / REPEATS)


def oob_bootstrap(Xs, y, rng):
    n = len(y)
    aucs = {name: [] for name in Xs}
    failed = 0
    for _ in range(BOOTSTRAPS):
        idx = rng.integers(0, n, n)
        oob = np.setdiff1d(np.arange(n), idx)
        if len(np.unique(y[idx])) < 2 or len(np.unique(y[oob])) < 2:
            failed += 1
            continue
        for name, X in Xs.items():
            model = pipeline().fit(X.iloc[idx], y[idx])
            aucs[name].append(roc_auc_score(y[oob], model.predict_proba(X.iloc[oob])[:, 1]))
    return {name: np.array(v) for name, v in aucs.items()}, failed


def print_scale(conn):
    print("\nTime-safe rating scale (fitted on seasons up to each year):")
    print(query_df(conn, """
        SELECT as_of, seasons_used, ROUND(slope::numeric, 3) AS car_slope,
               ROUND(tm_sd::numeric, 3) AS teammate_gap_sd
        FROM f1.rating_scale_by_season ORDER BY as_of
    """).to_string(index=False))
    print(query_df(conn, """
        SELECT ROUND(CORR(t.rating_ts_raw, r.rating_raw::float8)::numeric, 3) AS corr_with_global_rating,
               COUNT(*) AS seasons_rated
        FROM f1.junior_season_ratings_ts t
        JOIN f1.junior_season_ratings r USING (season, driver_key)
        WHERE t.rating_available
    """).to_string(index=False))


def run_experiments(conn, rng):
    snaps = query_df(conn, "SELECT * FROM f1.experiment_snapshots")
    rows, contrasts = [], []
    for question, (in_col, target, ks) in QUESTIONS.items():
        for k in ks:
            df = snaps[(snaps["k"] == k) & snaps[in_col].astype(bool)].reset_index(drop=True)
            y = df[target].astype(bool).to_numpy()
            base = {"question": question, "prediction_point": f"end of season {k}",
                    "drivers": len(df), "positives": int(y.sum())}
            if y.sum() < MIN_CLASS or (~y).sum() < MIN_CLASS:
                rows.append({**base, "features": "(too few drivers in one class)"})
                continue

            sets = feature_sets(k)
            Xs = {name: df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
                  for name, cols in sets.items()}
            boots, failed = oob_bootstrap(Xs, y, rng)

            for a, b, label in CONTRASTS:
                d = boots[a] - boots[b]
                contrasts.append({**base, "comparison": label, "delta": round(d.mean(), 3),
                                  "delta_ci_low": round(np.percentile(d, 2.5), 3),
                                  "delta_ci_high": round(np.percentile(d, 97.5), 3),
                                  "verdict": verdict(d)})

            for name in sets:
                row = {**base, "features": name,
                       "auc": round(cv_auc(Xs[name], y), 3),
                       "oob_ci_low": round(np.percentile(boots[name], 2.5), 3),
                       "oob_ci_high": round(np.percentile(boots[name], 97.5), 3),
                       "failed_replicates": failed}
                if name != "performance":
                    d = boots[name] - boots["performance"]
                    row.update(delta=round(d.mean(), 3),
                               delta_ci_low=round(np.percentile(d, 2.5), 3),
                               delta_ci_high=round(np.percentile(d, 97.5), 3),
                               helps=verdict(d))
                rows.append(row)

    results = pd.DataFrame(rows)
    contrasts = pd.DataFrame(contrasts)
    for question in QUESTIONS:
        print(f"\n{question} - CV AUC, out-of-bag 95% interval, gain over performance alone:")
        view = results[results["question"] == question].drop(columns=["question"])
        print(view.to_string(index=False, na_rep=""))

    print("\nSensitivity - what team strength and age add beyond each other "
          "(paired out-of-bag deltas):")
    print(contrasts.drop(columns=["drivers", "positives"]).to_string(index=False))
    return results, contrasts


STAGE_NOTES = {
    "RQ1 progression": (
        "Drivers whose k-th GP2/F2 season ended 2007-2025 and who had not raced in F1 before it. "
        "Positive = reached F1 at any point (including 'Too early to tell'). "
        "Excluded: Pending (no F1 yet, still in GP2/F2 in 2025-2026), F1 before junior, career cut short."),
    "RQ2 establishment": (
        "As RQ1, but only drivers who reached F1 and whose F1 career is settled. "
        "Positive = Established or Star. Excluded: Too early to tell, plus the RQ1 exclusions."),
}


def class_composition(conn):
    snaps = query_df(conn, "SELECT * FROM f1.experiment_snapshots")
    rows = []
    for question, (in_col, target, ks) in QUESTIONS.items():
        pop = snaps[snaps[in_col].astype(bool)]
        for k in ks:
            here = pop[pop["k"] == k]
            prev = set(pop.loc[pop["k"] == k - 1, "driver_key"])
            nxt = set(pop.loc[pop["k"] == k + 1, "driver_key"])
            leaving = here[~here["driver_key"].isin(nxt)]
            pos = here[target].astype(bool)
            tracked = k < pop["k"].max()
            rows.append({
                "question": question, "prediction_point": f"end of season {k}",
                "drivers": len(here), "positives": int(pos.sum()), "negatives": int((~pos).sum()),
                "positive_rate": round(pos.mean(), 3) if len(here) else None,
                "entered_at_this_stage": int((~here["driver_key"].isin(prev)).sum()) if k > 1 else None,
                "left_with_positive_outcome": int(leaving[target].astype(bool).sum()) if tracked else None,
                "left_with_negative_outcome": int((~leaving[target].astype(bool)).sum()) if tracked else None,
                "continued_to_next_season": int(here["driver_key"].isin(nxt).sum()) if tracked else None,
            })
    table = pd.DataFrame(rows)
    counts = ["entered_at_this_stage", "left_with_positive_outcome",
              "left_with_negative_outcome", "continued_to_next_season"]
    table[counts] = table[counts].astype("Int64")
    print("\nClass composition at each prediction point (time-safe ratings, 2007 onwards):")
    print(table.to_string(index=False, na_rep=""))
    print("  entered_at_this_stage = drivers whose earlier season could not be rated (before 2007) "
          "or who had a gap; left_with_positive_outcome = promoted (RQ1) or established (RQ2) "
          "without a further GP2/F2 season.")
    return table


def as_markdown(df):
    df = df.astype(object).where(df.notna(), "")
    try:
        return df.to_markdown(index=False)
    except ImportError:
        return "```\n" + df.to_string(index=False) + "\n```"


def write_population_doc(table, chrono_windows):
    lines = ["# Risk populations and class counts", "",
             "Each prediction point is the end of a driver's k-th GP2/F2 season. Only drivers who had "
             "not raced in F1 before that season are 'at risk'. Later points therefore ask a narrower "
             "question: among drivers still in GP2/F2 at this stage, who goes on to the outcome?", ""]
    for question, note in STAGE_NOTES.items():
        lines += [f"## {question}", "", note, ""]
        view = table[table["question"] == question].drop(columns=["question"])
        lines += [as_markdown(view), ""]
    lines += ["## Known biases", "",
              "- Most future stars were promoted after one season, so later stages contain few of them.",
              "- Rookie seasons before 2007 cannot be rated (3-season burn-in); those drivers enter at season 2.",
              "- Recent cohorts are incomplete: Pending drivers are excluded from the eventual-outcome "
              "analysis. The strict chronological test avoids this with a fixed 5-year horizon.",
              "- The strict horizon counts debuts more than 5 years after the GP2/F2 debut as negatives.", ""]
    for name, w in chrono_windows.items():
        lines += [f"## Chronological validation windows - {name}", "",
                  as_markdown(w), ""]
    path = OUT / "risk_populations.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def chrono_evaluate(df, y, train_rule, test_years, rng, extra_cols):
    """Fit on rows allowed by train_rule(t), predict the year-t rookie cohort, pool predictions."""
    sets = feature_sets(1)
    Xs = {name: df[cols].apply(pd.to_numeric, errors="coerce").astype(float) for name, cols in sets.items()}
    preds = {name: np.full(len(df), np.nan) for name in sets}
    windows = []
    for t in test_years:
        train, test = train_rule(t), (df["season"] == t).to_numpy()
        if test.sum() == 0 or y[train].sum() < MIN_CLASS or (~y[train]).sum() < MIN_CLASS:
            continue
        for name, X in Xs.items():
            preds[name][test] = pipeline().fit(X[train], y[train]).predict_proba(X[test])[:, 1]
        windows.append({"test_cohort": t, "train_drivers": int(train.sum()),
                        "train_positives": int(y[train].sum()), "test_drivers": int(test.sum()),
                        "test_positives": int(y[test].sum()),
                        **{c: f(t) for c, f in extra_cols.items()}})

    tested = ~np.isnan(preds["performance"])
    if tested.sum() == 0 or len(np.unique(y[tested])) < 2:
        return pd.DataFrame(windows), pd.DataFrame([{"features": "(not enough cohorts to test)"}])
    yt, p = y[tested], {name: v[tested] for name, v in preds.items()}
    boots = {name: [] for name in sets}
    failed = 0
    for _ in range(BOOTSTRAPS):
        idx = rng.integers(0, len(yt), len(yt))
        if len(np.unique(yt[idx])) < 2:
            failed += 1
            continue
        for name in sets:
            boots[name].append(roc_auc_score(yt[idx], p[name][idx]))
    boots = {name: np.array(v) for name, v in boots.items()}

    rows = []
    for name in sets:
        row = {"features": name, "auc": round(roc_auc_score(yt, p[name]), 3),
               "ci_low": round(np.percentile(boots[name], 2.5), 3),
               "ci_high": round(np.percentile(boots[name], 97.5), 3),
               "test_drivers": int(tested.sum()), "test_positives": int(yt.sum()),
               "failed_replicates": failed}
        if name != "performance":
            d = boots[name] - boots["performance"]
            row.update(delta=round(d.mean(), 3), delta_ci_low=round(np.percentile(d, 2.5), 3),
                       delta_ci_high=round(np.percentile(d, 97.5), 3), helps=verdict(d))
        rows.append(row)
    return pd.DataFrame(windows), pd.DataFrame(rows)


def chronological_validation(conn, rng):
    """RQ1, rookie season. Two versions:
    eventual outcome  train on cohorts before year t, labelled with whether they ever reached F1.
                      Features and fitting are out-of-time, but some training labels only became
                      known after year t. Pending drivers are excluded.
    strict horizon    label = reached F1 within HORIZON years of the GP2/F2 debut. A cohort is only
                      used for training once its window has closed by year t, so every training
                      label was known at the time. Test cohorts must also have closed windows,
                      so nothing is pending.
    Intervals resample test drivers around the fixed fitted models."""
    snaps = query_df(conn, "SELECT * FROM f1.experiment_snapshots")
    rookies = snaps[snaps["k"] == 1].copy()
    rookies["season"] = pd.to_numeric(rookies["season"]).astype(int)
    rookies["debut"] = pd.to_numeric(rookies["f1_debut_season"], errors="coerce")
    pending = rookies[rookies["outcome"] == "Pending"].groupby("season").size().to_dict()
    windows, results = {}, []

    # Version 1: eventual outcome
    df = rookies[rookies["in_rq1"].astype(bool)].reset_index(drop=True)
    y = df["rq1_reached_f1"].astype(bool).to_numpy()
    seasons = df["season"].to_numpy()
    w, r = chrono_evaluate(df, y, lambda t: seasons < t,
                           [t for t in sorted(df["season"].unique()) if t >= CHRONO_FIRST_TEST_YEAR],
                           rng, {"pending_excluded": lambda t: int(pending.get(t, 0))})
    windows["eventual outcome"] = w
    results.append(r.assign(version="eventual outcome"))

    # Version 2: strict horizon
    df = rookies[~rookies["outcome"].str.startswith("Excluded")].reset_index(drop=True)
    y = (df["debut"].notna() & (df["debut"] - df["season"] <= HORIZON)).to_numpy()
    seasons = df["season"].to_numpy()
    test_years = [t for t in sorted(df["season"].unique())
                  if t >= CHRONO_FIRST_TEST_YEAR and t + HORIZON <= LAST_COMPLETE_SEASON]
    w, r = chrono_evaluate(df, y, lambda t: seasons + HORIZON <= t, test_years, rng, {})
    windows[f"strict {HORIZON}-year horizon"] = w
    results.append(r.assign(version=f"strict {HORIZON}-year horizon"))

    result = pd.concat(results, ignore_index=True)
    for name, w in windows.items():
        print(f"\nChronological validation - RQ1 rookie season, {name}:")
        print(w.to_string(index=False))
        view = result[result["version"] == name].drop(columns=["version"])
        print(view.to_string(index=False, na_rep=""))
    print("  Intervals resample test drivers around fixed models, so they are tighter than the "
          "out-of-bag intervals above.")
    return result, windows


def compare_with_original(results):
    path = OUT / "model_results.csv"
    if not path.exists():
        print("\n(No Part 4 results found to compare with.)")
        return
    original = pd.read_csv(path)
    names = {"Model 1: reached F1": "RQ1 progression", "Model 2: Established or Star": "RQ2 establishment"}
    original["question"] = original["model"].map(names)

    rows = []
    for question in names.values():
        for features in ["performance", "+ age"]:
            o = original[(original["question"] == question) & (original["snapshot"] == "rookie")
                         & (original["features"] == features)]
            n = results[(results["question"] == question) & (results["prediction_point"] == "end of season 1")
                        & (results["features"] == features)]
            if o.empty or n.empty:
                continue
            rows.append({"question": question, "features": features,
                         "original_auc": o["auc"].iloc[0], "original_drivers": o["drivers"].iloc[0],
                         "revised_auc": n["auc"].iloc[0], "revised_drivers": n["drivers"].iloc[0],
                         "revised_ci": f"{n['oob_ci_low'].iloc[0]}-{n['oob_ci_high'].iloc[0]}"})
    print("\nRookie season: original (global ratings, all years) vs revised (time-safe, from 2007):")
    print(pd.DataFrame(rows).to_string(index=False))

    final = original[(original["snapshot"] == "final") & (original["features"] == "performance")]
    for _, r in final.iterrows():
        print(f"  Exploratory only, outcome-dependent snapshot: {r['model']} final-season AUC {r['auc']}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    with psycopg.connect(**DB) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_PATH.read_text(encoding="utf-8"))
        conn.commit()
        print_scale(conn)
        composition = class_composition(conn)
        results, contrasts = run_experiments(conn, rng)
        chronological, chrono_windows = chronological_validation(conn, rng)
        write_population_doc(composition, chrono_windows)

    compare_with_original(results)
    results.to_csv(OUT / "experiment_results.csv", index=False)
    contrasts.to_csv(OUT / "experiment_sensitivity.csv", index=False)
    composition.to_csv(OUT / "experiment_composition.csv", index=False)
    chronological.to_csv(OUT / "experiment_chronological.csv", index=False)


if __name__ == "__main__":
    main()