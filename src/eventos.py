"""Publicacion de eventos de dominio al topic SNS compartido."""
import os
import json
import uuid
from datetime import datetime, timezone

import boto3

_sns = boto3.client("sns")
TOPIC = os.environ["SNS_TOPIC_ARN"]
ORIGEN = os.environ["SERVICIO"]


def publicar(tipo, tenant_id, datos):
    """Publica un evento. Llamar SIEMPRE despues de confirmar la escritura en BD.

    Los atributos de mensaje son los que usan las filter policies de las colas
    SQS para quedarse solo con lo que les interesa.
    """
    evento = {
        "evento_id": str(uuid.uuid4()),
        "tipo": tipo,
        "version": 1,
        "tenant_id": tenant_id,
        "ocurrido_en": datetime.now(timezone.utc).isoformat(),
        "origen": ORIGEN,
        "datos": datos,
    }
    _sns.publish(
        TopicArn=TOPIC,
        Message=json.dumps(evento, ensure_ascii=False, default=str),
        MessageAttributes={
            "tipo": {"DataType": "String", "StringValue": tipo},
            "tenant_id": {"DataType": "String", "StringValue": tenant_id},
            "origen": {"DataType": "String", "StringValue": ORIGEN},
        },
    )
    return evento["evento_id"]
