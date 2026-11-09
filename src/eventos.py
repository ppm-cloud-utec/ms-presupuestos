"""Publicacion de eventos de dominio al topic SNS compartido."""
import os
import json
import uuid
from datetime import datetime, timezone

import boto3

# El cliente se crea UNA vez al cargar el modulo. En Lambda el contenedor se
# reutiliza entre invocaciones calientes, asi que crearlo aqui ahorra 100-200 ms
# por evento publicado. Crearlo dentro de publicar() paga ese costo cada vez.
_sns = boto3.client("sns")
TOPIC = os.environ["SNS_TOPIC_ARN"]
ORIGEN = os.environ["SERVICIO"]


def publicar(tipo, tenant_id, datos):
    """Publica un evento. Llamar SIEMPRE despues de confirmar la escritura en BD.

    Los atributos de mensaje son los que usan las filter policies de las colas
    SQS para quedarse solo con lo que les interesa.
    """
    if not tipo or not tenant_id:
        raise ValueError("Un evento necesita tipo y tenant_id")

    evento = {
        "evento_id": str(uuid.uuid4()),
        "tipo": tipo,
        "version": 1,
        "tenant_id": tenant_id,
        "ocurrido_en": datetime.now(timezone.utc).isoformat(),
        "origen": ORIGEN,
        "datos": datos,
    }

    respuesta = _sns.publish(
        TopicArn=TOPIC,
        Message=json.dumps(evento, ensure_ascii=False, default=str),
        MessageAttributes={
            "tipo": {"DataType": "String", "StringValue": tipo},
            "tenant_id": {"DataType": "String", "StringValue": tenant_id},
            "origen": {"DataType": "String", "StringValue": ORIGEN},
        },
    )

    # SNS lanza excepcion si falla, pero una respuesta sin MessageId significa
    # que el evento no quedo publicado y el llamador debe enterarse.
    if not respuesta.get("MessageId"):
        raise RuntimeError(f"SNS no devolvio MessageId al publicar {tipo}")

    return evento["evento_id"]
