# Ingest COCO 2017 validation annotations into the lakehouse.
# Downloads images and annotations directly from cocodataset.org,
# uploads images to RustFS, and lands annotations in raw.coco_annotations.
#
# Run: docker compose exec lab python notebooks/02_ingest_coco.py
# First run takes ~10-20 min. Subsequent runs are fast (files cached).

import os, io, json, zipfile, urllib.request, duckdb, boto3
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

ENDPOINT   = "http://rustfs:9000"
ACCESS_KEY = "rustfsadmin"
SECRET_KEY = "rustfsadmin"
BUCKET     = "lakehouse"
LOCAL_TMP  = "/data/local"
MAX_IMAGES = 500  # set to None to process all 5000 val images

IMAGES_URL = "http://images.cocodataset.org/zips/val2017.zip"
ANNOT_URL  = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"

s3 = boto3.client(
    "s3",
    endpoint_url=ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

def download_if_missing(url, dest):
    if not os.path.exists(dest):
        print(f"Downloading {url} ...")
        urllib.request.urlretrieve(url, dest)
        print(f"  Saved to {dest}")
    else:
        print(f"  Already downloaded: {dest}")

os.makedirs(LOCAL_TMP, exist_ok=True)
images_zip = os.path.join(LOCAL_TMP, "val2017.zip")
annot_zip  = os.path.join(LOCAL_TMP, "annotations_trainval2017.zip")

download_if_missing(IMAGES_URL, images_zip)
download_if_missing(ANNOT_URL,  annot_zip)

# extract annotations
annot_dir  = os.path.join(LOCAL_TMP, "annotations")
annot_file = os.path.join(annot_dir, "instances_val2017.json")
if not os.path.exists(annot_file):
    print("Extracting annotations ...")
    with zipfile.ZipFile(annot_zip) as z:
        z.extractall(LOCAL_TMP)
else:
    print("Annotations already extracted.")

print("Loading instances_val2017.json ...")
with open(annot_file) as f:
    coco = json.load(f)

cat_map   = {c["id"]: c for c in coco["categories"]}
image_map = {img["id"]: img for img in coco["images"]}

ann_list = coco["annotations"]
if MAX_IMAGES:
    seen, filtered = set(), []
    for ann in ann_list:
        seen.add(ann["image_id"])
        filtered.append(ann)
        if len(seen) >= MAX_IMAGES:
            break
    ann_list = filtered
    image_ids_needed = seen
else:
    image_ids_needed = {a["image_id"] for a in ann_list}

print(f"Processing {len(image_ids_needed)} images ({len(ann_list)} annotations) ...")

uploaded = set()
print("Extracting + uploading images to RustFS ...")
with zipfile.ZipFile(images_zip) as z:
    members = {os.path.basename(n): n for n in z.namelist() if n.endswith(".jpg")}
    for img_id in tqdm(image_ids_needed):
        img_info  = image_map[img_id]
        file_name = img_info["file_name"]
        if file_name in uploaded:
            continue
        s3_key = f"assets/coco/images/{file_name}"
        member  = members.get(file_name)
        if member:
            with z.open(member) as f:
                s3.upload_fileobj(f, BUCKET, s3_key)
        uploaded.add(file_name)

print(f"Uploaded {len(uploaded)} images.")

rows = []
for ann in ann_list:
    img_id    = ann["image_id"]
    img_info  = image_map.get(img_id, {})
    file_name = img_info.get("file_name", f"{str(img_id).zfill(12)}.jpg")
    cat_id    = ann.get("category_id")
    cat_info  = cat_map.get(cat_id, {})
    bbox      = ann.get("bbox", [None, None, None, None])

    rows.append({
        "image_id":      int(img_id),
        "image_uri":     f"s3://{BUCKET}/assets/coco/images/{file_name}",
        "file_name":     file_name,
        "width":         int(img_info.get("width",  0)),
        "height":        int(img_info.get("height", 0)),
        "ann_id":        int(ann["id"]),
        "category_id":   int(cat_id) if cat_id else None,
        "category_name": cat_info.get("name"),
        "supercategory": cat_info.get("supercategory"),
        "bbox_x":        float(bbox[0]) if bbox[0] is not None else None,
        "bbox_y":        float(bbox[1]) if bbox[1] is not None else None,
        "bbox_w":        float(bbox[2]) if bbox[2] is not None else None,
        "bbox_h":        float(bbox[3]) if bbox[3] is not None else None,
        "area":          float(ann.get("area", 0)),
        "iscrowd":       int(ann.get("iscrowd", 0)),
        "caption":       None,
    })

print(f"Built {len(rows):,} annotation rows.")

schema = pa.schema([
    ("image_id",      pa.int64()),   ("image_uri",     pa.string()),
    ("file_name",     pa.string()),  ("width",         pa.int32()),
    ("height",        pa.int32()),   ("ann_id",        pa.int64()),
    ("category_id",   pa.int32()),   ("category_name", pa.string()),
    ("supercategory", pa.string()),  ("bbox_x",        pa.float64()),
    ("bbox_y",        pa.float64()), ("bbox_w",        pa.float64()),
    ("bbox_h",        pa.float64()), ("area",          pa.float64()),
    ("iscrowd",       pa.int32()),   ("caption",       pa.string()),
])
table = pa.Table.from_pylist(rows, schema=schema)
parquet_path = os.path.join(LOCAL_TMP, "coco_annotations_raw.parquet")
pq.write_table(table, parquet_path)
print(f"Saved Parquet: {parquet_path}  ({len(table):,} rows)")

print("Attaching DuckLake and inserting into raw.coco_annotations ...")
con = duckdb.connect()
con.execute(open("sql/00_attach.sql").read())
con.execute("USE lake;")
con.execute(open("sql/10_raw.sql").read())
con.execute(f"INSERT INTO raw.coco_annotations SELECT * FROM read_parquet('{parquet_path}');")

count = con.sql("SELECT COUNT(*) FROM raw.coco_annotations").fetchone()[0]
print(f"raw.coco_annotations now has {count:,} rows.")
print("COCO ingestion complete.")
