# References — Where to Look When Stuck

> **Purpose.** This is the single, curated reading list every agent on the relay consults when the local plan does not answer a question.
> **Rule of use.** Before guessing, *open the link*. Cite what you read in the doc you are editing (filename + section). If the answer is *not* in the official source, escalate to `decision.md`.

---

## 1. AWS Service Documentation

### Step Functions
- **Developer Guide** — https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html
- **Amazon States Language (ASL) spec** — https://states-language.net/spec.html
- **Service integrations (`.sync`, `.waitForTaskToken`)** — https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html
- **Glue integration** — https://docs.aws.amazon.com/step-functions/latest/dg/connect-glue.html
- **Error handling & retries** — https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html
- **Map state (Distributed)** — https://docs.aws.amazon.com/step-functions/latest/dg/concepts-asl-use-map-state-distributed.html

### AWS Glue
- **Developer Guide** — https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html
- **PySpark `awsglue` reference** — https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-python.html
- **Python Shell jobs** — https://docs.aws.amazon.com/glue/latest/dg/add-job-python.html
- **Job parameters (`--default-arguments`)** — https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-etl-glue-arguments.html
- **`getResolvedOptions`** — https://docs.aws.amazon.com/glue/latest/dg/aws-glue-api-crawler-pyspark-extensions-get-resolved-options.html
- **Glue Catalog tables from PySpark** — https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-etl-libraries.html
- **Worker types & DPU sizing** — https://docs.aws.amazon.com/glue/latest/dg/add-job.html#create-job-worker-type
- **Job monitoring** — https://docs.aws.amazon.com/glue/latest/dg/monitor-glue.html

### Amazon DynamoDB
- **Developer Guide** — https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html
- **Best practices (modelling)** — https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/best-practices.html
- **Single-table vs multi-table** — https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-modeling-nosql-B.html
- **`batch_writer` (boto3)** — https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb/service-resource/batch_writer.html
- **On-demand vs provisioned capacity** — https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadWriteCapacityMode.html
- **PITR** — https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/PointInTimeRecovery.html
- **Global Secondary Indexes** — https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GSI.html

### Amazon S3
- **EventBridge notifications** — https://docs.aws.amazon.com/AmazonS3/latest/userguide/EventBridge.html
- **Lifecycle configuration** — https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html
- **SSE-KMS** — https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingKMSEncryption.html
- **Strong read-after-write consistency** — https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html#ConsistencyModel

### AWS Lambda (added per `.ai/review.md`)
- **Developer Guide** — https://docs.aws.amazon.com/lambda/latest/dg/welcome.html
- **Python 3.12 runtime** — https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html
- **Reserved concurrency** — https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html
- **Step Functions Lambda integration** — https://docs.aws.amazon.com/step-functions/latest/dg/connect-lambda.html
- **EventBridge → Lambda + SQS targets** — https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-targets.html

### Amazon SQS (added per `.ai/review.md`)
- **Developer Guide** — https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/welcome.html
- **DLQ + redrive policy** — https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html
- **Long polling** — https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-short-and-long-polling.html
- **Lambda event source mapping for SQS** — https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html
- **`aws_sqs_queue` (Terraform)** — https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sqs_queue

### EventBridge (rules + pipes)
- **Event patterns** — https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-event-patterns.html
- **Input transformer** — https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-transform-target-input.html
- **Targets** — https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-targets.html
- **EventBridge Pipes overview** — https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-pipes.html
- **Pipes SQS source** — https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-pipes-sqs.html
- **Pipes Step Functions target** — https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-pipes-targets.html#eb-pipes-target-sfn
- **`aws_pipes_pipe` (Terraform)** — https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/pipes_pipe
- **Boto3 `adaptive` retry mode** — https://botocore.amazonaws.com/v1/documentation/api/latest/reference/config.html

### CloudWatch
- **Embedded Metric Format (EMF)** — https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format.html
- **Logs Insights query syntax** — https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax.html
- **Alarms** — https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/AlarmThatSendsEmail.html

### IAM
- **Policy reference** — https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies.html
- **Least-privilege guidance** — https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html

## 2. Infrastructure as Code

- **Terraform AWS provider** — https://registry.terraform.io/providers/hashicorp/aws/latest/docs
- **`aws_glue_job`** — https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/glue_job
- **`aws_sfn_state_machine`** — https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sfn_state_machine
- **`aws_dynamodb_table`** — https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/dynamodb_table
- **`aws_cloudwatch_event_rule`** — https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule
- **Remote state in S3** — https://developer.hashicorp.com/terraform/language/settings/backends/s3
- **`templatefile()`** — https://developer.hashicorp.com/terraform/language/functions/templatefile
- **`tflint`** — https://github.com/terraform-linters/tflint
- **`checkov`** — https://www.checkov.io/

## 3. Apache Spark / PySpark

- **PySpark API (3.5, matches Glue 5.0)** — https://spark.apache.org/docs/3.5.0/api/python/index.html
- **Window functions** — https://spark.apache.org/docs/3.5.0/api/python/reference/pyspark.sql/api/pyspark.sql.Window.html
- **`partitionOverwriteMode = dynamic`** — https://spark.apache.org/docs/3.5.0/sql-data-sources-parquet.html
- **Adaptive Query Execution** — https://spark.apache.org/docs/3.5.0/sql-performance-tuning.html#adaptive-query-execution
- **Broadcast joins** — https://spark.apache.org/docs/3.5.0/sql-performance-tuning.html#broadcast-hint-for-sql-queries

## 4. Python Tooling

- **boto3 reference** — https://boto3.amazonaws.com/v1/documentation/api/latest/index.html
- **`pyarrow.parquet`** — https://arrow.apache.org/docs/python/parquet.html
- **`pandas`** — https://pandas.pydata.org/docs/
- **`pydantic` v2** — https://docs.pydantic.dev/2.7/
- **`pytest`** — https://docs.pytest.org/
- **`pytest-spark`** — https://github.com/malexer/pytest-spark
- **`moto` (mock AWS)** — https://docs.getmoto.org/

## 4b. Security Scanning (added per `.ai/review.md` §6)

- **Snyk Code (Python SAST)** — https://docs.snyk.io/scan-with-snyk/snyk-code
- **`semgrep` Python ruleset** — https://semgrep.dev/p/python
- **`checkov` (IaC)** — https://www.checkov.io/
- **`tflint` AWS ruleset** — https://github.com/terraform-linters/tflint-ruleset-aws

## 5. Project Documents (the relay)

| Topic                             | Doc                          |
|-----------------------------------|------------------------------|
| Strategy & objectives             | `master_plan.md`             |
| Senior-engineer decisions         | `decision.md`                |
| Relay conventions & hand-offs     | `agentic_workflow.md`        |
| Repo layout                       | `directory_structure.md`     |
| IaC modules + apply order         | `terraform.md`               |
| State machine + ASL               | `step_functions.md`          |
| Backfill + arrival semantics      | `data_handling.md`           |
| Validation tiers (T1/T2/T3)       | `data_validation.md`         |
| KPI computation in PySpark        | `transformation_logic.md`    |
| Job inventory + sizing            | `glue_jobs.md`               |
| DynamoDB tables + sample queries  | `dynamodb_schema.md`         |
| Retries, quarantine, DLQ          | `error_handling.md`          |
| CloudWatch logs/metrics/alarms    | `logging_monitoring.md`      |
| Archive + lifecycle               | `file_archival.md`           |
| IAM, KMS, PII                     | `security.md`                |
| Test pyramid + CI                 | `testing_strategy.md`        |
| Sprint goals (no timeline)        | `sprint_planning.md`         |
| Promotion, rollback, day-2 ops    | `production_deployment.md`   |

## 6. Source Material

- `Intructions.txt` — original brief at repo root. The contract.
- `data/users/users.csv`, `data/songs/songs.csv`, `data/streams/streams*.csv` — sample dataset; columns recorded in `data_validation.md` §2.

## 7. When to Use This File

| You are about to…                                       | Open this section first |
|---------------------------------------------------------|-------------------------|
| Write an ASL retry block                                | §1 Step Functions       |
| Choose a Glue worker type                               | §1 Glue                 |
| Decide PK/SK for a new access pattern                   | §1 DynamoDB (modelling) |
| Wire an EventBridge rule                                | §1 S3 + §1 EventBridge  |
| Add a custom CloudWatch metric                          | §1 CloudWatch (EMF)     |
| Author a Terraform resource you haven't used            | §2                      |
| Reach for a Spark API you don't remember                | §3                      |
| Add a `moto`-mocked integration test                    | §4                      |
| Reorient after a long break                             | §5 — start at `master_plan.md` |

## 8. Update Policy

This file is **append-only by default**. If a link rots or a better source is found, replace the URL but leave the bullet's intent intact. If a new tool enters the stack (e.g. Iceberg in v2), add it under a new sub-section and reference it from `decision.md`. Never delete a section silently — the telephone skill applies here too.
