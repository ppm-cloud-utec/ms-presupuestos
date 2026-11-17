"""Conexion a RDS PostgreSQL con aislamiento por schema de tenant.

Patron del enunciado: Single Database, Multiple Schemas. Una database por
microservicio, y dentro un schema por tenant.
"""
import os
from contextlib import contextmanager

import psycopg

from src import secretos, tenants


def _dsn():
    # Las credenciales se resuelven aqui, no al desplegar: antes la clave
    # quedaba grabada como variable de entorno de la Lambda, visible en la
    # consola. Ver src/secretos.py.
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
    """Abre la conexion y fija el search_path al schema del tenant.

    De ahi en adelante los queries van sin prefijo: `SELECT * FROM proyectos`
    ya solo ve las filas de ese tenant.
    """
    # La lista de tenants vive en SSM, no en el codigo: ver src/tenants.py.
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
    """Conexion SIN tenant, para crear o borrar el schema de uno nuevo.

    `conexion(tenant_id)` exige que el tenant ya este habilitado y fija el
    search_path. En el alta pasa justo lo contrario: el schema todavia no
    existe. Por eso el aprovisionador entra por aqui.
    """
    with psycopg.connect(_dsn()) as con:
        yield con
