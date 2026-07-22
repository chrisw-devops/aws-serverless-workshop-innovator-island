#!/usr/bin/env python3
import datetime as dt
import json
import mimetypes
import os
import random
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).parent
PUBLIC = ROOT / "public"
LOCAL_DIR = ROOT / ".local"
DATA_FILE = LOCAL_DIR / "data.json"
UPLOAD_DIR = LOCAL_DIR / "uploads"

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
    {"id": "parade", "time": "14:30", "title": "Harbor Circuit Parade", "area": "Main Loop", "severity": "info"},
    {"id": "maintenance", "time": "16:00", "title": "Orbit Foundry restraint inspection", "area": "Launch Yard", "severity": "warning"},
    {"id": "fireworks", "time": "21:15", "title": "Drone light finale", "area": "Skyline Pier", "severity": "info"},
]


class LocalHandler(BaseHTTPRequestHandler):
    server_version = "IslandLocal/1.0"

    def do_OPTIONS(self):
        self.send_json({}, status=204)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            self.handle_api("GET", path, parse_qs(parsed.query))
            return
        self.serve_static(path)

    def do_POST(self):
        self.handle_api("POST", urlparse(self.path).path)

    def do_PATCH(self):
        self.handle_api("PATCH", urlparse(self.path).path)

    def do_PUT(self):
        path = unquote(urlparse(self.path).path)
        if not path.startswith("/uploads/"):
            self.send_json({"message": "Route not found"}, status=404)
            return
        target = UPLOAD_DIR / path.removeprefix("/uploads/")
        target.parent.mkdir(parents=True, exist_ok=True)
        length = int(self.headers.get("content-length", "0"))
        target.write_bytes(self.rfile.read(length))
        self.send_json({"ok": True, "path": str(target.relative_to(ROOT))})

    def handle_api(self, method, path, query=None):
        data = load_data()
        query = query or {}
        try:
            if method == "GET" and path == "/api/attractions":
                attractions = data["attractions"]
                status = query.get("status", [None])[0]
                if status:
                    attractions = [item for item in attractions if item["status"] == status]
                return self.send_json({"attractions": sorted(attractions, key=lambda item: item["name"])})

            if method == "GET" and path == "/api/events":
                return self.send_json({"events": data["events"]})

            if method == "GET" and path == "/api/bookings":
                return self.send_json({"bookings": sorted(data["bookings"], key=lambda item: item["createdAt"], reverse=True)})

            if method == "GET" and path == "/api/stats":
                return self.send_json(stats(data))

            if method == "POST" and path == "/api/bookings":
                booking = create_booking(data, self.read_json())
                save_data(data)
                return self.send_json({"booking": booking}, status=201)

            if method == "POST" and path == "/api/photos/presign":
                return self.send_json(local_upload_url(self.read_json()))

            if method == "POST" and path == "/api/simulate":
                simulate(data)
                save_data(data)
                return self.send_json({"attractions": data["attractions"]})

            if method == "PATCH" and path.startswith("/api/attractions/"):
                attraction_id = unquote(path.removeprefix("/api/attractions/"))
                attraction = update_attraction(data, attraction_id, self.read_json())
                save_data(data)
                return self.send_json({"attraction": attraction})

            self.send_json({"message": "Route not found"}, status=404)
        except ValueError as exc:
            self.send_json({"message": str(exc)}, status=400)

    def serve_static(self, path):
        if path in {"", "/"}:
            path = "/index.html"
        target = (PUBLIC / path.lstrip("/")).resolve()
        if not str(target).startswith(str(PUBLIC.resolve())) or not target.exists() or target.is_dir():
            target = PUBLIC / "index.html"
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def read_json(self):
        length = int(self.headers.get("content-length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, payload, status=200):
        body = b"" if status == 204 else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET,POST,PATCH,PUT,OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def load_data():
    LOCAL_DIR.mkdir(exist_ok=True)
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    data = {"attractions": ATTRACTIONS, "events": EVENTS, "bookings": []}
    save_data(data)
    return data


def save_data(data):
    LOCAL_DIR.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2))


def stats(data):
    attractions = data["attractions"]
    active = [item for item in attractions if item["status"] in {"operating", "boarding"}]
    average_wait = round(sum(int(item["waitMinutes"]) for item in attractions) / max(len(attractions), 1))
    return {
        "openAttractions": len(active),
        "totalAttractions": len(attractions),
        "averageWait": average_wait,
        "bookingsToday": len(data["bookings"]),
        "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def create_booking(data, payload):
    attraction = find_attraction(data, payload.get("attractionId"))
    if not attraction:
        raise ValueError("Unknown attraction")
    party_name = str(payload.get("partyName") or "").strip()
    if not party_name:
        raise ValueError("Guest name is required")
    party_size = int(payload.get("partySize") or 0)
    if party_size < 1 or party_size > 12:
        raise ValueError("Party size must be between 1 and 12")
    now = dt.datetime.now(dt.timezone.utc)
    booking = {
        "id": str(uuid.uuid4()),
        "attractionId": attraction["id"],
        "attractionName": attraction["name"],
        "partyName": party_name[:80],
        "partySize": party_size,
        "returnWindow": build_return_window(now, int(attraction["waitMinutes"])),
        "createdAt": now.isoformat(),
    }
    data["bookings"].append(booking)
    return booking


def update_attraction(data, attraction_id, payload):
    attraction = find_attraction(data, attraction_id)
    if not attraction:
        raise ValueError("Unknown attraction")
    if "status" in payload:
        if payload["status"] not in {"operating", "boarding", "delayed", "maintenance", "closed"}:
            raise ValueError("Invalid status")
        attraction["status"] = payload["status"]
    if "waitMinutes" in payload:
        attraction["waitMinutes"] = max(0, min(240, int(payload["waitMinutes"])))
    attraction["updatedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return attraction


def local_upload_url(payload):
    file_name = str(payload.get("fileName") or "island-photo.jpg")
    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "jpg"
    if extension not in {"jpg", "jpeg", "png", "webp"}:
        raise ValueError("Only jpg, png, and webp uploads are supported")
    key = f"{dt.date.today().isoformat()}/{uuid.uuid4()}.{extension}"
    return {"bucket": "local", "key": f"uploads/{key}", "uploadUrl": f"/uploads/{key}", "expiresIn": 900}


def simulate(data):
    for attraction in data["attractions"]:
        status = attraction["status"]
        roll = random.random()
        if status in {"maintenance", "closed"} and roll < 0.65:
            status = "operating"
        elif roll < 0.04:
            status = "maintenance"
        elif roll < 0.12:
            status = "delayed"
        elif roll < 0.24:
            status = "boarding"
        else:
            status = "operating"
        attraction["status"] = status
        if status in {"maintenance", "closed"}:
            attraction["waitMinutes"] = 0
        elif status == "delayed":
            attraction["waitMinutes"] = min(120, int(attraction["waitMinutes"]) + random.randint(8, 18))
        else:
            attraction["waitMinutes"] = max(3, min(90, int(attraction["waitMinutes"]) + random.randint(-6, 9)))


def find_attraction(data, attraction_id):
    return next((item for item in data["attractions"] if item["id"] == attraction_id), None)


def build_return_window(now, wait_minutes):
    start = now + dt.timedelta(minutes=max(wait_minutes - 5, 0))
    end = start + dt.timedelta(minutes=20)
    return f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')} UTC"


def main():
    port = int(os.environ.get("PORT", "5173"))
    load_data()
    server = ThreadingHTTPServer(("127.0.0.1", port), LocalHandler)
    print(f"Serverless Island Ops local dev server: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
