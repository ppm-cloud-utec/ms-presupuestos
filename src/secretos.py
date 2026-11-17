"""Lectura de secretos desde AWS Secrets Manager, en tiempo de ejecucion.

Antes los secretos se resolvian en el DESPLIEGUE:

    environment:
      JWT_SECRET: ${ssm:/ppm/jwt-secret}

Serverless lee ese valor al desplegar y lo escribe como variable de entorno
de la Lambda. El secreto queda guardado en la configuracion de la funcion y
en la plantilla de CloudFormation: cualquiera que pueda abrir la consola de
Lambda lo lee en texto plano. Con el JWT_SECRET eso es grave, porque permite
firmar tokens de cualquier tenant.

Ahora la Lambda recibe solo el NOMBRE del secreto y lo resuelve al arrancar.
Se cachea en memoria porque el contenedor se reutiliza entre invocaciones:
una lectura por contenedor, no una por request.

Parameter Store sigue usandose para CONFIGURACION que no es secreta, como
/ppm/tenants. La separacion es deliberada: secretos en Secrets Manager,
configuracion en Parameter Store.
"""
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
    """Lee el secreto cuyo NOMBRE viene en esa variable de entorno.

    La variable guarda la RUTA del secreto, nunca su contenido: es lo que
    permite enseñar la configuracion de la Lambda sin filtrar nada.
    """
    return obtener(os.environ[variable])
