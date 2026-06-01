# Production Deployment

> Agent: **Release**.
> Goal: a *boring* prod deployment — same shape as dev, gated by tests and a human.

---

## 1. Promotion Model

```
feature branch ─► PR ─► main ─► tag (v0.x.y)
                        │           │
                        │           └─► cd-prod workflow (manual approval)
                        │
                        └─► cd-dev workflow (auto)
```

- **Dev** auto-applies on every merge to `main`.
- **Prod** applies only when a semver tag is pushed *and* a human approves the apply step in GitHub Environments.

## 2. Release Artefacts

A tag (`v0.3.0`) produces:

| Artefact                                   | Source                                | Consumed by             |
|--------------------------------------------|---------------------------------------|-------------------------|
| `shared-0.3.0-py3-none-any.whl`            | `glue/` packaging                     | Glue jobs `--extra-py-files` |
| `glue/pyspark/transform_kpis.py@v0.3.0`    | `glue/pyspark/` source                | Glue PySpark job        |
| `glue/python_shell/*.py@v0.3.0`            | `glue/python_shell/` source           | Glue Python Shell jobs  |
| `step_functions/pipeline.asl.json@v0.3.0`  | `step_functions/` source              | Terraform `templatefile` |
| `ui/` (Streamlit app)                      | `ui/` source                          | Run locally or Streamlit Community Cloud |
| Terraform plan (saved against prod)        | CI                                    | `terraform apply`       |

All artefacts are uploaded to `s3://musicstream-prod-scripts/releases/v0.3.0/` *first*, then Terraform points the Glue jobs at that prefix. This means a rollback is a Terraform variable change, not a redeploy.

## 3. Deployment Steps (prod)

1. **Tag.** `git tag v0.3.0 && git push --tags`.
2. **CI builds** the wheel, uploads to `s3://musicstream-prod-scripts/releases/v0.3.0/`.
3. **CI runs `terraform plan`** against prod with `release_version = "v0.3.0"`.
4. Plan posted as a check; **human approves** in the `prod` GitHub Environment.
5. **CI runs `terraform apply`**.
6. **Post-deploy smoke** uploads a synthetic file to `prod-raw/streams/yyyy=2099/...`, waits for the SM execution to succeed, queries DynamoDB.
7. **Rollback gate** ready: if smoke fails, CI does *not* mark the release green.

## 4. Rollback

Two flavours:

- **Code-only rollback** (Glue script regression):
  ```bash
  terraform -chdir=infra/envs/prod apply -var "release_version=v0.2.4"
  # No data migration; Glue jobs immediately point back to the older scripts.
  ```
- **Schema/infra rollback** (DynamoDB or Step Functions change):
  - `terraform apply` of the prior tag's plan.
  - If a DynamoDB table was destructively altered, restore from PITR.
  - This is *invasive*; the team owes a post-mortem.

PITR window: 35 days on all KPI tables.

## 5. Pre-Deploy Checklist

- [ ] All CI jobs green on the tagged commit.
- [ ] `decision.md` updated if behaviour changed.
- [ ] `CHANGELOG.md` lines for the tag.
- [ ] Schema migration script attached if any DynamoDB change.
- [ ] `terraform plan` reviewed and *expected*.
- [ ] On-call notified.

## 6. Post-Deploy Validation

- Dashboards green for 15 min after deploy.
- No new entries in `quarantine/prod-quarantine/`.
- Smoke test executed; KPI written.
- `aws dynamodb describe-table` on each table — `TableStatus == ACTIVE`.

## 7. Day-2 Operations

| Task                                | Cadence       | Owner    |
|-------------------------------------|---------------|----------|
| Review quarantine bucket            | Daily         | Ops      |
| Review CloudWatch dashboard         | Daily         | Ops      |
| Open Streamlit UI, spot-check KPIs  | Daily         | Ops/Analyst |
| Cost-anomaly check (DPU-hours, DDB) | Weekly        | Ops      |
| Reference data refresh              | On-demand     | Engineer |
| Streamlit + `ui/requirements.txt` upgrade | Quarterly | Engineer |
| Dependency upgrade (Glue version, providers) | Quarterly | Engineer |
| DR test (restore PITR to a sandbox) | Quarterly     | Engineer |

## 8. Capacity Planning

After 30 days of prod traffic:

- Read CloudWatch metrics for `ConsumedReadCapacity` and `ConsumedWriteCapacity` on each KPI table.
- If steady-state and predictable, switch to provisioned capacity with auto-scaling (likely 7× cost reduction).
- If DPU-hours on `transform_kpis` exceed budget, evaluate Glue Flex execution class for non-urgent runs (50% discount).

## 9. v2 Backlog (deliberately deferred)

- Kinesis-based true streaming ingestion.
- Iceberg table format on raw to support time-travel queries.
- Small-file coalescer Lambda.
- Cross-region replication for the archive bucket.
- Lake Formation fine-grained access.
- ML-derived KPIs (genre recommendation, user-cohort behaviour).

## 10. Hand-off

End of relay. The pipeline is in production and self-healing. The next stick to be picked up is *operations*, governed by the day-2 table above.
