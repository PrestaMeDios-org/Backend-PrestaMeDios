# PrestaMeDios — Backend

API REST del sistema de préstamos de equipamiento y reservas de espacios del **Laboratorio de Medios Audiovisuales (LMA)** del ICSE — Universidad Nacional de Tierra del Fuego (UNTDF), para las sedes **Ushuaia** y **Río Grande**.

| | |
| --- | --- |
| **Requisitos (ERS IEEE 830)** | [`docs/ERS.md`](docs/ERS.md) |
| **Documentación interactiva** | `http://localhost:8000/docs` (Swagger) · `/redoc` |
| **Frontend** | [`Frontend-PrestaMeDios`](https://github.com/PrestaMeDios-org/Frontend-PrestaMeDios) |
| **Stack** | Python 3.11+ · FastAPI · Pydantic v2 · SQLAlchemy 2.0 async · PostgreSQL 15+ · Alembic |

---

## Contenido

1. [Arquitectura](#arquitectura)
2. [Requisitos previos](#requisitos-previos)
3. [Instalación y puesta en marcha](#instalación-y-puesta-en-marcha)
4. [Variables de entorno](#variables-de-entorno)
5. [Autenticación](#autenticación)
6. [Endpoints](#endpoints)
7. [Tests](#tests)
8. [Migraciones](#migraciones)
9. [Estructura del proyecto](#estructura-del-proyecto)
10. [Flujo de trabajo](#flujo-de-trabajo)
11. [Equipo](#equipo)

---

## Arquitectura

**Monolito modular por dominio, API-First.** Cada dominio de negocio vive en `app/modules/<dominio>/` con sus modelos, esquemas, servicios y router; los elementos transversales (configuración, seguridad, errores, enums) viven en `app/core/`. El contrato OpenAPI generado por FastAPI lo consumen el frontend React y, a futuro, el asistente IA (que nunca accede directamente a la base de datos).

Las invariantes críticas se garantizan en PostgreSQL: unicidad, `CHECK`, claves foráneas y restricciones de exclusión `GIST` que impiden solapar reservas aprobadas.

| Módulo | Prefijo | Requisitos | Estado |
| --- | --- | --- | --- |
| `users` | `/api/v1/auth`, `/api/v1/users` | USR-01, USR-03, USR-04, USR-05, GLO-01 | Implementado |
| `config` | `/api/v1/config` | GLO-03 | Implementado |
| `inventory` | `/api/v1/inventory` | PRE-01, PRE-02, PRE-12, PRE-14, PRE-19 | Implementado |
| `spaces` | `/api/v1/spaces` | RES-01…RES-05, GLO-02, GLO-04 | Implementado |
| `loans` | — | PRE-03…PRE-20 | Pendiente |
| `notifications` | — | NOV-01…NOV-04 | Pendiente |
| `assistant` | — | IA-01…IA-03 | Pendiente |

**Roles:** `SUPERADMIN` (ambas sedes) · `ADMIN_LOCAL` (una sede) · `DOCENTE` · `ESTUDIANTE`. Los usuarios sólo operan sobre los recursos de su sede, excepto el Superadministrador.

**Seguridad transversal.** Todos los endpoints, salvo registro, login y `/health`, requieren sesión. El solicitante de una reserva es siempre el usuario autenticado; los recursos creados por un administrador local reciben su sede automáticamente; un recurso de otra sede se responde como inexistente (`404`). Las cuentas creadas o restablecidas por un administrador deben cambiar la contraseña antes de operar (`403 CAMBIO_PASSWORD_REQUERIDO`).

---

## Requisitos previos

- **Python 3.11 o superior** (validado con 3.12).
- **PostgreSQL 15 o superior** con la extensión `btree_gist` disponible (incluida en `postgresql-contrib`).
- Un usuario de PostgreSQL con permiso para crear bases (para los tests).

---

## Instalación y puesta en marcha

```bash
# 1. Entorno virtual y dependencias
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt  # incluye requirements.txt + herramientas de test

# 2. Configuración
cp .env.example .env                 # completar DATABASE_URL y JWT_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"   # genera un JWT_SECRET_KEY

# 3. Base de datos
createdb prestamedios                # o desde psql: CREATE DATABASE prestamedios;
alembic upgrade head                 # crea tablas, tipos, restricciones y parámetros semilla

# 4. Superadministrador inicial (pide la contraseña por consola)
python -m app.modules.users.cli crear-superadmin \
  --email natalia.ader@untdf.edu.ar --nombre Natalia --apellido Ader --dni 30111222

# 5. Servidor de desarrollo
uvicorn app.main:app --reload        # http://localhost:8000
```

> La aplicación **no arranca** si falta `JWT_SECRET_KEY` o tiene menos de 32 caracteres.

---

## Variables de entorno

Definidas en `.env` (ver [`.env.example`](.env.example)). **Nunca versionar `.env`.**

| Variable | Obligatoria | Default | Descripción |
| --- | --- | --- | --- |
| `DATABASE_URL` | Sí | — | `postgresql+asyncpg://usuario:clave@localhost:5432/prestamedios` |
| `JWT_SECRET_KEY` | Sí | — | Secreto de firma de tokens (≥ 32 caracteres) |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | No | `60` | Vida del token de acceso |
| `CORS_ORIGINS` | No | `http://localhost:8443` | Orígenes permitidos, separados por coma |
| `TEST_DATABASE_URL` | Sólo tests | — | Base dedicada; su nombre debe contener `test` |
| `BOOTSTRAP_SUPERADMIN_PASSWORD` | No | — | Contraseña para el CLI sin prompt interactivo |

Fechas y horas de reservas se interpretan en la zona del laboratorio, `America/Argentina/Ushuaia` (dependencia `tzdata`).

Las **reglas operativas** del laboratorio (plazos de préstamo, horario, anticipación mínima, tolerancias) no son variables de entorno: se administran desde el Panel de Parámetros Globales (`/api/v1/config/parametros`) y se siembran con la migración `0005`.

---

## Autenticación

JWT (`HS256`) en el header `Authorization: Bearer <token>`. Las contraseñas se almacenan con Argon2id.

```bash
# Registro (la cuenta queda "Pendiente en aprobación" hasta que un administrador la valida)
curl -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' -d '{
  "email": "lucia@untdf.edu.ar", "password": "Camara2026!", "nombre": "Lucía",
  "apellido": "Pérez", "dni": "40123456", "rol": "ESTUDIANTE", "sede": "Ushuaia"}'

# Inicio de sesión
curl -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email": "lucia@untdf.edu.ar", "password": "Camara2026!"}'

# Uso del token
curl localhost:8000/api/v1/auth/me -H "Authorization: Bearer <access_token>"
```

En Swagger (`/docs`) usar el botón **Authorize** y pegar el `access_token`.

**Errores.** Los errores de negocio responden `{"detail": "<mensaje>", "code": "<CODIGO>"}` (p. ej. `CUENTA_PENDIENTE_APROBACION`, `SEDE_FUERA_DE_ALCANCE`, `TOKEN_REVOCADO`); los de validación usan el formato estándar de FastAPI (`422`).

---

## Endpoints

Resumen; el detalle de cada contrato, ejemplo y código de error está en `/docs`.

| Módulo | Método y ruta | Descripción |
| --- | --- | --- |
| Autenticación | `POST /api/v1/auth/register` | Autorregistro de Estudiante o Docente |
| | `POST /api/v1/auth/login` | Inicio de sesión (JWT) |
| | `GET /api/v1/auth/me` · `PATCH /api/v1/auth/me` | Perfil propio; editar teléfono y email |
| | `POST /api/v1/auth/me/password` | Cambiar la contraseña (emite un token nuevo) |
| Usuarios | `GET /api/v1/users` | Directorio con filtros y aislamiento de sede |
| | `GET /api/v1/users/{id}` | Detalle administrativo |
| | `POST /api/v1/users` | Alta directa (Superadministrador) |
| | `PATCH /api/v1/users/{id}` | Editar datos, rol, sede o restablecer la contraseña |
| | `PATCH /api/v1/users/{id}/estado` | Aprobar, rechazar, suspender, dar de baja, reactivar |
| Configuración | `GET /api/v1/config/parametros[/{clave}]` | Parámetros operativos |
| | `PUT /api/v1/config/parametros/{clave}` | Modificar (Superadministrador, con control de versión) |
| | `GET /api/v1/config/parametros/{clave}/historial` | Historial de cambios |
| Inventario | `GET/POST /api/v1/inventory/categorias` | Categorías del catálogo |
| | `GET/POST /api/v1/inventory/equipamiento` | Catálogo de equipamiento |
| | `POST /api/v1/inventory/equipamiento/{id}/unidades` | Alta de unidades físicas |
| | `GET /api/v1/inventory/unidades` · `PATCH …/{id}/estado` | Stock y estado (mantenimiento) |
| Espacios | `GET/POST /api/v1/spaces/espacios` | Espacios reservables |
| | `GET/POST /api/v1/spaces/reservas` · `PATCH …/{id}/estado` | Solicitudes y su ciclo de vida |
| | `GET/POST /api/v1/spaces/bloqueos` | Bloqueos administrativos |
| | `GET /api/v1/spaces/disponibilidad` | Franjas libres y ocupadas por fecha |
| Salud | `GET /health` | Health check |

---

## Tests

Los tests de integración corren contra **PostgreSQL real** (nunca SQLite), porque el sistema depende de tipos `ENUM`, `JSONB`, restricciones `CHECK`/`EXCLUDE` y bloqueos de fila.

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://usuario:clave@localhost:5432/prestamedios_test
pytest -q                                                    # suite completa
pytest --cov=app --cov-report=term-missing                   # con cobertura
pytest tests/users/test_login.py -k suspension               # un subconjunto
```

- La base de `TEST_DATABASE_URL` se **recrea desde cero** en cada corrida (por seguridad, su nombre debe contener `test`).
- Sin `TEST_DATABASE_URL`, los tests marcados `integracion` se omiten y sólo corren los unitarios.
- Cada test indica el criterio de aceptación que cubre (`# AC-NN`) del spec correspondiente.

---

## Migraciones

```bash
alembic upgrade head          # aplicar todas
alembic downgrade -1          # revertir la última
alembic current               # revisión actual
```

- Archivos en `alembic/versions/` con el formato `000N_<descripcion>.py`, escritos a mano y **siempre reversibles** (`upgrade` + `downgrade`).
- Cada módulo nuevo registra sus modelos en `alembic/env.py`.
- Requiere la extensión `btree_gist` (la crea la migración `0001`; el usuario necesita permiso para crear extensiones o un administrador debe crearla antes).

---

## Estructura del proyecto

```text
Backend-PrestaMeDios/
├── app/
│   ├── main.py                 # creación de la app y registro explícito de routers
│   ├── database.py             # engine async, Base declarativa, NAMING_CONVENTION, get_db
│   ├── core/                   # transversal: settings, enums, errors, security, deps
│   └── modules/
│       └── <dominio>/          # models · schemas · service · router · enums
├── alembic/versions/           # migraciones 000N_<desc>.py
├── tests/                      # conftest.py + tests por módulo
├── docs/ERS.md                 # especificación de requisitos (documento académico)
├── .env.example
├── requirements.txt            # dependencias de ejecución
└── requirements-dev.txt        # + herramientas de test
```

---

## Flujo de trabajo

El equipo aplica **Spec-Driven Development** dentro de Scrum (ClickUp):

1. Toda funcionalidad parte de un spec aprobado (requisitos → contratos → criterios de aceptación).
2. Ramas desde `develop`: `feat/<tema>`, `fix/<tema>`, `docs/<tema>`.
3. Commits con [Conventional Commits](https://www.conventionalcommits.org/) en español: `feat(users): …`, `fix(spaces): …`.
4. Pull Request a `develop` con al menos una revisión, tests en verde y referencia a los requisitos (`USR-05`, `GLO-03`…).
5. `main` recibe sólo versiones estables para las entregas.

**Convenciones de código:** dominio en español y términos técnicos en inglés; esquemas de entrada con `extra="forbid"`; errores de negocio con `AppError`; cambios de estado vía `PATCH /<recurso>/{id}/estado`; reglas operativas leídas con `obtener_parametro()` en lugar de constantes.

---

## Equipo

Proyecto académico de la asignatura **Laboratorio de Software** (UNTDF, curso 2026).

- Matías Araujo · Joaquín Eberle · Daniel Sardinas · Fabrizio Verdú · Facundo Zamora
- **Referente:** Natalia Ader — Laboratorio de Medios Audiovisuales, ICSE.
