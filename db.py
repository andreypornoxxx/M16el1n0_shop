"""
Универсальный модуль базы данных.
Если есть DATABASE_URL (Railway PostgreSQL) — используем его.
Если нет — падаем на SQLite (для локальной разработки).
"""

import os
import sqlite3

DATABASE_URL = os.getenv("DATABASE_URL")  # Railway сам подставляет

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras

    def db_connect():
        con = psycopg2.connect(DATABASE_URL)
        return con

    # PostgreSQL использует %s вместо ?
    PH = "%s"

else:
    # Локально — SQLite
    PH = "?"

    def db_connect():
        con = sqlite3.connect("shop.db")
        con.row_factory = sqlite3.Row
        return con


def db_init():
    con = db_connect()
    cur = con.cursor()

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS products (
            id          SERIAL PRIMARY KEY,
            name        TEXT    NOT NULL,
            description TEXT    NOT NULL,
            price_stars INTEGER NOT NULL,
            content     TEXT,
            file_id     TEXT,
            file_name   TEXT,
            active      INTEGER DEFAULT 1
        )
    """)

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS sales (
            id         SERIAL PRIMARY KEY,
            user_id    BIGINT,
            product_id INTEGER,
            stars      INTEGER,
            ts         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id     BIGINT PRIMARY KEY,
            username    TEXT,
            plan        TEXT,
            sub_end     TIMESTAMP,
            activated   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.commit()
    cur.close()
    con.close()


def fetchall(query, params=()):
    query = query.replace("?", PH)
    con = db_connect()
    cur = con.cursor()
    cur.execute(query, params)
    if DATABASE_URL:
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    else:
        rows = cur.fetchall()
    cur.close()
    con.close()
    return rows


def fetchone(query, params=()):
    query = query.replace("?", PH)
    con = db_connect()
    cur = con.cursor()
    cur.execute(query, params)
    if DATABASE_URL:
        cols = [d[0] for d in cur.description]
        row  = cur.fetchone()
        result = dict(zip(cols, row)) if row else None
    else:
        result = cur.fetchone()
    cur.close()
    con.close()
    return result


def execute(query, params=()):
    query = query.replace("?", PH)
    con = db_connect()
    cur = con.cursor()
    cur.execute(query, params)
    lastrowid = cur.lastrowid if not DATABASE_URL else None
    if DATABASE_URL and "RETURNING id" in query:
        lastrowid = cur.fetchone()[0]
    con.commit()
    cur.close()
    con.close()
    return lastrowid
