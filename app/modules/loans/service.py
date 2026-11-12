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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import puede_ver_sede, resolver_alcance_sede
from app.core.enums import RolUsuario, SedeEnum
from app.core.errors import AppError
from app.core.settings import ZONA_HORARIA_LAB, ahora_lab
from app.modules.config.service import obtener_parametro
from app.modules.files.enums import PropositoArchivo
from app.modules.files.service import ArchivoContenido, abrir_archivo, vincular_archivo
from app.modules.inventory.service import (
    bloquear_unidad,
    datos_equipamiento_por_ids,
    unidad_es_asignable,
    unidades_asignables,
)
from app.modules.loans.enums import (
    ESTADOS_DETALLE_QUE_OCUPAN,
    EstadoDetalleEnum,
    EstadoOrdenEnum,
)
from app.modules.loans.models import DetallePrestamo, OrdenHistorialEstado, OrdenPedido
from app.modules.loans.schemas import (
    LineaUnidadesLibresResponse,
    OrdenPedidoCreate,
    OrdenPedidoEstadoUpdate,
    OrdenPedidoResponse,
    ReglasResponse,
    SolicitanteResumen,
)
from app.modules.users.models import Usuario
from app.modules.users.service import DatosPublicosUsuario, datos_publicos_por_ids

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


async def listar_bandeja(
    db: AsyncSession,
    actor: Usuario,
    estado: EstadoOrdenEnum,
    sede: SedeEnum | None,
    limit: int,
    offset: int,
) -> list[OrdenPedidoResponse]:
    """Bandeja de validación (PRE-15): órdenes de la jurisdicción del administrador.

    - Sedes con ``resolver_alcance_sede``: el ``ADMIN_LOCAL`` siempre la suya (pedir
      otra responde ``403 SEDE_FUERA_DE_ALCANCE``); el ``SUPERADMIN``, la indicada o
      ambas. El filtro va en el ``WHERE`` (RN-L26).
    - De la más vieja a la más nueva, para atender primero lo que espera hace más.
    - Con el resumen del solicitante (P6).
    """
    sedes = resolver_alcance_sede(actor, sede)
    stmt = (
        select(OrdenPedido)
        .where(OrdenPedido.sede.in_(sedes), OrdenPedido.estado == estado)
        .order_by(OrdenPedido.fecha_solicitud.asc(), OrdenPedido.id.asc())
        .limit(limit)
        .offset(offset)
    )
    ordenes = list((await db.scalars(stmt)).all())
    return await respuestas_de_ordenes(db, actor, ordenes)


async def obtener_orden(db: AsyncSession, actor: Usuario, orden_id: int) -> OrdenPedidoResponse:
    """Detalle de una orden para el dueño o un administrador con jurisdicción; si no, 404."""
    orden = await _orden_con_alcance(db, actor, orden_id)
    return (await respuestas_de_ordenes(db, actor, [orden]))[0]


# ── Cambio de estado (PATCH /ordenes/{id}/estado) ────────────────────────────


def transicion_invalida(orden: OrdenPedido) -> AppError:
    return AppError(
        409,
        "TRANSICION_INVALIDA",
        f"La orden está {orden.estado.value} y no admite esta acción.",
        estado_actual=orden.estado.value,
    )


def _motivo_requerido(motivo: str | None) -> str:
    """RN-L15, RN-L16: rechazar y la cancelación del administrador exigen motivo."""
    if motivo is None:
        raise AppError(422, "MOTIVO_REQUERIDO", "Indicá el motivo.", campo="motivo")
    return motivo


def _resolver(
    orden: OrdenPedido,
    actor: Usuario,
    estado_nuevo: EstadoOrdenEnum,
    estado_lineas: EstadoDetalleEnum,
    motivo: str | None,
    lineas_desde: tuple[EstadoDetalleEnum, ...],
) -> OrdenHistorialEstado:
    """Aplica la transición en memoria: orden, líneas, resolución e historial (D-L10)."""
    historial = OrdenHistorialEstado(
        orden_id=orden.id,
        estado_anterior=orden.estado,
        estado_nuevo=estado_nuevo,
        motivo=motivo,
        actor_id=actor.id,
    )
    orden.estado = estado_nuevo
    orden.motivo_resolucion = motivo
    orden.resuelto_por_id = actor.id
    orden.resuelto_en = func.now()
    for detalle in orden.detalles:
        if detalle.estado in lineas_desde:
            detalle.estado = estado_lineas
    return historial


_SQLSTATE_EXCLUSION = "23P01"


def _es_solapamiento(exc: IntegrityError) -> bool:
    """¿La base rechazó la escritura por el ``EXCLUDE`` (SQLSTATE ``23P01``)?"""
    orig = exc.orig
    return _SQLSTATE_EXCLUSION in (getattr(orig, "sqlstate", None), getattr(orig, "pgcode", None))


def _asignaciones_invalidas(detalle: str) -> AppError:
    return AppError(422, "ASIGNACIONES_INVALIDAS", detalle)


def _unidad_no_asignable(detalle_id: int, unidad_id: int) -> AppError:
    return AppError(
        422,
        "UNIDAD_NO_ASIGNABLE",
        "La unidad elegida no se puede asignar a esa línea: no está disponible, "
        "es de otra sede o de otro equipo.",
        detalle_id=detalle_id,
        unidad_fisica_id=unidad_id,
    )


async def _validar_ajuste_horario(
    db: AsyncSession, orden: OrdenPedido, retiro: datetime, devolucion: datetime
) -> None:
    """RN-L18 (PRE-18, AC-L25): el horario nuevo cumple la franja y el plazo de cada línea.

    - El retiro nuevo tiene que ser futuro (``422 RETIRO_VENCIDO`` con ``campo``). No se
      exige la anticipación mínima: el administrador acuerda el horario con el solicitante.
    - Franja (RN-L04) y plazo por línea (RN-L06) con los parámetros vigentes, que pueden
      haber cambiado desde el pedido (EC-L11).
    - Que la devolución sea posterior al retiro ya lo valida el esquema.
    """
    if retiro <= ahora_lab():
        raise AppError(
            422,
            "RETIRO_VENCIDO",
            "El nuevo horario de retiro tiene que ser posterior a este momento.",
            campo="nuevo_retiro",
        )
    _validar_franja(
        retiro, devolucion, await _hora(db, "horario.apertura"), await _hora(db, "horario.cierre")
    )
    max_general = await _entero(db, "prestamo.general.max_dias")
    max_notebook = await _entero(db, "prestamo.notebook.max_dias")
    modelos = list(dict.fromkeys(d.equipamiento_id for d in orden.detalles))
    datos = await datos_equipamiento_por_ids(db, modelos)
    for equipamiento_id in modelos:
        item = datos.get(equipamiento_id)
        if item is None:  # no debería pasar: la FK lo impide
            continue
        limite = _limite_dias(item.es_notebook, max_general, max_notebook, item.max_dias_prestamo)
        _validar_plazo(retiro, devolucion, limite, equipamiento_id)


async def _aprobar(
    db: AsyncSession, orden: OrdenPedido, actor: Usuario, payload: OrdenPedidoEstadoUpdate
) -> OrdenHistorialEstado:
    """Aprobación de una orden ``pendiente`` ya bloqueada (RN-L11…L13, RN-L27, plan §8.5.5).

    1. Sin ajuste horario, el retiro tiene que ser futuro (``422 RETIRO_VENCIDO``) y no se
       revalidan plazos ni franja (EC-L11). Con ajuste (``nuevo_retiro`` y
       ``nueva_devolucion``), se valida el horario nuevo (``_validar_ajuste_horario``) y
       se aprueba aunque el retiro original haya vencido (EC-L05).
    2. Exactamente una asignación por línea, sin líneas ajenas ni unidades repetidas
       (``422 ASIGNACIONES_INVALIDAS``, AC-L22).
    3. Cada unidad se bloquea en orden ascendente de id (RN-L14) y tiene que ser del
       modelo de la línea, de la sede de la orden, ``disponible`` y de un ítem activo
       (``422 UNIDAD_NO_ASIGNABLE``, AC-L20, L21, L26; EC-L08). ``loans`` solo lee la
       unidad: su estado es de ``inventory`` (DT-20).
    4. Líneas ``reservado`` con su unidad y, si hubo ajuste, con las fechas nuevas en todas
       las líneas y ``fin_ocupacion`` igual a la devolución nueva (RN-L18). El solapamiento
       con otra reserva lo rechaza la base al hacer ``commit`` con el período definitivo
       (``409 UNIDAD_NO_DISPONIBLE``, lo traduce quien llama).
    """
    # 1. Ajuste horario (RN-L18) o retiro vencido (RN-L27, AC-L30).
    ajuste = None
    if payload.nuevo_retiro is not None and payload.nueva_devolucion is not None:
        ajuste = (payload.nuevo_retiro, payload.nueva_devolucion)
        await _validar_ajuste_horario(db, orden, *ajuste)
    retiro = min((d.retiro_pactado for d in orden.detalles), default=None)
    if ajuste is None and retiro is not None and retiro <= ahora_lab():
        raise AppError(
            422,
            "RETIRO_VENCIDO",
            "La fecha de retiro ya pasó: rechazá la orden o aprobala ajustando el horario.",
        )

    # 2. Asignaciones (RN-L11, AC-L22). El esquema ya rechaza dos para la misma línea.
    lineas = {d.id: d for d in orden.detalles}
    unidad_de = {a.detalle_id: a.unidad_fisica_id for a in payload.asignaciones}
    if set(unidad_de) - set(lineas):
        raise _asignaciones_invalidas("Hay asignaciones para líneas que no son de esta orden.")
    if set(lineas) - set(unidad_de):
        raise _asignaciones_invalidas("Asigná una unidad a cada línea de la orden.")
    if len(set(unidad_de.values())) != len(unidad_de):
        raise _asignaciones_invalidas("No se puede asignar la misma unidad a dos líneas.")

    # 3. Unidades, bloqueadas en orden ascendente de id (RN-L14).
    for detalle_id, unidad_id in sorted(unidad_de.items(), key=lambda par: par[1]):
        unidad = await bloquear_unidad(db, unidad_id)
        if (
            unidad is None
            or unidad.equipamiento_id != lineas[detalle_id].equipamiento_id
            or not await unidad_es_asignable(db, unidad_id, orden.sede)
        ):
            raise _unidad_no_asignable(detalle_id, unidad_id)

    # 4. Aplicar (AC-L19, AC-L25).
    for detalle_id, unidad_id in unidad_de.items():
        lineas[detalle_id].unidad_fisica_id = unidad_id
        if ajuste is not None:
            linea = lineas[detalle_id]
            linea.retiro_pactado, linea.devolucion_pactada = ajuste
            linea.fin_ocupacion = ajuste[1]
    return _resolver(
        orden,
        actor,
        EstadoOrdenEnum.APROBADA,
        EstadoDetalleEnum.RESERVADO,
        payload.motivo,
        lineas_desde=(EstadoDetalleEnum.PENDIENTE,),
    )


async def cambiar_estado_orden(
    db: AsyncSession, actor: Usuario, orden_id: int, payload: OrdenPedidoEstadoUpdate
) -> OrdenPedidoResponse:
    """Aprobar, rechazar o cancelar una orden (PRE-10, RN-L14…L16, plan §8.5.4).

    Orden de los controles: (1) rol, que no depende de la orden (403); (2) leer y
    bloquear la orden con alcance (404); (3) transición válida desde el estado actual
    (409); (4) datos del pedido (422); (5) aplicar y ``commit``. Ante un ``AppError``
    después de bloquear, ``rollback`` antes de propagarlo (RN-L14).

    - ``rechazada``: administrador con jurisdicción, orden ``pendiente``, con motivo.
    - ``cancelada`` por el dueño: solo su orden ``pendiente``; motivo opcional. Si está
      ``aprobada``, ``403 CANCELACION_NO_PERMITIDA`` (AC-L32).
    - ``aprobada``: administrador con jurisdicción, orden ``pendiente``, una unidad por
      línea (``_aprobar``). Un solapamiento que rechaza la base responde
      ``409 UNIDAD_NO_DISPONIBLE`` sin cambios parciales (RN-L13).
    - ``cancelada`` por el administrador: solo una orden ``aprobada`` sin líneas
      ``entregado`` (si no, ``409``), con motivo (``422 MOTIVO_REQUERIDO``). Las líneas
      ``reservado`` pasan a ``cancelado`` y liberan su unidad (AC-L33, AC-L34).
    """
    pedido = payload.estado
    # 1. Aprobar y rechazar son administrativos, sea o no el dueño (AC-L29).
    if pedido is not EstadoOrdenEnum.CANCELADA and not _es_admin(actor):
        raise AppError(
            403, "ROL_NO_AUTORIZADO", "Solo un administrador puede aprobar o rechazar órdenes."
        )
    try:
        # 2. Alcance y bloqueo de la fila (RN-L14, RN-L25, RN-L26).
        orden = await _orden_con_alcance(db, actor, orden_id, bloquear=True)
        actual = orden.estado
        es_dueño = orden.solicitante_id == actor.id

        if pedido is EstadoOrdenEnum.APROBADA:
            if actual is not EstadoOrdenEnum.PENDIENTE:
                raise transicion_invalida(orden)
            historial = await _aprobar(db, orden, actor, payload)

        elif pedido is EstadoOrdenEnum.RECHAZADA:
            # 3. Solo se rechaza una pendiente (AC-L28); 4. con motivo (AC-L27).
            if actual is not EstadoOrdenEnum.PENDIENTE:
                raise transicion_invalida(orden)
            historial = _resolver(
                orden,
                actor,
                EstadoOrdenEnum.RECHAZADA,
                EstadoDetalleEnum.RECHAZADO,
                _motivo_requerido(payload.motivo),
                lineas_desde=(EstadoDetalleEnum.PENDIENTE,),
            )
        elif es_dueño:
            # Cancelación del solicitante (RN-L16, AC-L31, AC-L32).
            if actual is EstadoOrdenEnum.APROBADA:
                raise AppError(
                    403,
                    "CANCELACION_NO_PERMITIDA",
                    "Tu orden ya fue aprobada: para cancelarla, comunicate con el laboratorio.",
                )
            if actual is not EstadoOrdenEnum.PENDIENTE:
                raise transicion_invalida(orden)
            historial = _resolver(
                orden,
                actor,
                EstadoOrdenEnum.CANCELADA,
                EstadoDetalleEnum.CANCELADO,
                payload.motivo,
                lineas_desde=(EstadoDetalleEnum.PENDIENTE,),
            )
        else:
            # Cancelación del administrador (RN-L16, AC-L33, AC-L34): solo una aprobada,
            # sin entregas, con motivo. Las líneas reservado liberan su unidad.
            if actual is not EstadoOrdenEnum.APROBADA or any(
                d.estado is EstadoDetalleEnum.ENTREGADO for d in orden.detalles
            ):
                raise transicion_invalida(orden)
            historial = _resolver(
                orden,
                actor,
                EstadoOrdenEnum.CANCELADA,
                EstadoDetalleEnum.CANCELADO,
                _motivo_requerido(payload.motivo),
                lineas_desde=(EstadoDetalleEnum.RESERVADO,),
            )

        # 5. Aplicar en una sola transacción: todo o nada (RN-L13).
        db.add(historial)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _es_solapamiento(exc):  # el EXCLUDE de 0009 (RN-L12, AC-L23, AC-L47)
            raise AppError(
                409,
                "UNIDAD_NO_DISPONIBLE",
                "Alguna de las unidades ya está reservada en fechas que se superponen.",
            ) from exc
        raise  # CHECK, unicidad o FK no se enmascaran como conflicto (AC-L53)
    except Exception:
        await db.rollback()
        raise
    await db.refresh(orden)  # resuelto_en lo pone la base
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


async def unidades_libres_de_orden(
    db: AsyncSession, actor: Usuario, orden_id: int
) -> list[LineaUnidadesLibresResponse]:
    """Por cada línea de la orden, las unidades que se le pueden asignar (RN-L12, AC-L58).

    Mismo criterio que ``ids_unidades_libres``: del modelo de la línea, en la sede de la
    orden, ``disponible`` y sin otra línea ocupante que se solape con su período. Una
    reserva en otras fechas no la excluye (AC-L47). Fuera de alcance, 404 (RN-L26).
    Las líneas de una orden comparten el período, así que alcanza con una llamada; se
    agrupa por período por si una línea quedara con otro.
    """
    orden = await _orden_con_alcance(db, actor, orden_id)
    por_periodo: dict[tuple[datetime, datetime], list[DetallePrestamo]] = {}
    for detalle in orden.detalles:
        periodo = (detalle.retiro_pactado, detalle.fin_ocupacion)
        por_periodo.setdefault(periodo, []).append(detalle)
    libres: dict[int, list[int]] = {}  # detalle_id → ids de unidades
    for (desde, hasta), detalles in por_periodo.items():
        modelos = [d.equipamiento_id for d in detalles]
        por_modelo = await ids_unidades_libres(db, modelos, orden.sede, desde, hasta)
        libres |= {d.id: por_modelo[d.equipamiento_id] for d in detalles}
    return [
        LineaUnidadesLibresResponse(
            detalle_id=d.id, equipamiento_id=d.equipamiento_id, unidades=libres[d.id]
        )
        for d in orden.detalles
    ]


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


# ── Reservas e historial por unidad (API pública para inventory, Fase C de SPEC-04) ──


@dataclass(frozen=True, slots=True)
class ReservaFutura:
    """Una reserva aprobada (línea ``reservado``) de una unidad, sin identidad (P6)."""

    orden_id: int
    detalle_id: int
    retiro: datetime
    devolucion: datetime


async def reservas_futuras_de_unidad(
    db: AsyncSession, unidad_id: int, desde: datetime
) -> list[ReservaFutura]:
    """API pública (§10.2): reservas aprobadas de la unidad que empiezan desde ``desde``.

    Para el aviso de ``reservas_afectadas`` al pasar una unidad a ``mantenimiento`` o
    ``baja`` (PRE-17, SPEC-04 §5.3): ``reservas_afectadas = len(...)``.

    - Solo líneas ``reservado`` con ``retiro_pactado >= desde``; una ``entregado`` ya
      empezó y no cuenta. Ordenadas por retiro (y por id ante un empate).
    - ``devolucion`` es ``devolucion_pactada``.
    - Sin solicitante ni sede: la jurisdicción la valida ``inventory`` antes de llamar.
    - Una sola consulta. No hace ``commit`` ni ``flush``.
    """
    filas = await db.execute(
        select(
            DetallePrestamo.orden_id,
            DetallePrestamo.id,
            DetallePrestamo.retiro_pactado,
            DetallePrestamo.devolucion_pactada,
        )
        .where(
            DetallePrestamo.unidad_fisica_id == unidad_id,
            DetallePrestamo.estado == EstadoDetalleEnum.RESERVADO,
            DetallePrestamo.retiro_pactado >= desde,
        )
        .order_by(DetallePrestamo.retiro_pactado, DetallePrestamo.id)
    )
    return [
        ReservaFutura(orden_id=orden_id, detalle_id=detalle_id, retiro=retiro, devolucion=dev)
        for orden_id, detalle_id, retiro, dev in filas
    ]


@dataclass(frozen=True, slots=True)
class MovimientoUnidad:
    """Una línea que usó (o tiene reservada) la unidad, para su historial (PRE-12).

    Campos de SPEC-04 §5.5. ``entregado_en``, ``devuelto_en`` y
    ``observacion_devolucion`` valen ``None`` hasta la migración ``0012`` (Fase 3); ya
    están en la firma para que el contrato no cambie.
    """

    orden_id: int
    detalle_id: int
    solicitante: DatosPublicosUsuario | None
    estado: EstadoDetalleEnum
    retiro_pactado: datetime
    devolucion_pactada: datetime
    entregado_en: datetime | None = None
    devuelto_en: datetime | None = None
    observacion_devolucion: str | None = None


async def historial_de_unidad(
    db: AsyncSession, unidad_id: int, actor: Usuario, *, limit: int = 20, offset: int = 0
) -> list[MovimientoUnidad]:
    """API pública (§10.2): las líneas de la unidad, de la más reciente a la más antigua.

    Para ``GET /unidades/{id}/historial`` de ``inventory`` (PRE-12, SPEC-04 §5.5).

    - Todas las líneas con esa unidad asignada, en cualquier estado, ordenadas por
      ``retiro_pactado`` descendente (y por id ante un empate), con ``limit`` y ``offset``.
    - Alcance (P5, RN-L26), en el ``WHERE``: el ``ADMIN_LOCAL`` ve solo las líneas de
      órdenes de su sede y el ``SUPERADMIN`` todas; cualquier otro rol, lista vacía.
    - ``solicitante``: ``id``, ``nombre`` y ``apellido`` de ``users.datos_publicos_por_ids``,
      nunca DNI, email ni teléfono (P6).
    - Dos consultas: las líneas y los solicitantes. No hace ``commit`` ni ``flush``.
    """
    if not _es_admin(actor):
        return []
    stmt = (
        select(
            DetallePrestamo.orden_id,
            DetallePrestamo.id,
            OrdenPedido.solicitante_id,
            DetallePrestamo.estado,
            DetallePrestamo.retiro_pactado,
            DetallePrestamo.devolucion_pactada,
        )
        .join(OrdenPedido, OrdenPedido.id == DetallePrestamo.orden_id)
        .where(
            DetallePrestamo.unidad_fisica_id == unidad_id,
            OrdenPedido.sede.in_(resolver_alcance_sede(actor, None)),
        )
        .order_by(DetallePrestamo.retiro_pactado.desc(), DetallePrestamo.id.desc())
        .limit(limit)
        .offset(offset)
    )
    filas = (await db.execute(stmt)).all()
    if not filas:
        return []
    solicitantes = await datos_publicos_por_ids(db, {f.solicitante_id for f in filas})
    return [
        MovimientoUnidad(
            orden_id=orden_id,
            detalle_id=detalle_id,
            solicitante=solicitantes.get(solicitante_id),
            estado=estado,
            retiro_pactado=retiro,
            devolucion_pactada=devolucion,
        )
        for orden_id, detalle_id, solicitante_id, estado, retiro, devolucion in filas
    ]


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
    leer sus modelos (P3.3). Con ítems de alta gama, el aval se vincula con
    ``files.vincular_archivo`` en la misma transacción que crea la orden (RN-L09, K3):
    si la creación falla, el archivo no queda vinculado. La renovación todavía
    responde ``501`` (T1.14).
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

    # 5. Aval (RN-L09): obligatorio si hay alta gama. Sin alta gama, `pdf_aval_id` se
    # ignora (no se vincula ni se guarda; `files` limpia los archivos huérfanos).
    alta_gama = [m for m in modelos if datos[m].alta_gama]
    if alta_gama and payload.pdf_aval_id is None:
        raise AppError(
            422,
            "AVAL_REQUERIDO",
            "Este equipo es de alta gama y requiere el aval en PDF.",
            equipamiento_id=alta_gama[0],
        )
    aval_id = payload.pdf_aval_id if alta_gama else None

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
        aval_archivo_id=aval_id,
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
        if aval_id is not None:  # 422 ARCHIVO_INVALIDO si es ajeno, de otro tipo o ya usado
            await vincular_archivo(
                db, aval_id, propietario_id=actor.id, proposito=PropositoArchivo.AVAL_PRESTAMO
            )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(orden)  # fecha_solicitud la pone la base
    return orden


# ── Aval de la orden (GET /ordenes/{id}/aval) ────────────────────────────────


def aval_no_encontrado() -> AppError:
    return AppError(404, "ARCHIVO_NO_ENCONTRADO", "Esta orden no tiene un aval para descargar.")


async def descargar_aval(db: AsyncSession, actor: Usuario, orden_id: int) -> ArchivoContenido:
    """El PDF de aval de la orden (AC-L60, RN-60 de SPEC-03).

    Lo descargan el solicitante y los administradores con jurisdicción, con el mismo
    alcance que el detalle (``_orden_con_alcance``). El docente de la asignatura no lo
    descarga: no es dueño ni administrador. Sin aval, 404.
    """
    orden = await _orden_con_alcance(db, actor, orden_id)
    if orden.aval_archivo_id is None:
        raise aval_no_encontrado()
    contenido = await abrir_archivo(db, orden.aval_archivo_id)
    if contenido is None:
        raise aval_no_encontrado()
    return contenido
