# Create the 'lakehouse' bucket in RustFS and verify connectivity.
# Run this once before any ingestion:
#   docker compose exec lab python notebooks/01_setup_bucket.py

import boto3
from botocore.exceptions import ClientError

ENDPOINT = "http://rustfs:9000"
ACCESS_KEY = "rustfsadmin"
SECRET_KEY = "rustfsadmin"
BUCKET = "lakehouse"

s3 = boto3.client(
    "s3",
    endpoint_url=ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

# create bucket if it doesn't exist
try:
    s3.head_bucket(Bucket=BUCKET)
    print(f"Bucket '{BUCKET}' already exists.")
except ClientError as e:
    if e.response["Error"]["Code"] in ("404", "NoSuchBucket"):
        s3.create_bucket(Bucket=BUCKET)
        print(f"Created bucket '{BUCKET}'.")
    else:
        raise

resp = s3.list_buckets()
buckets = [b["Name"] for b in resp["Buckets"]]
print("Buckets in RustFS:", buckets)
assert BUCKET in buckets, "Bucket creation failed!"
print("Setup complete.")
