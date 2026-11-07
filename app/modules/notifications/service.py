"""Lógica del módulo `notifications` (SPEC-06).

Este archivo tiene dos partes:

- **Interna** (comunicados, Fase A): la usan sólo los endpoints de este módulo.
- **Pública** (``crear_notificacion``, Fase B, §6): se agrega en la Fase B y es
  la única parte que otros módulos pueden importar.

Las funciones internas no hacen ``commit``: lo hace el endpoint.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import resolver_alcance_sede
from app.core.enums import ROLES_ADMIN, RolUsuario, SedeEnum
from app.core.errors import AppError
from app.core.settings import ZONA_HORARIA_LAB, ahora_lab
from app.modules.notifications.enums import EstadoComunicado
from app.modules.notifications.models import Comunicado
from app.modules.notifications.schemas import (
    AutorComunicado,
    ComunicadoCreate,
    ComunicadoResponse,
    ComunicadoUpdate,
)
from app.modules.users.models import Usuario
from app.modules.users.service import datos_publicos_por_ids

# ── Errores ──────────────────────────────────────────────────────────────────


def comunicado_no_encontrado() -> AppError:
    return AppError(404, "COMUNICADO_NO_ENCONTRADO", "Comunicado no encontrado.")


def _sede_fuera_de_alcance() -> AppError:
    return AppError(
        403, "SEDE_FUERA_DE_ALCANCE", "No tenés jurisdicción sobre la sede solicitada."
    )


# ── Alcance (RN-N2, RN-N3, RN-N5) ────────────────────────────────────────────


def sede_para_comunicado(
    usuario: Usuario, sede: SedeEnum | None, es_global: bool
) -> tuple[SedeEnum | None, bool]:
    """Sede y alcance de un comunicado nuevo (NOV-02, GLO-01, SPEC-06 RN-N2).

    - ``ADMIN_LOCAL``: siempre su sede; otra sede o global → ``403``.
    - ``SUPERADMIN``: exactamente una de las dos; ninguna → ``422 SEDE_REQUERIDA``.
      (Las dos a la vez ya las rechaza ``ComunicadoCreate``.)
    """
    if usuario.rol == RolUsuario.SUPERADMIN:
        if es_global:
            return None, True
        if sede is None:
            raise AppError(
                422, "SEDE_REQUERIDA", "Indicá la sede del comunicado o marcalo como global."
            )
        return sede, False

    assert usuario.sede is not None  # garantizado por CHECK ck_usuarios_sede_segun_rol
    if es_global or (sede is not None and sede != usuario.sede):
        raise _sede_fuera_de_alcance()
    return usuario.sede, False


def _es_admin(usuario: Usuario) -> bool:
    return usuario.rol in ROLES_ADMIN


def _vigente(ahora: datetime) -> ColumnElement[bool]:
    return and_(
        Comunicado.estado == EstadoComunicado.PUBLICADO,
        or_(Comunicado.vence_en.is_(None), Comunicado.vence_en > ahora),
    )


def _filtro_lectura(
    usuario: Usuario, sedes: Sequence[SedeEnum], incluir_archivados: bool, ahora: datetime
) -> list[ColumnElement[bool]]:
    """Condiciones de lectura (RN-N3): sedes del alcance más los globales."""
    condiciones: list[ColumnElement[bool]] = [
        or_(Comunicado.sede.in_(sedes), Comunicado.es_global.is_(True))
    ]
    if not _es_admin(usuario):
        condiciones.append(_vigente(ahora))
    elif not incluir_archivados:
        condiciones.append(Comunicado.estado == EstadoComunicado.PUBLICADO)
    return condiciones


# ── Lectura ──────────────────────────────────────────────────────────────────


async def listar_comunicados(
    db: AsyncSession,
    usuario: Usuario,
    *,
    sede: SedeEnum | None,
    incluir_archivados: bool,
    limit: int,
    offset: int,
) -> tuple[list[Comunicado], int]:
    """Comunicados visibles para ``usuario``, del más nuevo al más viejo (NOV-02)."""
    sedes = resolver_alcance_sede(usuario, sede)
    condiciones = _filtro_lectura(usuario, sedes, incluir_archivados, ahora_lab())
    total = await db.scalar(select(func.count()).select_from(Comunicado).where(*condiciones))
    filas = await db.scalars(
        select(Comunicado)
        .where(*condiciones)
        .order_by(Comunicado.publicado_en.desc(), Comunicado.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(filas.all()), total or 0


async def obtener_comunicado(db: AsyncSession, usuario: Usuario, comunicado_id: int) -> Comunicado:
    """Detalle con las mismas reglas de lectura; fuera de alcance → ``404`` (P4.5)."""
    sedes = resolver_alcance_sede(usuario, None)
    comunicado = await db.scalar(
        select(Comunicado).where(
            Comunicado.id == comunicado_id,
            *_filtro_lectura(usuario, sedes, incluir_archivados=True, ahora=ahora_lab()),
        )
    )
    if comunicado is None:
        raise comunicado_no_encontrado()
    return comunicado


async def _bloquear_para_editar(
    db: AsyncSession, usuario: Usuario, comunicado_id: int
) -> Comunicado:
    """Carga con ``FOR UPDATE`` un comunicado que ``usuario`` puede editar (RN-N5).

    Un ``ADMIN_LOCAL`` edita los de su sede (de cualquier autor), nunca los globales.
    """
    condiciones: list[ColumnElement[bool]] = [Comunicado.id == comunicado_id]
    if usuario.rol != RolUsuario.SUPERADMIN:
        condiciones.append(Comunicado.sede == usuario.sede)
    comunicado = await db.scalar(select(Comunicado).where(*condiciones).with_for_update())
    if comunicado is None:
        raise comunicado_no_encontrado()
    return comunicado


# ── Escritura ────────────────────────────────────────────────────────────────


def _validar_vencimiento(vence_en: datetime | None, ahora: datetime) -> None:
    if vence_en is not None and vence_en <= ahora:
        raise AppError(
            422, "VENCIMIENTO_INVALIDO", "La fecha de vencimiento tiene que ser futura."
        )


def crear_comunicado(db: AsyncSession, usuario: Usuario, datos: ComunicadoCreate) -> Comunicado:
    """Agrega un comunicado a la sesión (NOV-02, RN-N2). No hace ``commit``."""
    sede, es_global = sede_para_comunicado(usuario, datos.sede, datos.es_global)
    ahora = ahora_lab()
    _validar_vencimiento(datos.vence_en, ahora)
    comunicado = Comunicado(
        titulo=datos.titulo,
        contenido=datos.contenido,
        sede=sede,
        es_global=es_global,
        estado=EstadoComunicado.PUBLICADO,
        autor_id=usuario.id,
        publicado_en=ahora,
        vence_en=datos.vence_en,
        actualizado_en=ahora,
    )
    db.add(comunicado)
    return comunicado


async def editar_comunicado(
    db: AsyncSession, usuario: Usuario, comunicado_id: int, datos: ComunicadoUpdate
) -> Comunicado:
    """Edita título, contenido y vencimiento (RN-N5). No hace ``commit``."""
    comunicado = await _bloquear_para_editar(db, usuario, comunicado_id)
    ahora = ahora_lab()
    cambios = datos.model_dump(exclude_unset=True)
    if "vence_en" in cambios:
        _validar_vencimiento(cambios["vence_en"], ahora)
    for campo, valor in cambios.items():
        setattr(comunicado, campo, valor)
    comunicado.actualizado_en = ahora
    return comunicado


async def cambiar_estado_comunicado(
    db: AsyncSession, usuario: Usuario, comunicado_id: int, estado: EstadoComunicado
) -> Comunicado:
    """Archiva o reactiva (RN-N4). Mismo estado → sin cambios (idempotente)."""
    comunicado = await _bloquear_para_editar(db, usuario, comunicado_id)
    if comunicado.estado != estado:
        comunicado.estado = estado
        comunicado.actualizado_en = ahora_lab()
    return comunicado


# ── Respuesta ────────────────────────────────────────────────────────────────


def _local(valor: datetime | None) -> datetime | None:
    """Todas las fechas salen en la zona del laboratorio, vengan de la base o no."""
    return valor.astimezone(ZONA_HORARIA_LAB) if valor is not None else None


async def a_respuestas(
    db: AsyncSession, comunicados: Sequence[Comunicado]
) -> list[ComunicadoResponse]:
    """Arma las respuestas con el autor resuelto en **una** consulta (P6)."""
    autores = await datos_publicos_por_ids(
        db, (c.autor_id for c in comunicados if c.autor_id is not None)
    )
    ahora = ahora_lab()
    respuestas = []
    for c in comunicados:
        autor = autores.get(c.autor_id) if c.autor_id is not None else None
        respuestas.append(
            ComunicadoResponse(
                id=c.id,
                titulo=c.titulo,
                contenido=c.contenido,
                sede=c.sede,
                es_global=c.es_global,
                estado=c.estado,
                vigente=c.estado == EstadoComunicado.PUBLICADO
                and (c.vence_en is None or c.vence_en > ahora),
                autor=AutorComunicado.model_validate(autor) if autor else None,
                publicado_en=_local(c.publicado_en),
                vence_en=_local(c.vence_en),
                actualizado_en=_local(c.actualizado_en),
            )
        )
    return respuestas
