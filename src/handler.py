import json
import logging
import os

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def store_order(table, order):
    """Record each order ID once, even when SQS redelivers a message."""
    try:
        table.put_item(
            Item=order,
            ConditionExpression="attribute_not_exists(order_id)",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        existing = table.get_item(
            Key={"order_id": order["order_id"]}, ConsistentRead=True
        ).get("Item")
        if existing != order:
            raise ValueError("Conflicting payload for an existing order ID")
        LOGGER.info("Duplicate delivery acknowledged")


def process_batch(event, table):
    failures = []
    for record in event["Records"]:
        try:
            body = json.loads(record["body"])
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            order_id = body.get("order_id")
            amount = body.get("amount_cents")
            if (
                not isinstance(order_id, str)
                or not order_id.strip()
                or len(order_id.encode("utf-8")) > 128
                or type(amount) is not int
                or not 0 < amount <= 100_000_000
            ):
                raise ValueError("Invalid order fields")
            store_order(table, {"order_id": order_id, "amount_cents": amount})
        except Exception as error:
            LOGGER.warning(
                "Record failed: message_id=%s error_type=%s",
                record["messageId"],
                type(error).__name__,
            )
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def lambda_handler(event, context):
    import boto3

    table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return process_batch(event, table)
