"""Genera 30,000 registros ficticios repartidos en 3 tenants.

El enunciado pide 30,000 por microservicio. No son de una sola tabla: se
reparten entre las entidades del servicio.

Los tres tenants tienen PERFILES DISTINTOS a proposito. Si los datos salen
identicos, el multi-tenancy se ve falso en la demo.
"""
TENANTS = {
    # tenant_id      perfil
    "t-acme": dict(nombre="Acme Ingenieria", rubro="construccion",
                   proyectos=120, presupuesto_promedio=500_000, tareas_por_proyecto=12),
    "t-globex": dict(nombre="Globex Consulting", rubro="consultoria TI",
                     proyectos=400, presupuesto_promedio=80_000, tareas_por_proyecto=40),
    "t-initech": dict(nombre="Initech Software", rubro="software",
                      proyectos=60, presupuesto_promedio=30_000, tareas_por_proyecto=400),
}

OBJETIVO_POR_TENANT = 10_000


def main():
    raise SystemExit(
        "TODO: implementar el seed.\n"
        "Reglas: carga por lotes (batch_write_item / COPY), nunca fila por fila.\n"
        "Al terminar, imprime el conteo por tenant para la captura del informe."
    )


if __name__ == "__main__":
    main()
