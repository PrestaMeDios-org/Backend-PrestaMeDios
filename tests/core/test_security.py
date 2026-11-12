"""Tests unitarios del kernel de seguridad (SPEC-01 §6.2; AC-19, EC-15, RN-03, RN-06)."""

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.core.enums import RolUsuario, SedeEnum
from app.core.errors import AppError
from app.core.security import (
    crear_access_token,
    decodificar_token,
    hash_password,
    verify_password,
)
from app.core.settings import JWT_ISSUER, Settings, get_settings


def _token(**override) -> str:
    claims = {
        "sub": "7",
        "rol": "ESTUDIANTE",
        "sede": "Ushuaia",
        "tv": 0,
        "iss": JWT_ISSUER,
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
        "jti": "x",
    }
    claims.update(override)
    secreto = claims.pop("_secreto", get_settings().jwt_secret_key)
    return jwt.encode(claims, secreto, algorithm="HS256")


def _codigo(exc: pytest.ExceptionInfo[AppError]) -> str:
    return exc.value.code


class TestPassword:
    def test_hash_argon2id_y_verificacion(self):
        h = hash_password("Camara2026!")
        assert h.startswith("$argon2id$")
        assert "Camara2026!" not in h
        assert verify_password("Camara2026!", h)[0] is True
        assert verify_password("otra-clave1", h)[0] is False

    def test_hash_corrupto_no_lanza(self):
        assert verify_password("x", "no-es-un-hash") == (False, None)


class TestJwt:
    def test_round_trip_y_claims(self):
        token, expires_in = crear_access_token(
            usuario_id=42, rol=RolUsuario.ADMIN_LOCAL, sede=SedeEnum.RIO_GRANDE, token_version=3
        )
        assert expires_in == get_settings().jwt_access_token_expire_minutes * 60
        claims = jwt.decode(token, options={"verify_signature": False})
        assert set(claims) == {
            "sub", "rol", "sede", "tv", "iss", "iat", "auth_time", "exp", "jti"
        }
        assert claims["sub"] == "42" and claims["rol"] == "ADMIN_LOCAL"
        assert claims["sede"] == "Río Grande" and claims["tv"] == 3
        assert claims["auth_time"] == claims["iat"]  # sin auth_time explícito: el login
        payload = decodificar_token(token)
        assert (payload.sub, payload.tv, payload.auth_time) == (42, 3, claims["iat"])

    def test_auth_time_explicito_se_conserva(self):  # RN-65
        inicio = int((datetime.now(UTC) - timedelta(hours=2)).timestamp())
        token, _ = crear_access_token(
            usuario_id=5,
            rol=RolUsuario.ESTUDIANTE,
            sede=SedeEnum.USHUAIA,
            token_version=0,
            auth_time=inicio,
        )
        claims = jwt.decode(token, options={"verify_signature": False})
        assert claims["auth_time"] == inicio and claims["iat"] > inicio
        assert decodificar_token(token).auth_time == inicio

    def test_sin_auth_time_usa_iat(self):  # RN-68
        iat = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
        assert decodificar_token(_token(iat=iat)).auth_time == iat

    @pytest.mark.parametrize("valor", ["123", None, True, [1]])
    def test_auth_time_no_numerico(self, valor):
        with pytest.raises(AppError) as exc:
            decodificar_token(_token(auth_time=valor))
        assert _codigo(exc) == "TOKEN_INVALIDO"

    def test_superadmin_sede_null(self):
        token, _ = crear_access_token(
            usuario_id=1, rol=RolUsuario.SUPERADMIN, sede=None, token_version=0
        )
        assert jwt.decode(token, options={"verify_signature": False})["sede"] is None

    def test_firma_alterada(self):  # AC-19
        with pytest.raises(AppError) as exc:
            decodificar_token(_token(_secreto="otro-secreto-de-al-menos-32-caracteres!!"))
        assert _codigo(exc) == "TOKEN_INVALIDO"

    def test_alg_none_rechazado(self):  # AC-19, EC-15
        def b64(d: dict) -> str:
            return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

        sin_firma = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': '1', 'tv': 0, 'iss': JWT_ISSUER})}."
        with pytest.raises(AppError) as exc:
            decodificar_token(sin_firma)
        assert _codigo(exc) == "TOKEN_INVALIDO"

    def test_issuer_distinto(self):  # AC-19
        with pytest.raises(AppError) as exc:
            decodificar_token(_token(iss="otro-emisor"))
        assert _codigo(exc) == "TOKEN_INVALIDO"

    def test_expirado(self):  # AC-19
        pasado = int((datetime.now(UTC) - timedelta(minutes=5)).timestamp())
        with pytest.raises(AppError) as exc:
            decodificar_token(_token(exp=pasado))
        assert _codigo(exc) == "TOKEN_EXPIRADO"
        assert exc.value.status_code == 401

    def test_sub_no_numerico(self):
        with pytest.raises(AppError) as exc:
            decodificar_token(_token(sub="abc"))
        assert _codigo(exc) == "TOKEN_INVALIDO"

    def test_basura(self):
        with pytest.raises(AppError) as exc:
            decodificar_token("no.es.un-token")
        assert _codigo(exc) == "TOKEN_INVALIDO"


class TestSettings:
    def test_vida_del_token_y_tope_de_sesion_por_defecto(self, monkeypatch: pytest.MonkeyPatch):
        # SPEC-03 RN-65, RN-66: 30 minutos y 8 horas si el entorno no dice otra cosa.
        monkeypatch.delenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
        monkeypatch.delenv("JWT_SESION_MAX_HORAS", raising=False)
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.jwt_access_token_expire_minutes == 30
        assert settings.jwt_sesion_max_horas == 8

    def test_secreto_obligatorio_y_largo(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "corto")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]
        monkeypatch.delenv("JWT_SECRET_KEY")
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]
