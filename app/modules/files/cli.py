"""CLI de mantenimiento de `files` (SPEC-03 RN-63).

Uso::

    python -m app.modules.files.cli limpiar-huerfanos [--horas 24]

Borra los archivos sin vincular creados hace más de ``--horas`` (por defecto
``ARCHIVO_HUERFANO_HORAS``). Es idempotente; la periodicidad la define el despliegue.
"""

import argparse
import asyncio
import sys

from app.database import AsyncSessionLocal
from app.modules.files.service import limpiar_huerfanos


async def _main(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as db:
        borrados = await limpiar_huerfanos(db, horas=args.horas)
    print(f"Archivos huérfanos borrados: {borrados}")
    return 0


def _horas(valor: str) -> int:
    horas = int(valor)
    if horas < 1:
        raise argparse.ArgumentTypeError("--horas debe ser un entero positivo.")
    return horas


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.modules.files.cli")
    sub = parser.add_subparsers(dest="comando", required=True)
    limpiar = sub.add_parser(
        "limpiar-huerfanos", help="Borra los archivos sin vincular más viejos que --horas."
    )
    limpiar.add_argument("--horas", type=_horas, default=None)
    return parser


def main() -> None:
    args = construir_parser().parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
