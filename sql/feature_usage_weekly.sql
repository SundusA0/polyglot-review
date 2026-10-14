-- Weekly feature usage rollup from server-side product events.
--
-- Grain: one row per ISO week x feature x channel. unique_users is a distinct
-- count within that grain, so it can be compared with Pendo's weekly visitor
-- counts for channel = 'web' but should not be summed across channels (a user
-- who used both web and mobile appears in both rows).
--
-- Written in the ANSI subset that both Databricks SQL and DuckDB accept, so the
-- same file powers the local demo (scripts/generate_synthetic_data.py runs it
-- with DuckDB) and the live warehouse query in the app. On Databricks, point
-- product_events at the right catalog.schema.table.

SELECT
    CAST(DATE_TRUNC('week', event_ts) AS DATE) AS week_start,
    feature_name,
    product_area,
    channel,
    COUNT(*)                                    AS events,
    COUNT(DISTINCT user_id)                     AS unique_users,
    COUNT(DISTINCT account_id)                  AS accounts
FROM product_events
GROUP BY 1, 2, 3, 4
ORDER BY 1, 2, 4;
