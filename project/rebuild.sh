#!/usr/bin/env bash
# rebuild.sh
# ----------
# Wipe the lakehouse and rebuild it from scratch.
# Requires: docker compose up -d (containers running).
#
# Usage:
#   chmod +x rebuild.sh
#   ./rebuild.sh

set -euo pipefail

echo "=== Lakehouse rebuild started ==="

# ── 1. Remove old DuckLake catalog file ──────────────────────────────────────
echo "[1/6] Removing old catalog …"
rm -f metadata.ducklake
echo "      Done."

# ── 2. Wipe the RustFS 'lakehouse' bucket ────────────────────────────────────
echo "[2/6] Wiping RustFS bucket …"
docker compose exec lab python - <<'EOF'
import boto3
from botocore.exceptions import ClientError

s3 = boto3.client(
    "s3",
    endpoint_url="http://rustfs:9000",
    aws_access_key_id="rustfsadmin",
    aws_secret_access_key="rustfsadmin",
)

bucket = "lakehouse"

# Delete all objects
try:
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objs:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": objs})
    print(f"  Cleared bucket '{bucket}'.")
except ClientError as e:
    if e.response["Error"]["Code"] in ("NoSuchBucket", "404"):
        print(f"  Bucket '{bucket}' does not exist, will be created.")
    else:
        raise

# Recreate
try:
    s3.head_bucket(Bucket=bucket)
except ClientError:
    s3.create_bucket(Bucket=bucket)
    print(f"  Created bucket '{bucket}'.")
EOF
echo "      Done."

# ── 3. Clear local staging area ───────────────────────────────────────────────
echo "[3/6] Clearing local staging area …"
docker compose exec lab bash -c "rm -f /data/local/*.parquet"
echo "      Done."

# ── 4. Re-ingest COCO ────────────────────────────────────────────────────────
echo "[4/6] Ingesting COCO …"
docker compose exec lab python notebooks/02_ingest_coco.py
echo "      Done."

# ── 5. Re-ingest VisDrone ────────────────────────────────────────────────────
echo "[5/6] Ingesting VisDrone …"
docker compose exec lab python notebooks/03_ingest_visdrone.py
echo "      Done."

# ── 6. Run all transforms ─────────────────────────────────────────────────────
echo "[6/6] Running transforms (silver + gold) and version-control demos …"
docker compose exec lab python notebooks/04_transforms.py
echo "      Done."

echo ""
echo "=== Lakehouse rebuild complete ==="
echo "    Run notebooks/05_hf_roundtrip.py separately to push to Hugging Face."
