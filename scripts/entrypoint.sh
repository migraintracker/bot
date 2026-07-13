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

echo "Migrating telegram_id to BIGINT if needed..."
python -c "
import asyncio
from sqlalchemy import text
from bot.database import engine

async def migrate():
    async with engine.connect() as conn:
        result = await conn.execute(
            text(\"SELECT data_type FROM information_schema.columns WHERE table_name='users' AND column_name='telegram_id'\")
        )
        row = result.fetchone()
        if row and row[0] == 'integer':
            await conn.execute(text('ALTER TABLE users ALTER COLUMN telegram_id TYPE BIGINT'))
            await conn.commit()
            print('Migrated telegram_id to BIGINT')
        else:
            print('telegram_id already BIGINT or not found')

asyncio.run(migrate())
"

echo "Starting: $*"
exec "$@"