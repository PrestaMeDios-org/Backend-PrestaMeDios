"""SPEC-03 RN-63 · ``limpiar-huerfanos`` — AC-88, EC-42."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.enums import RolUsuario
from app.modules.files.cli import construir_parser
from app.modules.files.models import Archivo, ArchivoDatos
from app.modules.files.service import limpiar_huerfanos
from tests.files.conftest import jpeg_con_exif, subir_aval, subir_foto

pytestmark = pytest.mark.integracion


async def _envejecer(db, archivo_id: str, horas: int) -> None:
    await db.execute(
        update(Archivo)
        .where(Archivo.id == archivo_id)
        .values(created_at=datetime.now(UTC) - timedelta(hours=horas))
    )
    await db.commit()


async def _ids(db) -> set[str]:
    return {str(i) for i in await db.scalars(select(Archivo.id))}


async def test_borra_viejos_y_conserva_el_resto(client, db, crear_usuario):  # AC-88
    u = await crear_usuario(RolUsuario.ESTUDIANTE)
    viejo = (await subir_aval(client, u)).json()["id"]
    reciente = (await subir_aval(client, u)).json()["id"]
    vinculado_viejo = (await subir_aval(client, u)).json()["id"]
    foto = (await subir_foto(client, u, jpeg_con_exif(32, 32))).json()["foto_id"]
    for archivo_id in (viejo, vinculado_viejo, foto):
        await _envejecer(db, archivo_id, 30)
    await db.execute(
        update(Archivo).where(Archivo.id == vinculado_viejo).values(vinculado_en=func.now())
    )
    await db.commit()

    assert await limpiar_huerfanos(db) == 1
    assert await _ids(db) == {reciente, vinculado_viejo, foto}
    assert await db.scalar(select(func.count()).select_from(ArchivoDatos)) == 3

    assert await limpiar_huerfanos(db) == 0  # idempotente
    assert await _ids(db) == {reciente, vinculado_viejo, foto}


async def test_horas_configurables(client, db, crear_usuario):
    u = await crear_usuario(RolUsuario.DOCENTE)
    archivo_id = (await subir_aval(client, u)).json()["id"]
    await _envejecer(db, archivo_id, 3)
    assert await limpiar_huerfanos(db, horas=4) == 0
    assert await limpiar_huerfanos(db, horas=2) == 1


def test_parser():
    args = construir_parser().parse_args(["limpiar-huerfanos", "--horas", "12"])
    assert args.comando == "limpiar-huerfanos" and args.horas == 12
    assert construir_parser().parse_args(["limpiar-huerfanos"]).horas is None
    with pytest.raises(SystemExit):
        construir_parser().parse_args(["limpiar-huerfanos", "--horas", "0"])
