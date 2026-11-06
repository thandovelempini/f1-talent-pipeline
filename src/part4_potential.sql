-- Part 4 - Driver Potential Rating (v2) and model snapshots.
--
-- Two potential versions, compared in run_part4.py:
--   v2a age peers     rating vs all drivers of the same age (z-score within age band)
--   v2b development   projected rating = current rating + typical improvement at that age.
--                     Typical improvement comes from the same drivers' season-to-season
--                     changes, with regression to the mean removed first.
-- Age bands: 18 or younger, 19, 20, ... 24, 25 or older.
--
-- Use of the full period: the rating scale (Part 3) and the v2a age-peer averages are
-- computed from all completed seasons 2005-2025. They use no outcome information.
-- The development curve and projected_raw in these tables also use all season pairs and
-- are for description only: run_part4.py re-fits the curve inside every cross-validation
-- fold, leaving out the drivers being predicted.
--
-- Snapshots for the models, using no seasons after a driver's F1 debut:
--   rookie  first GP2/F2 season
--   final   last GP2/F2 season up to the F1 debut (or of the whole career)

SET search_path TO f1, public;

DROP TABLE IF EXISTS age_curve_fit CASCADE;


DROP TABLE IF EXISTS age_peer_norms CASCADE;
CREATE TABLE age_peer_norms AS
SELECT
    LEAST(GREATEST(FLOOR(age_at_season_start)::int, 18), 25) AS age_band,
    AVG(rating_raw::float8) AS mean_raw,
    STDDEV_SAMP(rating_raw::float8) AS sd_raw,
    COUNT(*) AS n
FROM junior_season_ratings
WHERE NOT season_in_progress
    AND confidence <> 'Low'
    AND age_at_season_start IS NOT NULL
GROUP BY 1;


-- One row per driver per pair of consecutive seasons
DROP TABLE IF EXISTS development_pairs CASCADE;
CREATE TABLE development_pairs AS
SELECT
    a.driver_key,
    a.season,
    LEAST(GREATEST(FLOOR(a.age_at_season_start)::int, 18), 25) AS age_band,
    a.rating_raw::float8 AS current_raw,
    b.rating_raw::float8 AS next_raw,
    b.rating_raw::float8 - a.rating_raw::float8 AS change
FROM junior_season_ratings a
JOIN junior_season_ratings b ON b.driver_key = a.driver_key AND b.season = a.season + 1
WHERE a.confidence <> 'Low'
    AND b.confidence <> 'Low'
    AND NOT b.season_in_progress
    AND a.age_at_season_start IS NOT NULL;


DROP TABLE IF EXISTS development_curve CASCADE;
CREATE TABLE development_curve AS
WITH pairs AS (
    SELECT age_band, current_raw, change FROM development_pairs
),
-- High ratings tend to fall back and low ratings rise (regression to the mean);
-- fit that first so the age effect isn't confused with it
mean_reversion AS (
    SELECT
        regr_slope(change, current_raw) AS slope,
        regr_intercept(change, current_raw) AS intercept,
        AVG(current_raw) AS mean_current
    FROM pairs
)
SELECT
    p.age_band,
    AVG(p.change - (m.intercept + m.slope * p.current_raw))
        + (m.intercept + m.slope * m.mean_current) AS expected_development,
    COUNT(*) AS n
FROM pairs p
CROSS JOIN mean_reversion m
GROUP BY 1, m.intercept, m.slope, m.mean_current;


DROP TABLE IF EXISTS junior_season_potential CASCADE;
CREATE TABLE junior_season_potential AS
WITH base AS (
    SELECT
        r.*,
        (r.rating_raw::float8 - n.mean_raw) / NULLIF(n.sd_raw, 0) AS peer_raw,
        d.expected_development,
        r.rating_raw::float8 + COALESCE(d.expected_development, 0) AS projected
    FROM junior_season_ratings r
    CROSS JOIN LATERAL (
        SELECT LEAST(GREATEST(FLOOR(r.age_at_season_start)::int, 18), 25) AS age_band
    ) b
    LEFT JOIN age_peer_norms n ON n.age_band = b.age_band
    LEFT JOIN development_curve d ON d.age_band = b.age_band
)
SELECT
    season,
    series,
    driver_key,
    driver_name,
    team,
    age_at_season_start,
    season_in_category,
    season_in_progress,
    confidence,
    rating AS performance_rating,
    rating_raw AS performance_raw,
    teammate_gap,
    pts_vs_leader,
    ROUND(peer_raw::numeric, 3) AS potential_peer_raw,
    CASE WHEN peer_raw IS NOT NULL
        THEN ROUND(100 * PERCENT_RANK() OVER (ORDER BY peer_raw NULLS FIRST))::int END AS potential_peer,
    ROUND(expected_development::numeric, 3) AS expected_development,
    ROUND(projected::numeric, 3) AS projected_raw,
    ROUND(100 * PERCENT_RANK() OVER (ORDER BY projected))::int AS potential_dev
FROM base;


DROP TABLE IF EXISTS model_snapshots CASCADE;
CREATE TABLE model_snapshots AS
WITH eligible AS (
    SELECT p.*
    FROM junior_season_potential p
    JOIN driver_outcomes o USING (driver_key)
    WHERE o.f1_debut_season IS NULL OR p.season <= o.f1_debut_season
),
so_far AS (
    SELECT
        e.*,
        MAX(performance_raw) OVER w AS best_raw_so_far,
        COUNT(*) OVER w AS seasons_so_far
    FROM eligible e
    WINDOW w AS (PARTITION BY driver_key ORDER BY season ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
rookie AS (
    SELECT 'rookie' AS snapshot, s.*
    FROM so_far s
    WHERE season_in_category = 1
),
final AS (
    SELECT DISTINCT ON (driver_key) 'final' AS snapshot, s.*
    FROM so_far s
    ORDER BY driver_key, season DESC
),
picked AS (
    SELECT * FROM rookie
    UNION ALL
    SELECT * FROM final
)
SELECT
    p.snapshot,
    p.driver_key,
    p.driver_name,
    p.season,
    p.team,
    p.age_at_season_start AS age,
    p.season_in_category,
    p.seasons_so_far,
    p.confidence,
    p.performance_rating,
    p.performance_raw,
    p.best_raw_so_far,
    p.teammate_gap,
    p.pts_vs_leader,
    p.potential_peer,
    p.potential_peer_raw,
    p.potential_dev,
    p.projected_raw,
    p.expected_development,
    o.outcome,
    o.in_model1,
    o.model1_reached_f1,
    o.in_model2,
    o.model2_succeeded
FROM picked p
JOIN driver_outcomes o USING (driver_key);