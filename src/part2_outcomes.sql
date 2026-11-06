-- Part 2 - Classify every junior driver into an outcome tier.
--
-- Star                         top-5 championship finish (completed season) OR 3+ race wins
-- Established                  3+ full F1 seasons
-- Reached, didn't stick        F1 starts, fewer than 3 full seasons, no longer racing
-- Didn't reach F1              no F1 starts, no outstanding opportunity
-- Too early to tell            raced F1 in the current season, fewer than 3 full seasons so far
-- Pending                      no F1 starts, raced GP2/F2 in the current or previous season
-- Excluded: F1 before junior   entered GP2/F2 after already racing in F1 (different pathway)
-- Excluded: career cut short   career ended by circumstances outside performance (Bianchi, Hubert)
--
-- Full season = started at least half that season's races.
-- Model 1 (progression) and Model 2 (success) exclude Too early, Pending and both Excluded tiers.

SET search_path TO f1, public;


DROP TABLE IF EXISTS f1_race_results CASCADE;
CREATE TABLE f1_race_results AS
WITH id_map AS (
    SELECT DISTINCT jolpica_id, driver_key FROM f1_seasons
)
SELECT
    r.season::int AS season,
    r.round::int AS round,
    r.race_name,
    CASE WHEN r.race_date ~ '^\d{4}-\d{2}-\d{2}$' THEN r.race_date::date END AS race_date,
    COALESCE(m.driver_key, 'jolpica::' || r.jolpica_id) AS driver_key,
    r.jolpica_id,
    r.constructor,
    CASE WHEN r.grid ~ '^\d+$' THEN r.grid::int END AS grid,
    CASE WHEN r.position ~ '^\d+$' THEN r.position::int END AS finish_pos,
    r.position_text,
    CASE WHEN r.points ~ '^\d+(\.\d+)?$' THEN r.points::numeric END AS points,
    r.status,
    NOT (COALESCE(r.status, '') ILIKE 'did not%'
         OR COALESCE(r.status, '') ILIKE 'withdrew%') AS started
FROM raw_f1_results r
LEFT JOIN id_map m ON m.jolpica_id = r.jolpica_id;


DROP TABLE IF EXISTS f1_driver_seasons CASCADE;
CREATE TABLE f1_driver_seasons AS
WITH season_races AS (
    SELECT season, COUNT(DISTINCT round) AS season_races
    FROM f1_race_results
    GROUP BY season
),
driver_starts AS (
    SELECT
        season,
        driver_key,
        COUNT(*) FILTER (WHERE started) AS starts,
        string_agg(DISTINCT constructor, ' / ') AS constructors
    FROM f1_race_results
    GROUP BY season, driver_key
)
SELECT
    d.season,
    d.driver_key,
    d.constructors,
    d.starts,
    s.season_races,
    d.starts >= 0.5 * s.season_races AS full_season,
    d.season = (SELECT current_season FROM project_settings) AS season_in_progress
FROM driver_starts d
JOIN season_races s ON s.season = d.season;


DROP TABLE IF EXISTS driver_outcomes CASCADE;
CREATE TABLE driver_outcomes AS
WITH settings AS (
    SELECT current_season FROM project_settings
),
career_cut_short AS (
    SELECT * FROM (VALUES ('Jules Bianchi'), ('Anthoine Hubert')) AS t(driver_key)
),
career AS (
    SELECT
        driver_key,
        SUM(starts) AS f1_starts,
        COUNT(*) FILTER (WHERE full_season) AS full_seasons,
        MIN(season) FILTER (WHERE starts > 0) AS first_start_season,
        MAX(season) FILTER (WHERE starts > 0) AS last_start_season
    FROM f1_driver_seasons
    GROUP BY driver_key
),
honours AS (
    SELECT
        driver_key,
        MIN(championship_pos) FILTER (WHERE NOT season_in_progress) AS best_completed_pos,
        COALESCE(SUM(wins), 0) AS f1_wins
    FROM f1_seasons
    GROUP BY driver_key
),
classified AS (
    SELECT
        ds.driver_key,
        ds.driver_name,
        ds.first_junior_season,
        ds.last_junior_season,
        ds.junior_seasons,
        COALESCE(c.f1_starts, 0) AS f1_starts,
        COALESCE(c.full_seasons, 0) AS full_f1_seasons,
        c.first_start_season AS f1_debut_season,
        c.last_start_season AS last_f1_season,
        h.best_completed_pos AS best_f1_championship_pos,
        COALESCE(h.f1_wins, 0) AS f1_wins,
        -- evaluated top to bottom: order sets precedence
        CASE
            WHEN ds.raced_f1_before_junior THEN 'Excluded: F1 before junior'
            WHEN ds.driver_key IN (SELECT driver_key FROM career_cut_short) THEN 'Excluded: career cut short'
            WHEN h.best_completed_pos <= 5 OR h.f1_wins >= 3 THEN 'Star'
            WHEN COALESCE(c.f1_starts, 0) = 0
                 AND ds.last_junior_season >= s.current_season - 1 THEN 'Pending'
            WHEN COALESCE(c.f1_starts, 0) = 0 THEN 'Didn''t reach F1'
            WHEN c.full_seasons >= 3 THEN 'Established'
            WHEN c.last_start_season = s.current_season THEN 'Too early to tell'
            ELSE 'Reached, didn''t stick'
        END AS outcome
    FROM driver_summary ds
    CROSS JOIN settings s
    LEFT JOIN career c ON c.driver_key = ds.driver_key
    LEFT JOIN honours h ON h.driver_key = ds.driver_key
)
SELECT
    *,
    CASE outcome
        WHEN 'Star' THEN 1
        WHEN 'Established' THEN 2
        WHEN 'Reached, didn''t stick' THEN 3
        WHEN 'Didn''t reach F1' THEN 4
        WHEN 'Too early to tell' THEN 5
        WHEN 'Pending' THEN 6
        ELSE 7
    END AS outcome_order,
    outcome IN ('Star', 'Established', 'Reached, didn''t stick', 'Too early to tell', 'Didn''t reach F1') AS in_model1,
    outcome IN ('Star', 'Established', 'Reached, didn''t stick', 'Too early to tell') AS model1_reached_f1,
    outcome IN ('Star', 'Established', 'Reached, didn''t stick') AS in_model2,
    outcome IN ('Star', 'Established') AS model2_succeeded
FROM classified;