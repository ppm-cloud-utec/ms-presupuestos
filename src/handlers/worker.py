
"""Worker SQS de ms-presupuestos."""

import json

from psycopg.rows import dict_row

from src import db


EVENTOS_SOPORTADOS = {
    "proyecto.creado",
    "recurso.asignado"
}


def _ya_procesado(cur, evento_id, tipo):
    """Registra el evento de forma idempotente."""
    cur.execute("""
        INSERT INTO eventos_procesados (evento_id, tipo)
        VALUES (%s, %s)
        ON CONFLICT (evento_id) DO NOTHING
        RETURNING evento_id
    """, (evento_id, tipo))

    return cur.fetchone() is None


def _crear_presupuesto(cur, datos):
    """Crea un presupuesto en estado borrador y monto cero."""
    cur.execute("""
        INSERT INTO presupuestos
            (proyecto_id, codigo_proyecto,
             nombre_proyecto, monto_aprobado, estado)
        VALUES (%s, %s, %s, 0, 'borrador')
        ON CONFLICT (proyecto_id) DO NOTHING
        RETURNING id
    """, (
        int(datos["proyecto_id"]),
        datos.get("codigo"),
        datos.get("nombre")
    ))

    return cur.fetchone()


def _proyectar_costo(cur, datos):
    """Registra o actualiza el costo proyectado de un recurso."""
    cur.execute("""
        SELECT id
        FROM presupuestos
        WHERE proyecto_id = %s
    """, (int(datos["proyecto_id"]),))

    presupuesto = cur.fetchone()

    if not presupuesto:
        raise RuntimeError(
            "El presupuesto del proyecto "
            f"{datos['proyecto_id']} aun no existe. "
            "El evento debe reintentarse."
        )

    cur.execute("""
        INSERT INTO proyecciones_costo
            (presupuesto_id, recurso_id,
             horas_semana, costo_hora, semanas)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (presupuesto_id, recurso_id)
        DO UPDATE SET
            horas_semana = EXCLUDED.horas_semana,
            costo_hora = EXCLUDED.costo_hora,
            semanas = EXCLUDED.semanas
        RETURNING costo_proyectado
    """, (
        presupuesto["id"],
        int(datos["recurso_id"]),
        datos.get("horas_semana", 0),
        datos.get("costo_hora", 0),
        datos.get("semanas", 1)
    ))

    return cur.fetchone()


def _procesar(registro):
    """Procesa un mensaje. Devuelve True si se aplico y False si se omitio."""
    sobre = json.loads(registro["body"])
    evento = json.loads(sobre["Message"]) if "Message" in sobre else sobre

    tipo = evento["tipo"]
    if tipo not in EVENTOS_SOPORTADOS:
        return False

    datos = evento.get("datos", {})
    with db.conexion(evento["tenant_id"]) as con:
        with con.cursor(row_factory=dict_row) as cur:
            if _ya_procesado(cur, evento["evento_id"], tipo):
                return False
            if tipo == "proyecto.creado":
                _crear_presupuesto(cur, datos)
            elif tipo == "recurso.asignado":
                _proyectar_costo(cur, datos)
    return True


def manejar(event, context):
    """Procesa los mensajes de SQS; solo los que fallan vuelven a la cola."""
    procesados, omitidos, fallidos = 0, 0, []

    for registro in event["Records"]:
        try:
            if _procesar(registro):
                procesados += 1
            else:
                omitidos += 1
        except Exception as exc:
            print(f"ERROR mensaje {registro.get('messageId')}: {type(exc).__name__}: {exc}")
            fallidos.append({"itemIdentifier": registro.get("messageId")})

    return {
        "procesados": procesados,
        "omitidos": omitidos,
        "batchItemFailures": fallidos
    }
