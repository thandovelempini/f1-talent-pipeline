-- Part 4b - Leakage-safe experiment: time-safe ratings and at-risk snapshots.
--
-- Time-safe rating: for each season, the car adjustment and z-score norms are fitted only
-- on completed seasons up to and including that season, so a 2012 rating uses nothing
-- from 2013 onwards. Ratings need at least 3 seasons of history (burn-in), so they start
-- in 2007. Composite weights (0.5 / 0.3 / 0.2) are fixed by hand, not estimated.
--
-- Snapshots: the end of a driver's 1st, 2nd and 3rd GP2/F2 season, for drivers still
-- "at risk", i.e. who had not raced in F1 before that season. An F1 debut in the same
-- year counts as reaching F1 after the snapshot.
--
-- Research question 1 (progression): will the driver eventually reach F1?
-- Research question 2 (establishment): among F1 entrants, Established or Star?

SET search_path TO f1, public;


DROP TABLE IF EXISTS rating_scale_by_season CASCADE;
CREATE TABLE rating_scale_by_season AS
WITH seasons AS (
    SELECT DISTINCT season AS as_of FROM junior_season_components
),
fit AS (
    SELECT
        s.as_of,
        regr_slope(c.pos_pct, c.team_strength) AS slope,
        regr_intercept(c.pos_pct, c.team_strength) AS intercept,
        COUNT(DISTINCT c.season) AS seasons_used
    FROM seasons s
    JOIN junior_season_components c ON c.season <= s.as_of AND NOT c.season_in_progress
    GROUP BY s.as_of
)
SELECT
    f.as_of,
    f.slope,
    f.intercept,
    f.seasons_used,
    AVG(c.teammate_gap) AS tm_mean,
    STDDEV_SAMP(c.teammate_gap) AS tm_sd,
    AVG(c.pos_pct - (f.intercept + f.slope * c.team_strength)) AS car_mean,
    STDDEV_SAMP(c.pos_pct - (f.intercept + f.slope * c.team_strength)) AS car_sd,
    AVG(c.pts_vs_leader) AS lead_mean,
    STDDEV_SAMP(c.pts_vs_leader) AS lead_sd
FROM fit f
JOIN junior_season_components c ON c.season <= f.as_of AND NOT c.season_in_progress
GROUP BY f.as_of, f.slope, f.intercept, f.seasons_used;


DROP TABLE IF EXISTS junior_season_ratings_ts CASCADE;
CREATE TABLE junior_season_ratings_ts AS
SELECT
    c.season,
    c.driver_key,
    c.driver_name,
    c.team,
    c.age_at_season_start,
    c.season_in_category,
    c.season_in_progress,
    c.teammate_gap,
    c.pts_vs_leader,
    c.team_strength,
    p.seasons_used,
    p.seasons_used >= 3 AS rating_available,
    0.5 * COALESCE((c.teammate_gap - p.tm_mean) / NULLIF(p.tm_sd, 0), 0)
        + 0.3 * COALESCE((c.pos_pct - (p.intercept + p.slope * c.team_strength) - p.car_mean) / NULLIF(p.car_sd, 0), 0)
        + 0.2 * COALESCE((c.pts_vs_leader - p.lead_mean) / NULLIF(p.lead_sd, 0), 0) AS rating_ts_raw
FROM junior_season_components c
JOIN rating_scale_by_season p ON p.as_of = c.season;


DROP TABLE IF EXISTS experiment_snapshots CASCADE;
CREATE TABLE experiment_snapshots AS
WITH seq AS (
    SELECT
        r.*,
        CASE WHEN r.rating_available THEN r.rating_ts_raw END
            - LAG(CASE WHEN r.rating_available THEN r.rating_ts_raw END)
                OVER (PARTITION BY r.driver_key ORDER BY r.season) AS trajectory
    FROM junior_season_ratings_ts r
)
SELECT
    s.season_in_category AS k,
    s.driver_key,
    s.driver_name,
    s.season,
    s.age_at_season_start AS age,
    s.rating_ts_raw,
    s.teammate_gap,
    s.pts_vs_leader,
    s.team_strength,
    s.trajectory,
    o.outcome,
    o.f1_debut_season,
    o.in_model1 AS in_rq1,
    o.model1_reached_f1 AS rq1_reached_f1,
    o.in_model2 AS in_rq2,
    o.model2_succeeded AS rq2_established
FROM seq s
JOIN driver_outcomes o USING (driver_key)
WHERE s.season_in_category <= 3
    AND s.rating_available
    AND NOT s.season_in_progress
    AND (o.f1_debut_season IS NULL OR s.season <= o.f1_debut_season);