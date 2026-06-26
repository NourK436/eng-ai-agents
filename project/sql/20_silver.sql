-- ============================================================
-- 20_silver.sql
-- raw → silver transforms: type fixes, deduplication, missing-
-- value handling, and at least one schema evolution example.
-- ============================================================

USE lake;

-- ------------------------------------------------------------
-- silver.coco_annotations
-- Clean types, drop rows with null image_uri or bbox, dedupe
-- on ann_id (DuckLake has no UNIQUE constraint, so we do it
-- explicitly with ROW_NUMBER).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.coco_annotations AS
SELECT
    image_id,
    image_uri,
    file_name,
    CAST(width  AS INTEGER)  AS width,
    CAST(height AS INTEGER)  AS height,
    ann_id,
    category_id,
    TRIM(category_name)      AS category_name,
    TRIM(supercategory)      AS supercategory,
    ROUND(bbox_x, 4)         AS bbox_x,
    ROUND(bbox_y, 4)         AS bbox_y,
    ROUND(bbox_w, 4)         AS bbox_w,
    ROUND(bbox_h, 4)         AS bbox_h,
    ROUND(area,   4)         AS area,
    COALESCE(iscrowd, 0)     AS iscrowd,
    caption
FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY ann_id ORDER BY ann_id) AS rn
    FROM raw.coco_annotations
    WHERE image_uri IS NOT NULL
      AND bbox_w    > 0
      AND bbox_h    > 0
) deduped
WHERE rn = 1;

-- Schema evolution example: add an aspect_ratio column after the
-- initial table is already snapshotted.
ALTER TABLE silver.coco_annotations
    ADD COLUMN IF NOT EXISTS aspect_ratio DOUBLE;

UPDATE silver.coco_annotations
SET aspect_ratio = ROUND(bbox_w / NULLIF(bbox_h, 0), 4);

-- ------------------------------------------------------------
-- silver.coco_categories (deduplicated lookup)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.coco_categories AS
SELECT DISTINCT
    category_id,
    TRIM(name)          AS name,
    TRIM(supercategory) AS supercategory
FROM raw.coco_categories
WHERE category_id IS NOT NULL
ORDER BY category_id;

-- ------------------------------------------------------------
-- silver.visdrone_fragments
-- Fix types, clamp negative counts to 0, dedupe on
-- (clip_name, fragment_id).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.visdrone_fragments AS
SELECT
    clip_name,
    clip_uri,
    fragment_id,
    start_frame,
    end_frame,
    ROUND(start_time, 6)         AS start_time,
    ROUND(end_time,   6)         AS end_time,
    GREATEST(n_objects,    0)    AS n_objects,
    GREATEST(n_pedestrian, 0)    AS n_pedestrian,
    GREATEST(n_car,        0)    AS n_car,
    GREATEST(n_truck,      0)    AS n_truck,
    GREATEST(n_bicycle,    0)    AS n_bicycle,
    GREATEST(n_other,      0)    AS n_other,
    -- derived: fraction of fragment with more than 10 objects
    CASE WHEN n_objects > 10 THEN true ELSE false END AS is_busy
FROM (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY clip_name, fragment_id
               ORDER BY clip_name
           ) AS rn
    FROM raw.visdrone_fragments
    WHERE clip_uri IS NOT NULL
) deduped
WHERE rn = 1;

-- Schema evolution: add duration_seconds after first snapshot
ALTER TABLE silver.visdrone_fragments
    ADD COLUMN IF NOT EXISTS duration_seconds DOUBLE;

UPDATE silver.visdrone_fragments
SET duration_seconds = ROUND(end_time - start_time, 6);

-- ------------------------------------------------------------
-- silver.visdrone_annotations
-- Dedupe on (clip_name, frame_index, ann_id), drop zero-area
-- boxes.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.visdrone_annotations AS
SELECT
    clip_name,
    fragment_id,
    frame_index,
    ann_id,
    bbox_left,
    bbox_top,
    bbox_width,
    bbox_height,
    COALESCE(score,    0)  AS score,
    category_id,
    TRIM(category_name)    AS category_name,
    COALESCE(truncation,0) AS truncation,
    COALESCE(occlusion, 0) AS occlusion
FROM (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY clip_name, frame_index, ann_id
               ORDER BY ann_id
           ) AS rn
    FROM raw.visdrone_annotations
    WHERE bbox_width  > 0
      AND bbox_height > 0
) deduped
WHERE rn = 1;
