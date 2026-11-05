-- Data quality checks before Part 4.
-- Each block starting with "-- check:" is one query. [issue] checks should return 0 rows;
-- [review] checks are lists to read through. run_checks.py saves every result to data/checks/.

SET search_path TO f1, public;

CREATE EXTENSION IF NOT EXISTS unaccent SCHEMA public;

-- Lower case, no accents, single spaces: 'Nico Hülkenberg' -> 'nico hulkenberg'
CREATE OR REPLACE FUNCTION f1.norm_name(name text) RETURNS text AS $$
    SELECT regexp_replace(lower(public.unaccent(COALESCE(name, ''))), '\s+', ' ', 'g')
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION f1.wiki_url(driver_key text) RETURNS text AS $$
    SELECT CASE WHEN driver_key LIKE '%::%' THEN NULL
        ELSE 'https://en.wikipedia.org/wiki/' || replace(driver_key, ' ', '_') END
$$ LANGUAGE sql IMMUTABLE;


-- 1. Drivers who reached F1

-- check: 1a_reached_f1 [review]
SELECT
    o.driver_name,
    o.outcome,
    ds.first_junior_season,
    ds.last_junior_season,
    ds.junior_seasons,
    ds.best_junior_pos,
    o.f1_debut_season,
    o.last_f1_season,
    o.f1_starts,
    o.full_f1_seasons,
    o.f1_wins,
    o.best_f1_championship_pos,
    o.f1_debut_season - ds.last_junior_season AS years_junior_to_f1,
    wiki_url(o.driver_key) AS wikipedia
FROM driver_outcomes o
JOIN driver_summary ds USING (driver_key)
WHERE ds.reached_f1
ORDER BY o.f1_debut_season, o.driver_name;

-- check: 1b_f1_standings_vs_starts [issue]
-- In the F1 standings but no race start that season, or the other way round
SELECT
    COALESCE(s.season, d.season) AS season,
    COALESCE(s.driver_key, d.driver_key) AS driver_key,
    s.championship_pos,
    d.starts,
    CASE
        WHEN s.driver_key IS NULL THEN 'starts but not in standings'
        WHEN d.driver_key IS NULL THEN 'in standings but no race results'
        ELSE 'in standings with 0 starts'
    END AS problem
FROM f1_seasons s
FULL JOIN f1_driver_seasons d ON d.season = s.season AND d.driver_key = s.driver_key
WHERE (s.driver_key IS NULL OR d.driver_key IS NULL OR d.starts = 0)
    AND COALESCE(s.driver_key, d.driver_key) IN (SELECT driver_key FROM driver_summary)
ORDER BY 1, 2;

-- check: 1c_f1_drivers_possibly_unlinked [issue]
-- F1 drivers with no junior record whose name or surname matches a junior driver
-- (same-surname rows are usually relatives, e.g. Mick and Michael Schumacher)
SELECT DISTINCT
    f.driver_name AS f1_driver,
    f.driver_key AS f1_key,
    MIN(f.season) OVER (PARTITION BY f.driver_key) AS first_f1_season,
    j.driver_name AS junior_driver,
    j.driver_key AS junior_key,
    CASE WHEN norm_name(j.driver_name) = norm_name(f.driver_name) THEN 'same name' ELSE 'same surname' END AS match_type
FROM f1_seasons f
JOIN driver_summary j
    ON j.driver_key <> f.driver_key
    AND (norm_name(j.driver_name) = norm_name(f.driver_name)
        OR regexp_replace(norm_name(j.driver_name), '^.* ', '') = regexp_replace(norm_name(f.driver_name), '^.* ', ''))
WHERE f.driver_key NOT IN (SELECT driver_key FROM driver_summary)
    AND f.season >= 2005
ORDER BY match_type DESC, 1;


-- 2. Duplicate or ambiguous names

-- check: 2a_same_name_different_driver [issue]
SELECT norm_name(driver_name) AS name, string_agg(driver_key, ' | ') AS driver_keys
FROM drivers
GROUP BY norm_name(driver_name)
HAVING COUNT(DISTINCT driver_key) > 1;

-- check: 2b_one_driver_several_names [review]
-- Names that were merged into one driver; confirm each is the same person
WITH names AS (
    SELECT driver_key, driver_name FROM junior_results
    UNION
    SELECT driver_key, driver_name FROM f1_seasons
)
SELECT driver_key, string_agg(driver_name, ' | ' ORDER BY driver_name) AS names_used, wiki_url(driver_key) AS wikipedia
FROM names
WHERE driver_key IN (SELECT driver_key FROM driver_summary)
GROUP BY driver_key
HAVING COUNT(DISTINCT norm_name(driver_name)) > 1
ORDER BY driver_key;

-- check: 2c_suspicious_wikipedia_links [issue]
-- Disambiguated titles other than '(racing driver)', or a title without the driver's surname
SELECT
    d.driver_name,
    d.driver_key,
    CASE WHEN d.driver_key LIKE '%(%' THEN 'disambiguated title' ELSE 'surname not in title' END AS reason,
    wiki_url(d.driver_key) AS wikipedia
FROM drivers d
WHERE d.driver_key IN (SELECT driver_key FROM driver_summary)
    AND d.driver_key NOT LIKE 'unlinked::%'
    AND ((d.driver_key LIKE '%(%' AND d.driver_key NOT LIKE '%(racing driver)')
        OR position(regexp_replace(norm_name(d.driver_name), '^.* ', '') IN norm_name(d.driver_key)) = 0)
ORDER BY reason, d.driver_name;

-- check: 2d_birth_date_mismatch [issue]
-- Wikidata and Jolpica disagree on date of birth: possibly the wrong person
SELECT
    d.driver_name,
    b.dob AS wikidata_dob,
    f.dob AS jolpica_dob,
    wiki_url(d.driver_key) AS wikipedia
FROM drivers d
JOIN driver_bios b ON b.title = d.driver_key
JOIN driver_summary ds ON ds.driver_key = d.driver_key
JOIN (SELECT driver_key, MAX(dob) AS dob FROM f1_seasons GROUP BY driver_key) f ON f.driver_key = d.driver_key
WHERE b.dob IS NOT NULL
    AND f.dob IS NOT NULL
    AND b.dob <> f.dob::text
ORDER BY d.driver_name;

-- check: 2e_implausible_age [issue]
SELECT season, driver_name, team, age_at_season_start, wiki_url(driver_key) AS wikipedia
FROM junior_seasons
WHERE age_at_season_start IS NULL OR age_at_season_start < 16 OR age_at_season_start > 35
ORDER BY season, driver_name;



-- 3. Team mappings

-- check: 3a_no_team [issue]
SELECT season, driver_name, final_pos, points, wiki_url(driver_key) AS wikipedia
FROM junior_seasons
WHERE team IS NULL
ORDER BY season, driver_name;

-- check: 3b_unusual_team_size [review]
-- Teams run two cars; 3-4 drivers usually means replacements, 1 or 5+ means a mapping problem
SELECT
    js.season,
    js.team,
    COUNT(*) AS drivers,
    string_agg(js.driver_name || ' (' || js.points || ' pts)', ', ' ORDER BY js.points DESC) AS lineup,
    CASE WHEN COUNT(*) = 1 OR COUNT(*) >= 5 THEN 'check' ELSE 'probably replacements' END AS note
FROM junior_seasons js
WHERE js.team IS NOT NULL
GROUP BY js.season, js.team
HAVING COUNT(*) <> 2
ORDER BY note, js.season, js.team;

-- check: 3c_team_switchers [review]
SELECT
    e.season,
    js.driver_name,
    string_agg(e.team || ' (rounds ' || COALESCE(NULLIF(e.rounds, ''), '?') || ')', ' -> ' ORDER BY e.entry_order) AS teams,
    js.team AS team_used_for_rating
FROM junior_entries e
JOIN junior_seasons js ON js.season = e.season AND js.driver_key = e.driver_key
WHERE js.n_teams > 1
GROUP BY e.season, js.driver_name, js.team
ORDER BY e.season, js.driver_name;

-- check: 3d_entered_but_not_classified [review]
-- In the entry list but missing from the standings
SELECT e.season, e.team, e.driver_key, e.rounds
FROM junior_entries e
LEFT JOIN junior_results r ON r.season = e.season AND r.driver_key = e.driver_key
WHERE r.driver_key IS NULL
ORDER BY e.season, e.team;



-- 4. Unusual career histories

-- check: 4a_f1_before_junior [review]
SELECT
    ds.driver_name,
    ds.first_f1_season,
    ds.first_junior_season,
    ds.last_junior_season,
    ds.f1_seasons,
    wiki_url(ds.driver_key) AS wikipedia
FROM driver_summary ds
WHERE ds.raced_f1_before_junior
ORDER BY ds.first_f1_season;

-- check: 4b_junior_after_f1_debut [review]
-- Back in GP2/F2 after already starting in F1 (kept in the analysis, but worth knowing)
SELECT
    o.driver_name,
    o.f1_debut_season,
    string_agg(js.season::text, ', ' ORDER BY js.season) AS junior_seasons_after_debut,
    o.outcome
FROM driver_outcomes o
JOIN junior_seasons js ON js.driver_key = o.driver_key AND js.season > o.f1_debut_season
WHERE o.outcome NOT LIKE 'Excluded%'
GROUP BY o.driver_name, o.f1_debut_season, o.outcome
ORDER BY o.f1_debut_season;

-- check: 4c_gaps_in_junior_career [review]
SELECT driver_name, previous_season, season AS returned_in, season - previous_season - 1 AS years_away
FROM (
    SELECT driver_name, season, LAG(season) OVER (PARTITION BY driver_key ORDER BY season) AS previous_season
    FROM junior_seasons
) s
WHERE season - previous_season > 1
ORDER BY years_away DESC, driver_name;

-- check: 4d_unusual_path_to_f1 [review]
-- Long wait after GP2/F2, or a very young / old F1 debut
SELECT
    o.driver_name,
    ds.last_junior_season,
    o.f1_debut_season,
    o.f1_debut_season - ds.last_junior_season AS years_wait,
    o.f1_debut_season - EXTRACT(YEAR FROM ds.dob)::int AS approx_debut_age,
    o.outcome
FROM driver_outcomes o
JOIN driver_summary ds USING (driver_key)
WHERE o.f1_debut_season IS NOT NULL
    AND (o.f1_debut_season - ds.last_junior_season > 2
        OR o.f1_debut_season - EXTRACT(YEAR FROM ds.dob) NOT BETWEEN 18 AND 28)
ORDER BY years_wait DESC;

-- check: 4e_long_junior_careers [review]
SELECT driver_name, junior_seasons, first_junior_season, last_junior_season, best_junior_pos, reached_f1
FROM driver_summary
WHERE junior_seasons >= 5
ORDER BY junior_seasons DESC, driver_name;



-- 5. Junior champions and standings consistency


-- check: 5a_champions [review]
WITH reference(season, expected) AS (
    VALUES
        (2005, 'Nico Rosberg'), (2006, 'Lewis Hamilton'), (2007, 'Timo Glock'),
        (2008, 'Giorgio Pantano'), (2009, 'Nico Hülkenberg'), (2010, 'Pastor Maldonado'),
        (2011, 'Romain Grosjean'), (2012, 'Davide Valsecchi'), (2013, 'Fabio Leimer'),
        (2014, 'Jolyon Palmer'), (2015, 'Stoffel Vandoorne'), (2016, 'Pierre Gasly'),
        (2017, 'Charles Leclerc'), (2018, 'George Russell'), (2019, 'Nyck de Vries'),
        (2020, 'Mick Schumacher'), (2021, 'Oscar Piastri'), (2022, 'Felipe Drugovich'),
        (2023, 'Théo Pourchaire'), (2024, 'Gabriel Bortoleto')
)
SELECT
    js.season,
    js.driver_name AS champion,
    js.team,
    js.points,
    js.age_at_season_start,
    js.season_in_category,
    r.rating,
    o.outcome,
    CASE
        WHEN ref.expected IS NULL THEN 'no reference'
        WHEN norm_name(ref.expected) = norm_name(js.driver_name) THEN 'ok'
        ELSE 'MISMATCH: expected ' || ref.expected
    END AS reference_check
FROM junior_seasons js
LEFT JOIN reference ref ON ref.season = js.season
LEFT JOIN junior_season_ratings r ON r.season = js.season AND r.driver_key = js.driver_key
LEFT JOIN driver_outcomes o ON o.driver_key = js.driver_key
WHERE js.final_pos = 1
ORDER BY js.season;

-- check: 5b_points_out_of_order [issue]
-- A driver classified ahead of someone with more points means a parsing error
SELECT season, final_pos, driver_name, points, prev_driver, prev_points
FROM (
    SELECT
        season, final_pos, driver_name, points,
        LAG(driver_name) OVER w AS prev_driver,
        LAG(points) OVER w AS prev_points
    FROM junior_seasons
    WHERE final_pos IS NOT NULL
    WINDOW w AS (PARTITION BY season ORDER BY final_pos)
) s
WHERE points > prev_points
ORDER BY season, final_pos;

-- check: 5c_position_gaps_or_duplicates [issue]
SELECT
    season,
    COUNT(final_pos) AS classified,
    COUNT(DISTINCT final_pos) AS distinct_positions,
    MAX(final_pos) AS last_position
FROM junior_seasons
GROUP BY season
HAVING COUNT(final_pos) <> COUNT(DISTINCT final_pos) OR COUNT(DISTINCT final_pos) <> MAX(final_pos)
ORDER BY season;


-- 6. Random sample of the remaining drivers (same sample every run)


-- check: 6_random_sample [review]
SELECT
    ds.driver_name,
    ds.nationality,
    ds.dob,
    ds.first_junior_season,
    ds.junior_seasons,
    ds.best_junior_pos,
    (SELECT string_agg(js.season || ' ' || COALESCE(js.team, '?') || ' P' || COALESCE(js.pos_text, '?'), '; ' ORDER BY js.season)
     FROM junior_seasons js WHERE js.driver_key = ds.driver_key) AS junior_career,
    o.outcome,
    wiki_url(ds.driver_key) AS wikipedia
FROM driver_summary ds
JOIN driver_outcomes o USING (driver_key)
WHERE NOT ds.reached_f1
ORDER BY md5(ds.driver_key || 'sample-1')
LIMIT 25;