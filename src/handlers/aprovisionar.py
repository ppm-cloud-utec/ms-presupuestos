"""Alta y baja del almacenamiento de un tenant en ESTE microservicio."""
import os

from psycopg import sql

from src import db, tenants

# Nunca se borran por compensacion, pase lo que pase.
PROTEGIDOS = frozenset({"t-acme", "t-globex", "t-initech"})

RUTA_DDL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "seed", "esquema.sql")


def _servicio():
    return os.environ.get("SERVICIO", os.environ.get("DB_NAME", "desconocido"))


def aprovisionar(event, context):
    """Crea el schema del tenant y aplica el DDL de este servicio."""
    tenant_id = event["tenant_id"]
    schema = tenants.esquema_para(tenant_id)
    usuario = os.environ["DB_USER"]

    with open(RUTA_DDL, encoding="utf-8") as f:
        ddl = f.read()

    with db.conexion_admin() as con:
        with con.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION {}")
                        .format(sql.Identifier(schema), sql.Identifier(usuario)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cur.execute(ddl)
            cur.execute("""
                SELECT count(*) FROM information_schema.tables
                WHERE table_schema = %s
            """, (schema,))
            tablas = cur.fetchone()[0]
        con.commit()

    return {"servicio": _servicio(), "tenant_id": tenant_id,
            "schema": schema, "tablas": tablas, "ok": True}


def compensar(event, context):
    """Deshace el alta: elimina el schema del tenant."""
    tenant_id = event["tenant_id"]
    if tenant_id in PROTEGIDOS:
        raise PermissionError(
            f"{tenant_id} es un tenant original: no se compensa jamas")
    schema = tenants.esquema_para(tenant_id)

    with db.conexion_admin() as con:
        with con.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE")
                        .format(sql.Identifier(schema)))
        con.commit()

    return {"servicio": _servicio(), "tenant_id": tenant_id,
            "schema": schema, "revertido": True}
