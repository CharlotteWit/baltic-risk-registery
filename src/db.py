"""
db.py — creates the SQLite database and its schema, and provides safe helpers
for reading/writing it.

Design notes (these enforce the project's non-negotiable rules):

* The `facts` table is APPEND-ONLY. We never UPDATE a fact in place. When a
  source reports a new value for a field (e.g. a vessel changes flag), we INSERT
  a new row with its own retrieved_at. The "current" value of a field is simply
  the most recently retrieved fact for that (imo, field). This means identity
  history (renames, reflagging) is preserved automatically — which the risk
  rules R3/R4 depend on.

* Facts live in `facts`/`positions`/`list_membership`. Inferences (things WE
  computed) live only in `port_calls`/`risk_flags`/`risk_scores`, and each
  carries an `evidence` reference back to the facts/positions it was built from.

* Every fact row must carry source_id + source_url + retrieved_at. The
  provenance gate in provenance.py enforces this before anything reaches here.
"""

import sqlite3
from pathlib import Path

# The single local database file lives in data/register.db
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "register.db"

SCHEMA = """
-- One row per data source. Everything else points back to this.
CREATE TABLE IF NOT EXISTS sources (
    source_id    TEXT PRIMARY KEY,   -- short stable id, e.g. 'opensanctions', 'eu_fsf', 'kse', 'gur'
    name         TEXT NOT NULL,      -- human-readable name
    type         TEXT NOT NULL,      -- sanctions | list | registry | psc | ais
    url          TEXT,               -- homepage / API root
    license      TEXT,               -- licensing terms (e.g. 'CC-BY-NC for non-commercial use')
    accessed_at  TEXT                -- UTC ISO-8601 of when we last used this source
);

-- THE CORE TABLE. One row per (vessel, field, value). Append-only.
CREATE TABLE IF NOT EXISTS facts (
    fact_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    imo          TEXT NOT NULL,      -- vessel IMO number (primary join key; see imo_verified)
    field        TEXT NOT NULL,      -- e.g. built_year, flag, name, insurer, vessel_type, mmsi
    value        TEXT,               -- the value as reported (NULL allowed only with field marked unknown)
    source_id    TEXT NOT NULL REFERENCES sources(source_id),
    source_url   TEXT NOT NULL,      -- exact URL / API endpoint this value came from
    retrieved_at TEXT NOT NULL,      -- UTC ISO-8601 timestamp of retrieval
    note         TEXT                -- optional free-text (e.g. 'via OpenSanctions, originally KSE')
);
CREATE INDEX IF NOT EXISTS idx_facts_imo_field ON facts (imo, field, retrieved_at);

-- AIS position pings (facts about where a vessel was).
CREATE TABLE IF NOT EXISTS positions (
    position_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    imo          TEXT,               -- may be NULL if only MMSI is known in a ping
    mmsi         TEXT,
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    sog          REAL,               -- speed over ground (knots)
    cog          REAL,               -- course over ground (degrees)
    nav_status   TEXT,
    timestamp    TEXT NOT NULL,      -- UTC ISO-8601 of the ping
    source_id    TEXT NOT NULL REFERENCES sources(source_id),
    confidence   TEXT,               -- e.g. 'normal' | 'low' (impossible jump / suspected spoof)
    ais_ship_type INTEGER,           -- raw AIS ship-type code (ITU-R M.1371), if known
    type_category TEXT               -- our category: tanker/cargo/unknown/other/... (see ais_types.py)
);
CREATE INDEX IF NOT EXISTS idx_positions_imo_ts ON positions (imo, timestamp);
CREATE INDEX IF NOT EXISTS idx_positions_mmsi_ts ON positions (mmsi, timestamp);

-- Which lists name a vessel (for cross-source reconciliation).
CREATE TABLE IF NOT EXISTS list_membership (
    membership_id INTEGER PRIMARY KEY AUTOINCREMENT,
    imo          TEXT NOT NULL,
    list_name    TEXT NOT NULL,      -- EU | OpenSanctions | KSE | GUR | UK | OFAC
    present      INTEGER NOT NULL,   -- 1 = listed, 0 = explicitly checked and absent
    as_of        TEXT NOT NULL,      -- UTC ISO-8601
    source_url   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listmem_imo ON list_membership (imo);

-- INFERRED: port calls computed from position history.
CREATE TABLE IF NOT EXISTS port_calls (
    port_call_id INTEGER PRIMARY KEY AUTOINCREMENT,
    imo          TEXT NOT NULL,
    port         TEXT,
    country      TEXT,
    arrival      TEXT,               -- UTC ISO-8601
    departure    TEXT,               -- UTC ISO-8601
    method_note  TEXT NOT NULL,      -- how this was inferred
    evidence     TEXT NOT NULL       -- refs to position_id rows used (e.g. JSON list)
);

-- INFERRED: which risk rules fired for a vessel.
CREATE TABLE IF NOT EXISTS risk_flags (
    flag_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    imo          TEXT NOT NULL,
    rule_id      TEXT NOT NULL,      -- e.g. R1, R3 (matches rules.yaml)
    triggered    INTEGER NOT NULL,   -- 1 / 0
    evidence     TEXT NOT NULL,      -- refs to fact_id / position_id rows behind this
    weight       INTEGER NOT NULL,
    evaluated_at TEXT NOT NULL       -- UTC ISO-8601
);
CREATE INDEX IF NOT EXISTS idx_riskflags_imo ON risk_flags (imo);

-- INFERRED, recomputable: the total score + band per vessel.
CREATE TABLE IF NOT EXISTS risk_scores (
    score_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    imo          TEXT NOT NULL,
    total_score  INTEGER NOT NULL,
    band         TEXT NOT NULL,      -- low | elevated | high
    computed_at  TEXT NOT NULL       -- UTC ISO-8601
);
CREATE INDEX IF NOT EXISTS idx_riskscores_imo ON risk_scores (imo);

-- Dated identity-change tracking for the fields shadow-fleet vessels alter most:
-- IMO number, flag, and name. These are FACTS (source-reported), with the dates
-- coming straight from the source's own statement history (first_seen/last_seen),
-- NOT from when we happened to fetch them. This is what lets us honestly say
-- "a new IMO/flag/name was first observed in the last 3 months" with evidence.
--
-- One row per (vessel, field, value, originating list). first_seen/last_seen are
-- the source's observation window for that value; they are a traceable proxy for
-- when a change occurred, NOT a claim about the exact day the vessel changed.
CREATE TABLE IF NOT EXISTS identity_history (
    history_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    imo            TEXT NOT NULL,      -- vessel key (the primary IMO we keyed on)
    field          TEXT NOT NULL,      -- imo_number | flag | name
    value          TEXT NOT NULL,
    source_id      TEXT NOT NULL REFERENCES sources(source_id),
    origin_dataset TEXT,               -- underlying list, e.g. eu_journal_sanctions
    source_url     TEXT NOT NULL,      -- spot-checkable entity page
    first_seen     TEXT,               -- SOURCE-provided UTC ISO: first observed
    last_seen      TEXT,               -- SOURCE-provided UTC ISO: last observed
    retrieved_at   TEXT NOT NULL,      -- when WE fetched it (UTC ISO)
    UNIQUE (imo, field, value, source_id, origin_dataset)
);
CREATE INDEX IF NOT EXISTS idx_idhist_imo_field ON identity_history (imo, field);
"""


def connect(db_path=DEFAULT_DB_PATH):
    """Open (creating the data/ folder if needed) and return a SQLite connection."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn):
    """Add columns introduced after a database was first created. Idempotent."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(positions)")}
    for name, decl in (("ais_ship_type", "INTEGER"), ("type_category", "TEXT")):
        if name not in cols:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {name} {decl}")


def init_db(db_path=DEFAULT_DB_PATH):
    """Create all tables if they do not exist (and migrate). Safe to run repeatedly."""
    conn = connect(db_path)
    with conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
    return conn


def upsert_source(conn, source_id, name, type, url=None, license=None, accessed_at=None):
    """Insert or update a row in the sources table."""
    with conn:
        conn.execute(
            """
            INSERT INTO sources (source_id, name, type, url, license, accessed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                name=excluded.name, type=excluded.type, url=excluded.url,
                license=excluded.license, accessed_at=excluded.accessed_at
            """,
            (source_id, name, type, url, license, accessed_at),
        )


def current_profile(conn, imo):
    """
    Assemble a vessel's CURRENT profile: the most recently retrieved fact per
    field, each still carrying its source. Returns a list of fact rows.

    A 'profile' is never stored as a single row — it is always derived from the
    append-only facts table, so every value keeps its provenance.
    """
    rows = conn.execute(
        """
        SELECT f.*
        FROM facts f
        JOIN (
            SELECT field, MAX(retrieved_at) AS max_ret
            FROM facts
            WHERE imo = ?
            GROUP BY field
        ) latest
          ON f.field = latest.field AND f.retrieved_at = latest.max_ret
        WHERE f.imo = ?
        ORDER BY f.field
        """,
        (imo, imo),
    ).fetchall()
    return rows


if __name__ == "__main__":
    # Running this file directly creates the database and prints the tables.
    conn = init_db()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    print("Database ready at:", DEFAULT_DB_PATH)
    print("Tables created:", ", ".join(r["name"] for r in tables))
