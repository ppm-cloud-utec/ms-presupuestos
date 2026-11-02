"""Worker SQS de ms-presupuestos.

Consume:
    proyecto.creado    -> crea el presupuesto en 0 (nadie lo pide por HTTP)
    recurso.asignado   -> proyecta el costo de horas-hombre

Este microservicio no conoce a ms-portafolios ni a ms-recursos: solo escucha.
"""
import json

from psycopg.rows import dict_row

from src import db


def _ya_procesado(cur, evento_id, tipo):
    """Idempotencia, en la misma transaccion que el efecto."""
    cur.execute("""
        INSERT INTO eventos_procesados (evento_id, tipo)
        VALUES (%s, %s) ON CONFLICT (evento_id) DO NOTHING
        RETURNING evento_id
    """, (evento_id, tipo))
    return cur.fetchone() is None


def _crear_presupuesto(cur, datos):
    """El presupuesto nace en 0 y en estado borrador.

    ON CONFLICT DO NOTHING porque el evento puede llegar dos veces desde SNS
    antes de que la tabla de idempotencia lo registre (dos lotes distintos).
    """
    cur.execute("""
        INSERT INTO presupuestos
            (proyecto_id, codigo_proyecto, nombre_proyecto, monto_aprobado, estado)
        VALUES (%s, %s, %s, 0, 'borrador')
        ON CONFLICT (proyecto_id) DO NOTHING
        RETURNING id
    """, (int(datos["proyecto_id"]), datos.get("codigo"), datos.get("nombre")))
    return cur.fetchone()


def _proyectar_costo(cur, datos):
    """Costo proyectado de un recurso asignado a un proyecto.

    El costo_proyectado es una columna generada: horas x costo_hora x semanas.
    """
    cur.execute("SELECT id FROM presupuestos WHERE proyecto_id = %s",
                (int(datos["proyecto_id"]),))
    presupuesto = cur.fetchone()
    if not presupuesto:
        # El proyecto es de otro tenant o el evento llego antes que
        # proyecto.creado. Se descarta: el reintento de SQS lo resolvera.
        return None

    cur.execute("""
        INSERT INTO proyecciones_costo
            (presupuesto_id, recurso_id, horas_semana, costo_hora, semanas)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (presupuesto_id, recurso_id) DO UPDATE
        SET horas_semana = EXCLUDED.horas_semana,
            costo_hora   = EXCLUDED.costo_hora,
            semanas      = EXCLUDED.semanas
        RETURNING costo_proyectado
    """, (presupuesto["id"], datos["recurso_id"],
          datos.get("horas_semana", 0), datos.get("costo_hora", 0),
          datos.get("semanas", 1)))
    return cur.fetchone()


def manejar(event, context):
    procesados, omitidos = 0, 0

    for registro in event["Records"]:
        sobre = json.loads(registro["body"])
        evento = json.loads(sobre["Message"]) if "Message" in sobre else sobre

        tipo = evento["tipo"]
        datos = evento.get("datos", {})

        with db.conexion(evento["tenant_id"]) as con:
            with con.cursor(row_factory=dict_row) as cur:
                if _ya_procesado(cur, evento["evento_id"], tipo):
                    omitidos += 1
                    continue

                if tipo == "proyecto.creado":
                    _crear_presupuesto(cur, datos)
                elif tipo == "recurso.asignado":
                    _proyectar_costo(cur, datos)
                else:
                    omitidos += 1
                    continue

                procesados += 1

    return {"procesados": procesados, "omitidos": omitidos}
