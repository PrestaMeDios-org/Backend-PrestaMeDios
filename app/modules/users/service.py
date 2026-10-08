"""Reglas de negocio del módulo `users` (SPEC-01 §3.2, §5, §7).

Los servicios no conocen HTTP salvo ``AppError``; los routers sólo validan
contrato y permisos y delegan aquí.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import permiso_insuficiente, resolver_alcance_sede
from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum
from app.core.errors import AppError
from app.core.security import (
    crear_access_token,
    hash_password,
    verify_dummy,
    verify_password,
)
from app.modules.users.models import Usuario, UsuarioHistorialEstado
from app.modules.users.schemas import CambioEstadoRequest, RegistroRequest, UsuarioAdminCreate

E = EstadoCuenta

# (desde, hacia) → ¿incrementa token_version? (SPEC-01 §3.2). Lo no listado es inválido.
TRANSICIONES: dict[tuple[EstadoCuenta, EstadoCuenta], bool] = {
    (E.PENDIENTE_APROBACION, E.ACTIVO): False,
    (E.PENDIENTE_APROBACION, E.RECHAZADO): False,
    (E.ACTIVO, E.SUSPENDIDO): True,
    (E.ACTIVO, E.INACTIVO): True,
    (E.SUSPENDIDO, E.ACTIVO): False,
    (E.SUSPENDIDO, E.INACTIVO): True,
    (E.INACTIVO, E.ACTIVO): False,
}

ROLES_GESTIONABLES_POR_ADMIN_LOCAL = frozenset({RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE})

MOTIVO_FIN_SANCION = "Fin automático de la sanción (vencimiento de suspendido_hasta)."


# ── Errores ──────────────────────────────────────────────────────────────────


def _email_duplicado() -> AppError:
    return AppError(409, "EMAIL_YA_REGISTRADO", "Ya existe una cuenta con ese email.")


def _dni_duplicado() -> AppError:
    return AppError(409, "DNI_YA_REGISTRADO", "Ya existe una cuenta con ese DNI.")


def _credenciales_invalidas() -> AppError:
    return AppError(401, "CREDENCIALES_INVALIDAS", "Email o contraseña incorrectos.")


def usuario_no_encontrado() -> AppError:
    return AppError(404, "USUARIO_NO_ENCONTRADO", "Usuario no encontrado.")


def _error_cuenta_no_activa(usuario: Usuario) -> AppError:
    """Sólo se invoca DESPUÉS de verificar la contraseña (RN-07)."""
    match usuario.estado:
        case E.PENDIENTE_APROBACION:
            return AppError(
                403,
                "CUENTA_PENDIENTE_APROBACION",
                "Tu cuenta está pendiente de aprobación por la administración del Laboratorio.",
            )
        case E.RECHAZADO:
            return AppError(403, "CUENTA_RECHAZADA", "Tu solicitud de cuenta fue rechazada.")
        case E.SUSPENDIDO:
            hasta = usuario.suspendido_hasta
            detalle = (
                f"Tu cuenta está suspendida hasta el {hasta:%Y-%m-%d}."
                if hasta is not None
                else "Tu cuenta está suspendida."
            )
            return AppError(403, "CUENTA_SUSPENDIDA", detalle, suspendido_hasta=hasta)
        case _:
            return AppError(403, "CUENTA_INACTIVA", "Tu cuenta está dada de baja.")


async def _persistir(db: AsyncSession, *, commit: bool) -> None:
    """``flush``/``commit`` traduciendo violaciones de UNIQUE a 409 (EC-12)."""
    try:
        await (db.commit() if commit else db.flush())
    except IntegrityError as exc:
        await db.rollback()
        mensaje = str(exc.orig)
        if "uq_usuarios_dni" in mensaje:
            raise _dni_duplicado() from exc
        if "uq_usuarios_email" in mensaje:
            raise _email_duplicado() from exc
        raise


def _registrar_historial(
    db: AsyncSession,
    usuario: Usuario,
    anterior: EstadoCuenta | None,
    nuevo: EstadoCuenta,
    *,
    motivo: str | None,
    actor_id: int | None,
) -> None:
    """RN-22: traza inmutable en la misma transacción."""
    db.add(
        UsuarioHistorialEstado(
            usuario_id=usuario.id,
            estado_anterior=anterior,
            estado_nuevo=nuevo,
            motivo=motivo,
            actor_id=actor_id,
        )
    )


async def _buscar_por(db: AsyncSession, **filtro: str) -> Usuario | None:
    return await db.scalar(select(Usuario).filter_by(**filtro))


# ── UC-01 · Autorregistro ────────────────────────────────────────────────────


async def registrar(db: AsyncSession, datos: RegistroRequest) -> Usuario:
    """Crea la cuenta en ``PENDIENTE_APROBACION`` o reabre una ``RECHAZADO`` (USR-05, D-04)."""
    por_email = await _buscar_por(db, email=datos.email)
    por_dni = await _buscar_por(db, dni=datos.dni)

    if por_email is not None and por_email.estado != E.RECHAZADO:
        raise _email_duplicado()
    if por_dni is not None and por_dni.estado != E.RECHAZADO:
        raise _dni_duplicado()
    if por_email is not None and por_dni is not None and por_email.id != por_dni.id:
        raise _dni_duplicado()

    reabrir = por_email or por_dni
    if reabrir is not None:  # UC-01 FA-03: re-registro tras rechazo
        reabrir.email = datos.email
        reabrir.dni = datos.dni
        reabrir.password_hash = hash_password(datos.password)
        reabrir.nombre = datos.nombre
        reabrir.apellido = datos.apellido
        reabrir.telefono = datos.telefono
        reabrir.rol = datos.rol
        reabrir.sede = datos.sede
        reabrir.estado = E.PENDIENTE_APROBACION
        reabrir.motivo_estado = None
        reabrir.aprobado_por_id = None
        reabrir.aprobado_en = None
        _registrar_historial(
            db, reabrir, E.RECHAZADO, E.PENDIENTE_APROBACION, motivo="Re-registro", actor_id=None
        )
        usuario = reabrir
    else:
        usuario = Usuario(
            email=datos.email,
            password_hash=hash_password(datos.password),
            nombre=datos.nombre,
            apellido=datos.apellido,
            dni=datos.dni,
            telefono=datos.telefono,
            rol=datos.rol,
            sede=datos.sede,
            estado=E.PENDIENTE_APROBACION,
        )
        db.add(usuario)
        await _persistir(db, commit=False)
        _registrar_historial(
            db, usuario, None, E.PENDIENTE_APROBACION, motivo=None, actor_id=None
        )

    await _persistir(db, commit=True)
    await db.refresh(usuario)
    return usuario


# ── UC-03 · Login ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Sesion:
    usuario: Usuario
    access_token: str
    expires_in: int


async def autenticar(db: AsyncSession, email: str, password: str) -> Sesion:
    """Verifica credenciales y estado y emite el access token (USR-01; RN-06…RN-09)."""
    usuario = await _buscar_por(db, email=email)
    if usuario is None:
        verify_dummy(password)  # RN-06: tiempo de respuesta homogéneo
        raise _credenciales_invalidas()

    valida, nuevo_hash = verify_password(password, usuario.password_hash)
    if not valida:
        raise _credenciales_invalidas()  # RN-07: no se revela el estado

    ahora = datetime.now(UTC)
    if (
        usuario.estado == E.SUSPENDIDO
        and usuario.suspendido_hasta is not None
        and usuario.suspendido_hasta <= ahora
    ):
        usuario = await _bloquear(db, usuario.id)
        if usuario.estado == E.SUSPENDIDO:  # re-chequeo tras el lock
            usuario.estado = E.ACTIVO
            usuario.suspendido_hasta = None
            usuario.motivo_estado = None
            _registrar_historial(
                db, usuario, E.SUSPENDIDO, E.ACTIVO, motivo=MOTIVO_FIN_SANCION, actor_id=None
            )

    if usuario.estado != E.ACTIVO:
        error = _error_cuenta_no_activa(usuario)  # antes del rollback: expira los atributos
        await db.rollback()  # libera un eventual lock tomado en _bloquear
        raise error

    if nuevo_hash is not None:
        usuario.password_hash = nuevo_hash
    usuario.ultimo_login_en = ahora
    await db.commit()

    token, expires_in = crear_access_token(
        usuario_id=usuario.id,
        rol=usuario.rol,
        sede=usuario.sede,
        token_version=usuario.token_version,
    )
    return Sesion(usuario=usuario, access_token=token, expires_in=expires_in)


async def _bloquear(db: AsyncSession, usuario_id: int) -> Usuario:
    usuario = await db.scalar(
        select(Usuario)
        .where(Usuario.id == usuario_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if usuario is None:
        raise usuario_no_encontrado()
    return usuario


# ── UC-05 · Directorio ───────────────────────────────────────────────────────

OrdenDirectorio = Literal["apellido", "created_at"]
Direccion = Literal["asc", "desc"]


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtrar_por_alcance(stmt: Select, actor: Usuario, sede: SedeEnum | None) -> Select:
    alcance = resolver_alcance_sede(actor, sede)
    if actor.rol == RolUsuario.SUPERADMIN and sede is None:
        return stmt  # vista consolidada: incluye a los SUPERADMIN (sede NULL)
    return stmt.where(Usuario.sede.in_(alcance))


async def listar_directorio(
    db: AsyncSession,
    actor: Usuario,
    *,
    sede: SedeEnum | None,
    rol: RolUsuario | None,
    estado: EstadoCuenta | None,
    q: str | None,
    ordenar_por: OrdenDirectorio,
    direccion: Direccion,
    limit: int,
    offset: int,
) -> tuple[list[Usuario], int]:
    """Directorio con aislamiento de sede (USR-04, GLO-01, RN-10)."""
    stmt = _filtrar_por_alcance(select(Usuario), actor, sede)
    if rol is not None:
        stmt = stmt.where(Usuario.rol == rol)
    if estado is not None:
        stmt = stmt.where(Usuario.estado == estado)
    if q is not None:
        patron = f"%{_escapar_like(q)}%"
        stmt = stmt.where(
            or_(
                Usuario.nombre.ilike(patron, escape="\\"),
                Usuario.apellido.ilike(patron, escape="\\"),
                Usuario.email.ilike(patron, escape="\\"),
                Usuario.dni.ilike(patron, escape="\\"),
            )
        )

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    columna = Usuario.apellido if ordenar_por == "apellido" else Usuario.created_at
    orden = columna.asc() if direccion == "asc" else columna.desc()
    items = await db.scalars(stmt.order_by(orden, Usuario.id.asc()).limit(limit).offset(offset))
    return list(items.all()), total


async def obtener_en_alcance(db: AsyncSession, actor: Usuario, usuario_id: int) -> Usuario:
    """RN-11: fuera de la jurisdicción del ADMIN_LOCAL se responde como inexistente."""
    usuario = await db.get(Usuario, usuario_id)
    if usuario is None or not _en_jurisdiccion(actor, usuario):
        raise usuario_no_encontrado()
    return usuario


def _en_jurisdiccion(actor: Usuario, objetivo: Usuario) -> bool:
    if actor.rol == RolUsuario.SUPERADMIN:
        return True
    return objetivo.sede is not None and objetivo.sede == actor.sede


# ── UC-06 · Alta directa por SUPERADMIN ──────────────────────────────────────


async def crear_por_admin(db: AsyncSession, actor: Usuario, datos: UsuarioAdminCreate) -> Usuario:
    """Crea la cuenta directamente en ``ACTIVO`` con alcance obligatorio (GLO-01)."""
    if await _buscar_por(db, email=datos.email) is not None:
        raise _email_duplicado()
    if await _buscar_por(db, dni=datos.dni) is not None:
        raise _dni_duplicado()

    ahora = datetime.now(UTC)
    usuario = Usuario(
        email=datos.email,
        password_hash=hash_password(datos.password),
        nombre=datos.nombre,
        apellido=datos.apellido,
        dni=datos.dni,
        telefono=datos.telefono,
        rol=datos.rol,
        sede=datos.sede,
        estado=E.ACTIVO,
        aprobado_por_id=actor.id,
        aprobado_en=ahora,
    )
    db.add(usuario)
    await _persistir(db, commit=False)
    _registrar_historial(db, usuario, None, E.ACTIVO, motivo="Alta directa", actor_id=actor.id)
    await _persistir(db, commit=True)
    await db.refresh(usuario)
    return usuario


# ── UC-02 / UC-07 · Cambio de estado ─────────────────────────────────────────


async def cambiar_estado(
    db: AsyncSession, actor: Usuario, usuario_id: int, req: CambioEstadoRequest
) -> Usuario:
    """Aprobar, rechazar, suspender, dar de baja o reactivar (USR-04, USR-05; RN-11…RN-16)."""
    if actor.id == usuario_id:
        raise AppError(
            403, "OPERACION_SOBRE_SI_MISMO", "No podés modificar el estado de tu propia cuenta."
        )

    objetivo = await db.scalar(
        select(Usuario)
        .where(Usuario.id == usuario_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if objetivo is None or not _en_jurisdiccion(actor, objetivo):
        await db.rollback()
        raise usuario_no_encontrado()
    if actor.rol == RolUsuario.ADMIN_LOCAL and objetivo.rol not in ROLES_GESTIONABLES_POR_ADMIN_LOCAL:
        await db.rollback()
        raise permiso_insuficiente()

    anterior = objetivo.estado
    nuevo = EstadoCuenta(req.nuevo_estado)
    revoca = TRANSICIONES.get((anterior, nuevo))
    if revoca is None:
        await db.rollback()
        raise AppError(
            409,
            "TRANSICION_INVALIDA",
            "La cuenta no admite el cambio de estado solicitado.",
            estado_actual=anterior.value,
        )

    if objetivo.rol == RolUsuario.SUPERADMIN and anterior == E.ACTIVO and nuevo != E.ACTIVO:
        otros_activos = await db.scalars(
            select(Usuario.id)
            .where(
                Usuario.rol == RolUsuario.SUPERADMIN,
                Usuario.estado == E.ACTIVO,
                Usuario.id != objetivo.id,
            )
            .with_for_update()
        )
        if not otros_activos.first():
            await db.rollback()
            raise AppError(
                409, "ULTIMO_SUPERADMIN", "Debe existir al menos un Superadministrador activo."
            )

    objetivo.estado = nuevo
    objetivo.motivo_estado = req.motivo
    objetivo.suspendido_hasta = req.suspendido_hasta if nuevo == E.SUSPENDIDO else None
    if anterior == E.PENDIENTE_APROBACION and nuevo == E.ACTIVO:
        objetivo.aprobado_por_id = actor.id
        objetivo.aprobado_en = datetime.now(UTC)
    if revoca:
        objetivo.token_version += 1  # RN-08: revoca todas las sesiones abiertas

    _registrar_historial(db, objetivo, anterior, nuevo, motivo=req.motivo, actor_id=actor.id)
    await db.commit()
    await db.refresh(objetivo)
    return objetivo
