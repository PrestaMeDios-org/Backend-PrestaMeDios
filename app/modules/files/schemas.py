"""Contratos API del módulo `files` (SPEC-03 §6.3)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.files.enums import PropositoArchivo


class ArchivoResponse(BaseModel):
    """Archivo recién subido. El contenido se descarga aparte (RN-60)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., examples=["3f2b8c1e-5d4a-4b6f-9a1e-2c7d8e9f0a1b"])
    proposito: PropositoArchivo = Field(..., examples=["AVAL_PRESTAMO"])
    tipo_mime: str = Field(..., examples=["application/pdf"])
    tamano_bytes: int = Field(..., examples=[184320])
    sha256: str = Field(
        ..., examples=["9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"]
    )
    nombre_original: str = Field(..., examples=["Resolucion CICSE 056-2026.pdf"])
    created_at: datetime = Field(..., examples=["2026-11-08T13:45:00Z"])
