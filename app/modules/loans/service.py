"""Servicio del módulo `loans` (SPEC-05, Fase 1: Solicitar).

Las reglas de negocio viven acá y los endpoints delegan en estas funciones.

- Las reglas operativas (franja, anticipación, plazos) se leen de `config` con
  ``obtener_parametro``; no se codifican (Constitución P8, RN-L28).
- Las fechas se comparan en la zona horaria del laboratorio (RN-L29).
- Todo error de negocio es un ``AppError`` (``{detail, code}``).
- ``get_db`` no hace ``commit``: lo hace el servicio cuando escribe.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import puede_ver_sede
from app.core.enums import RolUsuario, SedeEnum
from app.core.errors import AppError
from app.core.settings import ZONA_HORARIA_LAB, ahora_lab
from app.modules.config.service import obtener_parametro
from app.modules.inventory.service import datos_equipamiento_por_ids, unidades_asignables
from app.modules.loans.enums import (
    ESTADOS_DETALLE_QUE_OCUPAN,
    EstadoDetalleEnum,
    EstadoOrdenEnum,
)
from app.modules.loans.models import DetallePrestamo, OrdenPedido
from app.modules.loans.schemas import (
    OrdenPedidoCreate,
    OrdenPedidoResponse,
    ReglasResponse,
    SolicitanteResumen,
)
from app.modules.users.models import Usuario
from app.modules.users.service import datos_publicos_por_ids

# ── Lectura de parámetros ────────────────────────────────────────────────────


async def _entero(db: AsyncSession, clave: str) -> int:
    valor = await obtener_parametro(db, clave)
    assert isinstance(valor, int) and not isinstance(valor, bool), f"{clave} no es entero"
    return valor


async def _hora(db: AsyncSession, clave: str) -> time:
    valor = await obtener_parametro(db, clave)
    assert isinstance(valor, time), f"{clave} no es una hora"
    return valor


async def reglas(db: AsyncSession) -> ReglasResponse:
    """Reglas operativas vigentes, para que el formulario las conozca (D-L07)."""
    return ReglasResponse(
        horario_apertura=await _hora(db, "horario.apertura"),
        horario_cierre=await _hora(db, "horario.cierre"),
        anticipacion_min_horas=await _entero(db, "solicitud.anticipacion_min_horas"),
        max_dias_general=await _entero(db, "prestamo.general.max_dias"),
        max_dias_notebook=await _entero(db, "prestamo.notebook.max_dias"),
        tolerancia_retiro_horas=await _entero(db, "prestamo.tolerancia_retiro_horas"),
    )


# ── Consulta del solicitante ─────────────────────────────────────────────────


def orden_no_encontrada() -> AppError:
    return AppError(404, "ORDEN_NO_ENCONTRADA", "Orden no encontrada.")


async def listar_mis_ordenes(
    db: AsyncSession,
    actor: Usuario,
    estado: EstadoOrdenEnum | None,
    limit: int,
    offset: int,
) -> list[OrdenPedido]:
    """Órdenes del usuario autenticado, de la más nueva a la más vieja (P6)."""
    stmt = select(OrdenPedido).where(OrdenPedido.solicitante_id == actor.id)
    if estado is not None:
        stmt = stmt.where(OrdenPedido.estado == estado)
    stmt = (
        stmt.order_by(OrdenPedido.fecha_solicitud.desc(), OrdenPedido.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await db.scalars(stmt)).all())


# ── Alcance y respuestas (Fase 2) ────────────────────────────────────────────

_ROLES_ADMIN = (RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN)


def _es_admin(actor: Usuario) -> bool:
    return actor.rol in _ROLES_ADMIN


def _puede_ver(actor: Usuario, orden: OrdenPedido) -> bool:
    """La ve el dueño y el administrador con jurisdicción sobre su sede (RN-L25, RN-L26)."""
    if orden.solicitante_id == actor.id:
        return True
    return _es_admin(actor) and puede_ver_sede(actor, orden.sede)


async def _orden_con_alcance(
    db: AsyncSession, actor: Usuario, orden_id: int, *, bloquear: bool = False
) -> OrdenPedido:
    """La orden si ``actor`` puede verla; si no existe o no tiene alcance, 404 (nunca 403).

    Con ``bloquear=True`` la lee con ``SELECT ... FOR UPDATE`` para serializar las
    transiciones de la orden (RN-L14) y descarta lo que hubiera en la sesión.
    """
    stmt = select(OrdenPedido).where(OrdenPedido.id == orden_id)
    if bloquear:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    orden = await db.scalar(stmt)
    if orden is None or not _puede_ver(actor, orden):
        raise orden_no_encontrada()
    return orden


async def respuestas_de_ordenes(
    db: AsyncSession, actor: Usuario, ordenes: Sequence[OrdenPedido]
) -> list[OrdenPedidoResponse]:
    """Arma las respuestas; para administradores suma el resumen del solicitante.

    Una sola consulta a ``users.datos_publicos_por_ids`` para todas las órdenes (P6:
    solo ``id``, ``nombre`` y ``apellido``). El dueño recibe ``solicitante = null``.
    """
    respuestas = [OrdenPedidoResponse.model_validate(o) for o in ordenes]
    if not _es_admin(actor) or not respuestas:
        return respuestas
    datos = await datos_publicos_por_ids(db, [r.solicitante_id for r in respuestas])
    return [
        r.model_copy(
            update={"solicitante": SolicitanteResumen.model_validate(datos[r.solicitante_id])}
        )
        if r.solicitante_id in datos
        else r
        for r in respuestas
    ]


async def obtener_orden(db: AsyncSession, actor: Usuario, orden_id: int) -> OrdenPedidoResponse:
    """Detalle de una orden para el dueño o un administrador con jurisdicción; si no, 404."""
    orden = await _orden_con_alcance(db, actor, orden_id)
    return (await respuestas_de_ordenes(db, actor, [orden]))[0]


# ── Validaciones puras (sin base de datos) ───────────────────────────────────


def _a_hora_lab(instante: datetime) -> datetime:
    """Convierte un instante con zona a la zona del laboratorio (RN-L29)."""
    return instante.astimezone(ZONA_HORARIA_LAB)


def _validar_franja(retiro: datetime, devolucion: datetime, apertura: time, cierre: time) -> None:
    """RN-L04: la hora local de retiro y de devolución está dentro de la franja (inclusive)."""
    etiquetas = {"retiro": "retiro", "devolucion": "devolución"}
    for campo, instante in (("retiro", retiro), ("devolucion", devolucion)):
        hora = _a_hora_lab(instante).time()
        if not apertura <= hora <= cierre:
            raise AppError(
                422,
                "FRANJA_FUERA_DE_HORARIO",
                f"La hora de {etiquetas[campo]} debe estar entre las "
                f"{apertura:%H:%M} y las {cierre:%H:%M}.",
                campo=campo,
            )


def _validar_anticipacion(retiro: datetime, ahora: datetime, horas: int) -> None:
    """RN-L05: el retiro se pide con al menos ``horas`` de anticipación."""
    if retiro < ahora + timedelta(hours=horas):
        raise AppError(
            422,
            "ANTICIPACION_INSUFICIENTE",
            f"El retiro debe pedirse con al menos {horas} horas de anticipación.",
            anticipacion_min_horas=horas,
        )


def _dias_corridos(retiro: datetime, devolucion: datetime) -> int:
    """RN-L06: días corridos contando el día de retiro y el de devolución (D-L04)."""
    return (_a_hora_lab(devolucion).date() - _a_hora_lab(retiro).date()).days + 1


def _limite_dias(
    es_notebook: bool, max_general: int, max_notebook: int, max_item: int | None
) -> int:
    """RN-L06 (D-L03): el menor entre el parámetro del tipo y el máximo del ítem."""
    por_tipo = max_notebook if es_notebook else max_general
    return por_tipo if max_item is None else min(por_tipo, max_item)


def _validar_plazo(
    retiro: datetime, devolucion: datetime, limite: int, equipamiento_id: int
) -> None:
    """RN-L06: el rango no supera el límite de la línea."""
    if _dias_corridos(retiro, devolucion) > limite:
        raise AppError(
            422,
            "LIMITE_DIAS_EXCEDIDO",
            f"El plazo máximo para este equipo es de {limite} días.",
            equipamiento_id=equipamiento_id,
            max_dias=limite,
        )


def _validar_disponibilidad(
    solicitadas: Mapping[int, int], libres: Mapping[int, Sequence[int]]
) -> None:
    """RN-L10: por cada modelo, las unidades libres alcanzan para las líneas pedidas."""
    for equipamiento_id, cantidad in solicitadas.items():
        disponibles = len(libres.get(equipamiento_id, ()))
        if cantidad > disponibles:
            detalle = (
                "Este equipo no tiene unidades libres."
                if disponibles == 0
                else f"Solo hay {disponibles} unidades libres de este equipo y pediste {cantidad}."
            )
            raise AppError(
                409,
                "EQUIPAMIENTO_NO_DISPONIBLE",
                detalle,
                equipamiento_id=equipamiento_id,
                solicitadas=cantidad,
                libres=disponibles,
            )


# ── Unidades libres por período (RN-L10, D-L17 descartada: criterio por fechas) ──


async def _ocupadas_en_periodo(
    db: AsyncSession, unidad_ids: list[int], desde: datetime, hasta: datetime
) -> set[int]:
    """Unidades con una línea que ocupa y se solapa con ``[desde, hasta)``.

    Ocupan los estados de ``ESTADOS_DETALLE_QUE_OCUPAN``, los mismos del ``EXCLUDE``.
    """
    if not unidad_ids:
        return set()
    stmt = select(DetallePrestamo.unidad_fisica_id).where(
        DetallePrestamo.unidad_fisica_id.in_(unidad_ids),
        DetallePrestamo.estado.in_(ESTADOS_DETALLE_QUE_OCUPAN),
        DetallePrestamo.periodo.op("&&")(func.tstzrange(desde, hasta, "[)")),
    )
    return set((await db.scalars(stmt)).all())


async def ids_unidades_libres(
    db: AsyncSession,
    equipamiento_ids: list[int],
    sede: SedeEnum,
    desde: datetime,
    hasta: datetime,
) -> dict[int, list[int]]:
    """Por modelo, los ids de las unidades libres en la sede para ``[desde, hasta)`` (RN-L10).

    Unidad libre = figura en ``inventory.unidades_asignables`` (``disponible`` hoy, de un
    ítem activo) y no tiene ninguna línea ``reservado`` o ``entregado`` que se solape con
    el período. Una reserva en otras fechas no la ocupa. Las líneas ``pendiente`` no
    cuentan. Es una verificación previa (P7.2): la garantía final es el ``EXCLUDE``.
    Los ids salen en el orden de ``inventory`` (por código de inventario). Uso interno
    de ``loans``: creación (RN-L10) y ``GET /ordenes/{id}/unidades-libres`` (RN-L12).
    """
    if hasta <= desde:
        raise ValueError("El período debe terminar después de empezar.")
    modelos = list(dict.fromkeys(equipamiento_ids))  # sin repetidos, en orden
    candidatas = {m: await unidades_asignables(db, m, sede) for m in modelos}
    ocupadas = await _ocupadas_en_periodo(
        db, [u for ids in candidatas.values() for u in ids], desde, hasta
    )
    return {m: [u for u in ids if u not in ocupadas] for m, ids in candidatas.items()}


async def unidades_libres(
    db: AsyncSession,
    equipamiento_ids: list[int],
    sede: SedeEnum,
    desde: datetime,
    hasta: datetime,
) -> dict[int, int]:
    """API pública (§10.2): por modelo, cuántas unidades están libres en ``[desde, hasta)``.

    Mismo criterio que RN-L10. Devuelve solo cantidades, sin identidad de unidades ni de
    solicitantes. Sirve al mini-calendario del catálogo (PRE-01, Perfil 2, INV-26).
    Un modelo inexistente, inactivo o de otra sede vale 0. No hace ``commit``.
    """
    libres = await ids_unidades_libres(db, equipamiento_ids, sede, desde, hasta)
    return {m: len(ids) for m, ids in libres.items()}


# ── Ocupación por unidad (API pública para inventory, PRE-01) ────────────────


@dataclass(frozen=True, slots=True)
class PeriodoOcupado:
    """Un período ``[desde, hasta)`` en que la unidad está ocupada por una línea."""

    desde: datetime
    hasta: datetime


async def ocupacion_de_unidades(
    db: AsyncSession, unidad_ids: Iterable[int], desde: datetime, hasta: datetime
) -> dict[int, list[PeriodoOcupado]]:
    """API pública (§10.2): por unidad, los períodos ocupados que se solapan con ``[desde, hasta)``.

    Para el mini-calendario y la disponibilidad por fechas del catálogo (PRE-01, Perfil 2,
    INV-26): ``inventory`` pasa las unidades operativas de un modelo y arma el conteo por
    día. Ocupan las líneas ``reservado`` y ``entregado``; cada período va de
    ``retiro_pactado`` a ``fin_ocupacion``, sin recortar al rango pedido.

    - Sin identidad (P6): no incluye orden, línea ni solicitante.
    - No filtra por sede: la unidad ya la determina; la autorización es de quien llama.
    - Siempre devuelve una clave por unidad pedida (lista vacía si está libre), sin
      repetidos; los períodos salen ordenados por inicio.
    - Una entrada vacía devuelve ``{}`` sin consultar; si no, una sola consulta.
    - Un período vacío o invertido es un ``ValueError``. No hace ``commit`` ni ``flush``.
    """
    if hasta <= desde:
        raise ValueError("El período debe terminar después de empezar.")
    unicas = list(dict.fromkeys(unidad_ids))
    if not unicas:
        return {}
    filas = await db.execute(
        select(
            DetallePrestamo.unidad_fisica_id,
            DetallePrestamo.retiro_pactado,
            DetallePrestamo.fin_ocupacion,
        )
        .where(
            DetallePrestamo.unidad_fisica_id.in_(unicas),
            DetallePrestamo.estado.in_(ESTADOS_DETALLE_QUE_OCUPAN),
            DetallePrestamo.periodo.op("&&")(func.tstzrange(desde, hasta, "[)")),
        )
        .order_by(DetallePrestamo.unidad_fisica_id, DetallePrestamo.retiro_pactado)
    )
    ocupacion: dict[int, list[PeriodoOcupado]] = {u: [] for u in unicas}
    for unidad_id, inicio, fin in filas:
        ocupacion[unidad_id].append(PeriodoOcupado(desde=inicio, hasta=fin))
    return ocupacion


# ── Crear orden (POST /ordenes) ──────────────────────────────────────────────


def equipamiento_no_encontrado(equipamiento_id: int) -> AppError:
    return AppError(
        404,
        "EQUIPAMIENTO_NO_ENCONTRADO",
        "El equipo pedido no existe o no está disponible para préstamo.",
        equipamiento_id=equipamiento_id,
    )


async def crear_orden(db: AsyncSession, actor: Usuario, payload: OrdenPedidoCreate) -> OrdenPedido:
    """Crea una orden ``pendiente`` con sus líneas ``pendiente`` (RN-L01…L10).

    Valida todo antes de escribir: un ``AppError`` de los pasos previos no deja nada
    que deshacer. Solo el último paso escribe, y si falla se hace ``rollback``.

    Los datos de los ítems salen de ``inventory.datos_equipamiento_por_ids`` (C8), sin
    leer sus modelos (P3.3). Primera versión (corte acordado mientras llega ``files``):
    la renovación responde ``501`` y un ítem de alta gama responde
    ``422 AVAL_REQUERIDO`` aunque traiga ``pdf_aval_id``, porque todavía no se
    puede vincular el archivo.
    """
    # 1. Rol y sede salen de la sesión (RN-L01, RN-L02); asignatura (RN-L07).
    if payload.renueva_detalle_id is not None:
        raise AppError(501, "NO_IMPLEMENTADO", "La renovación todavía no está disponible.")
    if actor.rol is RolUsuario.ESTUDIANTE and payload.asignatura_id is None:
        raise AppError(
            422, "ASIGNATURA_REQUERIDA", "Indicá la asignatura para la que pedís el equipo."
        )
    sede = actor.sede
    if sede is None:  # no debería pasar: el CHECK sede_segun_rol de usuarios lo impide
        raise AppError(
            403, "ROL_NO_AUTORIZADO", "Tu cuenta no tiene una sede asignada para pedir equipos."
        )
    retiro, devolucion = payload.retiro, payload.devolucion

    # 2. Parámetros (RN-L28). Horario global hasta que config publique el de cada sede (K10).
    apertura = await _hora(db, "horario.apertura")
    cierre = await _hora(db, "horario.cierre")
    anticipacion = await _entero(db, "solicitud.anticipacion_min_horas")
    max_general = await _entero(db, "prestamo.general.max_dias")
    max_notebook = await _entero(db, "prestamo.notebook.max_dias")

    # 3. Franja y anticipación (RN-L04, RN-L05).
    _validar_franja(retiro, devolucion, apertura, cierre)
    _validar_anticipacion(retiro, ahora_lab(), anticipacion)

    # 4. Datos de los ítems (RN-L10): inexistente o inactivo responde 404.
    solicitadas = Counter(item.equipamiento_id for item in payload.items)
    modelos = list(solicitadas)
    datos = await datos_equipamiento_por_ids(db, modelos)
    for equipamiento_id in modelos:
        item = datos.get(equipamiento_id)
        if item is None or not item.activo:
            raise equipamiento_no_encontrado(equipamiento_id)

    # 5. Aval (RN-L09). Sin files en develop, la alta gama todavía no se puede pedir.
    for equipamiento_id in modelos:
        if datos[equipamiento_id].alta_gama:
            raise AppError(
                422,
                "AVAL_REQUERIDO",
                "Este equipo es de alta gama y requiere el aval en PDF.",
                equipamiento_id=equipamiento_id,
            )

    # 6. Plazo por línea (RN-L06).
    for equipamiento_id in modelos:
        item = datos[equipamiento_id]
        limite = _limite_dias(item.es_notebook, max_general, max_notebook, item.max_dias_prestamo)
        _validar_plazo(retiro, devolucion, limite, equipamiento_id)

    # 7. Disponibilidad para el período (RN-L10). Las líneas pendientes no ocupan (RN-L03).
    libres = await ids_unidades_libres(db, modelos, sede, retiro, devolucion)
    _validar_disponibilidad(solicitadas, libres)

    # 8. Persistir en una sola transacción.
    orden = OrdenPedido(
        solicitante_id=actor.id,
        sede=sede,
        asignatura_id=payload.asignatura_id,
        estado=EstadoOrdenEnum.PENDIENTE,
        detalles=[
            DetallePrestamo(
                equipamiento_id=item.equipamiento_id,
                estado=EstadoDetalleEnum.PENDIENTE,
                retiro_pactado=retiro,
                devolucion_pactada=devolucion,
                fin_ocupacion=devolucion,
            )
            for item in payload.items
        ],
    )
    db.add(orden)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(orden)  # fecha_solicitud la pone la base
    return orden

