from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from . import config


def connect(dbname: str | None = None):
    dsn = config.dsn()
    if dbname:
        parts = []
        for part in dsn.split():
            if part.startswith("dbname="):
                parts.append(f"dbname={dbname}")
            else:
                parts.append(part)
        dsn = " ".join(parts)
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    return conn


@contextmanager
def cursor(conn=None, commit=True):
    own = conn is None
    if own:
        conn = connect()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cur
        if commit:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        if own:
            conn.close()


def vec_literal(values) -> str:
    return "[" + ",".join(f"{float(x):.8f}" for x in values) + "]"
