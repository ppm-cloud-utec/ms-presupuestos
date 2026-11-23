"""registrar_gasto rechaza partidas de otro presupuesto (sin AWS)."""
import json
import os
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:prueba")
os.environ.setdefault("SERVICIO", "ms-presupuestos")

from src.handlers import presupuestos


def gasto(partida_id, filas):
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.fetchone.side_effect = filas
    con = MagicMock()
    con.cursor.return_value = cur

    @contextmanager
    def conexion(_t):
        yield con

    evento = {"requestContext": {"authorizer": {"tenant_id": "t-acme", "rol": "pm",
                                                "usuario_id": str(uuid4())}},
              "pathParameters": {"proyecto_id": "1"},
              "body": json.dumps({"concepto": "Compra", "monto": 10, "partida_id": partida_id})}
    with patch.object(presupuestos.db, "conexion", conexion), \
         patch("src.tenants.habilitados", return_value={"t-acme"}), \
         patch.object(presupuestos, "publicar"):
        return presupuestos.registrar_gasto(evento, None), cur


PRESUPUESTO = {"id": 1, "monto_aprobado": Decimal("1000"), "total_gastado": Decimal("0"),
               "alerta_enviada": False, "codigo_proyecto": "P1"}


def test_partida_ajena():
    r, cur = gasto(99, [PRESUPUESTO, None])
    assert r["statusCode"] == 400, r
    assert json.loads(r["body"])["error"]["codigo"] == "PARTIDA_INVALIDA"
    assert not any("INSERT INTO gastos" in str(c) for c in cur.execute.call_args_list)


def test_partida_no_numerica():
    r, _ = gasto("abc", [PRESUPUESTO])
    assert r["statusCode"] == 400 and "entero" in r["body"], r


if __name__ == "__main__":
    for t in (test_partida_ajena, test_partida_no_numerica):
        t(); print("[OK]", t.__name__)
