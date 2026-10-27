"""Control de eventos ya procesados.

SQS entrega at-least-once: el mismo evento puede llegar dos veces. Sin esto, el
% de avance y la ejecucion presupuestal se inflan y en la demo no cuadran.
"""
import os
import time

import boto3
from botocore.exceptions import ClientError

_tabla = boto3.resource("dynamodb").Table(os.environ["TABLA_EVENTOS_PROCESADOS"])
TTL_DIAS = 30


def ya_procesado(evento_id):
    """Marca el evento como procesado. Devuelve True si ya lo estaba."""
    try:
        _tabla.put_item(
            Item={
                "evento_id": evento_id,
                "procesado_en": int(time.time()),
                "ttl": int(time.time()) + TTL_DIAS * 86400,
            },
            ConditionExpression="attribute_not_exists(evento_id)",
        )
        return False
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return True
        raise
