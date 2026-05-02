#!/bin/bash
# Setup PostgreSQL in Docker

docker run -d \
    --name coord_bot_db \
    -e POSTGRES_USER=coord_user \
    -e POSTGRES_PASSWORD=coord_pass \
    -e POSTGRES_DB=coord_db \
    -p 5432:5432 \
    -v postgres_data:/var/lib/postgresql/data \
    --health-cmd="pg_isready -U coord_user -d coord_db" \
    --health-interval=5s \
    postgres:15

echo "PostgreSQL container started. Waiting for health check..."
sleep 5
echo "You can now run: docker exec -it coord_bot_db psql -U coord_user -d coord_db"
