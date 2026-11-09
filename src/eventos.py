
"""Publicacion de eventos de dominio al topic SNS compartido."""

import os
import json
import uuid
from datetime import datetime, timezone

import boto3


def publicar(tipo, tenant_id, datos):
    """Publica un evento de dominio en AWS SNS.

    Se invoca despues de confirmar la escritura en PostgreSQL.
    Los atributos permiten filtrar mensajes mediante SNS/SQS.
    """

    topic = os.environ.get("SNS_TOPIC_ARN")
    origen = os.environ.get("SERVICIO", "ms-presupuestos")

    if not topic:
        raise ValueError(
            "Falta configurar SNS_TOPIC_ARN"
        )

    if not tipo or not tenant_id:
        raise ValueError(
            "El tipo y tenant_id son obligatorios"
        )

    evento = {
        "evento_id": str(uuid.uuid4()),
        "tipo": tipo,
        "version": 1,
        "tenant_id": tenant_id,
        "ocurrido_en": datetime.now(timezone.utc).isoformat(),
        "origen": origen,
        "datos": datos,
    }

    # Crear el cliente solo cuando se publica un evento
    sns = boto3.client(
        "sns",
        region_name=os.environ.get(
            "AWS_DEFAULT_REGION",
            os.environ.get("AWS_REGION", "us-east-1")
        )
    )

    respuesta = sns.publish(
        TopicArn=topic,
        Message=json.dumps(
            evento,
            ensure_ascii=False,
            default=str
        ),
        MessageAttributes={
            "tipo": {
                "DataType": "String",
                "StringValue": tipo
            },
            "tenant_id": {
                "DataType": "String",
                "StringValue": tenant_id
            },
            "origen": {
                "DataType": "String",
                "StringValue": origen
            }
        }
    )

    if not respuesta.get("MessageId"):
        raise RuntimeError(
            "SNS no devolvio un MessageId"
        )

    return evento["evento_id"]
