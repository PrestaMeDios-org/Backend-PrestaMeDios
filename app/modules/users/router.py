"""Endpoints REST de autenticación y gestión de usuarios (SPEC-01 §6.3).

- ``auth_router``  → montado en ``/api/v1/auth``  (USR-01, USR-05).
- ``users_router`` → montado en ``/api/v1/users`` (USR-04, USR-05, GLO-01).
"""

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    SesionActual,
    get_current_user_permitiendo_cambio,
    get_sesion_actual,
    get_sesion_operativa,
    require_roles,
)
from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum
from app.core.errors import error_responses
from app.database import get_db
from app.modules.files.router import content_length
from app.modules.users import service
from app.modules.users.models import Usuario
from app.modules.users.schemas import (
    CambioEstadoRequest,
    CambioPasswordRequest,
    ConfirmacionRecuperacion,
    MENSAJE_RECUPERACION_NEUTRO,
    MensajeResponse,
    SolicitudRecuperacion,
    PerfilUpdate,
    UsuarioAdminUpdate,
    LoginRequest,
    PaginaUsuarios,
    RegistroRequest,
    TokenResponse,
    UsuarioAdminCreate,
    UsuarioDetalle,
    UsuarioPublico,
    UsuarioResumen,
)

auth_router = APIRouter()
users_router = APIRouter()

_sesion_activa = require_roles(*RolUsuario)
_solo_admins = require_roles(RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN)
_solo_superadmin = require_roles(RolUsuario.SUPERADMIN)


# ── /auth ────────────────────────────────────────────────────────────────────


@auth_router.post(
    "/register",
    response_model=UsuarioPublico,
    status_code=status.HTTP_201_CREATED,
    summary="Autorregistro de Estudiante o Docente",
    responses=error_responses(409),
)
async def registrar(payload: RegistroRequest, db: AsyncSession = Depends(get_db)) -> Usuario:
    """Crea la cuenta en estado ``PENDIENTE_APROBACION``; no emite token (USR-01, USR-05).

    Si existe una cuenta ``RECHAZADO`` con ese email/DNI, se reabre la solicitud (D-04).
    """
    return await service.registrar(db, payload)


@auth_router.post(
    "/login",
    response_model=TokenResponse,
    summary="Inicio de sesión (JWT)",
    responses=error_responses(401, 403),
)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """Verifica credenciales y estado de la cuenta y emite un access token (USR-01)."""
    sesion = await service.autenticar(db, payload.email, payload.password)
    return TokenResponse(
        access_token=sesion.access_token,
        expires_in=sesion.expires_in,
        usuario=UsuarioPublico.model_validate(sesion.usuario),
    )


@auth_router.get(
    "/me",
    response_model=UsuarioPublico,
    summary="Perfil de la sesión actual",
    responses=error_responses(401),
)
async def me(usuario: Usuario = Depends(get_current_user_permitiendo_cambio)) -> Usuario:
    """Devuelve el perfil vigente en base de datos del usuario autenticado (UC-04).

    Disponible aun con cambio obligatorio de contraseña pendiente (SPEC-02 RN-33).
    """
    return usuario


@auth_router.patch(
    "/me",
    response_model=UsuarioPublico,
    summary="Editar mis datos de contacto",
    responses=error_responses(401, 403, 409),
)
async def actualizar_perfil(
    payload: PerfilUpdate,
    usuario: Usuario = Depends(_sesion_activa),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    """Teléfono y email; el email exige la contraseña actual (USR-03, SPEC-02 UC-10)."""
    return await service.actualizar_perfil(db, usuario, payload)


@auth_router.post(
    "/me/password",
    response_model=TokenResponse,
    summary="Cambiar mi contraseña",
    responses=error_responses(401, 403),
)
async def cambiar_password(
    payload: CambioPasswordRequest,
    usuario: Usuario = Depends(get_current_user_permitiendo_cambio),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Emite un token nuevo y cierra las demás sesiones (USR-03, SPEC-02 UC-11)."""
    sesion = await service.cambiar_password(db, usuario, payload)
    return TokenResponse(
        access_token=sesion.access_token,
        expires_in=sesion.expires_in,
        usuario=UsuarioPublico.model_validate(sesion.usuario),
    )


def _token_response(sesion: service.Sesion) -> TokenResponse:
    return TokenResponse(
        access_token=sesion.access_token,
        expires_in=sesion.expires_in,
        usuario=UsuarioPublico.model_validate(sesion.usuario),
    )


@auth_router.post(
    "/renovar",
    response_model=TokenResponse,
    summary="Renovar el access token de la sesión actual",
    responses=error_responses(401),
)
async def renovar(sesion: SesionActual = Depends(get_sesion_actual)) -> TokenResponse:
    """Cambia un token vigente por otro nuevo con el mismo inicio de sesión (D-06 de SPEC-01).

    Disponible aun con cambio obligatorio de contraseña pendiente. Pasadas
    ``JWT_SESION_MAX_HORAS`` desde el login responde ``401 TOKEN_SESION_MAXIMA`` y hay que
    volver a iniciar sesión (SPEC-03 RN-65…RN-68).
    """
    return _token_response(service.renovar_sesion(sesion))


@auth_router.post(
    "/me/sesiones/cerrar",
    response_model=TokenResponse,
    summary="Cerrar todas mis sesiones",
    responses=error_responses(401, 403),
)
async def cerrar_sesiones(
    sesion: SesionActual = Depends(get_sesion_operativa),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Invalida todos los tokens emitidos y devuelve uno nuevo para esta pestaña (SPEC-03 RN-69).

    Sirve para cerrar una sesión olvidada en una computadora compartida (D-14).
    """
    return _token_response(await service.cerrar_sesiones(db, sesion))


@auth_router.put(
    "/me/foto",
    response_model=UsuarioPublico,
    summary="Subir o reemplazar mi foto de perfil",
    responses=error_responses(401, 403, 422),
)
async def subir_foto(
    archivo: UploadFile = File(..., description="JPEG, PNG o WebP de hasta 2 MB."),
    largo: int | None = Depends(content_length),
    usuario: Usuario = Depends(_sesion_activa),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    """Se guarda como JPEG de hasta 512 px sin metadatos y reemplaza a la anterior (USR-03).

    El tipo se decide por los bytes (RN-55); la foto anterior se borra (RN-59).
    """
    return await service.reemplazar_foto(db, usuario, archivo, content_length=largo)


@auth_router.delete(
    "/me/foto",
    response_model=UsuarioPublico,
    summary="Quitar mi foto de perfil",
    responses=error_responses(401, 403),
)
async def quitar_foto(
    usuario: Usuario = Depends(_sesion_activa),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    """Deja ``foto_id = null`` y borra el archivo (USR-03, RN-59)."""
    return await service.quitar_foto(db, usuario)


@auth_router.post(
    "/recuperacion",
    response_model=MensajeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pedir un enlace para restablecer la contraseña",
    responses=error_responses(422, 429),
)
async def solicitar_recuperacion(
    payload: SolicitudRecuperacion,
    request: Request,
    tareas: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> MensajeResponse:
    """Público (excepción a P4.1). Responde lo mismo exista o no la cuenta (USR-02, RN-44).

    El correo se manda después de responder, para que el tiempo no delate la cuenta
    (RN-72, NFR-20). Límite por email y por IP en la última hora (RN-49).
    """
    ip = request.client.host if request.client else "desconocida"  # RN-54
    pendiente = await service.solicitar_recuperacion(db, payload.email, ip)
    if pendiente is not None:
        tareas.add_task(service.enviar_correo_recuperacion, pendiente)
    return MensajeResponse(detail=MENSAJE_RECUPERACION_NEUTRO)



@auth_router.post(
    "/recuperacion/confirmar",
    response_model=MensajeResponse,
    summary="Restablecer la contraseña con el enlace recibido",
    responses=error_responses(422),
)
async def confirmar_recuperacion(
    payload: ConfirmacionRecuperacion, db: AsyncSession = Depends(get_db)
) -> MensajeResponse:
    """Público (excepción a P4.1). Cierra todas las sesiones y no inicia una nueva (RN-52).

    Token inexistente, vencido, usado o de una cuenta no activa: ``422
    TOKEN_RECUPERACION_INVALIDO`` (RN-51). El token viaja en el cuerpo, nunca en la URL
    (RN-47).
    """
    await service.confirmar_recuperacion(db, payload.token, payload.password_nueva)
    return MensajeResponse(detail=service.MENSAJE_RECUPERACION_CONFIRMADA)


# ── /users ───────────────────────────────────────────────────────────────────


@users_router.get(
    "",
    response_model=PaginaUsuarios,
    summary="Directorio de usuarios con aislamiento de sede",
    responses=error_responses(401, 403),
)
async def listar_usuarios(
    sede: SedeEnum | None = Query(default=None),
    rol: RolUsuario | None = Query(default=None),
    estado: EstadoCuenta | None = Query(
        default=None, description="`PENDIENTE_APROBACION` = bandeja de validación."
    ),
    q: str | None = Query(default=None, min_length=2, max_length=100),
    ordenar_por: service.OrdenDirectorio = Query(default="apellido"),
    direccion: service.Direccion = Query(default="asc"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> PaginaUsuarios:
    """``ADMIN_LOCAL`` ve sólo su sede; ``SUPERADMIN`` ambas o la filtrada (USR-04, GLO-01)."""
    items, total = await service.listar_directorio(
        db,
        actor,
        sede=sede,
        rol=rol,
        estado=estado,
        q=q,
        ordenar_por=ordenar_por,
        direccion=direccion,
        limit=limit,
        offset=offset,
    )
    return PaginaUsuarios(
        items=[UsuarioResumen.model_validate(u) for u in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@users_router.get(
    "/{usuario_id}",
    response_model=UsuarioDetalle,
    summary="Detalle administrativo de una cuenta",
    responses=error_responses(401, 403, 404),
)
async def obtener_usuario(
    usuario_id: int,
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    """Fuera de la jurisdicción del ``ADMIN_LOCAL`` responde 404 (RN-11)."""
    return await service.obtener_en_alcance(db, actor, usuario_id)


@users_router.post(
    "",
    response_model=UsuarioDetalle,
    status_code=status.HTTP_201_CREATED,
    summary="Alta directa de cuenta (sólo Superadministrador)",
    responses=error_responses(401, 403, 409),
)
async def crear_usuario(
    payload: UsuarioAdminCreate,
    actor: Usuario = Depends(_solo_superadmin),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    """Crea la cuenta en ``ACTIVO`` con alcance obligatorio: sede o "Ambas sedes" (GLO-01)."""
    return await service.crear_por_admin(db, actor, payload)


@users_router.patch(
    "/{usuario_id}/estado",
    response_model=UsuarioDetalle,
    summary="Aprobar, rechazar, suspender, dar de baja o reactivar una cuenta",
    responses=error_responses(401, 403, 404, 409),
)
async def cambiar_estado(
    usuario_id: int,
    payload: CambioEstadoRequest,
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    """Transiciones de SPEC-01 §3.2 con jurisdicción por sede (USR-04, USR-05, GLO-01)."""
    return await service.cambiar_estado(db, actor, usuario_id, payload)


@users_router.patch(
    "/{usuario_id}",
    response_model=UsuarioDetalle,
    summary="Editar el perfil de una cuenta (datos, rol, sede, reseteo de contraseña)",
    responses=error_responses(401, 403, 404, 409),
)
async def editar_usuario(
    usuario_id: int,
    payload: UsuarioAdminUpdate,
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    """Edición administrativa con jurisdicción por sede y auditoría (USR-04, SPEC-02 UC-12)."""
    return await service.editar_por_admin(db, actor, usuario_id, payload)


@users_router.delete(
    "/{usuario_id}/foto",
    response_model=UsuarioDetalle,
    summary="Quitar la foto de perfil de una cuenta",
    responses=error_responses(401, 403, 404),
)
async def quitar_foto_de_usuario(
    usuario_id: int,
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    """Con jurisdicción por sede; el ``ADMIN_LOCAL`` sólo sobre estudiantes y docentes (RN-64)."""
    return await service.quitar_foto_por_admin(db, actor, usuario_id)
