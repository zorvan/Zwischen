# v3.3 Development Setup Guide

## Prerequisites

- Python 3.13-3.14
- PostgreSQL 15+
- Telegram Bot Token

## Setup Steps

### 1. Clone and Install

```bash
cd /home/zorvan/Work/projects/Zwischen/telegram-bot
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings
```

### 3. Run Database Migration (Fresh Deployment)

```bash
# Create new database
docker-compose up -d postgres
docker-compose exec postgres psql -U coord_user -d coord_db -f /app/db/schema.sql

# OR use manual setup
sudo -u postgres psql -c "CREATE USER coord_user WITH PASSWORD 'coord_pass';"
sudo -u postgres psql -c "CREATE DATABASE coord_db OWNER coord_user;"
PGPASSWORD=coord_pass psql -h localhost -U coord_user -d coord_db -f db/schema.sql
```

### 4. Run Bot

```bash
python main.py
```

## Testing

### Run All Tests

```bash
pytest
```

### Run Service Tests

```bash
pytest tests/test_services.py
```

### Run with Coverage

```bash
pytest --cov=bot --cov-report=html
```

## Testing v3.3 Features

### Test Live Cards

1. Create event in group: `/organize_event`
2. Verify live card appears in group chat
3. Join event in DM: Click "✅ Join"
4. Verify live card updates with new count
5. Lock event: Verify live card is deleted

### Test Memory-First Flow

1. Run `/organize_event` or `/plan`
2. Verify prior memories are shown (if any)
3. Type vague description: "something fun"
4. Verify clarifying question appears
5. After 2 turns, verify "🚀 Skip to structured" button
6. Click skip and verify structured flow with pre-filled data

### Test Hashtags

1. Create event with hashtags during formation
2. Verify hashtags displayed on live card
3. Lock event: Verify hashtags preserved in database
4. Query by hashtag: `/events #football`

### Test Lineage Door

1. Complete an event with memory fragments
2. Create new event of same type
3. Verify "Last time..." lineage fragment shown

## Common Issues

### Database Connection Errors

```bash
# Check PostgreSQL is running
docker-compose ps

# Verify credentials in .env
# DB_URL should use async driver: postgresql+asyncpg://
```

### LLM Unavailable

```bash
# Check AI endpoint
curl http://127.0.0.1:8080/v1/models

# Verify AI settings in .env
# AI features gracefully degrade if unavailable
```

### Live Cards Not Showing

```bash
# Check group settings
# Live cards enabled by default
# Can be disabled with: /settings live_cards off
```

## Development Tips

### Enable Debug Logging

```bash
export LOG_LEVEL=DEBUG
python main.py
```

### Use Existing Group

- Add bot to test group
- Run `/organize_event` to test live cards
- Monitor group chat for cards

### Check Database Directly

```bash
docker-compose exec postgres psql -U coord_user -d coord_db

# Check live cards
SELECT * FROM event_live_cards;

# Check group settings
SELECT * FROM group_settings;
```

## Next Steps

1. Test all v3.3 features in development
2. Run test suite: `pytest`
3. Deploy to staging environment
4. Monitor for errors in logs
5. Collect user feedback
6. Iterate and improve

## Support

- Check logs: `docker-compose logs -f bot`
- Debug: Set `LOG_LEVEL=DEBUG`
- Review: `docs/v3.3/IMPLEMENTATION_SUMMARY.md`
