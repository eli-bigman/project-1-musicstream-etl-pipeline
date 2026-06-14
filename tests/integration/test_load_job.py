"""Integration tests for the DynamoDB load path using moto."""

import os
import sys

import boto3
import pytest

# Ensure moto is used before any boto3 calls.
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "glue"))

from moto import mock_aws

from shared.dynamo_utils import shape_for_dynamo, batch_write, get_ddb_table


@pytest.fixture()
def ddb_tables():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="eu-west-1")

        ddb.create_table(
            TableName="dev_genre_daily_kpi",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "genre", "KeyType": "HASH"},
                {"AttributeName": "date", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "genre", "AttributeType": "S"},
                {"AttributeName": "date", "AttributeType": "S"},
            ],
        )
        ddb.create_table(
            TableName="dev_top_songs_daily",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "genre", "KeyType": "HASH"},
                {"AttributeName": "date_rank", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "genre", "AttributeType": "S"},
                {"AttributeName": "date_rank", "AttributeType": "S"},
            ],
        )
        ddb.create_table(
            TableName="dev_top_genres_daily",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "date", "KeyType": "HASH"},
                {"AttributeName": "rank", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "date", "AttributeType": "S"},
                {"AttributeName": "rank", "AttributeType": "N"},
            ],
        )
        yield ddb


def _genre_daily_items():
    for genre in ["rock", "pop"]:
        yield {
            "genre": genre,
            "listen_date": "2024-06-25",
            "listen_count": 1000,
            "unique_listeners": 400,
            "total_listening_time_ms": 20_000_000,
            "avg_listening_time_per_user_ms": 50000.0,
        }


def _top_songs_items():
    for rank in [1, 2, 3]:
        yield {
            "genre": "rock",
            "listen_date": "2024-06-25",
            "rank": rank,
            "track_id": f"T{rank}",
            "track_name": f"Song {rank}",
            "plays": 400 - rank * 10,
        }


def _top_genres_items():
    for rank in range(1, 6):
        yield {
            "listen_date": "2024-06-25",
            "rank": rank,
            "genre": ["pop", "rock", "hip-hop", "jazz", "electronic"][rank - 1],
            "listen_count": 8000 - rank * 500,
        }


@mock_aws
def test_batch_write_genre_daily(ddb_tables):
    items = [shape_for_dynamo("genre_daily", r) for r in _genre_daily_items()]
    count = batch_write("dev_genre_daily_kpi", "genre_daily", iter(items))
    assert count == 2
    table = get_ddb_table("dev_genre_daily_kpi")
    resp = table.get_item(Key={"genre": "rock", "date": "2024-06-25"})
    item = resp["Item"]
    assert item["listen_count"] == 1000
    assert "user_name" not in item


@mock_aws
def test_batch_write_top_songs(ddb_tables):
    items = [shape_for_dynamo("top_songs_daily", r) for r in _top_songs_items()]
    count = batch_write("dev_top_songs_daily", "top_songs_daily", iter(items))
    assert count == 3
    from boto3.dynamodb.conditions import Key

    table = get_ddb_table("dev_top_songs_daily")
    resp = table.query(
        KeyConditionExpression=Key("genre").eq("rock")
        & Key("date_rank").begins_with("2024-06-25#")
    )
    assert len(resp["Items"]) == 3
    ranks = sorted(item["date_rank"] for item in resp["Items"])
    assert ranks == ["2024-06-25#01", "2024-06-25#02", "2024-06-25#03"]


@mock_aws
def test_batch_write_top_genres(ddb_tables):
    items = [shape_for_dynamo("top_genres_daily", r) for r in _top_genres_items()]
    count = batch_write("dev_top_genres_daily", "top_genres_daily", iter(items))
    assert count == 5
    from boto3.dynamodb.conditions import Key

    table = get_ddb_table("dev_top_genres_daily")
    resp = table.query(KeyConditionExpression=Key("date").eq("2024-06-25"))
    assert len(resp["Items"]) == 5


@mock_aws
def test_idempotent_overwrite(ddb_tables):
    """Writing the same item twice must not duplicate — idempotent."""
    item1 = shape_for_dynamo(
        "genre_daily",
        {
            "genre": "pop",
            "listen_date": "2024-06-25",
            "listen_count": 100,
            "unique_listeners": 50,
            "total_listening_time_ms": 5_000_000,
            "avg_listening_time_per_user_ms": 100000.0,
        },
    )
    item1_updated = {**item1, "listen_count": 200}
    batch_write("dev_genre_daily_kpi", "genre_daily", iter([item1, item1_updated]))
    table = get_ddb_table("dev_genre_daily_kpi")
    resp = table.get_item(Key={"genre": "pop", "date": "2024-06-25"})
    # Last write wins — should be 200, not two items
    assert resp["Item"]["listen_count"] == 200

    # Verify no duplication
    scan = table.scan(
        FilterExpression="genre = :g", ExpressionAttributeValues={":g": "pop"}
    )
    assert scan["Count"] == 1
