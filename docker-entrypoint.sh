#!/bin/sh
set -eu

sample_routes_path="/app/data/sample_routes.json"
image_sample_routes_path="/app/image-data/sample_routes.json"

if [ ! -f "/app/data/sample_routes.json" ]; then
    mkdir -p "$(dirname "$sample_routes_path")"
    cp "/app/image-data/sample_routes.json" "/app/data/sample_routes.json"
fi

exec "$@"
