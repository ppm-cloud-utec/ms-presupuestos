"""Conexion a RDS PostgreSQL con aislamiento por schema de tenant."""
import os
from contextlib import contextmanager

import psycopg

from src import secretos, tenants


def _dsn():
    if os.environ.get("DB_PASSWORD"):  # solo para pruebas locales
        _u, _p = os.environ["DB_USER"], os.environ["DB_PASSWORD"]
    else:
        _s = os.environ["DB_SECRETO"]
        _u, _p = secretos.campo(_s, "username"), secretos.campo(_s, "password")
    return (
        f"host={os.environ['DB_HOST']} port=5432 "
        f"dbname={os.environ['DB_NAME']} "
        f"user={_u} password={_p} "
        f"connect_timeout=5"
    )


@contextmanager
def conexion(tenant_id):
    """Abre la conexion y fija el search_path al schema del tenant."""
    schema = tenants.schema_de(tenant_id)
    if not schema:
        raise ValueError(f"tenant desconocido: {tenant_id}")
    con = psycopg.connect(_dsn())
    try:
        with con.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@contextmanager
def conexion_admin():
    """Conexion SIN tenant, para crear o borrar el schema de uno nuevo."""
    with psycopg.connect(_dsn()) as con:
        yield con
