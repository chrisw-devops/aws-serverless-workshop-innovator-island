import base64
import datetime as dt
import decimal
import json
import os
import uuid
from urllib.parse import unquote

import boto3
from boto3.dynamodb.conditions import Key


TABLE_NAME = os.environ["TABLE_NAME"]
MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3")


ATTRACTIONS = [
    {
        "id": "aurora",
        "name": "Aurora Drop",
        "area": "Skyline Pier",
        "type": "Thrill",
        "status": "operating",
        "waitMinutes": 28,
        "capacityPerHour": 920,
        "mood": "high demand",
    },
    {
        "id": "reef",
        "name": "Reef Runner",
        "area": "Coral Harbor",
        "type": "Family",
        "status": "operating",
        "waitMinutes": 14,
        "capacityPerHour": 760,
        "mood": "steady",
    },
    {
        "id": "orbit",
        "name": "Orbit Foundry",
        "area": "Launch Yard",
        "type": "Interactive",
        "status": "operating",
        "waitMinutes": 21,
        "capacityPerHour": 540,
        "mood": "building",
    },
    {
        "id": "grove",
        "name": "Kinetic Grove",
        "area": "Garden District",
        "type": "Show",
        "status": "boarding",
        "waitMinutes": 8,
        "capacityPerHour": 1200,
        "mood": "open",
    },
]

EVENTS = [
    {
        "id": "parade",
        "time": "14:30",
        "title": "Harbor Circuit Parade",
        "area": "Main Loop",
        "severity": "info",
    },
    {
        "id": "maintenance",
        "time": "16:00",
        "title": "Orbit Foundry restraint inspection",
        "area": "Launch Yard",
        "severity": "warning",
    },
    {
        "id": "fireworks",
        "time": "21:15",
        "title": "Drone light finale",
        "area": "Skyline Pier",
        "severity": "info",
    },
]


def handler(event, _context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "/")

    if method == "OPTIONS":
        return response(204, None)

    try:
        seed_if_needed()

        if method == "GET" and path == "/api/attractions":
            return response(200, {"attractions": list_attractions()})

        if method == "GET" and path == "/api/events":
            return response(200, {"events": list_events()})

        if method == "GET" and path == "/api/bookings":
            return response(200, {"bookings": list_bookings()})

        if method == "GET" and path == "/api/stats":
            return response(200, get_stats())

        if method == "POST" and path == "/api/bookings":
            return response(201, create_booking(read_body(event)))

        if method == "POST" and path == "/api/photos/presign":
            return response(200, create_upload_url(read_body(event)))

        if method == "PATCH" and path.startswith("/api/attractions/"):
            attraction_id = unquote(path.removeprefix("/api/attractions/"))
            return response(200, update_attraction(attraction_id, read_body(event)))

        return response(404, {"message": "Route not found"})
    except ValueError as exc:
        return response(400, {"message": str(exc)})
    except Exception as exc:
        print(f"Unhandled error: {exc}")
        return response(500, {"message": "Internal server error"})


def seed_if_needed():
    result = table.query(
        KeyConditionExpression=Key("pk").eq("ATTRACTION"),
        Limit=1,
    )
    if result.get("Items"):
        return

    today = dt.date.today().isoformat()
    with table.batch_writer() as batch:
        for attraction in ATTRACTIONS:
            batch.put_item(Item={"pk": "ATTRACTION", "sk": attraction["id"], **attraction})
        for event in EVENTS:
            batch.put_item(Item={"pk": f"EVENT#{today}", "sk": f"{event['time']}#{event['id']}", **event})


def list_attractions():
    result = table.query(KeyConditionExpression=Key("pk").eq("ATTRACTION"))
    return sorted(result.get("Items", []), key=lambda item: item["name"])


def list_events():
    today = dt.date.today().isoformat()
    result = table.query(KeyConditionExpression=Key("pk").eq(f"EVENT#{today}"))
    return result.get("Items", [])


def list_bookings():
    today = dt.date.today().isoformat()
    result = table.query(KeyConditionExpression=Key("pk").eq(f"BOOKING#{today}"))
    return sorted(result.get("Items", []), key=lambda item: item["createdAt"], reverse=True)


def create_booking(payload):
    required = ["attractionId", "partyName", "partySize"]
    missing = [field for field in required if not payload.get(field)]
    if missing:
        raise ValueError(f"Missing required field: {', '.join(missing)}")

    attraction_id = str(payload["attractionId"])
    attraction = get_attraction(attraction_id)
    if not attraction:
        raise ValueError("Unknown attraction")

    party_size = int(payload["partySize"])
    if party_size < 1 or party_size > 12:
        raise ValueError("Party size must be between 1 and 12")

    now = dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    booking_id = str(uuid.uuid4())
    item = {
        "pk": f"BOOKING#{today}",
        "sk": booking_id,
        "id": booking_id,
        "attractionId": attraction_id,
        "attractionName": attraction["name"],
        "partyName": str(payload["partyName"])[:80],
        "partySize": party_size,
        "returnWindow": build_return_window(now, int(attraction.get("waitMinutes", 0))),
        "createdAt": now.isoformat(),
    }
    table.put_item(Item=item)
    return {"booking": item}


def create_upload_url(payload):
    file_name = str(payload.get("fileName") or "island-photo.jpg")
    content_type = str(payload.get("contentType") or "image/jpeg")
    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "jpg"
    if extension not in {"jpg", "jpeg", "png", "webp"}:
        raise ValueError("Only jpg, png, and webp uploads are supported")

    key = f"guest-photos/{dt.date.today().isoformat()}/{uuid.uuid4()}.{extension}"
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": MEDIA_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=900,
    )
    return {"bucket": MEDIA_BUCKET, "key": key, "uploadUrl": upload_url, "expiresIn": 900}


def update_attraction(attraction_id, payload):
    if not get_attraction(attraction_id):
        raise ValueError("Unknown attraction")

    allowed_statuses = {"operating", "boarding", "delayed", "maintenance", "closed"}
    status = payload.get("status")
    wait_minutes = payload.get("waitMinutes")

    updates = []
    names = {}
    values = {}
    if status is not None:
        if status not in allowed_statuses:
            raise ValueError("Invalid status")
        updates.append("#status = :status")
        names["#status"] = "status"
        values[":status"] = status
    if wait_minutes is not None:
        wait = int(wait_minutes)
        if wait < 0 or wait > 240:
            raise ValueError("Wait time must be between 0 and 240")
        updates.append("waitMinutes = :wait")
        values[":wait"] = wait

    if not updates:
        raise ValueError("No supported fields provided")

    values[":updatedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    updates.append("updatedAt = :updatedAt")

    update_args = {
        "Key": {"pk": "ATTRACTION", "sk": attraction_id},
        "UpdateExpression": "SET " + ", ".join(updates),
        "ExpressionAttributeValues": values,
        "ReturnValues": "ALL_NEW",
    }
    if names:
        update_args["ExpressionAttributeNames"] = names

    result = table.update_item(
        **update_args,
    )
    return {"attraction": result["Attributes"]}


def get_stats():
    attractions = list_attractions()
    bookings = list_bookings()
    active = [item for item in attractions if item.get("status") in {"operating", "boarding"}]
    average_wait = round(sum(int(item.get("waitMinutes", 0)) for item in attractions) / max(len(attractions), 1))
    return {
        "openAttractions": len(active),
        "totalAttractions": len(attractions),
        "averageWait": average_wait,
        "bookingsToday": len(bookings),
        "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def get_attraction(attraction_id):
    result = table.get_item(Key={"pk": "ATTRACTION", "sk": attraction_id})
    return result.get("Item")


def build_return_window(now, wait_minutes):
    start = now + dt.timedelta(minutes=max(wait_minutes - 5, 0))
    end = start + dt.timedelta(minutes=20)
    return f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')} UTC"


def read_body(event):
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be valid JSON") from exc


def response(status_code, body):
    payload = "" if body is None else json.dumps(body, default=json_default)
    return {
        "statusCode": status_code,
        "headers": {
            "access-control-allow-origin": ALLOWED_ORIGIN,
            "access-control-allow-methods": "GET,POST,PATCH,OPTIONS",
            "access-control-allow-headers": "content-type",
            "content-type": "application/json",
        },
        "body": payload,
    }


def json_default(value):
    if isinstance(value, decimal.Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
