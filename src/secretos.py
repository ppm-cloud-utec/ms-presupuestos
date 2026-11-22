"""Lectura de secretos desde AWS Secrets Manager, en tiempo de ejecucion."""
import json
import os
import time

import boto3

TTL = int(os.environ.get("SECRETOS_TTL", "900"))

_cache = {}


def obtener(nombre):
    """Devuelve el secreto como texto. Cachea TTL segundos."""
    valor, expira = _cache.get(nombre, (None, 0.0))
    if valor is not None and time.monotonic() < expira:
        return valor
    r = boto3.client("secretsmanager").get_secret_value(SecretId=nombre)
    valor = r.get("SecretString")
    if valor is None:
        raise ValueError(f"El secreto {nombre} no es texto")
    _cache[nombre] = (valor, time.monotonic() + TTL)
    return valor


def campo(nombre, clave):
    """Para secretos que guardan un JSON, por ejemplo {"user":..,"password":..}."""
    return json.loads(obtener(nombre))[clave]


def de_entorno(variable):
    """Lee el secreto cuyo NOMBRE viene en esa variable de entorno."""
    return obtener(os.environ[variable])
