# ms-presupuestos

Presupuestos, partidas, gastos y ejecucion presupuestal.

Parte del proyecto final de Cloud Computing (CS2032), Grupo 4. Todas las rutas cuelgan de la API compartida `ppm-api-dev` bajo `/presupuestos` y, salvo el login, piden el token JWT.

Base de datos: RDS PostgreSQL, base ppm_presupuestos, un schema por organizacion.

## Endpoints

- GET /presupuestos/health
- GET /presupuestos/presupuestos
- GET /presupuestos/presupuestos/{proyecto_id}
- POST /presupuestos/presupuestos/{proyecto_id}/aprobar
- GET /presupuestos/presupuestos/{proyecto_id}/gastos
- POST /presupuestos/presupuestos/{proyecto_id}/gastos
- GET /presupuestos/ejecucion

## Eventos

Publica gasto.registrado y presupuesto.excedido. Consume proyecto.creado y recurso.asignado desde su cola SQS.

## Despliegue

Requiere que `infra-compartida` ya este desplegado.

```bash
npm install
npx serverless deploy
```

Los servicios con RDS necesitan Docker para compilar psycopg.

## Datos de prueba

```bash
python seed/generar.py
python seed/generar.py --contar
```
