"""SPEC-03 Fase A · ``datos_publicos_por_ids`` (RN-35…RN-43, AC-61…AC-70).

La función se llama siempre con una sesión **nueva** de ``sessionmaker_``: la
sesión ``db`` del fixture ya tiene a los usuarios creados en su *identity map*
y no serviría para comprobar AC-68 (plan-03 §4.3).
"""

import dataclasses
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum
from app.modules.config.models import ParametroGlobal
from app.modules.users.models import Usuario
from app.modules.users.service import DatosPublicosUsuario, datos_publicos_por_ids

pytestmark = pytest.mark.integracion


@pytest.fixture
async def sesion(
    db: AsyncSession, sessionmaker_: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncSession]:
    """Sesión limpia, distinta de ``db``, como la que recibiría un servicio de otro módulo."""
    async with sessionmaker_() as session:
        yield session


@pytest.fixture
def consultas(engine: AsyncEngine) -> Iterator[list[str]]:
    """SQL emitido mientras el test corre (listener ``before_cursor_execute``)."""
    emitidas: list[str] = []

    def _registrar(conn, cursor, statement, parameters, context, executemany) -> None:
        emitidas.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _registrar)
    yield emitidas
    event.remove(engine.sync_engine, "before_cursor_execute", _registrar)


def _esperado(usuario: Usuario) -> DatosPublicosUsuario:
    return DatosPublicosUsuario(usuario.id, usuario.nombre, usuario.apellido)


# AC-61
async def test_devuelve_id_nombre_y_apellido_de_la_base(crear_usuario, sesion):
    ana = await crear_usuario(nombre="Ana", apellido="Núñez")
    beto = await crear_usuario(nombre="Beto", apellido="Ojeda")

    resultado = await datos_publicos_por_ids(sesion, [ana.id, beto.id])

    assert resultado == {
        ana.id: DatosPublicosUsuario(id=ana.id, nombre="Ana", apellido="Núñez"),
        beto.id: DatosPublicosUsuario(id=beto.id, nombre="Beto", apellido="Ojeda"),
    }
    assert all(type(clave) is int for clave in resultado)


# AC-62
async def test_ids_repetidos_una_entrada_por_id_y_una_sola_consulta(
    crear_usuario, sesion, consultas
):
    ana = await crear_usuario()
    beto = await crear_usuario()
    consultas.clear()

    resultado = await datos_publicos_por_ids(sesion, [ana.id, beto.id, ana.id, ana.id, beto.id])

    assert resultado == {ana.id: _esperado(ana), beto.id: _esperado(beto)}
    assert len(consultas) == 1
    # RN-41: un único parámetro de tipo arreglo, no uno por id.
    assert "ANY" in consultas[0].upper()
    assert consultas[0].count("$") == 1


# AC-63
@pytest.mark.parametrize(
    "vacio",
    [[], set(), (), (i for i in ())],
    ids=["lista", "conjunto", "tupla", "generador"],
)
async def test_entrada_vacia_devuelve_vacio_sin_consultar(sesion, consultas, vacio):
    consultas.clear()

    assert await datos_publicos_por_ids(sesion, vacio) == {}
    assert consultas == []


# AC-64
async def test_ids_inexistentes_se_omiten(crear_usuario, sesion):
    ana = await crear_usuario()

    assert await datos_publicos_por_ids(sesion, [ana.id, 9_999, 10_000]) == {
        ana.id: _esperado(ana)
    }


# AC-64
async def test_todos_inexistentes_devuelve_vacio_sin_error(db, sesion):
    assert await datos_publicos_por_ids(sesion, [9_999, 10_000]) == {}


# AC-65 · EC-34
async def test_incluye_usuarios_en_los_cinco_estados(crear_usuario, sesion):
    usuarios = [await crear_usuario(estado=estado) for estado in EstadoCuenta]
    assert {u.estado for u in usuarios} == set(EstadoCuenta)

    resultado = await datos_publicos_por_ids(sesion, [u.id for u in usuarios])

    assert resultado == {u.id: _esperado(u) for u in usuarios}


# AC-66
async def test_no_filtra_por_sede(crear_usuario, sesion):
    ushuaia = await crear_usuario(sede=SedeEnum.USHUAIA)
    rio_grande = await crear_usuario(RolUsuario.ADMIN_LOCAL, SedeEnum.RIO_GRANDE)
    superadmin = await crear_usuario(RolUsuario.SUPERADMIN)
    assert superadmin.sede is None

    resultado = await datos_publicos_por_ids(sesion, [ushuaia.id, rio_grande.id, superadmin.id])

    assert resultado == {u.id: _esperado(u) for u in (ushuaia, rio_grande, superadmin)}


# AC-67
def test_datos_publicos_solo_tiene_id_nombre_y_apellido_e_inmutable():
    campos = [f.name for f in dataclasses.fields(DatosPublicosUsuario)]
    assert campos == ["id", "nombre", "apellido"]

    datos = DatosPublicosUsuario(id=1, nombre="Ana", apellido="Núñez")
    with pytest.raises(dataclasses.FrozenInstanceError):
        datos.nombre = "Otra"  # type: ignore[misc]
    # DT-30: con slots=True, 3.12 y 3.13 lanzan TypeError al agregar un atributo; 3.14, FrozenInstanceError.
    with pytest.raises((dataclasses.FrozenInstanceError, TypeError, AttributeError)):
        datos.dni = "30111222"  # type: ignore[attr-defined]
    assert not hasattr(datos, "__dict__")


# AC-68
async def test_no_carga_entidades_usuario_en_la_sesion(crear_usuario, sesion, consultas):
    ana = await crear_usuario()
    beto = await crear_usuario()
    consultas.clear()

    await datos_publicos_por_ids(sesion, [ana.id, beto.id])

    assert [o for o in sesion.identity_map.values() if isinstance(o, Usuario)] == []
    # RN-40: la consulta selecciona sólo las tres columnas públicas.
    sql = consultas[0].lower()
    for columna in ("dni", "email", "telefono", "password_hash"):
        assert columna not in sql


# AC-69 · EC-35
async def test_no_confirma_ni_emite_la_transaccion_del_llamador(
    crear_usuario, sesion, sessionmaker_
):
    ana = await crear_usuario()
    clave = (await sesion.scalars(select(ParametroGlobal.clave).limit(1))).one()
    parametro = await sesion.get(ParametroGlobal, clave)
    assert parametro is not None
    descripcion_original = parametro.descripcion
    parametro.descripcion = "Cambio pendiente del llamador"

    resultado = await datos_publicos_por_ids(sesion, [ana.id])

    assert resultado == {ana.id: _esperado(ana)}
    assert sesion.in_transaction()
    assert parametro in sesion.dirty  # sin flush explícito (RN-42)
    await sesion.rollback()

    async with sessionmaker_() as otra:
        guardado = await otra.get(ParametroGlobal, clave)
        assert guardado is not None
        assert guardado.descripcion == descripcion_original


# AC-70
@pytest.mark.parametrize("forma", ["lista", "conjunto", "generador"])
async def test_lote_de_40000_ids_en_una_consulta(crear_usuario, sesion, consultas, forma):
    ana = await crear_usuario()
    beto = await crear_usuario()
    base = [ana.id, beto.id, *range(100_000, 100_000 + 39_998)]
    assert len(base) == 40_000
    ids = {"lista": list(base), "conjunto": set(base), "generador": (i for i in base)}[forma]
    consultas.clear()

    resultado = await datos_publicos_por_ids(sesion, ids)

    assert resultado == {ana.id: _esperado(ana), beto.id: _esperado(beto)}
    assert len(consultas) == 1
