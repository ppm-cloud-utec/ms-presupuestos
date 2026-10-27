# Integrante responsable

**carloscondor1610**

Microservicio: `ms-presupuestos` — Presupuesto aprobado, gastos y ejecucion presupuestal

## Checklist de entrega

- [ ] `sls deploy` funciona de cero, sin pasos manuales
- [ ] 5+ endpoints REST protegidos con el authorizer
- [ ] `docs/modelo.md` con el ER
- [ ] `seed/generar.py` carga 30,000 registros en 3 tenants
- [ ] Publica sus eventos a SNS despues de confirmar en BD
- [ ] Worker SQS idempotente (si consume eventos)
- [ ] Capturas en `docs/capturas/`: deploy, 401 sin token, mismo endpoint con
      dos tenants distintos, conteo de registros
- [ ] README con los endpoints y como probarlos
