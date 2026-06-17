# MusicStream Architecture Diagram Review

## Review Notes

Overall, the diagram is much easier to follow than the previous compact version. The main left-to-right data flow is clear, the AWS service grouping is intuitive, and the focus is now correctly on the data engineering pipeline rather than peripheral infrastructure.

## What Looks Good

- The high-level sections are well chosen: Data Lake, Event Ingestion, Validation/Transformation/Loading, KPI Serving, and Ops/Security/Network Support.
- The main flow reads naturally from left to right: CSV producers -> Raw S3 -> EventBridge -> SQS -> EventBridge Pipe -> Step Functions -> Lambda -> Glue -> KPI Parquet -> DynamoDB -> Streamlit.
- The diagram gives the data engineering details good priority: schema/date validation, reference joins, daily KPI computation, KPI Parquet, DynamoDB serving tables, quarantine, archive, and DLQ.
- Text size is now readable for a README crop.
- The icon colors and service group boundaries make the architecture feel professional and AWS-native.

## Issues Or Improvements

1. There are stray connector artifacts near the top and bottom of the canvas.
   - At the top, around the Data Lake title, there are pale blue arrow/handle-looking shapes that do not belong to the architecture.
   - At the bottom, there is a small horizontal arrow or connector fragment near the AWS account boundary.
   - These should be removed because they will look accidental in the README.

2. The Step Functions orchestration relationship is slightly ambiguous.
   - The diagram shows Step Functions near Lambda, but it is not visually obvious that Step Functions orchestrates Lambda validation, Glue PySpark transform, Glue Python Shell load, and S3 archival.
   - A technical reviewer may ask whether Lambda directly triggers Glue or whether Step Functions owns the workflow.
   - Better: use a clean control-flow lane from Step Functions to Lambda, Glue PySpark, Glue Python Shell, and Archive S3, or place Step Functions as the orchestration parent above those tasks.

3. The Archive S3 connector appears technically inaccurate.
   - The diagram currently suggests Glue Python Shell sends processed raw files to Archive S3.
   - In the project, archival is a Step Functions S3 copy/delete task after DynamoDB loading.
   - Better: connect Step Functions or an explicit "ArchiveBatch S3 copy/delete" task to Archive S3, not Glue Python Shell directly.

4. The Quarantine S3 connector may be incomplete.
   - Lambda validation can quarantine invalid files, but the Glue transform also receives a quarantine bucket and may produce data-quality failures depending on validation/reference integrity logic.
   - Better: either label Quarantine as "schema/data quality failures" or show both Lambda validation and Glue transform feeding Quarantine S3 if the implementation does both.

5. Raw S3 data access is underrepresented.
   - The Raw S3 -> EventBridge line shows event notification, but Lambda validation and Glue transform also need to read the actual raw S3 objects.
   - Better: add a subtle secondary data-read connector from Raw S3 to Lambda/Glue, or label the Pipe payload as "S3 keys" and the Lambda/Glue side as "read objects from Raw S3".

6. The connectors around Lambda, Glue PySpark, Reference S3, and Scripts S3 are visually crowded.
   - The "valid files", "reference joins", and "job artifacts" labels sit very close to each other.
   - Some lines terminate near the same Glue icon side, making the area feel busier than the rest of the diagram.
   - Better: route Reference S3 and Scripts S3 into Glue from below with separate vertical lanes and keep their labels outside the connector path.

7. CloudWatch and SNS are shown but not connected.
   - This is acceptable if the bottom row is intended as a support legend.
   - If it is meant to show behavior, add light dashed connectors from Step Functions, Lambda, Glue, and SQS DLQ to CloudWatch, then CloudWatch alarms to SNS.
   - At minimum, label the bottom row as "supporting services / not all connectors shown" or keep it clearly as a legend.

8. IAM/KMS and VPC endpoints are also shown as support boxes without connectors.
   - This is fine for a README-level diagram, but the current boxes look like components rather than legend items.
   - Better: label them as "security controls" and "optional network controls" so readers do not expect every connection to be drawn.

9. The EventBridge Pipe label says "batch S3 keys", which is useful, but the batching behavior could be more explicit.
   - Since this is a core project design point, consider making the connector label from SQS to Pipe say "micro-batch S3 object keys".

10. The DynamoDB table detail is good, but it could be easier to scan.
   - "genre_daily, top songs, top genres" is correct, but the line wraps tightly.
   - Better: shorten to "3 KPI tables" on the main label and add the table names in smaller text below if space allows.

## Recommended Priority Fixes

1. Remove the stray top and bottom connector artifacts.
2. Fix Archive S3 so it is connected to Step Functions / ArchiveBatch instead of Glue Python Shell.
3. Clarify Step Functions as the orchestrator for Lambda, Glue transform, Glue load, and archive.
4. Add or label the Raw S3 data-read path so the diagram distinguishes event flow from object reads.
5. Clean the connector crowding around Glue PySpark, Reference S3, Scripts S3, and Quarantine S3.

## Technical Lead Walkthrough

This architecture is a MusicStream data engineering ETL pipeline designed to process streaming activity files that arrive in S3 at irregular intervals.

Starting on the left, CSV producers upload stream files into the Raw S3 bucket under `streams/*.csv`. That bucket emits object-created events into EventBridge. EventBridge filters those events and sends them into an SQS buffer queue, which gives the system a durable intake layer and protects the downstream workflow from irregular arrival patterns. Failed event batches can be moved into the SQS DLQ for later inspection or redrive.

From SQS, EventBridge Pipe batches the S3 object keys and starts a Step Functions execution. Step Functions is the orchestration layer for the pipeline run. It receives the list of S3 keys, creates the run context, and coordinates the validation, transformation, loading, and archival stages.

The first processing stage is Lambda validation. Lambda validates the incoming files for required schema and date constraints. Invalid files or rows are sent toward the Quarantine S3 bucket, while valid file keys continue into the transformation stage.

The main data engineering work happens in the Glue PySpark job. This job reads the valid raw stream files, joins them with reference datasets from Reference S3, and computes the daily KPIs. Those KPIs include genre-level listen counts, unique listeners, total listening time, average listening time, top songs per genre, and top genres per day. The Glue job writes the transformed KPI output as Parquet under the KPI path in S3.

The second Glue job is a Python Shell loader. It reads the KPI Parquet output and reshapes the data for serving in DynamoDB. The results are written into the DynamoDB KPI tables, which serve the dashboard and downstream applications with low-latency lookups.

On the serving side, the Streamlit dashboard queries DynamoDB to show pipeline status and KPI views. This keeps the dashboard separate from the raw processing path and allows the UI to read already-curated serving data rather than scanning S3 directly.

The lower support row captures operational and security services. CloudWatch collects logs, metrics, alarms, and dashboard views, while SNS handles email alerts. IAM roles and KMS encryption support least-privilege access and encrypted storage across Lambda, Glue, EventBridge Pipe, Step Functions, S3, and DynamoDB. The optional VPC stub shows where private subnet routing and S3/DynamoDB endpoints can be introduced if the deployment requires private network access.

The architecture is strong because it separates event intake, orchestration, transformation, serving, and operations. The main improvement I would make before presenting it formally is to make Step Functions' orchestration ownership visually explicit and correct the archive connector so the diagram matches the implemented state machine.
