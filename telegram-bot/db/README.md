# Database Configuration

## Schema Definition

The database schema is defined through **SQLAlchemy models** (`models.py`), which is the primary source of truth.

- **Primary Source**: [models.py](models.py) - SQLAlchemy ORM models
- **Reference**: [schema.sql](schema.sql) - SQL schema documentation

## Initialization

When the application starts, `init_db()` in `connection.py`:

1. Creates all tables defined in SQLAlchemy models
2. Applies any constraints and relationships
3. Creates indexes as defined in models

No migrations needed for fresh deployments.

## Schema Changes

When you need to modify the schema:

1. **Update the model** in `models.py`
2. **Update the reference** in `schema.sql`
3. **Restart the application**
4. `init_db()` will create/update tables automatically

## Directory Contents

- `connection.py` - Async database connection and initialization
- `models.py` - SQLAlchemy ORM models (primary schema definition)
- `schema.sql` - SQL schema reference documentation
- `users.py` - User-related database operations
- `errors.py` - Database error definitions
- `migrations/` - Directory for future migrations (if needed)

## Future Migrations

If you need to implement database migrations for complex schema changes:

1. Check git history for previous migration system implementation
2. Re-implement from `git log --all --grep="migration"` or branches

The old migration system provided:
- Version tracking in `schema_migrations` table
- Sequential migration application
- Migration CLI (`scripts/migrations.py`)

## Database URL Format

PostgreSQL with asyncpg driver:
```
postgresql+asyncpg://user:password@localhost:5432/database
```

Set via environment variable or `.env`:
```
DATABASE_URL=postgresql+asyncpg://coord_user:coord_pass@localhost:5432/coord_db
```

## Development

Create a PostgreSQL docker container:
```bash
bash scripts/setup_db.sh
```

Check connection:
```bash
python main.py  # init_db() runs automatically
```
