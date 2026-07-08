-- good_deals.sql — a dbt-style model (Part 16).
--
-- A view over the frozen-snapshot `products` table that surfaces the honest
-- deals: items priced meaningfully below their same-query median, excluding the
-- too-good-to-be-true outliers the naive median signal is fooled by (spec §2 —
-- the $10.75 Kindle Paperwhite reads 91.7% under median but is a mislisting).
--
-- This is deliberately model-free SQL (the residual guard lives in Python, Part
-- 3/17); the point here is the *pipeline seam*: a warehouse view the orchestrated
-- flow can materialize. In dbt this would carry a `{{ config(materialized=...) }}`
-- and `ref()`s; the flow in flows.py runs it as plain SQL against DuckDB/SQLite
-- over the snapshot rows so it reproduces offline.
--
-- `median_deal_pct` = how far below the same-query median this listing sits
-- (0.72 == 72% under). We keep 0.10 <= median_deal_pct <= 0.90: at least a real
-- 10% discount, but drop anything >90% under (the mislistings). Price must be > 0.

SELECT
    id,
    query,
    category,
    title,
    brand,
    price,
    median_price_at_capture,
    (median_price_at_capture - price) / median_price_at_capture AS median_deal_pct
FROM products
WHERE price > 0
  AND median_price_at_capture > 0
  AND (median_price_at_capture - price) / median_price_at_capture BETWEEN 0.10 AND 0.90
ORDER BY median_deal_pct DESC
