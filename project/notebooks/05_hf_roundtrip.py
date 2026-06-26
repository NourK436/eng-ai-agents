# Export gold.coco_training from DuckLake and push it to Hugging Face Hub.
# Requires HF_TOKEN env var (set in .env file) and your HF username below.
#
# Run: docker compose exec lab python notebooks/05_hf_roundtrip.py

import os
import duckdb
import pyarrow.parquet as pq
from datasets import Dataset
from huggingface_hub import login

HF_TOKEN    = os.environ["HF_TOKEN"]
HF_USERNAME = "NouryKen"
REPO_NAME   = f"{HF_USERNAME}/coco-gold-lakehouse"
LOCAL_TMP   = "/data/local"
GOLD_PARQUET = os.path.join(LOCAL_TMP, "coco_gold.parquet")

login(token=HF_TOKEN)
print("Logged in to Hugging Face.")

print("Connecting to DuckLake and exporting gold.coco_training ...")
con = duckdb.connect()
con.execute(open("sql/00_attach.sql").read())
con.execute("USE lake;")

con.execute(f"""
    COPY (SELECT * FROM gold.coco_training)
    TO '{GOLD_PARQUET}' (FORMAT PARQUET);
""")

table = pq.read_table(GOLD_PARQUET)
print(f"Exported {len(table):,} rows to {GOLD_PARQUET}")
print("Schema:", table.schema)

print(f"Pushing to Hub as '{REPO_NAME}' ...")
ds = Dataset.from_parquet(GOLD_PARQUET)
ds.push_to_hub(
    REPO_NAME,
    private=False,
    commit_message="gold COCO training table from DuckLake lakehouse",
)
print(f"Dataset pushed: https://huggingface.co/datasets/{REPO_NAME}")
print("Hugging Face round-trip complete.")
