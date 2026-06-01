# Final Pre-Build Architectural & Security Review (Doc-Verified)

This review compiles the findings from the **AWS Architecture and Data Engineering Expert** and the **Security and Compliance Expert** subagents. All architectural assumptions and service limitations have been verified against the official AWS service documentation.

---

## 1. Verified AWS Compatibility Constraints

These issues have been verified against AWS documentation to prevent runtime deployment failures.

### 1.1 Glue PySpark Worker Type Constraint (D-24)
* **The Constraint:** Decision `D-24` attempts to use `G.025X` (0.25 DPU) workers for PySpark to save costs. 
* **Doc Validation:** Verified in AWS Glue documentation that the **`G.025X` worker type is exclusively supported for Glue Streaming ETL jobs (`gluestreaming` command)**. It is unsupported for standard batch jobs (`glueetl`).
* **Resolution:** The PySpark `transform_kpis` job must use **`G.1X`** (minimum `number_of_workers = 2`, yielding 2 DPU total) for standard batch processing.

### 1.2 Glue Python Shell Version Limit (Python 3.9 Cap)
* **The Constraint:** The pipeline was planning to share code using Python 3.10+ syntax.
* **Doc Validation:** Verified in AWS Glue documentation that **AWS Glue Python Shell jobs only support Python 3.9 or 3.6 (with 3.6 deprecated)**. Python 3.10, 3.11, or 3.12 are unsupported for Python Shell.
* **Resolution:**
  1. Configure Python Shell jobs to use `python_version = "3.9"` in Terraform.
  2. Ensure the shared utilities under `glue/shared/` are strictly compatible with **Python 3.9** (avoiding match-case, advanced pipe typing, etc.).
  3. The PySpark job (Glue 4.0/5.0) can continue using Python 3.10/3.11.

### 1.3 AWS Glue 5.0 Upgrade (Latest Long-Term Stable)
* **The Recommendation:** The repository originally targeted Glue 4.0.
* **Doc Validation:** AWS Glue 5.0 was released in **December 2024** and supports **Apache Spark 3.5.4** and **Python 3.11**.
* **Resolution:** Upgrade the PySpark ETL job to use **Glue 5.0** (set `glue_version = "5.0"` in Terraform). Update reference documentation links to point to the Spark 3.5.0 API.

### 1.4 KMS Key Policies Service Principal Lockout (D-25)
* **The Constraint:** Decision `D-25` delegates KMS permissions to the account root principal.
* **Doc Validation:** Services like CloudWatch Logs (`logs.<region>.amazonaws.com`) and EventBridge (`events.amazonaws.com`) perform encryption/decryption operations directly. They do not run as IAM roles inside your account, so their permissions **cannot** be delegated via IAM policies. A root-only KMS key policy will lock them out.
* **Resolution:** Add explicit, scoped service principal statements to the SQS and CloudWatch Logs KMS key policies (see Section 5 for the Terraform templates).

### 1.5 Spark Dynamic Partition Overwrite Configuration
* **The Constraint:** Spark defaults to a `static` overwrite mode for partitions.
* **Doc Validation:** Under `static` mode, writing data with `mode("overwrite")` to a partitioned directory wipes out the entire parent folder.
* **Resolution:** Explicitly set the dynamic overwrite property during Spark session creation:
  ```python
  spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")
  ```

---

## 2. Security & Compliance Gaps

These issues represent compliance failures or raw data exposure risks.

### 2.1 Quarantine S3 Bucket PII Exposure
* **The Flaw:** Raw files failing validation land in `quarantine/` and contain raw customer PII (`user_id`, `user_name`, `user_country`). There is no policy restricting read access on the quarantine bucket.
* **The Resolution:** Enforce a strict S3 bucket policy on the quarantine bucket restricting read permissions only to authorized operations roles.

### 2.2 Missing TLS/SSL In-Transit Enforcement
* **The Flaw:** Resource policies for S3, SQS, and SNS do not enforce TLS/SSL (HTTPS) in transit.
* **The Resolution:** Add a `Deny` statement for all non-HTTPS calls using the `aws:SecureTransport = false` condition across all resource policies.

### 2.3 Interface Endpoints for Private VPC Subnets
* **The Flaw:** Decision `D-27` introduces a stub VPC. If Glue or Lambda are moved into the private VPC subnet to achieve a secure network posture, they will lose access to KMS, CloudWatch Logs, and SQS without public routes.
* **The Resolution:** In addition to the free S3 and DynamoDB Gateway Endpoints, provision Interface VPC Endpoints (`com.amazonaws.<region>.<service>`) for KMS, Logs, SQS, and SNS if any compute resources are migrated into the customer VPC.

---

## 3. Data Durability and Ingestion Buffering

* **EventBridge Pipes & SQS Deletion:** Under EventBridge Pipes with SQS $\rightarrow$ Step Functions Standard Workflow target, the pipe uses asynchronous (`FIRE_AND_FORGET`) invocation. The SQS messages are deleted **as soon as the Step Functions `StartExecution` API returns successfully**.
* **Mitigation:** If the Step Functions execution subsequently fails (due to code syntax, AWS service throttling, or permissions), the message is already deleted. S3 raw files must **never be deleted/moved** until the final step of the Step Functions execution (`ArchiveBatch`). A daily reconciliation Lambda should be scheduled to identify any unprocessed files remaining in `raw/streams/` for more than 24 hours.

---

## 4. Standard Code Snippets for Key Fixes

### 4.1 KMS Key Policy with Service Principal Access (Terraform)
```hcl
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_iam_policy_document" "kms_key_policy" {
  # 1. Root Administration & Delegation (Decouples IAM roles)
  statement {
    sid       = "EnableIAMDelegation"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  # 2. CloudWatch Logs Key Policy (Required if CloudWatch Log Group is encrypted)
  dynamic "statement" {
    for_each = var.purpose == "logs" ? [1] : []
    content {
      sid    = "AllowCloudWatchLogs"
      effect = "Allow"
      actions = [
        "kms:Encrypt*",
        "kms:Decrypt*",
        "kms:ReEncrypt*",
        "kms:GenerateDataKey*",
        "kms:Describe*"
      ]
      resources = ["*"]
      principals {
        type        = "Service"
        identifiers = ["logs.${data.aws_region.current.name}.amazonaws.com"]
      }
      condition {
        test     = "ArnLike"
        variable = "kms:EncryptionContext:aws:logs:arn"
        values   = ["arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:*"]
      }
    }
  }

  # 3. EventBridge Pipe writing to encrypted SQS (Required if SQS Queue is encrypted)
  dynamic "statement" {
    for_each = var.purpose == "sqs" ? [1] : []
    content {
      sid    = "AllowEventBridgeToSQS"
      effect = "Allow"
      actions = [
        "kms:GenerateDataKey*",
        "kms:Decrypt"
      ]
      resources = ["*"]
      principals {
        type        = "Service"
        identifiers = ["events.amazonaws.com"]
      }
    }
  }
}
```

### 4.2 SQS SSL In-Transit Enforced Queue Policy (Terraform)
```hcl
resource "aws_sqs_queue_policy" "buffer_policy" {
  queue_url = aws_sqs_queue.buffer.id
  policy    = data.aws_iam_policy_document.sqs_policy.json
}

data "aws_iam_policy_document" "sqs_policy" {
  # Deny all non-SSL transport requests
  statement {
    sid       = "EnforceTLS"
    effect    = "Deny"
    actions   = ["sqs:*"]
    resources = [aws_sqs_queue.buffer.arn]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}
```

### 4.3 VPC Subnet Association & Endpoint Policy (Terraform)
```hcl
resource "aws_route_table_association" "private" {
  count          = var.enabled ? 1 : 0
  subnet_id      = aws_subnet.private[0].id
  route_table_id = aws_route_table.private[0].id
}

resource "aws_vpc_endpoint" "s3" {
  count           = var.enabled ? 1 : 0
  vpc_id          = aws_vpc.this[0].id
  service_name    = "com.amazonaws.${var.region}.s3"
  route_table_ids = [aws_route_table.private[0].id]
  
  # Custom Endpoint Policy restricting exfiltration to other accounts
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "LimitS3AccessToLocalAccount"
        Effect    = "Allow"
        Principal = "*"
        Action    = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource  = [
          "arn:aws:s3:::musicstream-${var.env}-*",
          "arn:aws:s3:::musicstream-${var.env}-*/*"
        ]
      }
    ]
  })
}
```
