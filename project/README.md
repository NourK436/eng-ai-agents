# AI Lakehouse Project

> Three-week project: construct a versioned medallion lakehouse with DuckLake over a self-hosted RustFS S3 layer, and move data between local storage and Hugging Face.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Docker + Docker Compose | 24+ |
| ~5 GB free disk space | — |
| Hugging Face account + write token | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |

---

## Repository Layout

```
lakehouse-project/
  docker-compose.yml        # RustFS + Python lab containers
  .env                      # HF_TOKEN (do NOT commit real tokens)
  local-store/              # staging area (host ↔ container hand-off)
  rustfs-data/              # RustFS object data (host-mounted)
  sql/
    00_attach.sql           # extensions + S3 secret + ATTACH DuckLake
    10_raw.sql              # raw layer schema
    20_silver.sql           # raw → silver transforms
    30_gold.sql             # silver → gold ML-ready tables
  notebooks/
    01_setup_bucket.py      # create 'lakehouse' bucket in RustFS
    02_ingest_coco.py       # ingest COCO val2017 from Hugging Face
    03_ingest_visdrone.py   # ingest VisDrone VID validation set
    04_transforms.py        # run SQL transforms + version-control demos
    05_hf_roundtrip.py      # push gold table back to Hugging Face Hub
  rebuild.sh                # full teardown + rebuild from scratch
  REPORT.md                 # design-principle report (6 questions)
  README.md                 # this file
```

---

## Quick Start

### 1. Clone and configure

```bash
git clone <your-repo-url>
cd lakehouse-project
cp .env .env.local           # edit .env with your real HF_TOKEN
```

### 2. Prepare RustFS data directory

RustFS runs as UID 10001 inside Docker. The host mount must be owned by that UID:

```bash
mkdir rustfs-data
mkdir rustfs-logs
mkdir local-store
sudo chown 10001 rustfs-data rustfs-logs
```

### 3. Start containers

```bash
docker compose --env-file .env up -d
```

Wait until RustFS is healthy (the `lab` container waits for it automatically):

```bash
docker compose ps        # both services should show "running"
```

### 4. Create the S3 bucket

```bash
docker compose exec lab python notebooks/01_setup_bucket.py
```

You can also do this through the RustFS web console at **http://localhost:9001**  
(credentials: `rustfsadmin` / `rustfsadmin`).

### 5. Ingest datasets

```bash
# COCO val2017 - downloads from cocodataset.org (~825 MB)
# Note: downloaded directly from cocodataset.org rather than Hugging Face because
# the HF-hosted versions use legacy loading scripts that are no longer supported.
docker compose exec lab python notebooks/02_ingest_coco.py

# VisDrone DET val set - downloads from Ultralytics mirror (~70 MB)
docker compose exec lab python notebooks/03_ingest_visdrone.py
```

### 6. Run transforms and version-control demos

```bash
docker compose exec lab python notebooks/04_transforms.py
```

This script:
- Runs `sql/20_silver.sql` (raw → silver, including schema evolution)
- Runs `sql/30_gold.sql` (silver → gold)
- Executes the COCO crowded-scene query
- Executes the VisDrone busy-fragment query
- Demonstrates time travel (`AT (VERSION => N)`)
- Deliberately corrupts data and rolls back

### 7. Push gold table to Hugging Face Hub

Edit `notebooks/05_hf_roundtrip.py` and set `HF_USERNAME` to your account name, then:

```bash
docker compose exec lab python notebooks/05_hf_roundtrip.py
```

The dataset will appear at `https://huggingface.co/datasets/<HF_USERNAME>/coco-gold-lakehouse`.

---

## Full Rebuild from Scratch

The `rebuild.sh` script wipes the catalog and bucket and runs all steps 4–6 in order:

```bash
chmod +x rebuild.sh
./rebuild.sh
```

Run `notebooks/05_hf_roundtrip.py` manually afterward if you want to re-publish to the Hub.

---

## Architecture

```
[Hugging Face Hub]  ─ingest──▶  [local-store/]  ──▶  [RustFS raw/]
                                                            │
                                                    DuckLake catalog
                                                    (metadata.ducklake)
                                                            │
                                                     DuckDB engine
                                                    /      │      \
                                                  raw    silver   gold
                                                                    │
                                               push_to_hub ──▶ [HF Hub]
```

---

## Stack

| Component | Role |
|---|---|
| **RustFS** | S3-compatible object store; holds all Parquet + media bytes |
| **DuckLake** | Table format + catalog; snapshots, time travel, schema evolution |
| **DuckDB** | Query and transform engine |
| **Hugging Face datasets** | Source (COCO, VisDrone) and sink (gold table) |

---

## Graded Deliverables Checklist

- [x] `docker-compose.yml`, `sql/`, `notebooks/`, `rebuild.sh`, `README.md`
- [x] Populated lakehouse: `raw`, `silver`, `gold` for COCO and VisDrone
- [x] Image/video bytes in RustFS; URIs + annotations in DuckLake
- [x] Versioning: snapshots, time-travel query, snapshot comparison, rollback
- [x] Video-fragment query (VisDrone) + COCO crowded-scene query
- [x] HF round-trip: ingest from Hub + gold dataset published back
- [x] 2–3 page report (`REPORT.md`)

---

## References

- [DuckLake documentation](https://ducklake.select)
- [DuckDB S3 / httpfs](https://duckdb.org/docs/stable/core_extensions/httpfs/s3api)
- [RustFS GitHub](https://github.com/rustfs/rustfs)
- [Hugging Face datasets](https://huggingface.co/docs/datasets)
- [COCO dataset on HF](https://huggingface.co/datasets/HuggingFaceM4/COCO)
- [VisDrone dataset](https://github.com/VisDrone/VisDrone-Dataset)
