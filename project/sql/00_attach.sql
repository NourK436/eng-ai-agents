-- ============================================================
-- 00_attach.sql
-- Load extensions, configure the RustFS S3 secret, and
-- attach the DuckLake catalog.  Run this at the top of every
-- session before any other SQL.
-- ============================================================

INSTALL ducklake;
LOAD ducklake;
INSTALL httpfs;
LOAD httpfs;

-- S3 secret pointing at the local RustFS container.
-- When connecting from the host (not from inside Docker) change
-- the ENDPOINT to 'localhost:9000'.
CREATE OR REPLACE SECRET rustfs (
    TYPE       s3,
    KEY_ID     'rustfsadmin',
    SECRET     'rustfsadmin',
    ENDPOINT   'rustfs:9000',
    URL_STYLE  'path',
    USE_SSL    false
);

-- Catalog file lives on the local filesystem; Parquet data files
-- go into the 'lakehouse' bucket on RustFS.
ATTACH 'ducklake:metadata.ducklake' AS lake (
    DATA_PATH 's3://lakehouse/'
);

USE lake;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
