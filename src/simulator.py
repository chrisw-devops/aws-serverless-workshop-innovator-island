import datetime as dt
import os
import random

import boto3
from boto3.dynamodb.conditions import Key


TABLE_NAME = os.environ["TABLE_NAME"]
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def handler(_event, _context):
    attractions = table.query(KeyConditionExpression=Key("pk").eq("ATTRACTION")).get("Items", [])
    if not attractions:
        return {"updated": 0}

    for attraction in attractions:
        current_wait = int(attraction.get("waitMinutes", 0))
        current_status = attraction.get("status", "operating")
        next_status = choose_status(current_status)
        next_wait = adjust_wait(current_wait, next_status)

        table.update_item(
            Key={"pk": "ATTRACTION", "sk": attraction["sk"]},
            UpdateExpression="SET waitMinutes = :wait, #status = :status, updatedAt = :updated",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":wait": next_wait,
                ":status": next_status,
                ":updated": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
        )

    return {"updated": len(attractions)}


def choose_status(current_status):
    roll = random.random()
    if current_status in {"maintenance", "closed"} and roll < 0.65:
        return "operating"
    if roll < 0.04:
        return "maintenance"
    if roll < 0.12:
        return "delayed"
    if roll < 0.24:
        return "boarding"
    return "operating"


def adjust_wait(current_wait, status):
    if status in {"maintenance", "closed"}:
        return 0
    if status == "delayed":
        return min(120, current_wait + random.randint(8, 18))
    delta = random.randint(-6, 9)
    return max(3, min(90, current_wait + delta))
