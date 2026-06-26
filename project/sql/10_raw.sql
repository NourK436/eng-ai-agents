-- ============================================================
-- 10_raw.sql
-- Land COCO annotations and VisDrone fragment index in the
-- raw layer.  Heavy media bytes are written to RustFS by the
-- Python ingestion notebooks; only URIs and metadata live here.
-- ============================================================

USE lake;

-- ------------------------------------------------------------
-- COCO: one row per annotation (bounding box / caption / seg)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.coco_annotations (
    image_id      BIGINT,
    image_uri     VARCHAR,        -- s3://lakehouse/assets/coco/images/<file>
    file_name     VARCHAR,
    width         INTEGER,
    height        INTEGER,
    ann_id        BIGINT,
    category_id   INTEGER,
    category_name VARCHAR,
    supercategory VARCHAR,
    bbox_x        DOUBLE,
    bbox_y        DOUBLE,
    bbox_w        DOUBLE,
    bbox_h        DOUBLE,
    area          DOUBLE,
    iscrowd       INTEGER,
    caption       VARCHAR         -- NULL when row comes from detection split
);

-- COCO categories lookup
CREATE TABLE IF NOT EXISTS raw.coco_categories (
    category_id   INTEGER,
    name          VARCHAR,
    supercategory VARCHAR
);

-- ------------------------------------------------------------
-- VisDrone: fragment index (one row per short video chunk)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.visdrone_fragments (
    clip_name     VARCHAR,        -- e.g. "uav0000013_00000_v"
    clip_uri      VARCHAR,        -- s3://lakehouse/assets/visdrone/clips/<clip_name>.mp4
    fragment_id   INTEGER,
    start_frame   INTEGER,
    end_frame     INTEGER,
    start_time    DOUBLE,         -- seconds
    end_time      DOUBLE,
    n_objects     INTEGER,        -- total detections in this fragment
    n_pedestrian  INTEGER,
    n_car         INTEGER,
    n_truck       INTEGER,
    n_bicycle     INTEGER,
    n_other       INTEGER
);

-- VisDrone per-frame annotations
CREATE TABLE IF NOT EXISTS raw.visdrone_annotations (
    clip_name     VARCHAR,
    fragment_id   INTEGER,
    frame_index   INTEGER,
    ann_id        INTEGER,
    bbox_left     INTEGER,
    bbox_top      INTEGER,
    bbox_width    INTEGER,
    bbox_height   INTEGER,
    score         INTEGER,
    category_id   INTEGER,
    category_name VARCHAR,
    truncation    INTEGER,
    occlusion     INTEGER
);
