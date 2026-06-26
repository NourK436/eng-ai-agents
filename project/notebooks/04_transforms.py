# Run raw -> silver -> gold SQL transforms and demonstrate DuckLake
# version control: snapshots, time travel, and transaction rollback.
#
# Run: docker compose exec lab python notebooks/04_transforms.py

import duckdb

con = duckdb.connect()
con.execute(open("sql/00_attach.sql").read())
con.execute("USE lake;")

print("=== Running silver transforms ===")
con.execute(open("sql/20_silver.sql").read())

snaps = con.sql("FROM lake.snapshots()").fetchdf()
print(f"Snapshots after silver: {len(snaps)}")
silver_snap = int(snaps.iloc[-1]["snapshot_id"])
print(f"Latest snapshot id = {silver_snap}")

print("\n=== Running gold transforms ===")
con.execute(open("sql/30_gold.sql").read())

snaps = con.sql("FROM lake.snapshots()").fetchdf()
gold_snap = int(snaps.iloc[-1]["snapshot_id"])
print(f"Snapshots after gold: {len(snaps)}  (latest id = {gold_snap})")

print("\n=== COCO crowded-scene query ===")
crowded = con.sql("""
    SELECT image_uri, COUNT(*) AS n_people
    FROM silver.coco_annotations
    WHERE category_name = 'person'
    GROUP BY image_uri
    HAVING COUNT(*) >= 5
    ORDER BY n_people DESC
    LIMIT 10
""").fetchdf()
print(crowded.to_string(index=False))

print("\n=== VisDrone busy-fragment query ===")
busy = con.sql("""
    SELECT clip_uri, fragment_id, start_frame, end_frame, n_objects
    FROM silver.visdrone_fragments
    WHERE n_objects > 20
    ORDER BY n_objects DESC
    LIMIT 20
""").fetchdf()
print(busy.to_string(index=False))

print("\n=== Time travel demo ===")
row_count_now = con.sql("SELECT COUNT(*) AS n FROM silver.coco_annotations").fetchone()[0]
print(f"Row count now: {row_count_now}")

row_count_past = con.sql(f"""
    SELECT COUNT(*) AS n
    FROM silver.coco_annotations AT (VERSION => {silver_snap})
""").fetchone()[0]
print(f"Row count at snapshot {silver_snap}: {row_count_past}")

print("\n=== Transaction rollback demo ===")
good_before = con.sql(
    "SELECT COUNT(*) FROM silver.coco_annotations WHERE bbox_w > 0"
).fetchone()[0]
print(f"Rows with bbox_w > 0 before bad update: {good_before}")

con.execute("BEGIN TRANSACTION;")
con.execute("UPDATE silver.coco_annotations SET bbox_x = 0, bbox_y = 0, bbox_w = 0, bbox_h = 0;")

bad_count = con.sql(
    "SELECT COUNT(*) FROM silver.coco_annotations WHERE bbox_w = 0"
).fetchone()[0]
print(f"Inside transaction - zeroed rows: {bad_count}")

con.execute("ROLLBACK;")

good_after = con.sql(
    "SELECT COUNT(*) FROM silver.coco_annotations WHERE bbox_w > 0"
).fetchone()[0]
print(f"After ROLLBACK - rows with bbox_w > 0: {good_after}  (data restored)")

print("\n=== Snapshot comparison ===")
snaps_final = con.sql("FROM lake.snapshots()").fetchdf()
print(snaps_final[["snapshot_id", "snapshot_time", "schema_version"]].to_string(index=False))

gold_count = con.sql("SELECT COUNT(*) FROM gold.coco_training").fetchone()[0]
print(f"\ngold.coco_training contains {gold_count} rows total")

print("\nAll transforms and version-control demos complete.")
