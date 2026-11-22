"""Tenants habilitados, leidos de SSM en caliente."""
import json
import os
import re
import time

import boto3

PARAMETRO = os.environ.get("TENANTS_PARAM", "/ppm/tenants")
TTL = int(os.environ.get("TENANTS_TTL", "60"))

_VALIDO = re.compile(r"^t-[a-z0-9]{2,30}$")

_RESPALDO = ("t-acme", "t-globex", "t-initech")

_cache = None
_expira = 0.0


def _derivar(tenant_id):
    """t-acme -> t_acme. Devuelve None si el id no tiene forma de tenant."""
    if not isinstance(tenant_id, str) or not _VALIDO.match(tenant_id):
        return None
    return tenant_id.replace("-", "_", 1)


def habilitados():
    """Lista de tenant_id vigentes. Cachea TTL segundos."""
    global _cache, _expira
    if _cache is not None and time.monotonic() < _expira:
        return _cache
    try:
        valor = boto3.client("ssm").get_parameter(Name=PARAMETRO)["Parameter"]["Value"]
        leidos = [t for t in json.loads(valor) if _derivar(t)]
        if leidos:
            _cache, _expira = leidos, time.monotonic() + TTL
    except Exception:
        if _cache is None:
            _cache, _expira = list(_RESPALDO), time.monotonic() + TTL
    return _cache


def schema_de(tenant_id):
    """Nombre del schema del tenant, o None si no esta habilitado."""
    if tenant_id not in habilitados():
        return None
    return _derivar(tenant_id)


def esquema_para(tenant_id):
    """Schema de un tenant SIN exigir que ya este habilitado."""
    schema = _derivar(tenant_id)
    if schema is None:
        raise ValueError(f"tenant_id invalido: {tenant_id!r}")
    return schema


def invalidar():
    """Fuerza la relectura en la proxima llamada (lo usa el aprovisionador)."""
    global _cache, _expira
    _cache, _expira = None, 0.0
