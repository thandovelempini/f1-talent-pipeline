-- Part 1 - Build the clean tables from the raw tables loaded by run_part1.py.
-- Outputs: drivers, junior_seasons, f1_seasons, driver_summary

SET search_path TO f1, public;


DROP TABLE IF EXISTS junior_results CASCADE;
CREATE TABLE junior_results AS
SELECT
    s.season::int AS season,
    s.series,
    COALESCE(m.canonical_title, s.wiki_title, 'unlinked::' || s.driver_name) AS driver_key,
    s.driver_name,
    s.pos_text,
    CASE WHEN s.pos_text ~ '^\d+$' THEN s.pos_text::int END AS final_pos,
    -- '0' prefix handles a lone '½' and guarantees a numeric match
    COALESCE(
        substring('0' || replace(s.points_text, '½', '.5') FROM '^[0-9]+(?:\.[0-9]+)?')::numeric,
        0) AS points
FROM raw_junior_standings s
LEFT JOIN title_map m ON m.raw_title = s.wiki_title;


DROP TABLE IF EXISTS junior_entries CASCADE;
CREATE TABLE junior_entries AS
SELECT
    e.season::int AS season,
    COALESCE(m.canonical_title, e.wiki_title, 'unlinked::' || e.driver_name) AS driver_key,
    e.team,
    e.car_no,
    e.rounds,
    e.entry_order::int AS entry_order,
    COALESCE(lower(e.rounds) LIKE '%all%', false) AS all_rounds,
    r.rounds_covered,
    r.last_round
FROM raw_junior_entries e
LEFT JOIN title_map m ON m.raw_title = e.wiki_title
-- Expand round lists like '1–5', '6–12' or '1, 3–5' and count the rounds
LEFT JOIN LATERAL (
    SELECT COUNT(DISTINCT n) AS rounds_covered, MAX(n) AS last_round
    FROM regexp_matches(COALESCE(e.rounds, ''), '(\d+)(?:\s*[–-]\s*(\d+))?', 'g') AS m,
        generate_series(m[1]::int, COALESCE(m[2], m[1])::int) AS n
) r ON true;


-- Primary team: the 'All' rounds entry, otherwise the team with the most rounds
DROP TABLE IF EXISTS junior_primary_team CASCADE;
CREATE TABLE junior_primary_team AS
SELECT season, driver_key, team, car_no, n_teams
FROM (
    SELECT
        e.*,
        ROW_NUMBER() OVER (
            PARTITION BY season, driver_key
            ORDER BY all_rounds DESC, rounds_covered DESC, entry_order
        ) AS rn,
        COUNT(*) OVER (PARTITION BY season, driver_key) AS n_teams
    FROM junior_entries e
) ranked
WHERE rn = 1;


DROP TABLE IF EXISTS f1_seasons CASCADE;
CREATE TABLE f1_seasons AS
SELECT
    f.season::int AS season,
    COALESCE(m.canonical_title, f.wiki_title, 'jolpica::' || f.jolpica_id) AS driver_key,
    f.jolpica_id,
    f.driver_name,
    CASE WHEN f.dob ~ '^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$'
         THEN f.dob::date END AS dob,
    f.constructor,
    CASE WHEN f.position ~ '^\d+$' THEN f.position::int END AS championship_pos,
    CASE WHEN f.points ~ '^\d+(\.\d+)?$' THEN f.points::numeric END AS points,
    CASE WHEN f.wins ~ '^\d+$' THEN f.wins::int END AS wins,
    f.season::int = (SELECT current_season FROM project_settings) AS season_in_progress
FROM raw_f1_standings f
LEFT JOIN title_map m ON m.raw_title = f.wiki_title;


DROP TABLE IF EXISTS drivers CASCADE;
CREATE TABLE drivers AS
WITH all_appearances AS (
    SELECT driver_key, driver_name, season FROM junior_results
    UNION ALL
    SELECT driver_key, driver_name, season FROM f1_seasons
),
named AS (
    SELECT DISTINCT ON (driver_key) driver_key, driver_name
    FROM all_appearances
    ORDER BY driver_key, season
),
f1_dob AS (
    SELECT driver_key, MAX(dob) AS dob FROM f1_seasons GROUP BY driver_key
)
SELECT
    n.driver_key,
    n.driver_name,
    -- F1 data first: Wikidata sometimes holds more than one birth date
    COALESCE(
        f.dob,
        CASE WHEN b.dob ~ '^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$' THEN b.dob::date END) AS dob,
    b.nationality
FROM named n
LEFT JOIN driver_bios b ON b.title = n.driver_key
LEFT JOIN f1_dob f ON f.driver_key = n.driver_key;


DROP TABLE IF EXISTS junior_seasons CASCADE;
CREATE TABLE junior_seasons AS
SELECT
    r.season,
    r.series,
    r.driver_key,
    d.driver_name,
    t.team,
    t.car_no,
    COALESCE(t.n_teams, 0) AS n_teams,
    r.pos_text,
    r.final_pos,
    r.points,
    ROUND((make_date(r.season, 1, 1) - d.dob) / 365.25, 1) AS age_at_season_start,
    ROW_NUMBER() OVER (PARTITION BY r.driver_key ORDER BY r.season) AS season_in_category,
    r.season = (SELECT current_season FROM project_settings) AS season_in_progress
FROM junior_results r
JOIN drivers d ON d.driver_key = r.driver_key
LEFT JOIN junior_primary_team t ON t.season = r.season AND t.driver_key = r.driver_key;


DROP TABLE IF EXISTS driver_summary CASCADE;
CREATE TABLE driver_summary AS
WITH junior AS (
    SELECT
        driver_key,
        MIN(season) AS first_junior_season,
        MAX(season) AS last_junior_season,
        COUNT(*) AS junior_seasons,
        MIN(final_pos) AS best_junior_pos,
        COUNT(*) FILTER (WHERE final_pos = 1) AS junior_titles,
        MAX(age_at_season_start) FILTER (WHERE season_in_category = 1) AS age_at_junior_debut,
        BOOL_OR(season_in_progress) AS still_in_junior
    FROM junior_seasons
    GROUP BY driver_key
),
f1 AS (
    SELECT
        driver_key,
        MIN(season) AS first_f1_season,
        MAX(season) AS last_f1_season,
        COUNT(*) AS f1_seasons,
        SUM(points) AS f1_points,
        SUM(wins) AS f1_wins,
        MIN(championship_pos) AS best_f1_pos
    FROM f1_seasons
    GROUP BY driver_key
)
SELECT
    d.driver_key,
    d.driver_name,
    d.nationality,
    d.dob,
    j.first_junior_season,
    j.last_junior_season,
    j.junior_seasons,
    j.best_junior_pos,
    j.junior_titles,
    j.age_at_junior_debut,
    j.still_in_junior,
    f.first_f1_season,
    f.last_f1_season,
    COALESCE(f.f1_seasons, 0) AS f1_seasons,
    COALESCE(f.f1_points, 0) AS f1_points,
    COALESCE(f.f1_wins, 0) AS f1_wins,
    f.best_f1_pos,
    f.first_f1_season IS NOT NULL AS reached_f1,
    COALESCE(f.first_f1_season < j.first_junior_season, false) AS raced_f1_before_junior
FROM junior j
JOIN drivers d ON d.driver_key = j.driver_key
LEFT JOIN f1 f ON f.driver_key = j.driver_key;