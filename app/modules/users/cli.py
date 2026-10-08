"""CLI de bootstrap del Superadministrador inicial (SPEC-01 §11.1).

Uso::

    python -m app.modules.users.cli crear-superadmin \\
        --email natalia.ader@untdf.edu.ar --nombre Natalia --apellido Ader --dni 30111222

La contraseña se solicita por prompt oculto o se lee de
``BOOTSTRAP_SUPERADMIN_PASSWORD``. Es idempotente: si ya existe una cuenta
con ese email, no hace nada. Nunca se siembran credenciales por defecto.
"""

import argparse
import asyncio
import getpass
import os
import sys
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import EstadoCuenta, RolUsuario
from app.core.security import hash_password
from app.database import AsyncSessionLocal
from app.modules.users.models import Usuario, UsuarioHistorialEstado
from app.modules.users.schemas import UsuarioAdminCreate


async def crear_superadmin(db: AsyncSession, datos: UsuarioAdminCreate) -> tuple[Usuario, bool]:
    """Crea el SUPERADMIN si no existe. Devuelve ``(usuario, creado)``."""
    existente = await db.scalar(select(Usuario).where(Usuario.email == datos.email))
    if existente is not None:
        return existente, False

    usuario = Usuario(
        email=datos.email,
        password_hash=hash_password(datos.password),
        nombre=datos.nombre,
        apellido=datos.apellido,
        dni=datos.dni,
        telefono=datos.telefono,
        rol=RolUsuario.SUPERADMIN,
        sede=None,
        estado=EstadoCuenta.ACTIVO,
        aprobado_en=datetime.now(UTC),
    )
    db.add(usuario)
    await db.flush()
    db.add(
        UsuarioHistorialEstado(
            usuario_id=usuario.id,
            estado_anterior=None,
            estado_nuevo=EstadoCuenta.ACTIVO,
            motivo="Bootstrap por CLI",
            actor_id=None,
        )
    )
    await db.commit()
    return usuario, True


def _leer_password() -> str:
    desde_env = os.getenv("BOOTSTRAP_SUPERADMIN_PASSWORD")
    if desde_env:
        return desde_env
    password = getpass.getpass("Contraseña: ")
    if password != getpass.getpass("Repetir contraseña: "):
        sys.exit("Las contraseñas no coinciden.")
    return password


async def _main(args: argparse.Namespace) -> int:
    try:
        datos = UsuarioAdminCreate(
            email=args.email,
            password=_leer_password(),
            nombre=args.nombre,
            apellido=args.apellido,
            dni=args.dni,
            telefono=args.telefono,
            rol=RolUsuario.SUPERADMIN,
            sede=None,
        )
    except ValidationError as exc:
        print(f"Datos inválidos:\n{exc}", file=sys.stderr)
        return 2

    async with AsyncSessionLocal() as db:
        usuario, creado = await crear_superadmin(db, datos)
    if creado:
        print(f"Superadministrador creado: id={usuario.id} email={usuario.email}")
    else:
        print(f"Ya existe una cuenta con email {usuario.email} (id={usuario.id}); sin cambios.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.modules.users.cli")
    sub = parser.add_subparsers(dest="comando", required=True)
    crear = sub.add_parser("crear-superadmin", help="Crea el Superadministrador inicial.")
    crear.add_argument("--email", required=True)
    crear.add_argument("--nombre", required=True)
    crear.add_argument("--apellido", required=True)
    crear.add_argument("--dni", required=True)
    crear.add_argument("--telefono", default=None)
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
