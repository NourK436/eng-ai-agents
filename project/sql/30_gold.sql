-- ============================================================
-- 30_gold.sql
-- silver → gold: ML-ready feature/label tables for both
-- datasets, plus the video-fragment query demo.
-- ============================================================

USE lake;

-- ------------------------------------------------------------
-- gold.coco_training
-- One row per annotation, deterministic train/val/test split
-- (80/10/10) based on image_id hash so it is reproducible.
-- This is the table that will be pushed to the Hugging Face Hub.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.coco_training AS
SELECT
    a.image_id,
    a.image_uri,
    a.file_name,
    a.ann_id,
    a.category_id,
    a.category_name,
    a.supercategory,
    a.bbox_x,
    a.bbox_y,
    a.bbox_w,
    a.bbox_h,
    a.area,
    a.aspect_ratio,
    a.iscrowd,
    a.caption,
    -- deterministic split
    CASE
        WHEN (a.image_id % 10) < 8 THEN 'train'
        WHEN (a.image_id % 10) < 9 THEN 'validation'
        ELSE                             'test'
    END AS split
FROM silver.coco_annotations a
WHERE a.iscrowd = 0          -- exclude crowd annotations from training
  AND a.area    > 100;       -- exclude tiny boxes

-- Crowded-scene query (graded deliverable)
-- Returns images with >= 5 person annotations, ordered by crowd size.
-- Run this interactively:
--
--   SELECT image_uri, COUNT(*) AS n_people
--   FROM silver.coco_annotations
--   WHERE category_name = 'person'
--   GROUP BY image_uri
--   HAVING COUNT(*) >= 5
--   ORDER BY n_people DESC;

-- ------------------------------------------------------------
-- gold.visdrone_training
-- One row per fragment selected for model training:
-- only busy fragments (n_objects > 5), with per-fragment stats
-- and the clip URI so the data loader can fetch just those bytes.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.visdrone_training AS
SELECT
    f.clip_name,
    f.clip_uri,
    f.fragment_id,
    f.start_frame,
    f.end_frame,
    f.start_time,
    f.end_time,
    f.duration_seconds,
    f.n_objects,
    f.n_pedestrian,
    f.n_car,
    f.n_truck,
    f.n_bicycle,
    f.n_other,
    -- label: dominant class in this fragment
    CASE
        WHEN f.n_pedestrian >= f.n_car
         AND f.n_pedestrian >= f.n_truck
         AND f.n_pedestrian >= f.n_bicycle
        THEN 'pedestrian'
        WHEN f.n_car >= f.n_truck
         AND f.n_car >= f.n_bicycle
        THEN 'car'
        WHEN f.n_truck >= f.n_bicycle
        THEN 'truck'
        ELSE 'bicycle'
    END AS dominant_class,
    CASE
        WHEN (f.fragment_id % 10) < 8 THEN 'train'
        WHEN (f.fragment_id % 10) < 9 THEN 'validation'
        ELSE                                'test'
    END AS split
FROM silver.visdrone_fragments f
WHERE f.n_objects > 5;

-- ------------------------------------------------------------
-- Video-fragment query demo (graded deliverable)
-- Pick the 100 busiest VisDrone fragments for sampling.
-- The data loader then fetches ONLY those byte ranges from
-- RustFS — not the whole clips.
-- Run interactively to confirm:
--
--   SELECT clip_uri, fragment_id, start_frame, end_frame, n_objects
--   FROM silver.visdrone_fragments
--   WHERE n_objects > 20
--   ORDER BY n_objects DESC
--   LIMIT 100;
-- ------------------------------------------------------------
