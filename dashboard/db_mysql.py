"""
db_mysql.py — MySQL connection layer for ECP Dashboard
=======================================================
Drop-in replacement for the SQLite get_db() / db_rows() / db_scalar() functions.

SINGLE DATABASE MODE (current setup):
  All tables live in one MySQL database.
  Set MYSQL_DATABASE in your environment to the database name.
  If not set, falls back to individual DB names per table (legacy multi-DB mode).

  Tables in the single database:
    ecp                     ← ECP candidate data       (REPLACE daily)
    attendance_data         ← Attendance session data   (UPSERT daily)
    fa                      ← Formative assessment data (UPSERT daily)
    batch_plan              ← Batch plan data           (REPLACE as needed)
    centre_community_master ← Centre & community master (REPLACE daily)
    user_master             ← User accounts & roles

ENVIRONMENT VARIABLES (set in Google Cloud Run):
  MYSQL_HOST      ← Cloud SQL Public IP  e.g. 34.xx.xx.xx
  MYSQL_PORT      ← 3306 (default)
  MYSQL_USER      ← root
  MYSQL_PASSWORD  ← your password
  MYSQL_DATABASE  ← single database name (e.g. attendance_db)
  MYSQL_CHARSET   ← utf8mb4 (default)

FIXES:
  - replace_table / upsert_table batch_size raised 500 → 5000 (10x fewer
    round-trips; critical for 50-lakh-row uploads — Bug #2).
  - Added MySQL indexes hint comment for DBA to run once (Bug #2).
  - Pool size raised 5 → 10 to handle concurrent rebuild + API requests.
  - Single-DB mode: all tables use one connection pool when MYSQL_DATABASE is set.
"""

import os
import threading
from contextlib import contextmanager

# ── Optional .env support for local development ────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import mysql.connector
    from mysql.connector import pooling
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    print("WARNING: mysql-connector-python not installed. Run: pip install mysql-connector-python")

# ── Connection config ──────────────────────────────────────────────────────────
MYSQL_HOST     = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT     = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER     = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_CHARSET  = os.environ.get("MYSQL_CHARSET", "utf8mb4")

# ── Single DB mode ─────────────────────────────────────────────────────────────
# If MYSQL_DATABASE is set, ALL tables use that one database.
# This matches the actual Cloud SQL setup where all tables are in one DB.
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "")
# ── One pool per database ──────────────────────────────────────────────────────
# FIX #2 — Raised pool size from 5 → 10.
# With 50L rows, rebuild takes 2-3 min and holds a connection the whole time.
# Other API requests need their own connections concurrently.
POOL_SIZE = 10

# If MYSQL_DATABASE is set → single DB mode: all keys point to same database.
# Otherwise → legacy multi-DB mode with separate databases per dataset.
_single_db = MYSQL_DATABASE  # e.g. "attendance_db" from Cloud Run env

DB_NAMES = {
    "ecp":              _single_db or "ecp_db",
    "attendance":       _single_db or "attendance_db",
    "fa":               _single_db or "fa_db",
    "batch_plan":       _single_db or "batch_plan_db",
    "centre_community": _single_db or "centre_community_db",
    "user_master":      _single_db or "user_master_db",
}

# Table → which logical DB it lives in
TABLE_TO_DB = {
    "ecp":                     "ecp",
    "attendance_data":         "attendance",
    "fa":                      "fa",
    "batch_plan":              "batch_plan",
    "centre_community_master": "centre_community",
    "user_master":             "user_master",
    "session_log":             "user_master",  # ← ADDED
    "employers":               "ecp",          # ← SkillMap employer discovery
    "compliance_data":         "ecp",          # ← Compliance lives alongside ECP (joins on batch+cand)
}

_pools = {}
_pool_lock = threading.Lock()


def _make_pool(db_key):
    """Create a connection pool for one logical database."""
    db_name = DB_NAMES[db_key]
    common = dict(
        pool_name=f"pool_{db_key}",
        pool_size=POOL_SIZE,
        pool_reset_session=True,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=db_name,
        charset=MYSQL_CHARSET,
        collation="utf8mb4_unicode_ci",
        autocommit=False,
        connection_timeout=30,
        use_pure=True,
    )
    if MYSQL_HOST.startswith("/"):
        return pooling.MySQLConnectionPool(unix_socket=MYSQL_HOST, **common)
    return pooling.MySQLConnectionPool(host=MYSQL_HOST, port=MYSQL_PORT, **common)


def get_pool(db_key):
    """Return (or lazily create) the connection pool for a logical DB."""
    if db_key not in _pools:
        with _pool_lock:
            if db_key not in _pools:
                _pools[db_key] = _make_pool(db_key)
    return _pools[db_key]


@contextmanager
def get_conn(db_key):
    """Context manager: borrow a connection from the pool, auto-return it."""
    pool = get_pool(db_key)
    conn = pool.get_connection()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()   # returns to pool


def _db_key_for_table(table):
    """Look up which logical DB a table lives in."""
    key = TABLE_TO_DB.get(table)
    if not key:
        raise ValueError(f"Unknown table '{table}' — add it to TABLE_TO_DB in db_mysql.py")
    return key


# ── Public API (mirrors the old SQLite helpers) ────────────────────────────────

def db_rows(sql, params=(), table_hint=None):
    """
    Run a SELECT and return list of dicts.
    table_hint: the logical table name to pick the right DB pool.
                If omitted, extracted from the SQL (works for simple queries).
    """
    if not MYSQL_AVAILABLE:
        return []
    db_key = _resolve_db_key(sql, table_hint)
    mysql_sql = _convert_placeholders(sql)
    try:
        with get_conn(db_key) as conn:
            cur = conn.cursor(dictionary=True)
            cur.execute(mysql_sql, params or ())
            return cur.fetchall()
    except Exception as e:
        print(f"  DB ERROR db_rows [{db_key}]: {e}\n  SQL: {sql[:120]}")
        return []


def db_scalar(sql, params=(), table_hint=None):
    """Run a SELECT and return a single scalar value."""
    if not MYSQL_AVAILABLE:
        return None
    db_key = _resolve_db_key(sql, table_hint)
    mysql_sql = _convert_placeholders(sql)
    try:
        with get_conn(db_key) as conn:
            cur = conn.cursor()
            cur.execute(mysql_sql, params or ())
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as e:
        print(f"  DB ERROR db_scalar [{db_key}]: {e}\n  SQL: {sql[:120]}")
        return None


def db_execute(sql, params=(), table_hint=None):
    """Run an INSERT / UPDATE / DELETE on the correct DB."""
    if not MYSQL_AVAILABLE:
        return 0
    db_key = _resolve_db_key(sql, table_hint)
    mysql_sql = _convert_placeholders(sql)
    try:
        with get_conn(db_key) as conn:
            cur = conn.cursor()
            cur.execute(mysql_sql, params or ())
            conn.commit()
            return cur.rowcount
    except Exception as e:
        print(f"  DB ERROR db_execute [{db_key}]: {e}\n  SQL: {sql[:120]}")
        return 0


def db_executemany(sql, param_list, table_hint=None):
    """Bulk INSERT/UPDATE — all rows must go to the same table/DB."""
    if not MYSQL_AVAILABLE or not param_list:
        return 0
    db_key = _resolve_db_key(sql, table_hint)
    mysql_sql = _convert_placeholders(sql)
    try:
        with get_conn(db_key) as conn:
            cur = conn.cursor()
            cur.executemany(mysql_sql, param_list)
            conn.commit()
            return cur.rowcount
    except Exception as e:
        print(f"  DB ERROR db_executemany [{db_key}]: {e}\n  SQL: {sql[:120]}")
        return 0


# ── Internal helpers ───────────────────────────────────────────────────────────

def _resolve_db_key(sql, table_hint):
    if table_hint:
        return _db_key_for_table(table_hint)
    import re
    m = re.search(r'\bFROM\s+["`]?(\w+)["`]?', sql, re.IGNORECASE)
    if not m:
        m = re.search(r'\bINTO\s+["`]?(\w+)["`]?', sql, re.IGNORECASE)
    if not m:
        m = re.search(r'\bUPDATE\s+["`]?(\w+)["`]?', sql, re.IGNORECASE)
    if m:
        table = m.group(1)
        if table in TABLE_TO_DB:
            return TABLE_TO_DB[table]
    raise ValueError(
        f"Cannot determine DB from SQL: '{sql[:80]}'. "
        "Pass table_hint= or add table to TABLE_TO_DB."
    )


def _convert_placeholders(sql):
    """
    Convert SQLite ? placeholders → MySQL %s.
    Also converts SQLite double-quoted identifiers to backtick-quoted,
    BUT leaves string literals like "No", "Yes", "Active" as single-quoted strings.
    MySQL treats double-quoted words as column names unless ANSI_QUOTES is off.
    """
    import re
    result = sql.replace("?", "%s")
    result = re.sub(r'"(\w+)"', r"'\1'", result)
    return result


def check_connectivity():
    """
    Test connectivity to all 6 databases.
    Returns dict of {db_key: True/False}.
    Called at startup to give early warning.
    """
    results = {}
    for db_key in DB_NAMES:
        try:
            with get_conn(db_key) as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
            results[db_key] = True
        except Exception as e:
            results[db_key] = False
            print(f"  ⚠ Cannot connect to {DB_NAMES[db_key]}: {e}")
    return results


def get_table_row_count(table):
    """Convenience: count rows in any table."""
    return db_scalar(f"SELECT COUNT(*) FROM `{table}`", table_hint=table)


# ── UPLOAD HELPERS ─────────────────────────────────────────────────────────────

def col_name_to_sql(name):
    """Convert column header → safe SQL column name."""
    import re
    n = name.strip()
    n = n.replace("/", "_").replace("(", "").replace(")", "")
    n = n.replace(".", "").replace(",", "").replace("  ", " ")
    n = n.replace(" ", "_").replace("-", "_")
    while n.endswith("_"):
        n = n[:-1]
    return n.lower()


def replace_table(table, columns, rows, batch_size=10000):
    """
    Full replace: DROP + CREATE the table then bulk-insert all rows.
    Uses true bulk INSERT (single SQL with multiple VALUES) for maximum speed.
    Disables unique checks and autocommit during insert for 3-5x speedup.
    """
    db_key = _db_key_for_table(table)
    sql_cols = [col_name_to_sql(c) for c in columns]
    col_list = ", ".join(f"`{c}`" for c in sql_cols)
    placeholders = ", ".join(["%s"] * len(sql_cols))

    # Build CREATE TABLE — all columns as TEXT
    col_defs = ",\n  ".join(f"`{c}` TEXT" for c in sql_cols)
    create_sql = (
        f"CREATE TABLE `{table}` (\n"
        f"  `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,\n"
        f"  {col_defs}\n"
        f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
    )

    try:
        with get_conn(db_key) as conn:
            cur = conn.cursor()
            # Drop + recreate so schema always matches columns exactly
            cur.execute(f"DROP TABLE IF EXISTS `{table}`")
            cur.execute(create_sql)
            conn.commit()
            print(f"  replace_table({table}): table recreated with {len(sql_cols)} columns", flush=True)

            # Disable checks for maximum insert speed
            cur.execute("SET autocommit=0")
            cur.execute("SET unique_checks=0")
            cur.execute("SET foreign_key_checks=0")

            inserted = 0
            total_rows = len(rows)
            batch = []

            for row in rows:
                vals = tuple(str(row.get(c, "") or "") for c in columns)
                batch.append(vals)

                if len(batch) >= batch_size:
                    # True bulk INSERT — one SQL with all VALUES
                    bulk_sql = (
                        f"INSERT INTO `{table}` ({col_list}) VALUES "
                        + ",".join([f"({placeholders})"] * len(batch))
                    )
                    flat_vals = [v for row_vals in batch for v in row_vals]
                    cur.execute(bulk_sql, flat_vals)
                    inserted += len(batch)
                    batch = []
                    conn.commit()
                    pct = int(inserted / total_rows * 40) if total_rows else 0
                    print(f"  replace_table({table}): {inserted:,}/{total_rows:,} rows…", flush=True)
                    try:
                        from . import app_state as _S
                        if _S.REBUILD_STATE.get("running"):
                            _S.REBUILD_STATE["step"] = f"Saving to database… {inserted:,}/{total_rows:,} rows"
                            _S.REBUILD_STATE["pct"]  = max(10, min(55, 10 + pct))
                    except Exception: pass

            # Insert remaining rows
            if batch:
                bulk_sql = (
                    f"INSERT INTO `{table}` ({col_list}) VALUES "
                    + ",".join([f"({placeholders})"] * len(batch))
                )
                flat_vals = [v for row_vals in batch for v in row_vals]
                cur.execute(bulk_sql, flat_vals)
                inserted += len(batch)

            conn.commit()
            # Re-enable checks
            cur.execute("SET unique_checks=1")
            cur.execute("SET foreign_key_checks=1")
            cur.execute("SET autocommit=1")
            print(f"  replace_table({table}): inserted {inserted:,} rows total")
            return inserted
    except Exception as e:
        print(f"  ERROR replace_table({table}): {e}")
        raise


def _bulk_upsert(cur, table, col_list, placeholders, update_clause, batch):
    """Execute a true bulk INSERT ... ON DUPLICATE KEY UPDATE for a batch of rows."""
    bulk_sql = (
        f"INSERT INTO `{table}` ({col_list}) VALUES "
        + ",".join([f"({placeholders})"] * len(batch))
        + f" ON DUPLICATE KEY UPDATE {update_clause}"
    )
    flat_vals = [v for row_vals in batch for v in row_vals]
    cur.execute(bulk_sql, flat_vals)


def upsert_table(table, columns, rows, key_columns, batch_size=5000):
    """
    Upsert: INSERT ... ON DUPLICATE KEY UPDATE ...
    Used for Attendance and FA.

    LARGE FILE FIX: same batch-commit strategy as replace_table.
    """
    db_key = _db_key_for_table(table)
    sql_cols = [col_name_to_sql(c) for c in columns]
    col_list = ", ".join(f"`{c}`" for c in sql_cols)
    placeholders = ", ".join(["%s"] * len(sql_cols))

    key_sql_cols = {col_name_to_sql(k) for k in key_columns}

    # Build update clause; if schema specifies a priority_date_col, only update
    # non-key columns when the incoming date >= the stored date (take latest).
    # UPSERT_SCHEMAS is defined below — accessed after table creation
    # Use a local forward-compatible lookup helper
    _SCHEMAS_EARLY = {
        "fa": {"priority_date_col": "evaluated_on"},
    }
    schema      = _SCHEMAS_EARLY.get(table, {})
    prio_col    = schema.get("priority_date_col")   # e.g. "evaluated_on" for FA
    update_parts = []
    for c in sql_cols:
        if c in key_sql_cols:
            continue
        if prio_col and c != prio_col:
            # Only overwrite if incoming evaluated_on is newer (or equal)
            update_parts.append(
                f"`{c}` = IF(VALUES(`{prio_col}`) >= `{prio_col}`, VALUES(`{c}`), `{c}`)"
            )
        elif prio_col and c == prio_col:
            update_parts.append(
                f"`{c}` = IF(VALUES(`{c}`) >= `{c}`, VALUES(`{c}`), `{c}`)"
            )
        else:
            update_parts.append(f"`{c}` = VALUES(`{c}`)")
    update_clause = ", ".join(update_parts) if update_parts else "`id` = `id`"

    upsert_sql = (
        f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_clause}"
    )

    commit_every = 20   # commit every 100k rows

    # Ensure the table exists with correct schema and UNIQUE key before upserting.
    # Without a UNIQUE key, ON DUPLICATE KEY UPDATE never triggers — every call inserts
    # fresh rows and the table grows without bound (duplicates accumulate).
    _UPSERT_SCHEMAS = {
        "attendance_data": {
            "cols": [
                "`batch_id` VARCHAR(64)", "`candidate_id` VARCHAR(64)",
                "`session_id` VARCHAR(64)", "`module_id` VARCHAR(64)",
                "`module_name` TEXT", "`session_date` VARCHAR(32)",
                "`session_trainer_name` TEXT", "`attendance_status` VARCHAR(32)",
                "`geo_coordinates` TEXT", "`session_photos` TEXT",
                "`session_updated_by` TEXT",
            ],
            "unique": ["batch_id", "candidate_id", "session_id"],
        },
        "fa": {
            "cols": [
                "`batch_id` VARCHAR(64)", "`candidate_id` VARCHAR(64)",
                "`module_name` VARCHAR(256)", "`topic_name` VARCHAR(500)",
                "`actual_marks` VARCHAR(32)", "`pass_marks` VARCHAR(32)",
                "`pass_fail_attempted` VARCHAR(32)",
                "`evaluation_status` VARCHAR(64)", "`evaluated_on` VARCHAR(32)",
                "`module_schedule_start_date` VARCHAR(32)",
                "`module_schedule_by` TEXT",
            ],
            "unique": ["batch_id", "candidate_id", "topic_name"],
            "priority_date_col": "evaluated_on",
        },
        "compliance_data": {
            "cols": [
                "`batch_id` VARCHAR(64)", "`candidate_id` VARCHAR(64)",
                "`course_name` VARCHAR(256)", "`sub_project_name` TEXT",
                "`new_criteria` VARCHAR(512)", "`age` VARCHAR(32)",
                "`remarks_of_validation` TEXT", "`remark_2` VARCHAR(256)",
                "`short_remark` VARCHAR(128)", "`date` VARCHAR(32)",
            ],
            "unique": ["batch_id", "candidate_id"],
            "priority_date_col": "date",
        },
    }

    try:
        with get_conn(db_key) as conn:
            cur = conn.cursor()

            # Create table with UNIQUE key if it does not exist yet
            schema = _UPSERT_SCHEMAS.get(table)
            if schema:
                col_defs = ",\n  ".join(schema["cols"])
                uq_cols  = ", ".join(f"`{c}`" for c in schema["unique"])
                create_sql = (
                    f"CREATE TABLE IF NOT EXISTS `{table}` (\n"
                    f"  `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,\n"
                    f"  {col_defs},\n"
                    f"  UNIQUE KEY `uq_{table}` ({uq_cols})\n"
                    f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
                )
                cur.execute(create_sql)

                # For FA: migrate schema if needed (old column was pass_fail_attempted_not_attempted)
                if table == "fa":
                    try:
                        cur.execute(
                            "ALTER TABLE `fa` CHANGE COLUMN `pass_fail_attempted_not_attempted` "
                            "`pass_fail_attempted` VARCHAR(32)"
                        )
                        conn.commit()
                    except Exception:
                        pass  # column already renamed or doesn't exist yet

                # For compliance_data: widen `new_criteria` on already-deployed tables.
                # Older schema used VARCHAR(128); some incoming eligibility strings
                # (e.g. multi-trade ITI/Diploma descriptions) reach ~156 chars and
                # trigger MySQL error 1406 (22001) "Data too long". Idempotent —
                # MODIFY to the same width on subsequent runs is a no-op.
                if table == "compliance_data":
                    try:
                        cur.execute(
                            "ALTER TABLE `compliance_data` "
                            "MODIFY COLUMN `new_criteria` VARCHAR(512)"
                        )
                        conn.commit()
                    except Exception:
                        pass  # column already wide enough or table just created

                # Ensure existing tables without the UNIQUE key get it added (idempotent)
                try:
                    cur.execute(
                        f"ALTER TABLE `{table}` ADD UNIQUE KEY `uq_{table}` ({uq_cols})"
                    )
                except Exception:
                    pass  # key already exists — fine
                conn.commit()

            inserted = 0
            batch = []
            batches_since_commit = 0
            commit_every = 20

            # Build bulk upsert SQL template
            bulk_upsert_template = (
                f"INSERT INTO `{table}` ({col_list}) VALUES "
                "{{values_placeholder}} "
                f"ON DUPLICATE KEY UPDATE {update_clause}"
            )

            for row in rows:
                vals = tuple(str(row.get(c, "") or "") for c in columns)
                batch.append(vals)
                if len(batch) >= batch_size:
                    _bulk_upsert(cur, table, col_list, placeholders, update_clause, batch)
                    inserted += len(batch)
                    batch = []
                    batches_since_commit += 1
                    if batches_since_commit >= commit_every:
                        conn.commit()
                        batches_since_commit = 0
                        print(f"  upsert_table({table}): {inserted:,} rows committed…", flush=True)

            if batch:
                _bulk_upsert(cur, table, col_list, placeholders, update_clause, batch)
                inserted += len(batch)

            conn.commit()
            print(f"  upsert_table({table}): processed {inserted:,} rows total")
            return inserted
    except Exception as e:
        print(f"  ERROR upsert_table({table}): {e}")
        raise


def get_user_master_conn():
    """Direct connection to user_master_db — used for user CRUD."""
    return get_conn("user_master")


# ── ONE-TIME DBA SCRIPT — run this once in MySQL to add indexes ────────────────
# These indexes cut API filter queries from full-table scans to index seeks.
# With 50L rows this makes a massive difference (Bug #2 performance fix).
#
# CREATE INDEX idx_ecp_project  ON ecp_db.ecp(project_name(64));
# CREATE INDEX idx_ecp_centre   ON ecp_db.ecp(centre_name(64));
# CREATE INDEX idx_ecp_status   ON ecp_db.ecp(candidate_last_status(32));
# CREATE INDEX idx_ecp_batch    ON ecp_db.ecp(batch_id(32));
# CREATE INDEX idx_att_batch_cand ON attendance_db.attendance_data(batch_id(32), candidate_id(32));
# CREATE INDEX idx_fa_batch_cand  ON fa_db.fa(batch_id(32), candidate_id(32));
