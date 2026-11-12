-- Part 5 - Tables for the Streamlit app.
--
-- app_prediction_rows  every driver-season at the end of a driver's 1st-3rd GP2/F2 season,
--                      before any F1 debut, with the time-safe features used in Part 4b.
--                      Includes the season in progress, which is provisional.
-- app_driver_seasons   every junior season with its performance rating, for driver profiles
-- app_drivers          one row per driver with junior and F1 career summaries

SET search_path TO f1, public;


DROP TABLE IF EXISTS app_prediction_rows CASCADE;
CREATE TABLE app_prediction_rows AS
SELECT
    r.season,
    r.driver_key,
    r.driver_name,
    r.team,
    r.season_in_category AS k,
    r.age_at_season_start AS age,
    r.rating_ts_raw,
    r.teammate_gap,
    r.team_strength,
    r.season_in_progress,
    o.outcome,
    o.f1_debut_season,
    o.in_model1 AS in_rq1,
    o.model1_reached_f1 AS rq1_reached_f1
FROM junior_season_ratings_ts r
JOIN driver_outcomes o USING (driver_key)
WHERE r.season_in_category <= 3
    AND r.rating_available
    AND (o.f1_debut_season IS NULL OR r.season <= o.f1_debut_season);


DROP TABLE IF EXISTS app_driver_seasons CASCADE;
CREATE TABLE app_driver_seasons AS
SELECT
    js.season,
    js.series,
    js.driver_key,
    js.driver_name,
    js.team,
    js.pos_text,
    js.final_pos,
    js.points,
    js.age_at_season_start AS age,
    js.season_in_category AS k,
    js.season_in_progress,
    r.rating AS performance_rating,
    r.teammate_gap,
    r.team_strength,
    r.confidence
FROM junior_seasons js
LEFT JOIN junior_season_ratings r USING (season, driver_key);


DROP TABLE IF EXISTS app_drivers CASCADE;
CREATE TABLE app_drivers AS
SELECT
    ds.driver_key,
    ds.driver_name,
    ds.nationality,
    ds.dob,
    ds.first_junior_season,
    ds.last_junior_season,
    ds.junior_seasons,
    ds.best_junior_pos,
    ds.junior_titles,
    o.outcome,
    o.outcome_order,
    o.f1_debut_season,
    o.last_f1_season,
    o.f1_starts,
    o.full_f1_seasons,
    o.f1_wins,
    o.best_f1_championship_pos
FROM driver_summary ds
JOIN driver_outcomes o USING (driver_key);