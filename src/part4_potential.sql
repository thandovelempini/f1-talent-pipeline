-- Part 4 - Driver Potential Rating and model snapshots.
--
-- Potential = how far ahead of schedule a driver is:
--   expected rating   what a driver of this age and experience typically rates
--                     (a straight-line fit of rating on age, per season in the category)
--   ahead_of_schedule actual rating minus expected
--   schedule_change   change in ahead_of_schedule since last season (0 for rookies)
--   potential = percentile (0-100) of 0.7*z(ahead_of_schedule) + 0.3*z(schedule_change)
--
-- Snapshots for the models, using no seasons after a driver's F1 debut:
--   rookie  first GP2/F2 season
--   final   last GP2/F2 season up to the F1 debut (or of the whole career)

SET search_path TO f1, public;


DROP TABLE IF EXISTS age_curve_fit CASCADE;
CREATE TABLE age_curve_fit AS
SELECT
    LEAST(season_in_category, 4) AS experience,
    regr_slope(rating_raw::float8, age_at_season_start::float8) AS slope,
    regr_intercept(rating_raw::float8, age_at_season_start::float8) AS intercept,
    regr_r2(rating_raw::float8, age_at_season_start::float8) AS r2,
    regr_count(rating_raw::float8, age_at_season_start::float8) AS n
FROM junior_season_ratings
WHERE NOT season_in_progress
    AND confidence <> 'Low'
GROUP BY LEAST(season_in_category, 4);


DROP TABLE IF EXISTS junior_season_potential CASCADE;
CREATE TABLE junior_season_potential AS
WITH expected AS (
    SELECT
        r.*,
        f.intercept + f.slope * r.age_at_season_start::float8 AS expected_raw
    FROM junior_season_ratings r
    JOIN age_curve_fit f ON f.experience = LEAST(r.season_in_category, 4)
),
ahead AS (
    SELECT
        *,
        rating_raw::float8 - expected_raw AS ahead_of_schedule,
        rating_raw::float8 - LAG(rating_raw::float8) OVER (PARTITION BY driver_key ORDER BY season) AS improvement
    FROM expected
),
changes AS (
    SELECT
        *,
        ahead_of_schedule - LAG(ahead_of_schedule) OVER (PARTITION BY driver_key ORDER BY season) AS schedule_change
    FROM ahead
),
norms AS (
    SELECT
        AVG(ahead_of_schedule) AS a_mean, STDDEV_SAMP(ahead_of_schedule) AS a_sd,
        AVG(schedule_change) AS c_mean, STDDEV_SAMP(schedule_change) AS c_sd
    FROM changes
    WHERE NOT season_in_progress
),
scored AS (
    SELECT
        c.*,
        0.7 * (c.ahead_of_schedule - n.a_mean) / NULLIF(n.a_sd, 0)
            + 0.3 * COALESCE((c.schedule_change - n.c_mean) / NULLIF(n.c_sd, 0), 0) AS potential_raw
    FROM changes c
    CROSS JOIN norms n
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
    ROUND(expected_raw::numeric, 3) AS expected_raw,
    ROUND(ahead_of_schedule::numeric, 3) AS ahead_of_schedule,
    ROUND(improvement::numeric, 3) AS improvement,
    ROUND(potential_raw::numeric, 3) AS potential_raw,
    CASE WHEN potential_raw IS NOT NULL
        THEN ROUND(100 * PERCENT_RANK() OVER (ORDER BY potential_raw NULLS FIRST))::int END AS potential_rating
FROM scored;


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
    p.potential_rating,
    p.potential_raw,
    p.ahead_of_schedule,
    o.outcome,
    o.in_model1,
    o.model1_reached_f1,
    o.in_model2,
    o.model2_succeeded
FROM picked p
JOIN driver_outcomes o USING (driver_key);