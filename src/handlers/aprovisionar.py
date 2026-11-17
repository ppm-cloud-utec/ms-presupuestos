"""Alta y baja del almacenamiento de un tenant en ESTE microservicio.

Lo invoca la maquina de estados `ppm-aprovisionar-tenant` (infra-compartida).
La orquestacion no toca esta base de datos por su cuenta: llama a esta Lambda,
que es la unica que sabe que tablas necesita el servicio. Asi se cumple la
regla del enunciado de que cada microservicio es dueno de su propia BD, y a la
vez el alta de una organizacion es un solo flujo observable.

Dos pasos, los dos idempotentes:

    aprovisionar  crea el schema del tenant y aplica su DDL
    compensar     lo elimina, si un paso posterior del flujo fallo

`compensar` se niega a borrar los tres tenants originales: un rollback mal
disparado no puede llevarse por delante los datos de la demo.
"""
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
            # Identifier() cita el nombre correctamente; el regex de
            # tenants.py ya garantizo que solo trae [a-z0-9_].
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
    """Deshace el alta: elimina el schema del tenant.

    Solo lo llama el Catch de la maquina de estados. Es idempotente: si el
    schema no existe, no es un error.
    """
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
