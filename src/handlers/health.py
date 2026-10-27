"""Endpoint de verificacion. Protegido: sin token devuelve 401."""
from src.respuesta import ok, tenant_de

SERVICIO = "ms-presupuestos"


def manejar(event, context):
    return ok({"servicio": SERVICIO, "estado": "ok", "tenant": tenant_de(event)})
