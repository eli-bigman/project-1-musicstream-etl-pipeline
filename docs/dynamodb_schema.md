# DynamoDB Schema Design

> Agent: **Storage**.
> Input: KPI catalogue (`transformation_logic.md`), access patterns (US4, US5).
> Output: three table designs, sample queries, and the load shape the PySpark output must conform to.

---

## 1. Modelling Principle

DynamoDB rewards designs whose **partition key matches the most common query's filter** and whose **sort key matches the in-partition ordering** required by the consumer.

Our analyst will ask:
- *"Give me everything about genre X on date D."* → partition by date, sort by genre.
- *"What were the top songs in genre X on date D?"* → partition by `(date#genre)`, sort by rank.
- *"What were the top 5 genres on date D?"* → partition by date, sort by rank.

Three queries, three access patterns, three tables (D-03).

## 2. Table Designs

### 2.1 `${env}_genre_daily_kpi`

| Attribute                         | Type | Role |
|-----------------------------------|------|------|
| `date`                            | S    | **PK** — YYYY-MM-DD |
| `genre`                           | S    | **SK** |
| `listen_count`                    | N    |      |
| `unique_listeners`                | N    |      |
| `total_listening_time_ms`         | N    |      |
| `avg_listening_time_per_user_ms`  | N    |      |
| `updated_at`                      | S    | ISO timestamp (idempotency audit) |

**Access patterns**
- *All genres for a date* → `Query (PK=date)`.
- *One genre for a date* → `GetItem (PK=date, SK=genre)`.
- *A genre over a date range* → use a **GSI** with `genre` as PK and `date` as SK (`genre_date_index`).

### 2.2 `${env}_top_songs_daily`

| Attribute       | Type | Role |
|-----------------|------|------|
| `date_genre`    | S    | **PK** — `2024-06-25#rock` (composite to keep ranks together) |
| `rank`          | N    | **SK** — 1, 2, 3 |
| `track_id`      | S    |      |
| `track_name`    | S    |      |
| `plays`         | N    |      |
| `updated_at`    | S    |      |

**Access patterns**
- *Top 3 for genre on date* → `Query (PK=date_genre)` — 3 items, ~1 KB.

### 2.3 `${env}_top_genres_daily`

| Attribute       | Type | Role |
|-----------------|------|------|
| `date`          | S    | **PK** |
| `rank`          | N    | **SK** — 1..5 |
| `genre`         | S    |      |
| `listen_count`  | N    |      |
| `updated_at`    | S    |      |

**Access patterns**
- *Top 5 for date* → `Query (PK=date)`.

## 3. Item Shape (from the loader)

```python
# genre_daily_kpi item
{
  "date": "2024-06-25",
  "genre": "rock",
  "listen_count": 1234,
  "unique_listeners": 456,
  "total_listening_time_ms": 31415926,
  "avg_listening_time_per_user_ms": 68893,
  "updated_at": "2024-06-25T18:34:00Z"
}

# top_songs_daily item
{
  "date_genre": "2024-06-25#rock",
  "rank": 1,
  "track_id": "5SuOikwiRyPMVoIQDJUgSV",
  "track_name": "Comedy",
  "plays": 412,
  "updated_at": "2024-06-25T18:34:00Z"
}

# top_genres_daily item
{
  "date": "2024-06-25",
  "rank": 1,
  "genre": "pop",
  "listen_count": 8421,
  "updated_at": "2024-06-25T18:34:00Z"
}
```

## 4. Capacity & Cost

- **Billing mode:** PAY_PER_REQUEST (D-04).
- **TTL:** not enabled at v1 — KPIs are kept indefinitely for historical comparison. Lifecycle to S3 (Glacier) can be added in v2 if data accumulates.
- **PITR:** enabled — cheap, lets us recover from a bad load.
- **Encryption:** KMS CMK.
- **Deletion protection:** ON.

## 5. Idempotent Load

Each loader uses `batch_writer` with `overwrite_by_pkeys = [PK, SK]`. The same KPI for the same (date, genre) is overwritten on re-run, which matches the determinism of the transform stage.

```python
with table.batch_writer(overwrite_by_pkeys=["date", "genre"]) as bw:
    for item in items_iter():
        bw.put_item(Item=item)
```

Rate-limit safety: the loader respects `ProvisionedThroughputExceededException` with exponential backoff (boto3 standard retry mode).

## 6. Sample Analyst Queries

All examples assume `aws dynamodb` CLI or `boto3.resource("dynamodb")`.

### 6.1 *"Listen count for `rock` on 2024-06-25"*

```bash
aws dynamodb get-item \
  --table-name dev_genre_daily_kpi \
  --key '{"date":{"S":"2024-06-25"},"genre":{"S":"rock"}}' \
  --projection-expression "listen_count,unique_listeners"
```

### 6.2 *"All genre KPIs for 2024-06-25"*

```bash
aws dynamodb query \
  --table-name dev_genre_daily_kpi \
  --key-condition-expression "#d = :d" \
  --expression-attribute-names '{"#d":"date"}' \
  --expression-attribute-values '{":d":{"S":"2024-06-25"}}'
```

### 6.3 *"Top 3 songs in `pop` on 2024-06-25"*

```python
import boto3
ddb = boto3.resource("dynamodb").Table("dev_top_songs_daily")
resp = ddb.query(
    KeyConditionExpression="date_genre = :dg",
    ExpressionAttributeValues={":dg": "2024-06-25#pop"},
    ScanIndexForward=True,  # ranks ascending
)
print(resp["Items"])
```

### 6.4 *"Top 5 genres on 2024-06-25"*

```python
resp = boto3.resource("dynamodb").Table("dev_top_genres_daily").query(
    KeyConditionExpression="#d = :d",
    ExpressionAttributeNames={"#d": "date"},
    ExpressionAttributeValues={":d": "2024-06-25"},
)
```

### 6.5 *"How did `rock` trend over the last 30 days?"* (uses GSI)

```python
resp = boto3.resource("dynamodb").Table("dev_genre_daily_kpi").query(
    IndexName="genre_date_index",
    KeyConditionExpression="genre = :g AND #d BETWEEN :start AND :end",
    ExpressionAttributeNames={"#d": "date"},
    ExpressionAttributeValues={
        ":g": "rock",
        ":start": "2024-05-26",
        ":end": "2024-06-25",
    },
)
```

## 7. What we deliberately did *not* do

- **Single-table design.** Considered, rejected (D-03) — access patterns are disjoint, and analyst usability dominates.
- **Time-series-by-month partitioning.** Overkill at v1 volumes; PK by `date` (string) is cardinality ~365/year — well within DynamoDB hot-partition limits.
- **Storing raw plays in DynamoDB.** That belongs in S3/Athena. DynamoDB stores *only* aggregates.

## 8. Hand-off

- **Next agent:** Reliability agent — to wire idempotent retries and DLQ around the loader.

---

## 9. Revisions from `.ai/review.md` (binding)

Two of the three tables flip their key orientation. The third stands.

### 9.1 `${env}_genre_daily_kpi` — keys swapped

| Attribute | Type | Role (revised) |
|-----------|------|----------------|
| `genre`   | S    | **PK**         |
| `date`    | S    | **SK** — YYYY-MM-DD |
| (other attributes unchanged) | | |

**GSI `date_genre_index`** — PK = `date`, SK = `genre`. Supports the "all genres for a date" pattern at a slightly higher latency, which is acceptable because it is a low-cadence dashboard query.

**Access patterns (revised)**
- *Trend for genre over a date range* → base table `Query (PK=genre, SK BETWEEN :start AND :end)`. **No GSI needed.**
- *One genre on one date* → `GetItem (PK=genre, SK=date)`.
- *All genres for a date* → GSI `Query (PK=date)`.

### 9.2 `${env}_top_songs_daily` — composite SK

| Attribute    | Type | Role (revised) |
|--------------|------|----------------|
| `genre`      | S    | **PK** — e.g. `rock` |
| `date_rank`  | S    | **SK** — zero-padded composite, e.g. `2024-06-25#01` |
| `track_id`, `track_name`, `plays`, `updated_at` | | unchanged |

**Access pattern (revised)**
- *Top 3 for genre on date* → `Query (PK=genre, SK BEGINS_WITH "2024-06-25#")`. Returns 3 items, ranked.

**Rank format note.** Zero-padded (`01`, `02`, `03`) so the lexicographic sort matches the numeric one if the top-N is ever expanded past 9.

### 9.3 `${env}_top_genres_daily` — unchanged

`PK = date, SK = rank`. Five items per day, written once. Inversion gains nothing.

### 9.4 Why the swap

The reviewer cited hot partitions; the *real* reason recorded in `decision.md` D-03-R is **GSI elimination on the dominant analytical query** ("trend for genre X"). At v1 volumes the hot-partition risk is negligible. Future agents should not over-engineer partition keys for throughput problems that do not yet exist.

### 9.5 Revised sample queries

```python
# Trend: "rock over last 30 days" — base table, no GSI
boto3.resource("dynamodb").Table("dev_genre_daily_kpi").query(
    KeyConditionExpression="genre = :g AND #d BETWEEN :start AND :end",
    ExpressionAttributeNames={"#d": "date"},
    ExpressionAttributeValues={":g": "rock", ":start": "2024-05-26", ":end": "2024-06-25"},
)

# All genres for one date — GSI
boto3.resource("dynamodb").Table("dev_genre_daily_kpi").query(
    IndexName="date_genre_index",
    KeyConditionExpression="#d = :d",
    ExpressionAttributeNames={"#d": "date"},
    ExpressionAttributeValues={":d": "2024-06-25"},
)

# Top 3 songs in rock on date
boto3.resource("dynamodb").Table("dev_top_songs_daily").query(
    KeyConditionExpression="genre = :g AND begins_with(date_rank, :p)",
    ExpressionAttributeValues={":g": "rock", ":p": "2024-06-25#"},
)
```

### 9.6 Idempotent loader (revised key list)

```python
# genre_daily_kpi
with table.batch_writer(overwrite_by_pkeys=["genre", "date"]) as bw: ...
# top_songs_daily
with table.batch_writer(overwrite_by_pkeys=["genre", "date_rank"]) as bw: ...
# top_genres_daily
with table.batch_writer(overwrite_by_pkeys=["date", "rank"]) as bw: ...
```
