#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <ApiUrl>" >&2
  exit 2
fi

api_url="${1%/}"
endpoint="${api_url}/attractions?status=operating"

echo "Checking ${endpoint}"
curl --fail-with-body --silent --show-error "${endpoint}"
echo
echo "Deployment health check passed."
