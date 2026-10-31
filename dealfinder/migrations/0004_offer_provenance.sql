-- Store provenance for licensed rows. `sku` lets jobs re-price a Best Buy item
-- (BestBuySource.lookup_skus); `regular_price` is the store's own "was" price,
-- display-only. The indexes serve the retention purge (oldest rows per source)
-- and the watch re-price job (stalest watches first).
SET LOCAL search_path = dealfinder, extensions, public;

ALTER TABLE dealfinder.offers
    ADD COLUMN sku text,
    ADD COLUMN regular_price double precision;
CREATE INDEX offers_source_fetched ON dealfinder.offers (source, fetched_at);
CREATE INDEX watchlist_last_checked ON dealfinder.watchlist (last_checked_at);
