import json
import unittest
from types import SimpleNamespace

from src.handler import process_batch


class DuplicateKey(Exception):
    pass


class FakeTable:
    def __init__(self):
        self.items = {}
        self.meta = SimpleNamespace(client=SimpleNamespace(exceptions=SimpleNamespace(
            ConditionalCheckFailedException=DuplicateKey
        )))

    def put_item(self, *, Item, ConditionExpression):
        assert ConditionExpression == "attribute_not_exists(order_id)"
        key = Item["order_id"]
        if key in self.items:
            raise DuplicateKey
        self.items[key] = Item

    def get_item(self, *, Key, ConsistentRead):
        assert ConsistentRead
        return {"Item": self.items[Key["order_id"]]}


def record(message_id, order_id, amount):
    return {"messageId": message_id, "body": json.dumps(
        {"order_id": order_id, "amount_cents": amount}
    )}


class BatchTests(unittest.TestCase):
    def test_duplicate_and_invalid_record(self):
        table = FakeTable()
        event = {"Records": [record("1", "abc", 500), record("2", "abc", 500),
                             record("3", "bad", True), record("4", "abc", 900),
                             record("5", "xyz", 600)]}
        self.assertEqual(process_batch(event, table), {
            "batchItemFailures": [{"itemIdentifier": "3"}, {"itemIdentifier": "4"}]
        })
        self.assertEqual(table.items["abc"]["amount_cents"], 500)
        self.assertEqual(len(table.items), 2)

    def test_retries_only_failed_message(self):
        class FailingTable(FakeTable):
            def put_item(self, *, Item, ConditionExpression):
                if Item["order_id"] == "retry":
                    raise TimeoutError
                super().put_item(Item=Item, ConditionExpression=ConditionExpression)

        table = FailingTable()
        result = process_batch(
            {"Records": [record("1", "ok", 100), record("2", "retry", 100)]}, table
        )
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "2"}]})
        self.assertIn("ok", table.items)
