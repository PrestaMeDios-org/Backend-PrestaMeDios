"""Reglas del Panel de Parámetros Globales (GLO-03; SPEC-01 RN-18…RN-21).

``obtener_parametro`` es la API pública para el resto de los módulos
(`spaces`, `loans`, `notifications`): plazos, tolerancias, horario y
anticipación mínima se leen de aquí en lugar de codificarse (Constitución P8).
El horario y el correo de contacto de cada sede se leen con ``datos_de_sede`` y
``datos_de_sedes`` (SPEC-09 §4.4).
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import SedeEnum, TipoParametro
from app.core.errors import AppError
from app.modules.config.models import ParametroGlobal, ParametroGlobalHistorial
from app.modules.config.schemas import ParametroUpdate
from app.modules.users.models import Usuario

ValorTipado = int | float | bool | str | time

_HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_TEXTO_MAX = 300

# ── Claves por sede (SPEC-09 RN-78) ──────────────────────────────────────────

# Los valores de `SedeEnum` llevan mayúsculas, espacios y tilde, y el CHECK
# `clave_formato` sólo admite [a-z0-9_]: cada sede tiene un segmento fijo.
SEGMENTO_SEDE: dict[SedeEnum, str] = {
    SedeEnum.USHUAIA: "ushuaia",
    SedeEnum.RIO_GRANDE: "rio_grande",
}

_CORREO_CONTACTO_RE = re.compile(r"^contacto\.[a-z][a-z0-9_]*\.email$")
_CORREO_MAX = 254


def clave_horario_apertura(sede: SedeEnum) -> str:
    return f"horario.{SEGMENTO_SEDE[sede]}.apertura"


def clave_horario_cierre(sede: SedeEnum) -> str:
    return f"horario.{SEGMENTO_SEDE[sede]}.cierre"


def clave_contacto(sede: SedeEnum) -> str:
    return f"contacto.{SEGMENTO_SEDE[sede]}.email"


def claves_de_sede(sede: SedeEnum) -> tuple[str, str, str]:
    """Las tres claves de una sede: apertura, cierre y correo de contacto (RN-78)."""
    return clave_horario_apertura(sede), clave_horario_cierre(sede), clave_contacto(sede)


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
    # SPEC-09 RN-79: apertura antes del cierre, en cada sede.
    *(
        (
            clave_horario_apertura(sede),
            clave_horario_cierre(sede),
            lambda a, b: a < b,
            "La hora de apertura debe ser anterior a la de cierre.",
        )
        for sede in SEGMENTO_SEDE
    ),
]


def _claves_vinculadas(clave: str) -> list[str]:
    """La clave y las de todas las reglas cruzadas donde aparece, en orden (RN-79)."""
    claves = {clave}
    for clave_a, clave_b, _, _ in _REGLAS_CRUZADAS:
        if clave in (clave_a, clave_b):
            claves |= {clave_a, clave_b}
    return sorted(claves)


def normalizar_correo_contacto(clave: str, valor: Any) -> Any:
    """RN-80: las claves ``contacto.*.email`` guardan un correo válido, en minúsculas.

    Se llama después de ``validar_valor``, así que ``valor`` ya es un texto de 1 a
    300 caracteres (el ``""`` inicial sólo lo escribe la migración, D-05).
    """
    if not _CORREO_CONTACTO_RE.fullmatch(clave):
        return valor
    correo = valor.strip().lower()
    try:
        if len(correo) > _CORREO_MAX:
            raise EmailNotValidError
        validate_email(correo, check_deliverability=False)
    except EmailNotValidError:
        raise _valor_invalido("se esperaba una dirección de correo válida.") from None
    return correo


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
    """Modifica un parámetro con bloqueo de fila + optimista e historial (UC-09).

    Bloquea en una sola consulta, ordenada por clave, la fila editada y las de sus
    reglas cruzadas (SPEC-09 RN-79, G-5): dos ediciones del mismo par se esperan, la
    segunda se valida contra lo que confirmó la primera y no hay *deadlock*.
    """
    filas = await db.scalars(
        select(ParametroGlobal)
        .where(ParametroGlobal.clave.in_(_claves_vinculadas(clave)))
        .order_by(ParametroGlobal.clave)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    parametro = next((p for p in filas.all() if p.clave == clave), None)
    valor = req.valor
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
        validar_valor(parametro.tipo, valor, parametro.valor_min, parametro.valor_max)
        valor = normalizar_correo_contacto(clave, valor)
        await validar_reglas_cruzadas(db, clave, parametro.tipo, valor)
    except AppError:
        await db.rollback()
        raise

    if parametro.valor == valor and type(parametro.valor) is type(valor):
        await db.commit()  # FA-05: idempotente, sin nueva versión ni historial
        return parametro

    anterior = parametro.valor
    parametro.valor = valor
    parametro.version += 1
    parametro.actualizado_por_id = actor.id
    parametro.actualizado_en = datetime.now(UTC)
    db.add(
        ParametroGlobalHistorial(
            clave=clave,
            valor_anterior=anterior,
            valor_nuevo=valor,
            version=parametro.version,
            motivo=req.motivo,
            actor_id=actor.id,
        )
    )
    await db.commit()
    await db.refresh(parametro)
    return parametro


# ── API pública para otros módulos (SPEC-09 §4.4) ────────────────────────────


@dataclass(frozen=True, slots=True)
class DatosSede:
    """Horario y correo de contacto de una sede (GLO-02, GLO-03)."""

    sede: SedeEnum
    horario_apertura: time
    horario_cierre: time
    correo_contacto: str | None  # None mientras la clave valga "" (RN-80, EC-55)


async def _leer_sedes(db: AsyncSession, sedes: list[SedeEnum]) -> dict[SedeEnum, DatosSede]:
    claves = [c for sede in sedes for c in claves_de_sede(sede)]
    filas = await db.execute(
        select(ParametroGlobal.clave, ParametroGlobal.tipo, ParametroGlobal.valor).where(
            ParametroGlobal.clave.in_(claves)
        )
    )
    valores = {clave: convertir(tipo, valor) for clave, tipo, valor in filas.all()}
    faltan = [c for c in claves if c not in valores]
    if faltan:
        raise AppError(
            500, "PARAMETRO_NO_CONFIGURADO", f"Falta el parámetro global '{faltan[0]}'."
        )
    return {
        sede: DatosSede(
            sede=sede,
            horario_apertura=valores[clave_horario_apertura(sede)],
            horario_cierre=valores[clave_horario_cierre(sede)],
            correo_contacto=valores[clave_contacto(sede)] or None,
        )
        for sede in sedes
    }


async def datos_de_sede(db: AsyncSession, sede: SedeEnum) -> DatosSede:
    """Horario y correo de contacto de ``sede``, para `spaces` y `loans` (H1, H2; RN-82).

    Una sola consulta, sin ``commit`` ni ``flush``. Una clave faltante indica una
    migración pendiente: ``500 PARAMETRO_NO_CONFIGURADO``, como ``obtener_parametro``.
    """
    return (await _leer_sedes(db, [sede]))[sede]


async def datos_de_sedes(db: AsyncSession) -> dict[SedeEnum, DatosSede]:
    """Lo mismo que ``datos_de_sede`` para todas las sedes, en el orden de ``SedeEnum``."""
    return await _leer_sedes(db, list(SedeEnum))
