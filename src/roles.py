"""Los 4 roles del producto y quien puede hacer que."""
from src.respuesta import error

ADMIN = "admin"        # gestiona los usuarios de su organizacion
PMO = "pmo"
PM = "pm"
MIEMBRO = "miembro"    # completa sus tareas

TODOS = (ADMIN, PMO, PM, MIEMBRO)


def exige(event, *permitidos):
    """Devuelve una respuesta de error si el rol del token no esta permitido."""
    rol = event["requestContext"]["authorizer"].get("rol", MIEMBRO)
    if rol not in permitidos:
        return error(
            "ROL_INSUFICIENTE",
            f"Este recurso requiere uno de estos roles: {', '.join(permitidos)}",
            403,
        )
    return None
