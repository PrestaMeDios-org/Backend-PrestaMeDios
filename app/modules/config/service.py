"""Reglas del Panel de Parámetros Globales (GLO-03; SPEC-01 RN-18…RN-21).

``obtener_parametro`` es la API pública para el resto de los módulos
(`spaces`, `loans`, `notifications`): plazos, tolerancias, horario y
anticipación mínima se leen de aquí en lugar de codificarse (Constitución P8).
"""

import re
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import TipoParametro
from app.core.errors import AppError
from app.modules.config.models import ParametroGlobal, ParametroGlobalHistorial
from app.modules.config.schemas import ParametroUpdate
from app.modules.users.models import Usuario

ValorTipado = int | float | bool | str | time

_HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_TEXTO_MAX = 300


def _no_encontrado() -> AppError:
    return AppError(404, "PARAMETRO_NO_ENCONTRADO", "Parámetro no encontrado.")


def _valor_invalido(motivo: str) -> AppError:
    return AppError(
        422,
        "VALOR_PARAMETRO_INVALIDO",
        f"El valor no respeta el tipo o rango permitido: {motivo}",
    )


# ── Lectura ──────────────────────────────────────────────────────────────────


async def listar(db: AsyncSession) -> list[ParametroGlobal]:
    result = await db.scalars(select(ParametroGlobal).order_by(ParametroGlobal.clave))
    return list(result.all())


async def obtener(db: AsyncSession, clave: str) -> ParametroGlobal:
    parametro = await db.get(ParametroGlobal, clave)
    if parametro is None:
        raise _no_encontrado()
    return parametro


async def historial(db: AsyncSession, clave: str, limit: int) -> list[ParametroGlobalHistorial]:
    await obtener(db, clave)
    result = await db.scalars(
        select(ParametroGlobalHistorial)
        .where(ParametroGlobalHistorial.clave == clave)
        .order_by(ParametroGlobalHistorial.created_at.desc(), ParametroGlobalHistorial.id.desc())
        .limit(limit)
    )
    return list(result.all())


def convertir(tipo: TipoParametro, valor: Any) -> ValorTipado:
    """Valor persistido (JSON) → tipo Python nativo. ``HORA`` → ``datetime.time``."""
    if tipo == TipoParametro.HORA:
        return time.fromisoformat(valor)
    if tipo == TipoParametro.DECIMAL:
        return float(valor)
    return valor


async def obtener_parametro(db: AsyncSession, clave: str) -> ValorTipado:
    """Valor tipado de un parámetro global, para uso de otros módulos (SPEC-01 §12.1).

    Una clave inexistente indica una migración faltante, no un error del
    cliente: responde 500 ``PARAMETRO_NO_CONFIGURADO``.
    """
    parametro = await db.get(ParametroGlobal, clave)
    if parametro is None:
        raise AppError(
            500, "PARAMETRO_NO_CONFIGURADO", f"Falta el parámetro global '{clave}'."
        )
    return convertir(parametro.tipo, parametro.valor)


# ── Validación ───────────────────────────────────────────────────────────────


def validar_valor(
    tipo: TipoParametro, valor: Any, valor_min: Any = None, valor_max: Any = None
) -> None:
    """RN-19: validación estricta de tipo (``bool`` no es ``int``) y de rango."""
    match tipo:
        case TipoParametro.ENTERO:
            if type(valor) is not int:
                raise _valor_invalido("se esperaba un número entero.")
        case TipoParametro.DECIMAL:
            if type(valor) not in (int, float):
                raise _valor_invalido("se esperaba un número.")
        case TipoParametro.BOOLEANO:
            if type(valor) is not bool:
                raise _valor_invalido("se esperaba true o false.")
        case TipoParametro.TEXTO:
            if not isinstance(valor, str) or not 1 <= len(valor) <= _TEXTO_MAX:
                raise _valor_invalido(f"se esperaba un texto de 1 a {_TEXTO_MAX} caracteres.")
        case TipoParametro.HORA:
            if not isinstance(valor, str) or not _HORA_RE.fullmatch(valor):
                raise _valor_invalido("se esperaba una hora con formato HH:MM (00:00–23:59).")

    if tipo in (TipoParametro.ENTERO, TipoParametro.DECIMAL):
        if valor_min is not None and valor < valor_min:
            raise _valor_invalido(f"el mínimo es {valor_min}.")
        if valor_max is not None and valor > valor_max:
            raise _valor_invalido(f"el máximo es {valor_max}.")


# (clave_a, clave_b, predicado(a, b), mensaje) — RN-20
_REGLAS_CRUZADAS: list[tuple[str, str, Any, str]] = [
    (
        "horario.apertura",
        "horario.cierre",
        lambda a, b: a < b,
        "La hora de apertura debe ser anterior a la de cierre.",
    ),
    (
        "prestamo.general.max_dias",
        "prestamo.notebook.max_dias",
        lambda a, b: a <= b,
        "El plazo del préstamo general no puede superar al de notebooks.",
    ),
    (
        "solicitud.anticipacion_min_horas",
        "reserva_espacio.anticipacion_max_dias",
        lambda a, b: a < 24 * b,
        "La anticipación mínima debe ser menor que la ventana máxima de anticipación.",
    ),
]


async def validar_reglas_cruzadas(
    db: AsyncSession, clave: str, tipo: TipoParametro, valor: Any
) -> None:
    """Evalúa RN-20 sustituyendo el valor candidato en la configuración vigente."""
    relevantes = [r for r in _REGLAS_CRUZADAS if clave in (r[0], r[1])]
    if not relevantes:
        return
    claves = {c for r in relevantes for c in (r[0], r[1])}
    filas = await db.scalars(select(ParametroGlobal).where(ParametroGlobal.clave.in_(claves)))
    vigentes = {p.clave: convertir(p.tipo, p.valor) for p in filas.all()}
    vigentes[clave] = convertir(tipo, valor)

    for clave_a, clave_b, predicado, mensaje in relevantes:
        if clave_a in vigentes and clave_b in vigentes:
            if not predicado(vigentes[clave_a], vigentes[clave_b]):
                raise AppError(422, "PARAMETROS_INCONSISTENTES", mensaje)


# ── Escritura ────────────────────────────────────────────────────────────────


async def actualizar(
    db: AsyncSession, actor: Usuario, clave: str, req: ParametroUpdate
) -> ParametroGlobal:
    """Modifica un parámetro con bloqueo de fila + optimista e historial (UC-09)."""
    parametro = await db.scalar(
        select(ParametroGlobal)
        .where(ParametroGlobal.clave == clave)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    try:
        if parametro is None:
            raise _no_encontrado()
        if not parametro.editable:
            raise AppError(
                409, "PARAMETRO_NO_EDITABLE", "Este parámetro no puede modificarse desde el panel."
            )
        if req.version != parametro.version:
            raise AppError(
                409,
                "CONFLICTO_VERSION",
                "El parámetro fue modificado por otra persona. Recargá el panel.",
                version_actual=parametro.version,
            )
        validar_valor(parametro.tipo, req.valor, parametro.valor_min, parametro.valor_max)
        await validar_reglas_cruzadas(db, clave, parametro.tipo, req.valor)
    except AppError:
        await db.rollback()
        raise

    if parametro.valor == req.valor and type(parametro.valor) is type(req.valor):
        await db.commit()  # FA-05: idempotente, sin nueva versión ni historial
        return parametro

    anterior = parametro.valor
    parametro.valor = req.valor
    parametro.version += 1
    parametro.actualizado_por_id = actor.id
    parametro.actualizado_en = datetime.now(UTC)
    db.add(
        ParametroGlobalHistorial(
            clave=clave,
            valor_anterior=anterior,
            valor_nuevo=req.valor,
            version=parametro.version,
            motivo=req.motivo,
            actor_id=actor.id,
        )
    )
    await db.commit()
    await db.refresh(parametro)
    return parametro
