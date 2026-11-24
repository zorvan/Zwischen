-- Top statements by total execution time (T12).
--
-- Requires pg_stat_statements: shared_preload_libraries=pg_stat_statements
-- (docker-compose.yml sets it), then once per database:
--     CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
-- Reset the window with:  SELECT pg_stat_statements_reset();
--
-- Run:  psql "$DB_URL" -f scripts/top_queries.sql
-- Read-only. Query text is normalized ($1, $2...), so no user data appears.

SELECT
    round(total_exec_time::numeric, 1)            AS total_ms,
    calls,
    round(mean_exec_time::numeric, 2)             AS mean_ms,
    round((100 * total_exec_time
           / NULLIF(sum(total_exec_time) OVER (), 0))::numeric, 1) AS pct,
    rows,
    shared_blks_hit + shared_blks_read            AS blocks,
    left(regexp_replace(query, '\s+', ' ', 'g'), 160) AS query
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_exec_time DESC
LIMIT 10;

-- Indexes never chosen since statistics were last reset. An index that stays
-- at zero scans across a representative window is write cost for nothing.
SELECT
    s.relname        AS table_name,
    s.indexrelname   AS index_name,
    s.idx_scan       AS scans,
    pg_size_pretty(pg_relation_size(s.indexrelid)) AS size
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE NOT i.indisunique AND NOT i.indisprimary
ORDER BY s.idx_scan, pg_relation_size(s.indexrelid) DESC;
