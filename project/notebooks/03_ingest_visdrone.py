# Ingest VisDrone2019-DET validation set into the lakehouse.
# Downloads from the Ultralytics mirror (public, no login needed, ~70 MB).
# Uploads images to RustFS and builds a fragment index in raw.visdrone_fragments.
#
# Run: docker compose exec lab python notebooks/03_ingest_visdrone.py

import os, glob, zipfile, urllib.request, duckdb, boto3
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

ENDPOINT      = "http://rustfs:9000"
ACCESS_KEY    = "rustfsadmin"
SECRET_KEY    = "rustfsadmin"
BUCKET        = "lakehouse"
LOCAL_TMP     = "/data/local"
FRAGMENT_SIZE = 50  # images per synthetic fragment

VISDRONE_URL = (
    "https://github.com/ultralytics/yolov5/releases/download/v1.0/"
    "VisDrone2019-DET-val.zip"
)

CATEGORY_MAP = {
    0: "ignored", 1: "pedestrian", 2: "people",   3: "bicycle",
    4: "car",     5: "van",        6: "truck",     7: "tricycle",
    8: "awning-tricycle", 9: "bus", 10: "motor",   11: "others",
}

s3 = boto3.client(
    "s3",
    endpoint_url=ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

os.makedirs(LOCAL_TMP, exist_ok=True)
zip_path    = os.path.join(LOCAL_TMP, "VisDrone2019-DET-val.zip")
extract_dir = os.path.join(LOCAL_TMP, "VisDrone2019-DET-val")

if not os.path.exists(zip_path):
    print("Downloading VisDrone DET val (~70 MB) ...")
    urllib.request.urlretrieve(VISDRONE_URL, zip_path)
    print(f"  Saved to {zip_path}")
else:
    print("Already downloaded.")

if not os.path.exists(extract_dir):
    print("Extracting ...")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(LOCAL_TMP)
    print("Done.")
else:
    print("Already extracted.")

images_dir = os.path.join(extract_dir, "images")
annots_dir = os.path.join(extract_dir, "annotations")

image_files = sorted(glob.glob(os.path.join(images_dir, "*.jpg")))
print(f"Found {len(image_files)} images.")

print("Uploading images to RustFS ...")
for img_path in tqdm(image_files):
    fname  = os.path.basename(img_path)
    s3_key = f"assets/visdrone/images/{fname}"
    with open(img_path, "rb") as f:
        s3.upload_fileobj(f, BUCKET, s3_key)

fragment_rows   = []
annotation_rows = []

for frag_id, chunk_start in enumerate(range(0, len(image_files), FRAGMENT_SIZE)):
    chunk     = image_files[chunk_start : chunk_start + FRAGMENT_SIZE]
    clip_name = f"det_val_frag_{frag_id:04d}"
    clip_uri  = f"s3://{BUCKET}/assets/visdrone/images/"

    counts = {k: 0 for k in ["pedestrian","car","truck","bicycle","other"]}
    total  = 0

    for frame_idx, img_path in enumerate(chunk):
        fname    = os.path.basename(img_path)
        ann_file = os.path.join(annots_dir, fname.replace(".jpg", ".txt"))
        if not os.path.exists(ann_file):
            continue
        with open(ann_file) as f:
            for line_no, line in enumerate(f):
                parts = line.strip().split(",")
                if len(parts) < 8:
                    continue
                cat_id   = int(parts[5])
                cat_name = CATEGORY_MAP.get(cat_id, "unknown")
                total += 1
                if cat_name in ("pedestrian", "people"):
                    counts["pedestrian"] += 1
                elif cat_name in ("car", "van"):
                    counts["car"] += 1
                elif cat_name == "truck":
                    counts["truck"] += 1
                elif cat_name in ("bicycle", "motor", "tricycle"):
                    counts["bicycle"] += 1
                else:
                    counts["other"] += 1

                annotation_rows.append({
                    "clip_name":     clip_name,
                    "fragment_id":   frag_id,
                    "frame_index":   frame_idx,
                    "ann_id":        line_no,
                    "bbox_left":     int(parts[0]),
                    "bbox_top":      int(parts[1]),
                    "bbox_width":    int(parts[2]),
                    "bbox_height":   int(parts[3]),
                    "score":         int(parts[4]),
                    "category_id":   cat_id,
                    "category_name": cat_name,
                    "truncation":    int(parts[6]) if len(parts) > 6 else 0,
                    "occlusion":     int(parts[7]) if len(parts) > 7 else 0,
                })

    fps = 30.0
    fragment_rows.append({
        "clip_name":    clip_name,
        "clip_uri":     clip_uri,
        "fragment_id":  frag_id,
        "start_frame":  chunk_start,
        "end_frame":    chunk_start + len(chunk) - 1,
        "start_time":   round(chunk_start / fps, 6),
        "end_time":     round((chunk_start + len(chunk) - 1) / fps, 6),
        "n_objects":    total,
        "n_pedestrian": counts["pedestrian"],
        "n_car":        counts["car"],
        "n_truck":      counts["truck"],
        "n_bicycle":    counts["bicycle"],
        "n_other":      counts["other"],
    })

print(f"Built {len(fragment_rows)} fragment rows, {len(annotation_rows):,} annotation rows.")

frag_schema = pa.schema([
    ("clip_name",pa.string()),   ("clip_uri",   pa.string()),
    ("fragment_id",pa.int32()),  ("start_frame",pa.int32()),
    ("end_frame",pa.int32()),    ("start_time", pa.float64()),
    ("end_time", pa.float64()),  ("n_objects",  pa.int32()),
    ("n_pedestrian",pa.int32()), ("n_car",      pa.int32()),
    ("n_truck",  pa.int32()),    ("n_bicycle",  pa.int32()),
    ("n_other",  pa.int32()),
])
ann_schema = pa.schema([
    ("clip_name",    pa.string()),  ("fragment_id",  pa.int32()),
    ("frame_index",  pa.int32()),   ("ann_id",       pa.int32()),
    ("bbox_left",    pa.int32()),   ("bbox_top",     pa.int32()),
    ("bbox_width",   pa.int32()),   ("bbox_height",  pa.int32()),
    ("score",        pa.int32()),   ("category_id",  pa.int32()),
    ("category_name",pa.string()),  ("truncation",   pa.int32()),
    ("occlusion",    pa.int32()),
])

frag_path = os.path.join(LOCAL_TMP, "visdrone_fragments_raw.parquet")
ann_path  = os.path.join(LOCAL_TMP, "visdrone_annotations_raw.parquet")
pq.write_table(pa.Table.from_pylist(fragment_rows,   schema=frag_schema), frag_path)
pq.write_table(pa.Table.from_pylist(annotation_rows, schema=ann_schema),  ann_path)
print(f"Saved: {frag_path}")
print(f"Saved: {ann_path}")

print("Attaching DuckLake and inserting VisDrone tables ...")
con = duckdb.connect()
con.execute(open("sql/00_attach.sql").read())
con.execute("USE lake;")
con.execute(open("sql/10_raw.sql").read())
con.execute(f"INSERT INTO raw.visdrone_fragments   SELECT * FROM read_parquet('{frag_path}');")
con.execute(f"INSERT INTO raw.visdrone_annotations SELECT * FROM read_parquet('{ann_path}');")

fc = con.sql("SELECT COUNT(*) FROM raw.visdrone_fragments").fetchone()[0]
ac = con.sql("SELECT COUNT(*) FROM raw.visdrone_annotations").fetchone()[0]
print(f"raw.visdrone_fragments:   {fc} rows")
print(f"raw.visdrone_annotations: {ac:,} rows")
print("VisDrone ingestion complete.")
