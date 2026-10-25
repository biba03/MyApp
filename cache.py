"""
cache.py

SQLite-backed OHLCV cache.

Stores price history for every ticker in one on-disk SQLite database
(cache/market_data.db) instead of one pickle file per ticker. Every
save/update is a row-level upsert keyed on (ticker, date), so running
this a second day only inserts the handful of new rows since the last
cached date - it never re-writes or re-downloads history that's
already there.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import config


class Cache:

    def __init__(self, path=None, max_age_hours=20):

        # Anchor to config.CACHE_DIR (absolute, based on the project's
        # own folder) rather than a cwd-relative path - otherwise
        # launching Jupyter from a different starting directory
        # silently creates a brand-new, empty database instead of
        # finding the one from last time.
        self.path = Path(path) if path else (config.CACHE_DIR / "market_data.db")

        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.max_age_hours = max_age_hours

        self._init_db()

    ####################################################################
    # Connection
    ####################################################################

    def _connect(self):

        conn = sqlite3.connect(self.path)

        # WAL mode + a busy timeout let multiple downloader threads
        # write to the same file concurrently without "database is
        # locked" errors under normal load.
        conn.execute("PRAGMA journal_mode=WAL")

        conn.execute("PRAGMA busy_timeout=30000")

        return conn

    def _init_db(self):

        conn = self._connect()

        try:

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prices (
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    PRIMARY KEY (ticker, date)
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    ticker TEXT PRIMARY KEY,
                    last_checked_at TEXT
                )
                """
            )

            conn.commit()

        finally:

            conn.close()

    ####################################################################
    # Save / load
    ####################################################################

    def save(self, key, value):
        """
        Upsert every row of `value` (a dataframe indexed by date, with
        Open/High/Low/Close/Volume columns) for ticker `key`.
        """

        self._upsert(key, value)

        self._touch(key)

    def load(self, key):

        conn = self._connect()

        try:

            df = pd.read_sql_query(
                "SELECT date, open, high, low, close, volume "
                "FROM prices WHERE ticker = ? ORDER BY date",
                conn,
                params=(key,),
            )

        finally:

            conn.close()

        if df.empty:

            return None

        df["date"] = pd.to_datetime(df["date"])

        df = df.set_index("date")

        df.index.name = None

        df.columns = ["Open", "High", "Low", "Close", "Volume"]

        return df

    ####################################################################
    # Freshness
    ####################################################################

    def is_fresh(self, key):
        """
        True if `key` was successfully updated within `max_age_hours`.
        Lets downloader.py skip re-checking tickers that were already
        refreshed earlier the same trading day.
        """

        conn = self._connect()

        try:

            row = conn.execute(
                "SELECT last_checked_at FROM meta WHERE ticker = ?",
                (key,),
            ).fetchone()

        finally:

            conn.close()

        if row is None:

            return False

        last_checked = datetime.fromisoformat(row[0])

        return datetime.now() - last_checked < timedelta(hours=self.max_age_hours)

    ####################################################################
    # Last cached date
    ####################################################################

    def last_date(self, key):
        """
        Most recent date already cached for `key`, or None if nothing
        is cached yet. downloader.py uses this to start the next
        download just a few days before this date instead of from
        START_DATE.
        """

        conn = self._connect()

        try:

            row = conn.execute(
                "SELECT MAX(date) FROM prices WHERE ticker = ?",
                (key,),
            ).fetchone()

        finally:

            conn.close()

        if row is None or row[0] is None:

            return None

        return pd.Timestamp(row[0])

    ####################################################################
    # Incremental update
    ####################################################################

    def update(self, key, new_df):
        """
        Upsert just the newly downloaded rows (typically the last few
        days) and return the full merged history for `key`.
        """

        self._upsert(key, new_df)

        self._touch(key)

        return self.load(key)

    ####################################################################
    # Internal helpers
    ####################################################################

    def _upsert(self, key, df):

        if df is None or len(df) == 0:

            return

        rows = [
            (
                key,
                idx.strftime("%Y-%m-%d"),
                float(row.Open),
                float(row.High),
                float(row.Low),
                float(row.Close),
                float(row.Volume),
            )
            for idx, row in df.iterrows()
        ]

        conn = self._connect()

        try:

            conn.executemany(
                """
                INSERT INTO prices (ticker, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, date) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume
                """,
                rows,
            )

            conn.commit()

        finally:

            conn.close()

    def _touch(self, key):

        conn = self._connect()

        try:

            conn.execute(
                """
                INSERT INTO meta (ticker, last_checked_at) VALUES (?, ?)
                ON CONFLICT(ticker) DO UPDATE SET last_checked_at=excluded.last_checked_at
                """,
                (key, datetime.now().isoformat()),
            )

            conn.commit()

        finally:

            conn.close()


# Shared cache instance used across the project (downloader.py imports this).
cache = Cache()
