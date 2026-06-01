# File Archival

> Agent: **Reliability** (cont.).
> Goal: every file that enters `raw/` ends up *exactly once* in either `archive/` (success) or `quarantine/` (failure). `raw/` is always empty after the pipeline completes for that file.

---

## 1. State Machine

```
PUT raw/streams/.../file.csv
                │
                ▼
         (pipeline runs)
                │
       ┌────────┴─────────┐
       │ success          │ failure
       ▼                  ▼
archive/streams/.../    quarantine/streams/.../
   file.csv              file.csv
                         file.csv._reason.json
   ← DeleteObject(raw)   ← DeleteObject(raw)
```

Both branches preserve the original partition prefix. The full bucket-relative key in `archive/` is identical to the original key in `raw/`. Same for `quarantine/`.

## 2. Implementation in Step Functions

Two terminal branches in the state machine:

- **`ArchiveFile`** — used on the happy path after `LoadDynamoDB`:
  - `aws-sdk:s3:copyObject` from `raw/...` → `archive/...`
  - `aws-sdk:s3:deleteObject` on `raw/...`
- **`QuarantineFile`** — used by every `Catch` branch:
  - Write `_reason.json` first (so the reason can never be lost even if copy fails).
  - `copyObject` source → `quarantine/...`
  - `deleteObject` on source

Both are idempotent: re-running the copy to the same key is a no-op apart from a new `LastModified`.

## 3. Lifecycle Policies (Terraform)

```hcl
# archive: cheaper over time, eventually purged
resource "aws_s3_bucket_lifecycle_configuration" "archive" {
  bucket = module.data_lake.archive_bucket_name

  rule {
    id     = "tier-and-expire"
    status = "Enabled"

    transition { days = 30  storage_class = "STANDARD_IA" }
    transition { days = 90  storage_class = "GLACIER" }
    transition { days = 365 storage_class = "DEEP_ARCHIVE" }
    expiration { days = 730 }
  }
}

# quarantine: short retention; bad data should be investigated quickly
resource "aws_s3_bucket_lifecycle_configuration" "quarantine" {
  bucket = module.data_lake.quarantine_bucket_name
  rule {
    id     = "purge-after-30-days"
    status = "Enabled"
    expiration { days = 30 }
  }
}
```

## 4. Operator Procedures

- **Re-process a quarantined file.** After fixing the cause: `aws s3 cp s3://quarantine/.../file.csv s3://raw/.../file.csv` — EventBridge fires.
- **Find an archived file by date.** Direct prefix listing: `aws s3 ls s3://archive/streams/yyyy=2024/mm=06/dd=25/`.
- **Restore from Glacier.** `aws s3api restore-object ...` then re-copy to `raw/`.

## 5. Why archive instead of delete

- Reprocessing requires raw data — KPIs are derived; raw is the source of truth.
- Audits (e.g. "show me the file that produced the spike on 2024-06-25") need the original bytes.
- Tier-down to Deep Archive makes 2-year retention cheap (~$1/TB-month).

## 6. Hand-off

- **Next agent:** Security agent — needs to know that archive and quarantine buckets contain user-identifiable data (`user_id`) and so inherit the same KMS/IAM posture as raw.
