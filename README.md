# Serverless Island Ops

A compact serverless theme-park operations app inspired by the Innovator Island workshop. It keeps the same core idea, a park dashboard backed by managed AWS services, but trims it into a deployable demo focused on:

- S3 static website hosting
- API Gateway HTTP API
- Lambda request handling and scheduled simulation
- DynamoDB attraction, event, and booking state
- S3 guest photo uploads through presigned URLs

## Project layout

```text
serverless-island-ops/
  template.yaml        # AWS SAM infrastructure
  src/                 # Python Lambda handlers
  public/              # Static S3 website
```

## Deploy

Prerequisites: AWS CLI, AWS SAM CLI, and configured AWS credentials.

```bash
sam build
sam deploy --guided
```

After deployment, create the frontend runtime config from the stack output:

```bash
cat > public/config.js <<'EOF'
window.ISLAND_CONFIG = {
  apiBaseUrl: "REPLACE_WITH_ApiUrl_OUTPUT"
};
EOF
```

Upload the static site to the generated website bucket:

```bash
aws s3 sync public/ s3://REPLACE_WITH_WebsiteBucketName_OUTPUT/ --delete
```

Open the `WebsiteUrl` output in a browser.

## Run locally

This repo includes a local dev server for testing without AWS or Docker. It serves the static frontend and emulates the API with a JSON file under `.local/`.

```bash
python3 local_server.py
```

Open:

```text
http://127.0.0.1:5173
```

Local uploads are written to `.local/uploads/`. Local state is stored in `.local/data.json`.

## API

- `GET /api/attractions` returns current attraction status and wait times.
- `PATCH /api/attractions/{id}` updates an attraction status or wait time.
- `GET /api/stats` returns dashboard counters.
- `GET /api/events` returns today's operations log.
- `GET /api/bookings` returns today's virtual queue bookings.
- `POST /api/bookings` creates a virtual queue return window.
- `POST /api/photos/presign` returns a presigned S3 upload URL.

The first API request seeds DynamoDB with sample attractions and events. The scheduled simulator Lambda then adjusts attraction wait times every two minutes.
