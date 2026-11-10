"""Reglas de negocio del módulo `users` (SPEC-01 §3.2, §5, §7).

Los servicios no conocen HTTP salvo ``AppError``; los routers sólo validan
contrato y permisos y delegan aquí.
"""

import hashlib
import hmac
import logging
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import UploadFile
from fastapi.exceptions import RequestValidationError
from sqlalchemy import Integer, Select, any_, bindparam, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import permiso_insuficiente, resolver_alcance_sede
from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum
from app.core.email import ErrorEnvioCorreo, TipoCorreo, enviar_correo
from app.core.errors import AppError
from app.core.security import (
    crear_access_token,
    hash_password,
    verify_dummy,
    verify_password,
)
from app.modules.files import service as files
from app.modules.files.enums import PropositoArchivo
from app.core.settings import get_settings
from app.modules.users.models import (
    IntentoRecuperacion,
    TokenRecuperacion,
    Usuario,
    UsuarioHistorialCambios,
    UsuarioHistorialEstado,
)
from app.modules.users.schemas import (
    validar_politica_password,
    CambioEstadoRequest,
    CambioPasswordRequest,
    PerfilUpdate,
    RegistroRequest,
    UsuarioAdminCreate,
    UsuarioAdminUpdate,
)

E = EstadoCuenta

logger = logging.getLogger(__name__)

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
        debe_cambiar_password=True,  # SPEC-02 A9: la contraseña la definió otra persona
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


# ── SPEC-02 · Gestión de cuenta ──────────────────────────────────────────────

_OCULTO = "***"


def _password_actual_incorrecta() -> AppError:
    return AppError(403, "PASSWORD_ACTUAL_INCORRECTA", "La contraseña actual no es correcta.")


def _registrar_cambios(
    db: AsyncSession, usuario: Usuario, cambios: dict, *, actor_id: int | None
) -> None:
    """RN-34: traza de la edición en la misma transacción (sin contraseñas)."""
    if cambios:
        db.add(UsuarioHistorialCambios(usuario_id=usuario.id, actor_id=actor_id, cambios=cambios))


def _aplicar(usuario: Usuario, campo: str, valor: object, cambios: dict) -> None:
    anterior = getattr(usuario, campo)
    if anterior != valor:
        cambios[campo] = [_serializable(anterior), _serializable(valor)]
        setattr(usuario, campo, valor)


def _serializable(valor: object) -> object:
    return valor.value if hasattr(valor, "value") else valor


async def _email_disponible(db: AsyncSession, email: str, usuario_id: int) -> None:
    otro = await _buscar_por(db, email=email)
    if otro is not None and otro.id != usuario_id:
        raise _email_duplicado()


async def actualizar_perfil(db: AsyncSession, usuario: Usuario, datos: PerfilUpdate) -> Usuario:
    """UC-10 · Datos de contacto propios (USR-03; RN-32)."""
    cambios: dict = {}
    if "email" in datos.model_fields_set and datos.email != usuario.email:
        valida = datos.password_actual is not None and verify_password(
            datos.password_actual, usuario.password_hash
        )[0]
        if not valida:
            raise _password_actual_incorrecta()
        await _email_disponible(db, datos.email, usuario.id)  # type: ignore[arg-type]
        _aplicar(usuario, "email", datos.email, cambios)
    if "telefono" in datos.model_fields_set:
        _aplicar(usuario, "telefono", datos.telefono, cambios)
    if "email" in cambios:  # SPEC-03 RN-53: el enlace se mandó a la dirección anterior
        await _invalidar_tokens_recuperacion(db, usuario.id)

    _registrar_cambios(db, usuario, cambios, actor_id=usuario.id)
    await _persistir(db, commit=True)
    await db.refresh(usuario)
    return usuario


async def cambiar_password(
    db: AsyncSession, usuario: Usuario, datos: CambioPasswordRequest
) -> Sesion:
    """UC-11 · Cambio de contraseña propia; cierra las demás sesiones (RN-32)."""
    if not verify_password(datos.password_actual, usuario.password_hash)[0]:
        raise _password_actual_incorrecta()
    usuario.password_hash = hash_password(datos.password_nueva)
    usuario.debe_cambiar_password = False
    usuario.token_version += 1
    _registrar_cambios(db, usuario, {"password": [_OCULTO, _OCULTO]}, actor_id=usuario.id)
    await db.commit()
    await db.refresh(usuario)
    token, expires_in = crear_access_token(
        usuario_id=usuario.id,
        rol=usuario.rol,
        sede=usuario.sede,
        token_version=usuario.token_version,
    )
    return Sesion(usuario=usuario, access_token=token, expires_in=expires_in)


async def editar_por_admin(
    db: AsyncSession, actor: Usuario, usuario_id: int, datos: UsuarioAdminUpdate
) -> Usuario:
    """UC-12 · Edición administrativa con jurisdicción y auditoría (USR-04)."""
    objetivo = await db.scalar(
        select(Usuario)
        .where(Usuario.id == usuario_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    try:
        if objetivo is None or not _en_jurisdiccion(actor, objetivo):
            raise usuario_no_encontrado()
        campos = datos.model_fields_set
        es_local = actor.rol == RolUsuario.ADMIN_LOCAL
        if es_local and objetivo.rol not in ROLES_GESTIONABLES_POR_ADMIN_LOCAL:
            raise permiso_insuficiente()
        if actor.id == objetivo.id and campos & {"rol", "sede"}:
            raise AppError(
                403, "OPERACION_SOBRE_SI_MISMO", "No podés cambiar tu propio rol o sede."
            )

        nuevo_rol = datos.rol if "rol" in campos else objetivo.rol
        nueva_sede = datos.sede if "sede" in campos else objetivo.sede
        if es_local:
            if nuevo_rol not in ROLES_GESTIONABLES_POR_ADMIN_LOCAL:
                raise permiso_insuficiente()
            if nueva_sede != objetivo.sede:
                raise AppError(
                    403, "SEDE_FUERA_DE_ALCANCE", "No tenés jurisdicción sobre la sede solicitada."
                )
        if (nuevo_rol == RolUsuario.SUPERADMIN) != (nueva_sede is None):
            raise AppError(
                422,
                "ALCANCE_INCOHERENTE",
                "Un SUPERADMIN no tiene sede (ambas sedes); el resto de los roles requiere una.",
            )
        if (
            objetivo.rol == RolUsuario.SUPERADMIN
            and nuevo_rol != RolUsuario.SUPERADMIN
            and objetivo.estado == E.ACTIVO
        ):
            otros = await db.scalars(
                select(Usuario.id)
                .where(
                    Usuario.rol == RolUsuario.SUPERADMIN,
                    Usuario.estado == E.ACTIVO,
                    Usuario.id != objetivo.id,
                )
                .with_for_update()
            )
            if not otros.first():
                raise AppError(
                    409, "ULTIMO_SUPERADMIN", "Debe existir al menos un Superadministrador activo."
                )
        if "email" in campos and datos.email != objetivo.email:
            await _email_disponible(db, datos.email, objetivo.id)  # type: ignore[arg-type]
        if "dni" in campos and datos.dni != objetivo.dni:
            otro = await _buscar_por(db, dni=datos.dni)  # type: ignore[arg-type]
            if otro is not None and otro.id != objetivo.id:
                raise _dni_duplicado()
    except AppError:
        await db.rollback()
        raise

    cambios: dict = {}
    for campo in ("nombre", "apellido", "dni", "telefono", "email"):
        if campo in campos:
            _aplicar(objetivo, campo, getattr(datos, campo), cambios)
    _aplicar(objetivo, "rol", nuevo_rol, cambios)
    _aplicar(objetivo, "sede", nueva_sede, cambios)
    revoca = "rol" in cambios or "sede" in cambios
    if datos.password_nueva is not None:
        objetivo.password_hash = hash_password(datos.password_nueva)
        objetivo.debe_cambiar_password = True
        cambios["password"] = [_OCULTO, _OCULTO]
        revoca = True
    if revoca:
        objetivo.token_version += 1  # RN-08
    if "email" in cambios:  # SPEC-03 RN-53
        await _invalidar_tokens_recuperacion(db, objetivo.id)

    _registrar_cambios(db, objetivo, cambios, actor_id=actor.id)
    await _persistir(db, commit=True)
    await db.refresh(objetivo)
    return objetivo


# ── SPEC-03 · Foto de perfil (USR-03, Fase B2) ───────────────────────────────


def _str_o_none(valor: object) -> str | None:
    return None if valor is None else str(valor)


async def _cambiar_foto(
    db: AsyncSession, objetivo: Usuario, nueva_id, *, actor_id: int
) -> Usuario:
    """RN-59: apunta ``foto_id``, borra la anterior y deja traza, todo en una transacción.

    ``objetivo`` ya está bloqueado (``FOR UPDATE``, EC-41).
    """
    anterior = objetivo.foto_id
    if anterior == nueva_id:  # quitar sin foto: nada que cambiar
        await db.commit()  # libera el lock sin expirar los atributos
        return objetivo
    objetivo.foto_id = nueva_id
    await db.flush()
    if anterior is not None:
        await files.borrar_archivo(db, anterior)
    _registrar_cambios(
        db,
        objetivo,
        {"foto_id": [_str_o_none(anterior), _str_o_none(nueva_id)]},
        actor_id=actor_id,
    )
    await db.commit()
    await db.refresh(objetivo)
    return objetivo


async def reemplazar_foto(
    db: AsyncSession, usuario: Usuario, archivo: UploadFile, *, content_length: int | None
) -> Usuario:
    """``PUT /auth/me/foto``: sube, vincula y reemplaza en un solo paso (USR-03, D-11).

    La imagen se procesa antes de bloquear la fila, para no retener el lock.
    """
    jpeg, nombre = await files.preparar_foto(archivo, content_length=content_length)
    objetivo = await _bloquear(db, usuario.id)
    nueva = await files.guardar_archivo(
        db,
        propietario=objetivo,
        proposito=PropositoArchivo.FOTO_PERFIL,
        datos=jpeg,
        tipo_mime=files.JPEG,
        nombre=nombre,
        vinculado=True,
    )
    return await _cambiar_foto(db, objetivo, nueva.id, actor_id=usuario.id)


async def quitar_foto(db: AsyncSession, usuario: Usuario) -> Usuario:
    """``DELETE /auth/me/foto``. Sin foto, no cambia nada (RN-59)."""
    objetivo = await _bloquear(db, usuario.id)
    return await _cambiar_foto(db, objetivo, None, actor_id=usuario.id)


async def quitar_foto_por_admin(db: AsyncSession, actor: Usuario, usuario_id: int) -> Usuario:
    """``DELETE /users/{id}/foto`` con las reglas de UC-12 de SPEC-02 (RN-64).

    Fuera de la jurisdicción responde ``404``; el ``ADMIN_LOCAL`` sobre una cuenta que
    no es de estudiante ni de docente, ``403``.
    """
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
    return await _cambiar_foto(db, objetivo, None, actor_id=actor.id)


# ── SPEC-03 · Recuperación de contraseña (USR-02, Fase B1) ───────────────────


@dataclass(frozen=True, slots=True)
class CorreoRecuperacion:
    """Lo necesario para mandar el enlace después del commit (RN-72). Lleva el token: no
    se registra en logs ni se devuelve en respuestas (NFR-19)."""

    usuario_id: int
    destinatario: str
    nombre: str
    enlace: str
    vigencia_minutos: int


def _hash_token(token: str) -> str:
    """RN-46: en la base sólo queda el SHA-256 del token."""
    return hashlib.sha256(token.encode()).hexdigest()


def _hash_email(email: str) -> str:
    """RN-49: HMAC del email normalizado. Con un hash simple, un diccionario de emails
    conocidos lo revertiría."""
    clave = get_settings().jwt_secret_key.encode()
    return hmac.new(clave, email.encode(), hashlib.sha256).hexdigest()


def _demasiados_intentos() -> AppError:
    return AppError(
        429, "DEMASIADOS_INTENTOS", "Hiciste demasiados pedidos. Probá de nuevo más tarde."
    )


async def _invalidar_tokens_recuperacion(db: AsyncSession, usuario_id: int) -> None:
    """RN-48, RN-53: marca como usados los tokens pendientes de la cuenta. Sin ``commit``."""
    await db.execute(
        update(TokenRecuperacion)
        .where(TokenRecuperacion.usuario_id == usuario_id, TokenRecuperacion.usado_en.is_(None))
        .values(usado_en=func.now())
    )


async def solicitar_recuperacion(
    db: AsyncSession, email: str, ip: str
) -> CorreoRecuperacion | None:
    """Pedido de enlace de recuperación (USR-02, RN-44…RN-49).

    Devuelve los datos del correo sólo si la cuenta existe y está ``ACTIVO`` (RN-45); si
    no, ``None``. El router responde lo mismo en ambos casos (RN-44). ``429`` si se pasa
    el límite por email o por IP en la última hora, exista o no la cuenta (RN-49).
    """
    settings = get_settings()
    await db.execute(
        delete(IntentoRecuperacion).where(
            IntentoRecuperacion.created_at < func.now() - timedelta(hours=24)
        )
    )
    email_hash = _hash_email(email)
    hace_una_hora = func.now() - timedelta(hours=1)
    por_email = await db.scalar(
        select(func.count())
        .select_from(IntentoRecuperacion)
        .where(
            IntentoRecuperacion.email_hash == email_hash,
            IntentoRecuperacion.created_at >= hace_una_hora,
        )
    )
    por_ip = await db.scalar(
        select(func.count())
        .select_from(IntentoRecuperacion)
        .where(IntentoRecuperacion.ip == ip, IntentoRecuperacion.created_at >= hace_una_hora)
    )
    if (por_email or 0) >= settings.recuperacion_max_por_email_hora or (
        por_ip or 0
    ) >= settings.recuperacion_max_por_ip_hora:
        await db.commit()  # conserva la limpieza de los intentos viejos
        raise _demasiados_intentos()
    db.add(IntentoRecuperacion(email_hash=email_hash, ip=ip))

    usuario = await _buscar_por(db, email=email)
    pendiente: CorreoRecuperacion | None = None
    if usuario is not None and usuario.estado == E.ACTIVO:
        await _invalidar_tokens_recuperacion(db, usuario.id)  # RN-48
        token = secrets.token_urlsafe(32)  # 256 bits (RN-46)
        vigencia = settings.recuperacion_vigencia_minutos
        db.add(
            TokenRecuperacion(
                usuario_id=usuario.id,
                token_hash=_hash_token(token),
                expira_en=datetime.now(UTC) + timedelta(minutes=vigencia),
            )
        )
        pendiente = CorreoRecuperacion(
            usuario_id=usuario.id,
            destinatario=usuario.email,
            nombre=usuario.nombre,
            enlace=f"{settings.frontend_url.rstrip('/')}/#/restablecer?token={token}",  # RN-47
            vigencia_minutos=vigencia,
        )
    await db.commit()
    return pendiente


async def enviar_correo_recuperacion(pendiente: CorreoRecuperacion) -> None:
    """Manda el enlace (se agenda con ``BackgroundTasks``, RN-72). Un fallo del transporte
    se registra sin el enlace y no cambia la respuesta (RN-73, NFR-19)."""
    try:
        await enviar_correo(
            TipoCorreo.RECUPERACION_PASSWORD,
            pendiente.destinatario,
            {
                "nombre": pendiente.nombre,
                "enlace": pendiente.enlace,
                "vigencia_minutos": str(pendiente.vigencia_minutos),
            },
            usuario_id=pendiente.usuario_id,
        )
    except ErrorEnvioCorreo:
        logger.warning(
            "No se pudo enviar el correo de recuperación: usuario_id=%s", pendiente.usuario_id
        )


MENSAJE_RECUPERACION_CONFIRMADA = "Tu contraseña se actualizó. Iniciá sesión con la nueva."


def _token_recuperacion_invalido() -> AppError:
    return AppError(
        422, "TOKEN_RECUPERACION_INVALIDO", "El enlace no es válido o ya venció. Pedí uno nuevo."
    )


def _token_vigente(token_hash: str):
    return (
        TokenRecuperacion.token_hash == token_hash,
        TokenRecuperacion.usado_en.is_(None),
        TokenRecuperacion.expira_en > func.now(),
    )


async def confirmar_recuperacion(db: AsyncSession, token: str, password_nueva: str) -> None:
    """Restablece la contraseña con el token del enlace (USR-02, RN-50…RN-52).

    - Un token inexistente, vencido, usado o de una cuenta que ya no está ``ACTIVO``
      responde lo mismo: ``422 TOKEN_RECUPERACION_INVALIDO`` (RN-51).
    - La contraseña igual al email se rechaza **antes** de consumir el token (AC-77).
    - El consumo es un ``UPDATE ... RETURNING`` atómico: de dos confirmaciones
      simultáneas sólo una prospera (RN-50).
    - Nuevo hash, ``token_version + 1`` (cierra todas las sesiones), sin cambio
      obligatorio, demás tokens invalidados y traza sin la contraseña (RN-48, RN-52).
      No inicia sesión (D-09).
    """
    token_hash = _hash_token(token)
    email = await db.scalar(
        select(Usuario.email)
        .join(TokenRecuperacion, TokenRecuperacion.usuario_id == Usuario.id)
        .where(*_token_vigente(token_hash))
    )
    if email is None:
        raise _token_recuperacion_invalido()
    try:
        validar_politica_password(password_nueva, email)  # RN-03 con el email de la cuenta
    except ValueError as exc:
        await db.rollback()
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "password_nueva"),
                    "msg": str(exc),
                    "input": None,
                }
            ]
        ) from None

    usuario_id = await db.scalar(
        update(TokenRecuperacion)
        .where(*_token_vigente(token_hash))
        .values(usado_en=func.now())
        .returning(TokenRecuperacion.usuario_id)
    )
    if usuario_id is None:  # otra confirmación lo consumió primero (RN-50)
        await db.rollback()
        raise _token_recuperacion_invalido()
    usuario = await _bloquear(db, usuario_id)
    if usuario.estado != E.ACTIVO:  # RN-51, EC-38
        await db.rollback()
        raise _token_recuperacion_invalido()

    usuario.password_hash = hash_password(password_nueva)
    usuario.token_version += 1  # RN-08: cierra todas las sesiones (EC-37)
    usuario.debe_cambiar_password = False  # EC-39: la eligió el propio usuario
    await _invalidar_tokens_recuperacion(db, usuario_id)  # RN-48
    _registrar_cambios(db, usuario, {"password": [_OCULTO, _OCULTO]}, actor_id=usuario_id)
    await db.commit()


# ── API pública para otros módulos (SPEC-03 §4, P3.3) ────────────────────────
#
# Lo que está debajo de esta línea es contrato: `spaces` y `loans` lo importan.
# El resto de este archivo es interno de `users`.


@dataclass(frozen=True, slots=True)
class DatosPublicosUsuario:
    """Identidad mínima mostrable de un usuario (P6). Nunca incluye DNI, email ni teléfono."""

    id: int
    nombre: str
    apellido: str


async def datos_publicos_por_ids(
    db: AsyncSession, ids: Iterable[int]
) -> dict[int, DatosPublicosUsuario]:
    """Nombre y apellido por lote de ids (C2 de SPEC-05; bandeja de reservas del Perfil 4).

    Función pública (P3.3, enmienda 1.1.1). No filtra por sede ni por estado (RN-38,
    RN-39): la autorización es de quien llama, que sólo pasa ids de registros que ya
    puede mostrar (P5, P6). **Nunca** se usa para mostrar identidades en la
    disponibilidad de espacios o equipamiento, ni para mostrarle a un estudiante datos
    de otro solicitante (RN-43).

    - Los ids repetidos se consultan una sola vez (RN-35); una entrada vacía devuelve
      ``{}`` sin consultar la base (RN-36); los inexistentes se omiten (RN-37).
    - Selecciona sólo ``id``, ``nombre`` y ``apellido``, no la entidad ``Usuario``: no
      carga DNI, email ni teléfono en la sesión del llamador (RN-40).
    - Una sola consulta con los ids en un único parámetro arreglo (RN-41).
    - No hace ``commit``, ``rollback`` ni ``flush``: la transacción es de quien llama (RN-42).
    """
    unicos = list(set(ids))
    if not unicos:
        return {}
    filas = await db.execute(
        select(Usuario.id, Usuario.nombre, Usuario.apellido).where(
            Usuario.id == any_(bindparam("ids", unicos, type_=ARRAY(Integer)))
        )
    )
    return {
        fila.id: DatosPublicosUsuario(id=fila.id, nombre=fila.nombre, apellido=fila.apellido)
        for fila in filas
    }
