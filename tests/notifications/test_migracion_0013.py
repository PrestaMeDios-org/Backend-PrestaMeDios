"""SPEC-06 §7 · Migración `0013_notifications_init` — NTF-04.

Que el script declare las mismas tablas, índices y `CHECK` que los modelos (NTF-23) lo
verifica `tests/test_migraciones.py` contra PostgreSQL. Acá queda el comportamiento
del `CHECK` de alcance en la base.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.enums import SedeEnum
from app.modules.notifications.models import Comunicado

pytestmark = pytest.mark.integracion


@pytest.mark.parametrize(
    ("sede", "es_global"),
    [(SedeEnum.USHUAIA, True), (None, False)],
    ids=["global-con-sede", "sin-sede-ni-global"],
)
async def test_check_alcance_coherente_en_la_base(db, sede, es_global):  # NTF-04
    db.add(Comunicado(titulo="Aviso", contenido="Texto", sede=sede, es_global=es_global))
    with pytest.raises(IntegrityError, match="ck_comunicados_alcance_coherente"):
        await db.commit()
    await db.rollback()
