#!/usr/bin/env python3
"""Carga 30,000 registros en ms-presupuestos, repartidos en 3 tenants.

    python seed/generar.py --esquema
    python seed/generar.py
    python seed/generar.py --contar

Reparto por tenant (10,000):
    presupuestos         500   (uno por proyecto de ms-portafolios)
    partidas           1,500   (3 por presupuesto)
    gastos             7,500
    proyecciones_costo   500
                      ------
                      10,000
"""
import os
import sys
import uuid
import random
import argparse
from datetime import date, timedelta

import psycopg

SCHEMAS = {"t-acme": "t_acme", "t-globex": "t_globex", "t-initech": "t_initech"}

PERFILES = {
    "t-acme": dict(
        nombre="Acme Ingenieria", presupuesto=(200_000, 900_000),
        partidas=["Materiales", "Mano de obra", "Equipos"],
        conceptos=["Compra de cemento", "Alquiler de maquinaria", "Jornales",
                   "Acero corrugado", "Flete de materiales", "Supervision tecnica",
                   "Ladrillo y agregados", "Combustible"],
        proveedores=["Pacasmayo", "Aceros Arequipa", "Ferreyros", "Sodimac",
                     "Unicon", "Promart"],
    ),
    "t-globex": dict(
        nombre="Globex Consulting", presupuesto=(20_000, 150_000),
        partidas=["Consultores", "Viajes", "Licencias"],
        conceptos=["Honorarios de consultor senior", "Pasajes y hospedaje",
                   "Licencia de software", "Taller con el cliente",
                   "Horas de analista", "Material de capacitacion"],
        proveedores=["LATAM", "Microsoft", "Oracle", "Casa Andina", "Deloitte"],
    ),
    "t-initech": dict(
        nombre="Initech Software", presupuesto=(10_000, 60_000),
        partidas=["Desarrollo", "Infraestructura", "Herramientas"],
        conceptos=["Horas de desarrollo", "Factura de AWS", "Licencia de IDE",
                   "Servicio de monitoreo", "Horas de QA", "Dominio y certificados"],
        proveedores=["AWS", "JetBrains", "Datadog", "GitHub", "Cloudflare"],
    ),
}

N_PRESUPUESTOS, N_GASTOS, N_PROYECCIONES = 500, 7_500, 500


def dsn():
    return (f"host={os.environ['DB_HOST']} port=5432 "
            f"dbname={os.environ.get('DB_NAME', 'ppm_presupuestos')} "
            f"user={os.environ['DB_USER']} password={os.environ['DB_PASSWORD']}")


def aplicar_esquema():
    sql = open(os.path.join(os.path.dirname(__file__), "esquema.sql")).read()
    with psycopg.connect(dsn()) as con:
        for schema in SCHEMAS.values():
            with con.cursor() as cur:
                cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                cur.execute(f"SET search_path TO {schema}")
                cur.execute(sql)
            con.commit()
            print(f"  esquema aplicado en {schema}")


def generar(tenant_id, perfil):
    schema = SCHEMAS[tenant_id]
    hoy = date.today()
    total = 0

    with psycopg.connect(dsn()) as con:
        with con.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}")

            # --- presupuestos (uno por proyecto) ---
            presupuestos = []
            for pid in range(1, N_PRESUPUESTOS + 1):
                monto = random.randint(*perfil["presupuesto"])
                estado = random.choices(["aprobado", "borrador", "cerrado"],
                                        weights=[70, 15, 15])[0]
                cur.execute("""
                    INSERT INTO presupuestos
                        (proyecto_id, codigo_proyecto, nombre_proyecto,
                         monto_aprobado, estado, aprobado_en, creado_en)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """, (pid, f"PRY-{tenant_id[2:5].upper()}-{pid:05d}",
                      f"Proyecto {pid} de {perfil['nombre']}",
                      0 if estado == "borrador" else monto, estado,
                      None if estado == "borrador" else hoy - timedelta(days=random.randint(30, 500)),
                      hoy - timedelta(days=random.randint(30, 540))))
                presupuestos.append((cur.fetchone()[0], monto, estado))
                total += 1
            print(f"    {len(presupuestos)} presupuestos")

            # --- partidas (3 por presupuesto) ---
            lote = []
            for pid, monto, _ in presupuestos:
                for i, nombre in enumerate(perfil["partidas"]):
                    lote.append((pid, nombre, monto * [0.5, 0.3, 0.2][i]))
            cur.executemany("""
                INSERT INTO partidas (presupuesto_id, nombre, monto_asignado)
                VALUES (%s,%s,%s)
            """, lote)
            total += len(lote)
            print(f"    {len(lote)} partidas")

            cur.execute("SELECT id, presupuesto_id FROM partidas")
            por_presupuesto = {}
            for partida_id, presupuesto_id in cur.fetchall():
                por_presupuesto.setdefault(presupuesto_id, []).append(partida_id)

            # --- gastos ---
            # Se reparten de forma desigual: unos proyectos quedan al 20% de
            # ejecucion y otros pasan del 100%, para que el dashboard tenga
            # semaforos de los 3 colores y casos de alerta reales.
            gastados = {}
            lote = []
            for _ in range(N_GASTOS):
                pid, monto, estado = random.choice(presupuestos)
                if estado == "borrador":
                    continue
                objetivo = random.choice([0.2, 0.45, 0.7, 0.88, 0.95, 1.08])
                ya = gastados.get(pid, 0.0)
                tope = monto * objetivo
                if ya >= tope:
                    continue
                importe = round(min(monto * random.uniform(0.02, 0.15), tope - ya), 2)
                if importe <= 0:
                    continue
                gastados[pid] = ya + importe
                lote.append((
                    pid, random.choice(por_presupuesto.get(pid, [None])),
                    random.choice(perfil["conceptos"]), importe,
                    hoy - timedelta(days=random.randint(0, 400)),
                    random.choice(perfil["proveedores"]),
                    f"{tenant_id}/comprobantes/{uuid.uuid4().hex[:12]}.pdf",
                ))
            cur.executemany("""
                INSERT INTO gastos
                    (presupuesto_id, partida_id, concepto, monto, fecha,
                     proveedor, comprobante_key)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, lote)
            n_gastos = len(lote)
            total += n_gastos
            print(f"    {n_gastos} gastos")

            # El total_gastado se mantiene al dia en la tabla, igual que lo
            # hace el handler al registrar cada gasto.
            cur.execute("""
                UPDATE presupuestos p
                SET    total_gastado = COALESCE(s.suma, 0),
                       alerta_enviada = (p.monto_aprobado > 0 AND
                                         COALESCE(s.suma, 0) >= p.monto_aprobado * 0.9)
                FROM  (SELECT presupuesto_id, SUM(monto) AS suma
                       FROM gastos GROUP BY presupuesto_id) s
                WHERE p.id = s.presupuesto_id
            """)

            # --- proyecciones de costo ---
            lote = []
            usados = set()
            while len(lote) < N_PROYECCIONES:
                pid, _, _ = random.choice(presupuestos)
                recurso = str(uuid.UUID(int=random.getrandbits(128), version=4))
                if (pid, recurso) in usados:
                    continue
                usados.add((pid, recurso))
                lote.append((pid, recurso, random.choice([8, 16, 20, 30, 40]),
                             random.choice([25, 35, 50, 70, 90, 120]),
                             random.randint(2, 24)))
            cur.executemany("""
                INSERT INTO proyecciones_costo
                    (presupuesto_id, recurso_id, horas_semana, costo_hora, semanas)
                VALUES (%s,%s,%s,%s,%s)
            """, lote)
            total += len(lote)
            print(f"    {len(lote)} proyecciones de costo")

            # Relleno para llegar exactamente a 10,000
            faltan = 10_000 - total
            if faltan > 0:
                lote = []
                for _ in range(faltan):
                    pid, monto, _ = random.choice(presupuestos)
                    lote.append((pid, random.choice(por_presupuesto.get(pid, [None])),
                                 random.choice(perfil["conceptos"]),
                                 round(random.uniform(50, 500), 2),
                                 hoy - timedelta(days=random.randint(0, 400)),
                                 random.choice(perfil["proveedores"]), None))
                cur.executemany("""
                    INSERT INTO gastos
                        (presupuesto_id, partida_id, concepto, monto, fecha,
                         proveedor, comprobante_key)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """, lote)
                total += faltan
                print(f"    {faltan} gastos de ajuste (para llegar a 10,000)")
        con.commit()
    return total


def contar():
    gran_total = 0
    for schema in SCHEMAS.values():
        with psycopg.connect(dsn()) as con, con.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}")
            print(f"  {schema}")
            sub = 0
            for t in ("presupuestos", "partidas", "gastos", "proyecciones_costo"):
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                n = cur.fetchone()[0]
                print(f"    {t:<22} {n:>7}")
                sub += n
            cur.execute("SELECT COUNT(*) FROM ejecucion WHERE ejecutado_pct >= 90")
            print(f"    {'(en alerta >=90%)':<22} {cur.fetchone()[0]:>7}")
            print(f"    {'subtotal':<22} {sub:>7}\n")
            gran_total += sub
    print(f"  TOTAL {gran_total:>26}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--esquema", action="store_true")
    ap.add_argument("--contar", action="store_true")
    ap.add_argument("--tenant", choices=list(SCHEMAS))
    args = ap.parse_args()

    for v in ("DB_HOST", "DB_USER", "DB_PASSWORD"):
        if not os.environ.get(v):
            sys.exit(f"Falta la variable de entorno {v}")

    if args.esquema:
        return aplicar_esquema()
    if args.contar:
        return contar()

    random.seed(2026)
    objetivo = {args.tenant: PERFILES[args.tenant]} if args.tenant else PERFILES
    total = 0
    for tenant_id, perfil in objetivo.items():
        print(f"== {perfil['nombre']} ({tenant_id}) ==")
        n = generar(tenant_id, perfil)
        print(f"   {n} registros\n")
        total += n
    print(f"Listo: {total} registros. Verifica con --contar")


if __name__ == "__main__":
    main()
