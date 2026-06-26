# AI Lakehouse – Design Questions

## Q1 - Catalog–Storage Separation

DuckLake splits responsibility between two components: a SQL catalog (`metadata.ducklake`) that stores structural information - table schemas, snapshot history, and a file index - and an object store (RustFS) that holds the actual Parquet data files. These two layers never mix; the catalog contains no row data, and the Parquet files contain no metadata.

The most immediate benefit is scaling. Because the catalog only stores references (URIs and statistics), it stays small regardless of how much data is in the lake. The Parquet files go to object storage, which is cheap and can grow without affecting the catalog's performance. By contrast, a single `.duckdb` file holding both metadata and data eventually becomes a bottleneck - it needs enough disk and memory on one machine to open the whole thing.

Concurrent access is also much cleaner with this separation. A regular DuckDB file uses file-level locking, so multiple clients have to serialize their writes. With DuckLake, the catalog is a SQL database that supports concurrent reads natively, and the Parquet files in RustFS are plain HTTP objects that any number of readers can fetch simultaneously.

There is one meaningful tradeoff. DuckLake uses snapshot isolation rather than row-level locking for consistency - every write produces a new immutable snapshot, and concurrent writers can conflict if they both try to commit from the same parent snapshot. The second writer has to retry. For the batch-oriented workloads a lakehouse is designed for, this is generally acceptable, but it would be a problem for high-frequency concurrent writes.

---

## Q2 - Snapshots, Time Travel, and Rollback

DuckLake never modifies a Parquet file after it is written. When a row is updated, the old file is left untouched and a new Parquet file containing the changed rows is written to RustFS. A new snapshot is then recorded in the catalog pointing to the new file, with the old file marked as no longer visible from that snapshot onward. Every logical update is effectively a delete-plus-insert at the storage level.

Time travel follows naturally from this design. Since old Parquet files are never deleted, reading a previous state is just a matter of telling DuckLake which snapshot to use as the visibility filter. A query like:

```sql
SELECT COUNT(*) FROM silver.coco_annotations AT (VERSION => 18)
```

causes DuckLake to look up which files were live at snapshot 18 and read only those, ignoring everything written afterward. No data reconstruction is needed - the old files are simply re-read directly.

Rollback in DuckLake works through standard SQL transactions rather than a dedicated rollback function. Wrapping a destructive operation in `BEGIN TRANSACTION` and issuing `ROLLBACK` discards the entire operation before any snapshot is written. This is actually cleaner than a post-commit rollback because no record of the bad state ever enters the catalog.

The main cost of retaining all snapshots is storage growth. Every insert, update, or delete appends new Parquet files without removing old ones. In a production environment with frequent updates, the accumulated files can grow well beyond the size of the current logical table. Compaction and snapshot expiry would need to be run periodically to reclaim space.

---

## Q3 - Data Quality Without Constraints

DuckLake enforces no uniqueness constraints, foreign keys, or NOT NULL requirements. All data quality guarantees have to be built into the transform SQL, which puts more responsibility on the pipeline author but also makes the rules explicit and auditable.

Deduplication in the silver layer uses `ROW_NUMBER() OVER (PARTITION BY <natural key>)`, keeping only the first occurrence of each key. For COCO annotations the natural key is `ann_id`; for VisDrone fragments it is `(clip_name, fragment_id)`. Unlike a database constraint that silently rejects duplicates, this approach makes the deduplication logic visible in the SQL and controllable - you can choose which duplicate wins.

Type enforcement is also handled explicitly. The raw tables store values as ingested, and the silver transforms cast columns to their correct types, round floating-point coordinates for consistency, and clamp counts with `GREATEST(n, 0)` to prevent negative values from propagating into downstream statistics. Rows with null image URIs or zero-area bounding boxes are dropped entirely in the WHERE clause since they cannot represent valid annotations.

The gold layer adds a further round of business-logic filtering - excluding crowd annotations (`iscrowd = 0`) and very small boxes (`area > 100`) that would add noise to a training set. The train/val/test split is computed as `image_id % 10`, which gives a deterministic 80/10/10 partition that is stable across rebuilds.

Schema evolution is also versioned. When a column like `aspect_ratio` is added via `ALTER TABLE ... ADD COLUMN`, DuckLake records a new snapshot for the structural change. Queries using time travel against earlier snapshots will not see the new column; queries against the current snapshot will. This gives a full audit trail of schema changes without any manual tracking.

---

## Q4 - Tracing an INSERT to Bytes on Disk

Consider `INSERT INTO raw.coco_annotations SELECT * FROM read_parquet('...')`.

The DuckDB query engine first reads the source Parquet from the local staging path into memory. At this point nothing has reached RustFS yet.

The DuckLake extension intercepts the write and serializes the in-memory rows into a new Parquet file, uploading it to `s3://lakehouse/<table-uuid>/<snapshot-uuid>.parquet`. Once written, this file is never modified.

DuckLake then records a new snapshot in `metadata.ducklake` - a row containing the snapshot ID, timestamp, affected table, and URI of the new file. The previous snapshot's files remain marked as visible up to that point; the new file is visible from this snapshot onward.

At rest, the state is distributed across three locations:

- `metadata.ducklake` - table schemas, snapshot sequence, and the file-to-snapshot mapping. No actual row data.
- RustFS (`s3://lakehouse/...`) - the row bytes in columnar Parquet format, immutable after upload.
- `/data/local/` - the intermediate Parquet written by the Python ingestion scripts as a hand-off point; this is not part of the catalog and can be deleted after ingestion.

In-process DuckDB memory is released once the transaction commits.

---

## Q5 - Why a SQL Database for the Catalog?

Formats like Apache Iceberg and Delta Lake store their metadata - file lists, snapshot history, statistics - as JSON or Avro files directly in object storage alongside the data. DuckLake puts the catalog in a SQL database instead. This is not a minor implementation detail; it changes how several core operations work.

The clearest benefit is atomic writes. Recording a new snapshot requires updating the file list, incrementing a version counter, and writing statistics. In a SQL database this happens in a single transaction - either everything commits or nothing does. With file-based catalogs, a crash mid-write can leave the metadata in an inconsistent state that requires repair tooling to fix.

Point-in-time lookups are also more efficient. Finding which files were live at snapshot N is a single indexed SQL query. In a file-based catalog the equivalent operation may require deserializing hundreds of manifest files.

The main downside is operational. When every metadata artifact is in object storage there is no external dependency to manage - the catalog and data are in the same place. A SQL catalog is a separate service that must be kept running and backed up. If `metadata.ducklake` is lost or corrupted, the Parquet files in RustFS are still physically present but inaccessible through DuckLake.

For this project running on a single machine, the SQL catalog is the simpler and more capable choice. The operational concerns become real only at production scale with multiple writers and availability requirements.

---

## Q6 - Storing URIs Instead of Bytes, and the Fragment Index

Storing image or video bytes directly in a DuckLake table would undermine the entire columnar format. A columnar store is designed to scan many narrow rows efficiently. A single JPEG column would force the query engine to transfer megabytes of pixel data per row even for queries that only filter on metadata like category or bounding box size. The format is simply not built for this.

The solution is to store each image or video clip in RustFS as a standalone object and keep only its URI in the DuckLake table along with the scalar metadata that makes it queryable: dimensions, category labels, bounding boxes, timestamps. The query engine only ever sees strings and numbers. When a downstream data loader needs the actual pixel bytes, it reads the URI from the query result and fetches the object directly from RustFS, completely bypassing the catalog layer.

The fragment index addresses a specific problem with video. A VisDrone clip can have thousands of frames, and scanning all of them to find the densest segments would require decoding the entire video. Instead, per-segment statistics are computed at ingest time - detection counts by category for every 50-frame chunk - and stored in `silver.visdrone_fragments` as a normal DuckLake table.

This allows a query like:

```sql
SELECT clip_uri, fragment_id, start_frame, end_frame, n_objects
FROM silver.visdrone_fragments
WHERE n_objects > 20
ORDER BY n_objects DESC
LIMIT 100;
```

to run over a few hundred rows of integers and return results in milliseconds. The data loader then fetches only those specific frame ranges from RustFS rather than entire clips. In this project, fragment 7 (frames 350–399) had 6,954 object annotations - the busiest segment by a wide margin - which would have been very slow to identify by scanning the raw data.

Because the fragment index is a DuckLake table, it is versioned along with everything else. If the detection statistics are recomputed with a better model, a new snapshot is recorded and time travel can be used to compare the old and new fragment rankings directly.
