# Security

> Agent: **Security**.
> Goal: least-privilege, encryption everywhere, no human credentials in CI.

---

## 1. Identity Model

- **Glue job execution role — PySpark** (`glue_pyspark_role`)
  - `s3:GetObject` on `raw/`, `reference/`, `scripts/`
  - `s3:PutObject` / `DeleteObject` on `clean/` prefix of `raw/`, and the KPI parquet bucket
  - `glue:GetTable`, `glue:GetPartitions` on the catalog
  - `logs:*` on its own log group
  - `cloudwatch:PutMetricData` (namespace `MusicStream/ETL`)

- **Glue job execution role — Python Shell** (`glue_python_shell_role`)
  - Superset on validation paths
  - `dynamodb:BatchWriteItem`, `dynamodb:DescribeTable` on the three KPI tables (resource-scoped, no wildcards)

- **Step Functions role** (`sfn_role`)
  - `glue:StartJobRun` on the two jobs (resource-scoped)
  - `glue:GetJobRun`, `glue:GetJobRuns`, `glue:BatchStopJobRun`
  - `lambda:InvokeFunction` on the validator Lambda (resource-scoped)
  - `s3:CopyObject`, `s3:DeleteObject` on raw/archive/quarantine
  - `sns:Publish` on the `etl-ops` topic
  - **No** `states:*` — `states:StartExecution`/`DescribeExecution`/`StopExecution` are scoped to the SM ARN (D-20).

- **EventBridge role** (`eventbridge_role`)
  - `states:StartExecution` on the state machine
  - Permission to write to the DLQ

No role has `*` in `Resource` and no role has a wildcard in `Action` beyond service-prefix shortcuts that boto3 expects (e.g. none — every action is explicit). CI lints policies with `tflint` + `checkov` and SAST via Snyk Code / `semgrep` (D-21).

## 2. Encryption

| Layer            | Mechanism            |
|------------------|----------------------|
| S3 buckets       | SSE-KMS, project-owned CMK |
| DynamoDB         | KMS CMK              |
| CloudWatch Logs  | KMS CMK              |
| Terraform state  | SSE-KMS              |
| SNS topic        | KMS CMK              |
| SQS DLQs         | KMS CMK              |
| In-flight        | TLS — implicit for all AWS service calls |

Key rotation: annual, AWS-managed for the CMKs.

## 3. Network Posture

All AWS service calls happen over the public AWS endpoints from Glue's managed network. **VPC endpoints** (S3 Gateway, DynamoDB Gateway) are a deferred optimisation if data egress charges grow material.

## 4. PII Considerations

The dataset contains `user_id`, `user_name`, `user_age`, `user_country`. Treat as PII:

- KPI tables only store aggregates — never PII.
- Logs never echo `user_name`, `user_country`. The Python Shell jobs strip these fields *before* any log call.
- Reference data bucket has its own bucket policy denying read to anything but the Glue PySpark role.

## 5. Secrets

No external API keys at v1. If added later (e.g. Slack notification webhook), they go in AWS Secrets Manager, fetched at job start, never in `default_arguments`.

## 6. CI/CD Auth

GitHub Actions assumes an OIDC IAM role (`gha-etl-deploy`) — no long-lived access keys. The role has `terraform plan` rights everywhere and `terraform apply` rights only on `dev` automatically; `prod` apply requires a human approval gate.

## 7. Auditing

- CloudTrail organization trail on (covers IAM, KMS).
- S3 server-access logging enabled to a dedicated `${project}-${env}-access-logs` bucket.
- DynamoDB streams *off* at v1 (no consumer); revisit if change-data-capture is needed.

## 8. Hand-off

- **Next agent:** Testing — needs to know that fixtures must not contain real PII (use synthetic names).

---

## 9. Revisions from `.ai/review.md`

- **IAM wildcards removed** (D-20). Every `Action: "*"` and overbroad service wildcard (e.g. `states:*`, `logs:*`) is replaced with an explicit action list scoped to the smallest necessary set. Reflected in §1 above.
- **New principals** introduced by the revised architecture:
  - `lambda_validator_role` — `s3:GetObject` on `raw/`, `s3:PutObject` on `quarantine/`, `logs:CreateLogStream`/`PutLogEvents` on its log group, `sns:Publish` on `etl-ops`.
  - `lambda_trigger_role` — `sqs:ReceiveMessage`/`DeleteMessage`/`GetQueueAttributes` on the buffer queue, `states:StartExecution` on the SM ARN.
  - `sqs_buffer_dlq` — KMS CMK encryption, redrive policy.
- **SAST step (D-21).** CI runs Snyk Code (or `semgrep --config p/python`) on `glue/`, `lambda/`, and any new Python sources. Findings block merge.
- **PII discipline restated.** With the new Lambda + trigger Lambda in scope, the "never log `user_name`/`user_country`" rule explicitly extends to them. The `logging_utils` helper bundled in `glue/shared/` is repackaged so the Lambdas can `import shared.logging_utils` identically.
