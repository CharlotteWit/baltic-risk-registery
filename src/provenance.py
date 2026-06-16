"""
provenance.py — the single gate through which every fact must pass before it can
be stored. This is where the project's rule #1 ("provenance on every datum") and
rule #2 ("no invented data") are enforced by CODE, not by discipline.

Nothing should INSERT into the facts table directly. Connectors build a Fact and
call store_fact(); if it lacks a source_id, source_url, or retrieved_at, the
function raises and the value never reaches the database.
"""

from dataclasses import dataclass
from datetime import datetime, timezone


def utc_now_iso():
    """Current time as a UTC ISO-8601 string, e.g. '2026-06-16T08:30:00+00:00'."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_iso_utc(ts):
    """True if ts parses as an ISO-8601 datetime carrying timezone info."""
    if not isinstance(ts, str) or not ts.strip():
        return False
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    return dt.tzinfo is not None


@dataclass
class Fact:
    """One traceable value about a vessel. value=None is allowed ONLY when the
    field is being explicitly recorded as unknown (see store_unknown)."""
    imo: str
    field: str
    value: object
    source_id: str
    source_url: str
    retrieved_at: str
    note: str = None


class ProvenanceError(ValueError):
    """Raised when a value is missing the provenance it must carry to be stored."""


def _require(condition, message):
    if not condition:
        raise ProvenanceError(message)


def validate_fact(fact: Fact):
    """Raise ProvenanceError unless the fact carries complete provenance.

    Note: value may be None (an explicitly-unknown field), but the SOURCE of the
    statement 'this is unknown' must still be recorded. There is no such thing as
    a value — known or unknown — without a source in this system.
    """
    _require(isinstance(fact.imo, str) and fact.imo.strip(), "fact.imo is required")
    _require(isinstance(fact.field, str) and fact.field.strip(), "fact.field is required")
    _require(isinstance(fact.source_id, str) and fact.source_id.strip(),
             f"fact for {fact.imo}/{fact.field} has no source_id — refusing to store")
    _require(isinstance(fact.source_url, str) and fact.source_url.strip(),
             f"fact for {fact.imo}/{fact.field} has no source_url — refusing to store")
    _require(is_iso_utc(fact.retrieved_at),
             f"fact for {fact.imo}/{fact.field} has no valid UTC retrieved_at — refusing to store")
    return True


def store_fact(conn, fact: Fact):
    """Validate provenance, then append the fact. Returns the new fact_id.

    This is the ONLY sanctioned way to write to the facts table."""
    validate_fact(fact)
    value = None if fact.value is None else str(fact.value)
    with conn:
        cur = conn.execute(
            """
            INSERT INTO facts (imo, field, value, source_id, source_url, retrieved_at, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (fact.imo.strip(), fact.field.strip(), value,
             fact.source_id.strip(), fact.source_url.strip(),
             fact.retrieved_at, fact.note),
        )
        return cur.lastrowid


def store_unknown(conn, imo, field, source_id, source_url, retrieved_at=None, note="unknown"):
    """Record that a field is explicitly UNKNOWN per a source we actually checked.

    Use this instead of guessing. It still requires a real source — i.e. 'we
    looked at source X and it did not report this value'."""
    fact = Fact(
        imo=imo, field=field, value=None,
        source_id=source_id, source_url=source_url,
        retrieved_at=retrieved_at or utc_now_iso(),
        note=note,
    )
    return store_fact(conn, fact)
