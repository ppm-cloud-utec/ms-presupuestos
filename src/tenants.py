"""Tenants habilitados, leidos de SSM en caliente.

Antes esto era una constante en el codigo:

    SCHEMAS = {"t-acme": "t_acme", "t-globex": "t_globex", ...}

Con eso, dar de alta una organizacion obligaba a editar los tres
microservicios de RDS y redesplegarlos, o sea que la multi-tenancy quedaba
fijada en tiempo de despliegue. La maquina de estados
`ppm-aprovisionar-tenant` escribe la lista en /ppm/tenants al terminar, y
aqui se relee cada TTL segundos: un tenant nuevo queda operativo sin
desplegar nada.

Reglas de seguridad que no se negocian:

- El nombre del schema NUNCA sale de la peticion del usuario: se deriva del
  tenant_id del token y se valida contra una expresion estricta antes de
  tocar la base. psycopg no parametriza identificadores, asi que el unico
  blindaje posible es que el valor no pueda ser otra cosa que [a-z0-9_].
- Si SSM falla, se sigue usando la ultima lista conocida. Un hipo de red no
  puede dejar la aplicacion sin tenants en mitad de una demo.
"""
import json
import os
import re
import time

import boto3

PARAMETRO = os.environ.get("TENANTS_PARAM", "/ppm/tenants")
TTL = int(os.environ.get("TENANTS_TTL", "60"))

# t-acme, t-globex2... minusculas, digitos y un solo guion tras la "t".
_VALIDO = re.compile(r"^t-[a-z0-9]{2,30}$")

# Respaldo de arranque: los tres tenants originales. Solo se usa si la
# primera lectura de SSM falla; en cuanto una lectura funciona, manda SSM.
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
        # Sin parametro todavia, sin permisos o SSM caido: seguimos con lo
        # ultimo que funciono. Nunca dejamos la lista vacia.
        if _cache is None:
            _cache, _expira = list(_RESPALDO), time.monotonic() + TTL
    return _cache


def schema_de(tenant_id):
    """Nombre del schema del tenant, o None si no esta habilitado."""
    if tenant_id not in habilitados():
        return None
    return _derivar(tenant_id)


def esquema_para(tenant_id):
    """Schema de un tenant SIN exigir que ya este habilitado.

    Lo usa el aprovisionador: durante el alta el tenant todavia no esta en
    /ppm/tenants, pero su schema ya hay que crearlo. Valida igual de estricto.
    """
    schema = _derivar(tenant_id)
    if schema is None:
        raise ValueError(f"tenant_id invalido: {tenant_id!r}")
    return schema


def invalidar():
    """Fuerza la relectura en la proxima llamada (lo usa el aprovisionador)."""
    global _cache, _expira
    _cache, _expira = None, 0.0
