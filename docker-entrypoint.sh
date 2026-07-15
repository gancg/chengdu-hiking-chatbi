#!/bin/sh
set -eu

sample_routes_path="/app/data/sample_routes.json"
image_sample_routes_path="/app/image-data/sample_routes.json"
database_path="/app/data/chatbi.db"

if [ ! -f "/app/data/sample_routes.json" ]; then
    mkdir -p "$(dirname "$sample_routes_path")"
    cp "/app/image-data/sample_routes.json" "/app/data/sample_routes.json"
fi

if [ ! -f "/app/data/chatbi.db" ]; then
    mkdir -p "$(dirname "$database_path")"
    cp "/app/image-data/chatbi.db" "/app/data/chatbi.db"
fi

exec "$@"
