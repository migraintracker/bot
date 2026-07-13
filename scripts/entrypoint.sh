#!/bin/sh
set -e

echo "Waiting for PostgreSQL..."
max_retries=30
i=0
while [ $i -lt $max_retries ]; do
  if python -c "
import asyncio
from bot.database import engine
async def check():
    async with engine.connect() as conn:
        pass
asyncio.run(check())
" 2>/dev/null; then
    echo "PostgreSQL is ready"
    break
  fi
  i=$((i + 1))
  sleep 1
done

if [ $i -ge $max_retries ]; then
  echo "ERROR: PostgreSQL not available after ${max_retries}s"
  exit 1
fi

echo "Creating tables..."
python scripts/init_db.py

echo "Starting: $*"
exec "$@"