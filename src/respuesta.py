"""Forma unica de respuesta para los 6 microservicios."""
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Content-Type": "application/json",
}


class _Codificador(json.JSONEncoder):
    """Serializa lo que json no sabe manejar solo."""

    def default(self, o):
        if isinstance(o, Decimal):
            return float(o) if o % 1 else int(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, UUID):
            return str(o)
        return super().default(o)


def ok(datos, meta=None, estado=200):
    cuerpo = {"ok": True, "datos": datos}
    if meta:
        cuerpo["meta"] = meta
    return {
        "statusCode": estado,
        "headers": CORS,
        "body": json.dumps(cuerpo, cls=_Codificador, ensure_ascii=False),
    }


def error(codigo, mensaje, estado=400):
    return {
        "statusCode": estado,
        "headers": CORS,
        "body": json.dumps(
            {"ok": False, "error": {"codigo": codigo, "mensaje": mensaje}},
            ensure_ascii=False,
        ),
    }


def tenant_de(event):
    """El tenant_id SOLO sale del authorizer, nunca del body ni del query string."""
    return event["requestContext"]["authorizer"]["tenant_id"]


def usuario_de(event):
    return event["requestContext"]["authorizer"]["usuario_id"]


def rol_de(event):
    return event["requestContext"]["authorizer"]["rol"]


def cuerpo_de(event):
    return json.loads(event.get("body") or "{}")
