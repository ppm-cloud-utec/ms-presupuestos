"""Worker de presupuestos: recurso_id entero y fallos por mensaje (sin AWS)."""
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.handlers import worker


def registro(mid, tipo, datos):
    e = {"evento_id": str(uuid4()), "tipo": tipo, "tenant_id": "t-acme", "datos": datos}
    return {"messageId": mid, "body": json.dumps({"Message": json.dumps(e)})}


def test_lote_con_un_mensaje_malo():
    cur = MagicMock()
    cur.__enter__.return_value = cur
    con = MagicMock()
    con.cursor.return_value = cur
    # por mensaje: idempotencia (fila nueva) y despues presupuesto/proyeccion
    cur.fetchone.side_effect = [{"evento_id": 1}, {"id": 5}, {"costo_proyectado": 600},
                                {"evento_id": 2}, {"id": 5},
                                {"evento_id": 3}, {"id": 8}]

    @contextmanager
    def conexion(_t):
        yield con

    lote = {"Records": [
        registro("m1", "recurso.asignado", {"proyecto_id": 1, "recurso_id": "42",
                                            "horas_semana": 10, "costo_hora": 30, "semanas": 2}),
        registro("m2", "recurso.asignado", {"proyecto_id": 1, "recurso_id": "no-es-id"}),
        registro("m3", "proyecto.creado", {"proyecto_id": 2, "codigo": "P2", "nombre": "n"}),
    ]}
    with patch.object(worker.db, "conexion", conexion):
        r = worker.manejar(lote, None)

    assert r["batchItemFailures"] == [{"itemIdentifier": "m2"}], r
    assert r["procesados"] == 2, r
    insert = [c for c in cur.execute.call_args_list if "proyecciones_costo" in str(c)][0]
    assert insert.args[1][1] == 42 and isinstance(insert.args[1][1], int)


if __name__ == "__main__":
    test_lote_con_un_mensaje_malo(); print("[OK] test_lote_con_un_mensaje_malo")
