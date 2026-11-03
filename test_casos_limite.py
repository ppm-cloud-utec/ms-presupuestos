
"""Pruebas locales de casos limite para ms-presupuestos.

Ejecutar desde la raiz del repositorio:
    python test_casos_limite.py

Requiere PostgreSQL local, los tres schemas del seed y variables DB_*.
SNS siempre se simula: no se envian mensajes a AWS.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import db
from src.handlers import presupuestos, worker
from src import eventos


TENANT = "t-acme"
RESULTADOS = []


def revisar(nombre, fn):
    try:
        fn()
        RESULTADOS.append((nombre, "OK"))
        print(f"[OK] {nombre}")
    except Exception as exc:
        RESULTADOS.append((nombre, "FALLO"))
        print(f"[FALLO] {nombre}: {type(exc).__name__}: {exc}")


def api_event(rol="pmo", monto=10000, proyecto_id=25, partidas=None):
    payload = {"monto_aprobado": monto}

    if partidas is not None:
        payload["partidas"] = partidas

    return {
        "requestContext": {
            "authorizer": {
                "tenant_id": TENANT,
                "rol": rol,
                "usuario_id": str(uuid4())
            }
        },
        "pathParameters": {
            "proyecto_id": str(proyecto_id)
        },
        "body": json.dumps(payload)
    }


def mensaje(
    tipo,
    proyecto_id,
    evento_id=None,
    datos=None,
    tenant=TENANT,
    sns=True
):
    e = {
        "evento_id": evento_id or str(uuid4()),
        "tipo": tipo,
        "tenant_id": tenant,
        "datos": (
            datos if datos is not None
            else {"proyecto_id": proyecto_id}
        )
    }

    body = (
        {"Message": json.dumps(e)}
        if sns else e
    )

    return {
        "Records": [
            {"body": json.dumps(body)}
        ]
    }, e["evento_id"]


# ==========================================================
# PRUEBA 1: ROLES Y VALIDACIONES
# ==========================================================

def comprobar_validacion():
    casos = [
        ("pm", 100, 403, None),
        ("miembro", 100, 403, None),
        ("pmo", -1, 400, None),
        ("pmo", "abc", 400, None),
        ("pmo", "NaN", 400, None),
        ("pmo", "Infinity", 400, None),
        (
            "pmo",
            10000,
            400,
            {"Personal": 0.8, "Servicios": 0.1}
        )
    ]

    for rol, monto, estado, partidas in casos:
        respuesta = presupuestos.aprobar(
            api_event(
                rol=rol,
                monto=monto,
                partidas=partidas
            ),
            None
        )

        assert respuesta["statusCode"] == estado, (
            rol, monto, respuesta
        )


# ==========================================================
# PRUEBA 2: TENANT DESCONOCIDO
# ==========================================================

def comprobar_tenant_desconocido():
    try:
        with db.conexion("t_no_existe"):
            pass

    except ValueError as exc:
        assert "tenant desconocido" in str(exc)

    else:
        raise AssertionError(
            "Acepto tenant desconocido"
        )


# ==========================================================
# PRUEBA 3: EVENTO DESCONOCIDO
# ==========================================================

def comprobar_evento_desconocido():
    prueba, _ = mensaje(
        "evento.desconocido",
        -5
    )

    with patch.object(
        worker.db,
        "conexion",
        side_effect=AssertionError("No debe abrir BD")
    ):
        r = worker.manejar(prueba, None)

    assert r == {
        "procesados": 0,
        "omitidos": 1
    }, r


# ==========================================================
# PRUEBA 4: PUBLICACION SNS SIMULADA
# ==========================================================

def comprobar_sns_simulado():
    sns = MagicMock()

    sns.publish.return_value = {
        "MessageId": "mock-001"
    }

    with patch.dict(
        os.environ,
        {
            "SNS_TOPIC_ARN": (
                "arn:aws:sns:us-east-1:"
                "123456789012:prueba"
            ),
            "SERVICIO": "ms-presupuestos"
        }
    ):
        with patch.object(
            eventos.boto3,
            "client",
            return_value=sns
        ):
            identificador = eventos.publicar(
                "gasto.registrado",
                TENANT,
                {"monto": 10}
            )

    assert sns.publish.call_count == 1

    kwargs = sns.publish.call_args.kwargs
    datos = json.loads(kwargs["Message"])

    assert datos["evento_id"] == identificador
    assert datos["tenant_id"] == TENANT

    assert (
        kwargs["MessageAttributes"]["tipo"]["StringValue"]
        == "gasto.registrado"
    )

    assert (
        kwargs["MessageAttributes"]["tenant_id"]["StringValue"]
        == TENANT
    )


# ==========================================================
# PRUEBA 5: RECURSO ANTES DE CREAR PROYECTO
# ==========================================================

def comprobar_reintento_sin_proyecto():
    proyecto_id = -(
        uuid4().int % 1_000_000_000 + 1
    )

    datos = {
        "proyecto_id": proyecto_id,
        "recurso_id": str(uuid4()),
        "horas_semana": 10,
        "costo_hora": 30,
        "semanas": 2
    }

    evento, evento_id = mensaje(
        "recurso.asignado",
        proyecto_id,
        datos=datos
    )

    try:
        worker.manejar(evento, None)

    except RuntimeError as exc:
        assert "no existe" in str(exc), str(exc)

    else:
        raise AssertionError(
            "No genero error al faltar el proyecto"
        )

    # Verificar que PostgreSQL hizo ROLLBACK
    with db.conexion(TENANT) as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM eventos_procesados
                WHERE evento_id = %s
            """, (evento_id,))

            assert cur.fetchone()[0] == 0, (
                "El evento fallido quedo marcado "
                "como procesado"
            )


# ==========================================================
# PRUEBA 6: WORKER E IDEMPOTENCIA
# ==========================================================

def comprobar_worker_integral():
    proyecto_id = -(
        uuid4().int % 1_000_000_000 + 1
    )

    codigo = f"TEST-LIM-{abs(proyecto_id)}"
    recurso_id = str(uuid4())

    e_crear, id_crear = mensaje(
        "proyecto.creado",
        proyecto_id,
        datos={
            "proyecto_id": proyecto_id,
            "codigo": codigo,
            "nombre": "Prueba casos limite"
        }
    )

    ids_eventos = [id_crear]

    try:
        # Primera entrega: crear presupuesto
        resultado1 = worker.manejar(e_crear, None)

        assert resultado1["procesados"] == 1

        # Segunda entrega: evento duplicado
        resultado2 = worker.manejar(e_crear, None)

        assert resultado2["omitidos"] == 1

        # Asignar recurso
        e_rec, id_rec = mensaje(
            "recurso.asignado",
            proyecto_id,
            datos={
                "proyecto_id": proyecto_id,
                "recurso_id": recurso_id,
                "horas_semana": 10,
                "costo_hora": 30,
                "semanas": 2
            }
        )

        ids_eventos.append(id_rec)

        resultado3 = worker.manejar(e_rec, None)

        assert resultado3["procesados"] == 1

        # Repetir la asignacion
        resultado4 = worker.manejar(e_rec, None)

        assert resultado4["omitidos"] == 1

        # Comprobar resultados en PostgreSQL
        with db.conexion(TENANT) as con:
            with con.cursor() as cur:
                cur.execute("""
                    SELECT id, estado, monto_aprobado
                    FROM presupuestos
                    WHERE proyecto_id = %s
                """, (proyecto_id,))

                p = cur.fetchone()

                assert p is not None
                assert p[1] == "borrador"
                assert float(p[2]) == 0

                cur.execute("""
                    SELECT
                        COUNT(*),
                        COALESCE(SUM(costo_proyectado), 0)
                    FROM proyecciones_costo
                    WHERE presupuesto_id = %s
                """, (p[0],))

                numero, costo = cur.fetchone()

                assert numero == 1
                assert float(costo) == 600, (
                    numero, costo
                )

        # Comprobar aislamiento entre tenants
        with db.conexion("t-globex") as con:
            with con.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*)
                    FROM presupuestos
                    WHERE proyecto_id = %s
                """, (proyecto_id,))

                assert cur.fetchone()[0] == 0

    finally:
        # Eliminar datos temporales
        with db.conexion(TENANT) as con:
            with con.cursor() as cur:
                cur.execute("""
                    DELETE FROM presupuestos
                    WHERE proyecto_id = %s
                      AND codigo_proyecto = %s
                """, (proyecto_id, codigo))

                cur.execute("""
                    DELETE FROM eventos_procesados
                    WHERE evento_id = ANY(%s::uuid[])
                """, (ids_eventos,))


# ==========================================================
# PRUEBA 7: ALERTA DE PRESUPUESTO UNA SOLA VEZ
# ==========================================================

def comprobar_alerta_una_vez():
    proyecto_id = -(
        uuid4().int % 1_000_000_000 + 1
    )

    codigo = f"TEST-ALERTA-{abs(proyecto_id)}"

    with db.conexion(TENANT) as con:
        with con.cursor() as cur:
            cur.execute("""
                INSERT INTO presupuestos
                    (
                        proyecto_id,
                        codigo_proyecto,
                        nombre_proyecto,
                        estado,
                        monto_aprobado
                    )
                VALUES (%s, %s, %s, %s, %s)
            """, (
                proyecto_id,
                codigo,
                "Alerta temporal",
                "aprobado",
                10000
            ))

    try:
        with patch.object(
            presupuestos,
            "publicar"
        ) as enviar:

            # Primer gasto alcanza el 90%
            for monto in (9000, 100):
                e = {
                    "requestContext": {
                        "authorizer": {
                            "tenant_id": TENANT,
                            "rol": "pm",
                            "usuario_id": str(uuid4())
                        }
                    },
                    "pathParameters": {
                        "proyecto_id": str(proyecto_id)
                    },
                    "body": json.dumps({
                        "concepto": "Prueba alerta",
                        "monto": monto
                    })
                }

                r = presupuestos.registrar_gasto(
                    e, None
                )

                assert r["statusCode"] == 201, r

            tipos = [
                x.args[0]
                for x in enviar.call_args_list
            ]

            assert tipos.count(
                "gasto.registrado"
            ) == 2, tipos

            assert tipos.count(
                "presupuesto.excedido"
            ) == 1, tipos

        # Verificar el gasto y la bandera
        with db.conexion(TENANT) as con:
            with con.cursor() as cur:
                cur.execute("""
                    SELECT
                        total_gastado,
                        alerta_enviada
                    FROM presupuestos
                    WHERE proyecto_id = %s
                """, (proyecto_id,))

                total, alerta = cur.fetchone()

                assert float(total) == 9100
                assert alerta is True

    finally:
        # Limpiar datos temporales
        with db.conexion(TENANT) as con:
            with con.cursor() as cur:
                cur.execute("""
                    DELETE FROM presupuestos
                    WHERE proyecto_id = %s
                      AND codigo_proyecto = %s
                """, (proyecto_id, codigo))


# ==========================================================
# EJECUTAR TODAS LAS PRUEBAS
# ==========================================================

if __name__ == "__main__":
    print(
        "=== PRUEBAS FINALES ms-presupuestos ===",
        flush=True
    )

    revisar(
        "Roles, montos invalidos y partidas incorrectas",
        comprobar_validacion
    )

    revisar(
        "Tenant desconocido rechazado",
        comprobar_tenant_desconocido
    )

    revisar(
        "Evento desconocido sin acceso a BD",
        comprobar_evento_desconocido
    )

    revisar(
        "SNS publica formato esperado (mock)",
        comprobar_sns_simulado
    )

    revisar(
        "Recurso antes del proyecto: rollback",
        comprobar_reintento_sin_proyecto
    )

    revisar(
        "Worker: creacion, duplicados, costo y aislamiento",
        comprobar_worker_integral
    )

    revisar(
        "Registrar gasto: alerta emitida una sola vez",
        comprobar_alerta_una_vez
    )

    print("\n=== RESUMEN ===")

    for nombre, estado in RESULTADOS:
        print(f"{estado}: {nombre}")

    correctas = sum(
        estado == "OK"
        for _, estado in RESULTADOS
    )

    print(
        f"TOTAL: {correctas}/{len(RESULTADOS)}"
    )

    sys.exit(
        0 if all(
            estado == "OK"
            for _, estado in RESULTADOS
        ) else 1
    )
