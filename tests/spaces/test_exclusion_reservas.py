"""RN-S04 · La restricción GIST de ``reservas_espacios`` en la base (SPEC-08 AC-S13).

Las reservas ``Aprobada`` y ``En_Uso`` del mismo espacio no se pueden solapar; las
``Pendiente`` no participan. Es la garantía final ante concurrencia, así que se prueba
insertando directo en la base, sin pasar por el servicio. Que la migración ``0003``
declare la misma restricción que el modelo lo verifica ``tests/test_migraciones.py``.
"""

from datetime import time

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.enums import RolUsuario

pytestmark = pytest.mark.integracion


@pytest.mark.parametrize(
    ("primera", "segunda", "choca"),
    [
        ("En_Uso", "Aprobada", True),
        ("Aprobada", "En_Uso", True),
        ("En_Uso", "Pendiente", False),
    ],
)
async def test_reservas_activas_no_se_solapan(
    db, crear_usuario, crear_espacio, crear_reserva, primera, segunda, choca
):
    espacio = await crear_espacio()
    await crear_reserva(await crear_usuario(RolUsuario.ESTUDIANTE), espacio, estado=primera)
    otra = await crear_usuario(RolUsuario.DOCENTE)

    if not choca:
        await crear_reserva(otra, espacio, inicio=time(10, 30), fin=time(11, 30), estado=segunda)
        return
    with pytest.raises(IntegrityError, match="excl_reserva_aprobada_sin_solapamiento"):
        await crear_reserva(otra, espacio, inicio=time(10, 30), fin=time(11, 30), estado=segunda)
    await db.rollback()
