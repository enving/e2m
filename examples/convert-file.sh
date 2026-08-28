#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 path/to/document.pdf" >&2
  exit 2
fi

curl -sS -X POST "http://localhost:5001/v1/convert/file" \
  -H "accept: application/json" \
  -F "files=@$1" \
  -F "image_export_mode=placeholder"
