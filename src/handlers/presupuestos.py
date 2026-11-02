"""Presupuesto aprobado, gastos y ejecucion presupuestal.

Responde LA pregunta del producto: cuanto se aprobo, cuanto se gasto y cuanto
queda. El presupuesto no se crea por HTTP: lo crea el worker cuando
ms-portafolios publica proyecto.creado.
"""
import os

from psycopg.rows import dict_row

from src import db, roles
from src.eventos import publicar
from src.respuesta import cuerpo_de, error, ok, tenant_de, usuario_de

# Al cruzar este porcentaje se publica presupuesto.excedido, que marca el
# proyecto en riesgo en ms-portafolios y manda la alerta al PMO.
UMBRAL_ALERTA = float(os.environ.get("UMBRAL_ALERTA_PCT", 90))


def listar(event, context):
    """GET /presupuestos?estado=&en_alerta=true&limite=&pagina="""
    q = event.get("queryStringParameters") or {}
    limite = min(int(q.get("limite", 50)), 200)
    pagina = max(int(q.get("pagina", 1)), 1)

    filtros, valores = ["TRUE"], []
    if q.get("estado"):
        filtros.append("estado = %s")
        valores.append(q["estado"])
    if q.get("en_alerta") == "true":
        filtros.append(f"ejecutado_pct >= {UMBRAL_ALERTA}")
    where = " AND ".join(filtros)

    with db.conexion(tenant_de(event)) as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM ejecucion WHERE {where}", valores)
            total = cur.fetchone()["n"]
            cur.execute(f"""
                SELECT * FROM ejecucion WHERE {where}
                ORDER BY ejecutado_pct DESC, proyecto_id
                LIMIT %s OFFSET %s
            """, valores + [limite, (pagina - 1) * limite])
            filas = cur.fetchall()

    return ok(filas, meta={"total": total, "pagina": pagina,
                           "umbral_alerta_pct": UMBRAL_ALERTA})


def obtener(event, context):
    """GET /presupuestos/{proyecto_id} — con partidas y ultimos gastos."""
    proyecto_id = event["pathParameters"]["proyecto_id"]
    with db.conexion(tenant_de(event)) as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM ejecucion WHERE proyecto_id = %s",
                        (proyecto_id,))
            presupuesto = cur.fetchone()
            if not presupuesto:
                return error("NO_ENCONTRADO",
                             f"El proyecto {proyecto_id} no tiene presupuesto", 404)

            cur.execute("""
                SELECT pa.id, pa.nombre, pa.monto_asignado,
                       COALESCE(SUM(g.monto), 0) AS gastado
                FROM   partidas pa
                LEFT JOIN gastos g ON g.partida_id = pa.id
                WHERE  pa.presupuesto_id = %s
                GROUP BY pa.id ORDER BY pa.nombre
            """, (presupuesto["id"],))
            presupuesto["partidas"] = cur.fetchall()

            cur.execute("""
                SELECT id, concepto, monto, fecha, proveedor, comprobante_key
                FROM   gastos WHERE presupuesto_id = %s
                ORDER BY fecha DESC, id DESC LIMIT 20
            """, (presupuesto["id"],))
            presupuesto["ultimos_gastos"] = cur.fetchall()

            cur.execute("""
                SELECT COALESCE(SUM(costo_proyectado), 0) AS costo_horas_hombre,
                       COUNT(*) AS recursos_asignados
                FROM   proyecciones_costo WHERE presupuesto_id = %s
            """, (presupuesto["id"],))
            presupuesto["proyeccion"] = cur.fetchone()

    return ok(presupuesto)


def aprobar(event, context):
    """POST /presupuestos/{proyecto_id}/aprobar — solo el PMO fija el monto."""
    negado = roles.exige(event, roles.PMO, roles.ADMIN)
    if negado:
        return negado

    proyecto_id = event["pathParameters"]["proyecto_id"]
    c = cuerpo_de(event)
    monto = c.get("monto_aprobado")
    if monto is None or float(monto) <= 0:
        return error("MONTO_INVALIDO", "Se requiere monto_aprobado mayor que 0")

    with db.conexion(tenant_de(event)) as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                UPDATE presupuestos
                SET    monto_aprobado = %s, estado = 'aprobado',
                       aprobado_por = %s, aprobado_en = now(),
                       alerta_enviada = FALSE
                WHERE  proyecto_id = %s
                RETURNING id
            """, (monto, usuario_de(event), proyecto_id))
            fila = cur.fetchone()
            if not fila:
                return error("NO_ENCONTRADO",
                             f"El proyecto {proyecto_id} no tiene presupuesto. "
                             "Se crea solo cuando ms-portafolios publica "
                             "proyecto.creado.", 404)

            # Partidas por defecto, si el PMO no definio ninguna
            for nombre, pct in c.get("partidas", {}).items() or \
                    {"Personal": 0.5, "Materiales": 0.3, "Servicios": 0.2}.items():
                cur.execute("""
                    INSERT INTO partidas (presupuesto_id, nombre, monto_asignado)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (presupuesto_id, nombre)
                    DO UPDATE SET monto_asignado = EXCLUDED.monto_asignado
                """, (fila["id"], nombre, float(monto) * float(pct)))

            cur.execute("SELECT * FROM ejecucion WHERE id = %s", (fila["id"],))
            presupuesto = cur.fetchone()

    return ok(presupuesto)


def listar_gastos(event, context):
    """GET /presupuestos/{proyecto_id}/gastos"""
    proyecto_id = event["pathParameters"]["proyecto_id"]
    q = event.get("queryStringParameters") or {}
    limite = min(int(q.get("limite", 100)), 300)

    with db.conexion(tenant_de(event)) as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT g.*, pa.nombre AS partida
                FROM   gastos g
                JOIN   presupuestos p ON p.id = g.presupuesto_id
                LEFT JOIN partidas pa ON pa.id = g.partida_id
                WHERE  p.proyecto_id = %s
                ORDER BY g.fecha DESC, g.id DESC
                LIMIT %s
            """, (proyecto_id, limite))
            filas = cur.fetchall()
    return ok(filas, meta={"total": len(filas), "proyecto_id": proyecto_id})


def registrar_gasto(event, context):
    """POST /presupuestos/{proyecto_id}/gastos

    Publica gasto.registrado siempre, y presupuesto.excedido la PRIMERA vez
    que la ejecucion cruza el umbral. Ese segundo evento marca el proyecto en
    riesgo en ms-portafolios y dispara la alerta al PMO.
    """
    negado = roles.exige(event, roles.PM, roles.PMO, roles.ADMIN)
    if negado:
        return negado

    tenant_id = tenant_de(event)
    proyecto_id = event["pathParameters"]["proyecto_id"]
    c = cuerpo_de(event)

    if not c.get("concepto"):
        return error("DATOS_INCOMPLETOS", "Falta el concepto del gasto")
    try:
        monto = float(c.get("monto", 0))
    except (TypeError, ValueError):
        return error("MONTO_INVALIDO", "El monto debe ser numerico")
    if monto <= 0:
        return error("MONTO_INVALIDO", "El monto debe ser mayor que 0")

    with db.conexion(tenant_id) as con:
        with con.cursor(row_factory=dict_row) as cur:
            # FOR UPDATE: dos gastos simultaneos sobre el mismo presupuesto
            # podrian leer el mismo total y perder uno de los dos incrementos.
            cur.execute("""
                SELECT id, monto_aprobado, total_gastado, alerta_enviada,
                       codigo_proyecto
                FROM   presupuestos WHERE proyecto_id = %s FOR UPDATE
            """, (proyecto_id,))
            presupuesto = cur.fetchone()
            if not presupuesto:
                return error("NO_ENCONTRADO",
                             f"El proyecto {proyecto_id} no tiene presupuesto", 404)

            cur.execute("""
                INSERT INTO gastos
                    (presupuesto_id, partida_id, concepto, monto, fecha,
                     proveedor, comprobante_key, registrado_por)
                VALUES (%s,%s,%s,%s,COALESCE(%s, CURRENT_DATE),%s,%s,%s)
                RETURNING *
            """, (presupuesto["id"], c.get("partida_id"), c["concepto"].strip(),
                  monto, c.get("fecha"), c.get("proveedor"),
                  c.get("comprobante_key"), usuario_de(event)))
            gasto = cur.fetchone()

            cur.execute("""
                UPDATE presupuestos
                SET    total_gastado = total_gastado + %s
                WHERE  id = %s
                RETURNING total_gastado, monto_aprobado
            """, (monto, presupuesto["id"]))
            tras = cur.fetchone()

            aprobado = float(tras["monto_aprobado"])
            gastado = float(tras["total_gastado"])
            pct = round(100 * gastado / aprobado, 2) if aprobado else 0.0

            # La alerta se manda UNA sola vez: sin esta bandera, cada gasto
            # posterior al 90% volveria a notificar al PMO.
            alertar = pct >= UMBRAL_ALERTA and not presupuesto["alerta_enviada"]
            if alertar:
                cur.execute(
                    "UPDATE presupuestos SET alerta_enviada = TRUE WHERE id = %s",
                    (presupuesto["id"],))

    # Commit cerrado: ahora si se publican los eventos.
    publicar("gasto.registrado", tenant_id, {
        "proyecto_id": int(proyecto_id),
        "gasto_id": gasto["id"],
        "concepto": gasto["concepto"],
        "monto": float(gasto["monto"]),
        "total_gastado": gastado,
        "monto_aprobado": aprobado,
        "ejecutado_pct": pct,
    })

    if alertar:
        publicar("presupuesto.excedido", tenant_id, {
            "proyecto_id": int(proyecto_id),
            "codigo_proyecto": presupuesto["codigo_proyecto"],
            "monto_aprobado": aprobado,
            "total_gastado": gastado,
            "ejecutado_pct": pct,
            "umbral_pct": UMBRAL_ALERTA,
        })

    gasto.pop("presupuesto_id", None)
    return ok({
        "gasto": gasto,
        "ejecucion": {
            "monto_aprobado": aprobado,
            "total_gastado": gastado,
            "saldo": round(aprobado - gastado, 2),
            "ejecutado_pct": pct,
            "alerta_disparada": alertar,
        },
    }, estado=201)


def resumen(event, context):
    """GET /ejecucion — el total del tenant, para el dashboard."""
    with db.conexion(tenant_de(event)) as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(f"""
                SELECT  COUNT(*)                                  AS proyectos,
                        COALESCE(SUM(monto_aprobado), 0)           AS aprobado,
                        COALESCE(SUM(total_gastado), 0)            AS gastado,
                        COALESCE(SUM(monto_aprobado - total_gastado), 0) AS saldo,
                        COUNT(*) FILTER (WHERE ejecutado_pct >= {UMBRAL_ALERTA}) AS en_alerta,
                        COUNT(*) FILTER (WHERE ejecutado_pct > 100)              AS sobregirados
                FROM    ejecucion
            """)
            r = cur.fetchone()
            cur.execute(f"""
                SELECT proyecto_id, codigo_proyecto, nombre_proyecto,
                       monto_aprobado, total_gastado, ejecutado_pct
                FROM   ejecucion
                WHERE  ejecutado_pct >= {UMBRAL_ALERTA}
                ORDER BY ejecutado_pct DESC LIMIT 10
            """)
            r["top_en_riesgo"] = cur.fetchall()

    aprobado = float(r["aprobado"])
    r["ejecutado_pct"] = round(100 * float(r["gastado"]) / aprobado, 2) if aprobado else 0.0
    return ok(r, meta={"umbral_alerta_pct": UMBRAL_ALERTA})
