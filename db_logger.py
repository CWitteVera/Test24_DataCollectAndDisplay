"""
db_logger.py – SQLite logger for conveyor zone box counts.

Schema
------
zone_events   – every entry/exit event with its timestamp and resulting count
daily_totals  – one row per (date, zone) accumulating the entry count

The daily-total row is updated only on entry events (a box arriving).
Exit events are logged to zone_events for auditability but do not change
daily_totals because the box was already counted on entry.
"""

import sqlite3
import os
from datetime import date, datetime
from threading import Lock

DB_FILE = "conveyor_data.db"


class DBLogger:
    """Thread-safe SQLite logger for conveyor zone events."""

    def __init__(self, db_file=DB_FILE):
        self._db_file = db_file
        self._lock = Lock()
        self._init_db()

    # ── schema ─────────────────────────────────────────────────────────

    def _init_db(self):
        with sqlite3.connect(self._db_file) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS zone_events (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT    NOT NULL,
                    zone      TEXT    NOT NULL,
                    event     TEXT    NOT NULL,
                    count     INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_totals (
                    date  TEXT    NOT NULL,
                    zone  TEXT    NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (date, zone)
                )
            """)
            conn.commit()

    # ── write operations ───────────────────────────────────────────────

    def log_event(self, zone, event_type, count, timestamp=None):
        """
        Persist a zone event.

        :param zone:       Zone label, e.g. "L1Z1"
        :param event_type: "entry" or "exit"
        :param count:      Current box count after the event
        :param timestamp:  datetime object; defaults to now
        """
        if timestamp is None:
            timestamp = datetime.now()
        ts_str = timestamp.isoformat(timespec="seconds")
        today = str(timestamp.date())

        with self._lock:
            with sqlite3.connect(self._db_file) as conn:
                conn.execute(
                    "INSERT INTO zone_events (timestamp, zone, event, count) VALUES (?, ?, ?, ?)",
                    (ts_str, zone, event_type, count),
                )
                if event_type == "entry":
                    conn.execute(
                        """
                        INSERT INTO daily_totals (date, zone, total) VALUES (?, ?, 1)
                        ON CONFLICT(date, zone) DO UPDATE SET total = total + 1
                        """,
                        (today, zone),
                    )
                conn.commit()

    # ── read operations ────────────────────────────────────────────────

    def get_daily_totals(self, query_date=None):
        """
        Return {zone: total} for the given date (defaults to today).
        Zones with no entries for the date are returned as 0.
        """
        if query_date is None:
            query_date = str(date.today())
        with sqlite3.connect(self._db_file) as conn:
            rows = conn.execute(
                "SELECT zone, total FROM daily_totals WHERE date = ?",
                (query_date,),
            ).fetchall()
        return {row[0]: row[1] for row in rows}
