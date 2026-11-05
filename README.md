# ms-presupuestos

Presupuesto aprobado, gastos y ejecución presupuestal. Responde la pregunta
central del producto: **¿en qué estamos gastando y cuánto queda?**

- **Responsable:** @carloscondor1610
- **Base de datos:** RDS PostgreSQL · database `ppm_presupuestos` · un schema por tenant
- **Runtime:** Python 3.12 · Serverless Framework · us-east-1

## Endpoints (8, todos protegidos)

| Método | Ruta | Rol | Qué hace |
|---|---|---|---|
| GET | `/presupuestos` | todos | ejecución de todos los proyectos · `?en_alerta=true`, paginado |
| GET | `/presupuestos/{proyecto_id}` | todos | detalle con partidas, últimos gastos y proyección de horas |
| POST | `/presupuestos/{proyecto_id}/aprobar` | pmo, admin | fija el monto y las partidas |
| GET | `/presupuestos/{proyecto_id}/gastos` | todos | gastos del proyecto |
| POST | `/presupuestos/{proyecto_id}/gastos` | pm, pmo, admin | registra · **publica eventos** |
| GET | `/ejecucion` | todos | totales del tenant, para el dashboard |
| GET | `/health` | todos | verifica el servicio |

## El segundo flujo de eventos de la demo

```
   POST /presupuestos/7/gastos  { monto: 48000 }
                    |
     FOR UPDATE + suma a total_gastado  (una transaccion)
                    |
         ejecutado_pct = 94%  >= umbral 90%
                    |
      publica gasto.registrado  +  presupuesto.excedido
                    |
                SNS ppm-eventos
                 /          \
   cola-portafolios      cola-alertas
          |                    |
  en_riesgo = TRUE        notifica al PMO
  salud = rojo
```

En el dashboard el proyecto **pasa a rojo solo**. Nadie llamó a
`ms-portafolios`.

## Lo que este microservicio NO hace por HTTP

**No crea presupuestos.** El presupuesto nace en 0 cuando el worker recibe
`proyecto.creado` de `ms-portafolios`. Después el PMO lo aprueba con un monto.
Igualmente, las `proyecciones_costo` las escribe el worker al recibir
`recurso.asignado` de `ms-recursos`.

Ese es el punto del EDA: este servicio no conoce a los otros dos.

## Desplegar

```bash
npm install            # instala Serverless v3 y el plugin de Python
npx serverless deploy
```

Necesita **Docker corriendo** si este microservicio usa RDS: el plugin compila
`psycopg` contra Amazon Linux dentro de un contenedor.

## Cargar datos

```bash
export DB_HOST=<endpoint del RDS> DB_USER=ppm_presupuestos DB_PASSWORD=<de SSM>
export DB_NAME=ppm_presupuestos
python seed/generar.py --esquema
python seed/generar.py            # 30,000 registros
python seed/generar.py --contar
```

## Documentación

- [Modelo de datos](docs/modelo.md) — ER, la vista `ejecucion`, decisiones de diseño
- [Arquitectura general](https://github.com/ppm-cloud-utec/infra-compartida/blob/main/docs/arquitectura.md)
