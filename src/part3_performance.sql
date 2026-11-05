-- Part 3 - Driver Performance Rating.
--
-- One rating per junior season, built from three components:
--   teammate_gap     (points - other seat's points) / leader's points; same car, so car-neutral
--   car_adjusted     finishing percentile minus what the team's strength would predict
--   pts_vs_leader    points as a share of the season leader's; comparable across scoring systems
--
-- The other seat = everyone else who drove for the same team that season, so a mid-season
-- replacement doesn't flatter the full-time driver. teammate_share is kept for display only.
--
-- rating = percentile (0-100) of 0.5*z(teammate_gap) + 0.3*z(car_adjusted) + 0.2*z(pts_vs_leader),
-- where z-scores use completed seasons only. A rating of 90 = better than 90% of GP2/F2 seasons.
-- Part season = covered fewer than 75% of the season's rounds.
-- Confidence is Low for part seasons or no comparable teammate, Medium after a team switch.

SET search_path TO f1, public;


DROP TABLE IF EXISTS junior_team_seasons CASCADE;
CREATE TABLE junior_team_seasons AS
WITH team_points AS (
    SELECT season, team, SUM(points) AS team_points, COUNT(*) AS team_drivers
    FROM junior_seasons
    WHERE team IS NOT NULL
    GROUP BY season, team
)
SELECT
    season,
    team,
    team_points,
    team_drivers,
    RANK() OVER (PARTITION BY season ORDER BY team_points DESC) AS team_rank,
    COUNT(*) OVER (PARTITION BY season) AS teams_in_season,
    1 - PERCENT_RANK() OVER (PARTITION BY season ORDER BY team_points DESC) AS team_strength
FROM team_points;


DROP TABLE IF EXISTS junior_teammates CASCADE;
CREATE TABLE junior_teammates AS
SELECT
    a.season,
    a.driver_key,
    string_agg(b.driver_name, ' / ' ORDER BY b.points DESC) AS teammate_names,
    SUM(b.points) AS teammate_points
FROM junior_seasons a
JOIN junior_seasons b
    ON b.season = a.season
    AND b.team = a.team
    AND b.driver_key <> a.driver_key
GROUP BY a.season, a.driver_key;


DROP TABLE IF EXISTS junior_season_components CASCADE;
CREATE TABLE junior_season_components AS
WITH season_stats AS (
    SELECT season, MAX(points) AS leader_points, COUNT(final_pos) AS classified
    FROM junior_seasons
    GROUP BY season
),
season_rounds AS (
    SELECT season, MAX(last_round) AS season_rounds
    FROM junior_entries
    GROUP BY season
),
entry_info AS (
    SELECT
        season,
        driver_key,
        BOOL_OR(all_rounds) AS all_rounds,
        SUM(rounds_covered) AS rounds_covered
    FROM junior_entries
    GROUP BY season, driver_key
)
SELECT
    js.season,
    js.series,
    js.driver_key,
    js.driver_name,
    js.team,
    js.age_at_season_start,
    js.season_in_category,
    js.season_in_progress,
    js.final_pos,
    js.points,
    tm.teammate_names,
    tm.teammate_points,
    CASE WHEN js.points + tm.teammate_points > 0
        THEN (js.points / (js.points + tm.teammate_points))::float8 END AS teammate_share,
    ((js.points - tm.teammate_points) / NULLIF(ss.leader_points, 0))::float8 AS teammate_gap,
    (js.points / NULLIF(ss.leader_points, 0))::float8 AS pts_vs_leader,
    CASE WHEN js.final_pos IS NOT NULL AND ss.classified > 1
        THEN GREATEST(0, 1 - (js.final_pos - 1)::float8 / (ss.classified - 1))
        ELSE 0 END AS pos_pct,
    ts.team_strength,
    js.n_teams > 1 AS switched_team,
    CASE
        WHEN ei.all_rounds THEN false
        WHEN ei.rounds_covered > 0 THEN ei.rounds_covered < 0.75 * sr.season_rounds
    END AS part_season
FROM junior_seasons js
JOIN season_stats ss ON ss.season = js.season
LEFT JOIN junior_teammates tm ON tm.season = js.season AND tm.driver_key = js.driver_key
LEFT JOIN junior_team_seasons ts ON ts.season = js.season AND ts.team = js.team
LEFT JOIN entry_info ei ON ei.season = js.season AND ei.driver_key = js.driver_key
LEFT JOIN season_rounds sr ON sr.season = js.season;


-- Car adjustment: how well does team strength predict finishing percentile?
-- regr_slope / regr_intercept fit a straight line (least squares) in SQL.
DROP TABLE IF EXISTS car_adjustment_fit CASCADE;
CREATE TABLE car_adjustment_fit AS
SELECT
    regr_slope(pos_pct, team_strength) AS slope,
    regr_intercept(pos_pct, team_strength) AS intercept,
    regr_r2(pos_pct, team_strength) AS r2,
    regr_count(pos_pct, team_strength) AS n
FROM junior_season_components
WHERE NOT season_in_progress;


DROP TABLE IF EXISTS junior_season_ratings CASCADE;
CREATE TABLE junior_season_ratings AS
WITH adjusted AS (
    SELECT
        c.*,
        c.pos_pct - (f.intercept + f.slope * c.team_strength) AS car_adjusted
    FROM junior_season_components c
    CROSS JOIN car_adjustment_fit f
),
norms AS (
    SELECT
        AVG(teammate_gap) AS tm_mean, STDDEV_SAMP(teammate_gap) AS tm_sd,
        AVG(car_adjusted) AS car_mean, STDDEV_SAMP(car_adjusted) AS car_sd,
        AVG(pts_vs_leader) AS lead_mean, STDDEV_SAMP(pts_vs_leader) AS lead_sd
    FROM adjusted
    WHERE NOT season_in_progress
),
scored AS (
    SELECT
        a.*,
        COALESCE((a.teammate_gap - n.tm_mean) / NULLIF(n.tm_sd, 0), 0) AS z_teammate,
        COALESCE((a.car_adjusted - n.car_mean) / NULLIF(n.car_sd, 0), 0) AS z_car,
        COALESCE((a.pts_vs_leader - n.lead_mean) / NULLIF(n.lead_sd, 0), 0) AS z_leader
    FROM adjusted a
    CROSS JOIN norms n
),
combined AS (
    SELECT
        *,
        0.5 * z_teammate + 0.3 * z_car + 0.2 * z_leader AS rating_raw
    FROM scored
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
    final_pos,
    points,
    teammate_names,
    ROUND(teammate_share::numeric, 3) AS teammate_share,
    ROUND(teammate_gap::numeric, 3) AS teammate_gap,
    ROUND(team_strength::numeric, 3) AS team_strength,
    ROUND(car_adjusted::numeric, 3) AS car_adjusted,
    ROUND(pts_vs_leader::numeric, 3) AS pts_vs_leader,
    ROUND(rating_raw::numeric, 3) AS rating_raw,
    ROUND(100 * PERCENT_RANK() OVER (ORDER BY rating_raw))::int AS rating,
    CASE
        WHEN part_season OR teammate_gap IS NULL THEN 'Low'
        WHEN switched_team THEN 'Medium'
        ELSE 'High'
    END AS confidence
FROM combined;


DROP TABLE IF EXISTS driver_performance CASCADE;
CREATE TABLE driver_performance AS
WITH career AS (
    SELECT
        driver_key,
        COUNT(*) AS junior_seasons,
        MAX(rating) AS best_rating,
        MAX(rating) FILTER (WHERE confidence <> 'Low') AS best_confident_rating,
        ROUND(AVG(rating)) AS avg_rating,
        MAX(rating) FILTER (WHERE season_in_category = 1) AS rookie_rating,
        (array_agg(rating ORDER BY season DESC))[1] AS last_rating,
        (array_agg(season ORDER BY rating DESC, season))[1] AS best_season,
        ROUND(AVG(teammate_share), 3) AS avg_teammate_share,
        ROUND(AVG(teammate_gap), 3) AS avg_teammate_gap
    FROM junior_season_ratings
    GROUP BY driver_key
)
SELECT
    o.driver_key,
    o.driver_name,
    o.outcome,
    o.outcome_order,
    o.in_model1,
    o.model1_reached_f1,
    o.in_model2,
    o.model2_succeeded,
    c.junior_seasons,
    c.best_rating,
    c.best_confident_rating,
    c.avg_rating,
    c.rookie_rating,
    c.last_rating,
    c.best_season,
    c.avg_teammate_share,
    c.avg_teammate_gap
FROM driver_outcomes o
JOIN career c ON c.driver_key = o.driver_key;