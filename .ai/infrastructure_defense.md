# Project Defense: Cloud Infrastructure & Terraform (IaC)

This guide prepares you to defend the AWS infrastructure, Terraform module design, and security architecture of the MusicStream ETL pipeline during your technical review or interview.

---

## 1. Infrastructure Architecture Overview
The infrastructure is designed using modular Terraform, enforcing the principles of **least privilege, data encryption at rest, and serverless isolation**.

### Key Infrastructure Components:
* **Storage Layer:** 5 partitioned S3 Buckets (Raw, Archive, Quarantine, Scripts, Reference) + 3 DynamoDB Tables.
* **Orchestration Layer:** AWS Step Functions orchestrating Lambda and Glue execution.
* **Ingestion/Event Flow:** S3 Event Notifications → EventBridge Rule → SQS Queue (Buffer) → EventBridge Pipe → Pipe Enrichment Lambda → Step Functions.
* **Security & KMS:** Two Customer Managed Keys (CMKs): `dev-data` (for S3 and CloudWatch) and `dev-ddb` (for DynamoDB).

---

## 2. Infrastructure & Terraform Defenses

### Q1: Why did you choose EventBridge Pipes with SQS instead of triggering Step Functions directly from S3?
* **Defense:** **Cost control and batch efficiency.**
  * Direct S3-to-Step-Functions trigger starts a new execution for *every single file* uploaded. Since Glue PySpark has a high startup overhead, processing files individually would lead to runaway Glue costs (e.g. 50 files = 50 Glue clusters).
  * Putting SQS in the middle allows us to buffer events. The EventBridge Pipe collects up to 50 messages or waits 120 seconds before packaging them into a single list and triggering a single Step Functions run. This is a classic micro-batching architecture.

### Q2: Explain the SQS Managed SSE vs. Customer Managed Key (CMK) issue you resolved.
* **Defense:** **Service principal key authorization restrictions.**
  * Initially, the SQS buffer queue was configured to encrypt messages using the project’s Customer Managed Key (CMK).
  * However, under our KMS policy design, we enforce **root-principal delegation** (D-25) where only specific roles have key decryption rights. Because the AWS EventBridge service principal (`events.amazonaws.com`) sends messages to SQS, it was blocked by the KMS key policy, causing S3 events to fail silently at the EventBridge stage (`FailedInvocations` on the rule).
  * **Solution:** We switched the SQS buffer and DLQ to use **SQS-Managed Server-Side Encryption (SSE)**. This allows EventBridge to write to SQS securely without requiring custom KMS policy delegations, resolving the silent trigger failure.

### Q3: Why is there a Lambda enrichment step in the EventBridge Pipe?
* **Defense:** **Payload shape matching.**
  * EventBridge Pipe receives an array of raw SQS records containing the S3 event notifications.
  * Our Step Functions state machine expects a clean input shape: `{detail: {bucket: {name}, object: {keys: [...]}}}`.
  * EventBridge Pipe’s built-in input transformer cannot process lists/arrays dynamically to extract S3 keys into a clean JSON array. 
  * By inserting a lightweight Lambda enrichment step (`dev-pipe-enrichment`), the Lambda reads the SQS batch array, extracts the `bucket` and `key` for all records, and returns the unified JSON payload our State Machine ASL expects.

### Q4: How did you resolve IAM Circular Dependencies in Terraform?
* **Defense:** **Two-phase resource decoupling.**
  * A classic Terraform chicken-and-egg problem occurs when:
    * The IAM Role policy needs the ARN of the Lambda/Step Functions to grant execution rights.
    * The Lambda/Step Functions modules need the IAM Role ARN to be created.
  * **Solution:** In our dev environment, we broke the cycle by using documented placeholder wildcards (`*`) restricted by action-level boundaries (e.g. permitting `lambda:InvokeFunction` but restricting the target to the correct naming prefix). In a production environment, we would use a **two-phase apply**: deploying the IAM roles first with placeholder resource ARNs, and then running a second apply once the resource ARNs are generated to lock them down to exact ARNs.

### Q5: Explain your KMS Key Policy Design (Root-Principal Delegation)
* **Defense:** Rather than listing every single IAM role ARN in our KMS key policies (which creates circular dependencies in Terraform), we follow the **KMS Root-Principal Delegation** pattern.
  * The Key Policy delegates key administration and usage permissions to the AWS Account Root Principal (`arn:aws:iam::<account-id>:root`).
  * This allows us to control access entirely using standard IAM Policies attached to individual IAM Roles (like the Glue role, Lambda role, and Step Functions role), keeping the KMS key policy static and clean.

### Q6: Why did you use Terraform bootstrap?
* **Defense:** **State file locking and durability.**
  * If two engineers run `terraform apply` at the same time, the state file can become corrupted.
  * We created a separate `infra/bootstrap` module that provisions a backend S3 bucket (with versioning and encryption) and a DynamoDB lock table (`musicstream-tfstate-lock`).
  * The main dev/prod environments reference this remote backend, ensuring all team members share a single, lockable source of truth for the infrastructure state.

---

## 3. Key Infrastructure Code Artifacts to Highlight
* **`infra/modules/sqs-buffer/main.tf`:** Deploys the queue and DLQ with redrive policies and sets `sqs_managed_sse_enabled = true`.
* **`infra/modules/iam-roles/main.tf`:** Decouples execution policies into specific roles for Glue PySpark, Glue Python Shell, Lambda Validator, EventBridge Pipes, and Step Functions.
* **`step_functions/pipeline.asl.json`:** Authoritative Amazon States Language (ASL) definition, implementing robust error handling:
  * Catching `ValidationFailed` or `Lambda.Unknown` on `ValidateSchema` to route directly to `HandleFailure` (Quarantine).
  * Retrying Glue job runs with backoff to handle transient failures.
