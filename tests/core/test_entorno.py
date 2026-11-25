"""SPEC-11 §6.9.1 · Variable ``ENTORNO`` — AC-P10, AC-P11.

Sin base de datos. AC-P10 importa la app en un proceso aparte, porque ``app.main``
arma la aplicación al importarse con la configuración de ese momento.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings import Settings

RAIZ = Path(__file__).parents[2]

PRODUCCION_VALIDA = {
    "ENTORNO": "produccion",
    "JWT_SECRET_KEY": "x" * 48,
    "FRONTEND_URL": "https://prestamedios.example.com",
    "CORS_ORIGINS": "https://prestamedios.example.com",
    "EMAIL_BACKEND": "smtp",
}


def _settings(monkeypatch, **valores: str) -> Settings:
    for clave in ("ENTORNO", "FRONTEND_URL", "CORS_ORIGINS", "EMAIL_BACKEND"):
        monkeypatch.delenv(clave, raising=False)
    for clave, valor in valores.items():
        monkeypatch.setenv(clave, valor)
    return Settings(_env_file=None)  # type: ignore[call-arg]


class TestValidacionDeProduccion:  # AC-P11
    def test_desarrollo_por_defecto_acepta_localhost(self, monkeypatch):
        s = _settings(monkeypatch, JWT_SECRET_KEY="x" * 48)
        assert s.entorno == "desarrollo"
        assert "localhost" in s.frontend_url

    def test_produccion_valida(self, monkeypatch):
        s = _settings(monkeypatch, **PRODUCCION_VALIDA)
        assert s.entorno == "produccion"

    @pytest.mark.parametrize(
        ("clave", "valor"),
        [
            ("FRONTEND_URL", "http://localhost:8443"),
            ("FRONTEND_URL", "http://127.0.0.1:8443"),
            ("CORS_ORIGINS", "https://prestamedios.example.com,http://localhost:8443"),
            ("EMAIL_BACKEND", "memoria"),
        ],
    )
    def test_produccion_rechaza_valores_de_desarrollo(self, monkeypatch, clave, valor):
        with pytest.raises(ValidationError) as exc:
            _settings(monkeypatch, **{**PRODUCCION_VALIDA, clave: valor})
        assert clave in str(exc.value)

    def test_limite_diario_opcional(self, monkeypatch):
        assert _settings(monkeypatch, JWT_SECRET_KEY="x" * 48).email_limite_diario is None
        s = _settings(monkeypatch, JWT_SECRET_KEY="x" * 48, EMAIL_LIMITE_DIARIO="300")
        assert s.email_limite_diario == 300
        with pytest.raises(ValidationError):
            _settings(monkeypatch, JWT_SECRET_KEY="x" * 48, EMAIL_LIMITE_DIARIO="0")


_SONDA = textwrap.dedent(
    """
    import asyncio, json, httpx
    from app.main import app

    async def main():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            codigos = {r: (await c.get(r)).status_code for r in ("/docs", "/redoc", "/openapi.json", "/health")}
        print(json.dumps(codigos))

    asyncio.run(main())
    """
)


def _codigos(entorno: dict[str, str]) -> dict[str, int]:
    env = {k: v for k, v in os.environ.items() if k not in PRODUCCION_VALIDA}
    env.update(entorno)
    salida = subprocess.run(
        [sys.executable, "-c", _SONDA], cwd=RAIZ, env=env, capture_output=True, text=True, check=True
    )
    import json

    return json.loads(salida.stdout.strip().splitlines()[-1])


def test_documentacion_apagada_en_produccion():  # AC-P10
    codigos = _codigos(PRODUCCION_VALIDA)
    assert codigos == {"/docs": 404, "/redoc": 404, "/openapi.json": 404, "/health": 200}


def test_documentacion_disponible_en_desarrollo():  # AC-P10 (contraste)
    codigos = _codigos({"ENTORNO": "desarrollo", "JWT_SECRET_KEY": "x" * 48})
    assert codigos["/docs"] == 200 and codigos["/openapi.json"] == 200
