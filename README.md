# PrestaMeDios — Backend

API REST del sistema de préstamos de equipamiento y reservas de espacios del **Laboratorio de Medios Audiovisuales (LMA)** del ICSE — Universidad Nacional de Tierra del Fuego (UNTDF), para las sedes **Ushuaia** y **Río Grande**.

| | |
| --- | --- |
| **Requisitos (ERS IEEE 830)** | [`docs/ERS.md` en el repositorio de documentación](https://github.com/PrestaMeDios-org/Docs-PrestaMeDios/blob/main/docs/ERS.md) |
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
| `users` | `/api/v1/auth`, `/api/v1/users` | USR-01, USR-02, USR-03, USR-04, USR-05, GLO-01 | Implementado |
| `config` | `/api/v1/config` | GLO-03 | Implementado |
| `files` | `/api/v1/files` | PRE-05 (aval), USR-03 (foto) | Implementado (SPEC-03 Fase B2) |
| `inventory` | `/api/v1/inventory` | PRE-01, PRE-02, PRE-12, PRE-14, PRE-19 | Implementado |
| `spaces` | `/api/v1/spaces` | RES-01…RES-05, GLO-02, GLO-04 | Implementado |
| `loans` | `/api/v1/loans` | PRE-03…PRE-11, PRE-13, PRE-15…PRE-18, PRE-20 | Sólo contratos: los endpoints exigen sesión y responden `501 NO_IMPLEMENTADO` |
| `notifications` | `/api/v1/notifications` | NOV-01, NOV-02, NOV-04 (NOV-03 diferido) | Comunicados implementados (SPEC-06 Fase A); notificaciones personales en la Fase B |
| `assistant` | — | IA-01…IA-03 | Pendiente |

**Roles:** `SUPERADMIN` (ambas sedes) · `ADMIN_LOCAL` (una sede) · `DOCENTE` · `ESTUDIANTE`. Los usuarios sólo operan sobre los recursos de su sede, excepto el Superadministrador.

**Seguridad transversal.** Todos los endpoints, salvo registro, login, recuperación de contraseña y `/health`, requieren sesión. El solicitante de una reserva es siempre el usuario autenticado; los recursos creados por un administrador local reciben su sede automáticamente; un recurso de otra sede se responde como inexistente (`404`). Las cuentas creadas o restablecidas por un administrador deben cambiar la contraseña antes de operar (`403 CAMBIO_PASSWORD_REQUERIDO`).

**API pública de `users` para otros módulos.** `app.modules.users.service.datos_publicos_por_ids(db, ids)` devuelve `{id: DatosPublicosUsuario(id, nombre, apellido)}` en una sola consulta, para mostrar al solicitante en `spaces` y `loans` sin importar el modelo `Usuario` (SPEC-03 Fase A). No filtra por sede ni por estado: quien la llama sólo pasa ids que ya puede mostrar, y nunca la usa para exponer identidades en la disponibilidad.

**Archivos (SPEC-03 Fase B2).** La foto de perfil y el PDF de aval de los pedidos de alta gama (la resolución del Consejo) se guardan en PostgreSQL: metadatos en `archivos` y bytes en `archivos_contenido`. El tipo se decide por los primeros bytes, no por la extensión; la foto se vuelve a codificar como JPEG de hasta 512 px sin metadatos (se pierde la ubicación del EXIF). La descarga responde `404` a quien no tiene permiso: el propietario, los administradores con jurisdicción y el Superadministrador. API pública para `loans` en `app.modules.files.service`: `vincular_archivo` (en la transacción de la orden, sin `commit`), `abrir_archivo` (sin control de acceso: lo hace quien llama) y `respuesta_descarga` (encabezados de seguridad comunes).

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
                                     # Si tira el error about_Execution_Policies en Windows usa el comando: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
pip install -r requirements-dev.txt  # incluye requirements.txt + herramientas de test

# 2. Configuración
cp .env.example .env                 # completar DATABASE_URL y JWT_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"   # genera un JWT_SECRET_KEY

# 3. Base de datos
createdb prestamedios                # o desde psql: CREATE DATABASE prestamedios;
alembic upgrade head                 # crea tablas, tipos, restricciones y parámetros semilla

# 4. Superadministrador inicial (comando de una línea; pide la contraseña por consola)
python -m app.modules.users.cli crear-superadmin --email natalia.ader@untdf.edu.ar --nombre Natalia --apellido Ader --dni 30111222

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
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | No | `30` | Vida del token de acceso; el frontend lo renueva mientras haya actividad |
| `JWT_SESION_MAX_HORAS` | No | `8` | Tope de una sesión desde el login: pasado ese tiempo no se renueva y hay que volver a iniciar sesión |
| `CORS_ORIGINS` | No | `http://localhost:8443` | Orígenes permitidos, separados por coma |
| `TEST_DATABASE_URL` | Sólo tests | — | Base dedicada; su nombre debe contener `test` |
| `BOOTSTRAP_SUPERADMIN_PASSWORD` | No | — | Contraseña para el CLI sin prompt interactivo |
| `ARCHIVO_FOTO_MAX_MB` · `ARCHIVO_PDF_MAX_MB` | No | `2` · `10` | Tamaño máximo de la foto de perfil y del PDF de aval |
| `ARCHIVO_HUERFANO_HORAS` | No | `24` | Antigüedad desde la que `limpiar-huerfanos` borra los archivos sin vincular |
| `ARCHIVO_MAX_PENDIENTES` | No | `5` | Archivos sin vincular por usuario (el siguiente responde `409`) |
| `EMAIL_BACKEND` | No | `smtp` | `smtp` o `memoria` (los tests usan siempre `memoria`) |
| `SMTP_HOST` · `SMTP_PORT` | No | `localhost` · `1025` | Servidor de correo (Mailpit en desarrollo) |
| `SMTP_USER` · `SMTP_PASSWORD` | No | — | Credenciales SMTP (sólo en `.env`) |
| `SMTP_TLS` | No | `starttls` | `starttls`, `ssl` o `ninguno` (Mailpit: `ninguno`) |
| `EMAIL_FROM` | No | `PrestaMeDios <no-responder@localhost>` | Remitente |
| `FRONTEND_URL` | No | `http://localhost:8443` | Base de los enlaces de los correos |
| `RECUPERACION_VIGENCIA_MINUTOS` | No | `30` | Vida del enlace de recuperación de contraseña |
| `RECUPERACION_MAX_POR_EMAIL_HORA` · `RECUPERACION_MAX_POR_IP_HORA` | No | `3` · `20` | Pedidos de recuperación por hora (el siguiente responde `429`) |

Fechas y horas de reservas se interpretan en la zona del laboratorio, `America/Argentina/Ushuaia` (dependencia `tzdata`).

Las **reglas operativas** del laboratorio (plazos de préstamo, horario, anticipación mínima, tolerancias) no son variables de entorno: se administran desde el Panel de Parámetros Globales (`/api/v1/config/parametros`) y se siembran con las migraciones `0005` y `0017`.

**Horario y correo de contacto por sede (SPEC-09 Fase A).** Cada sede tiene su horario y su correo de contacto: `horario.<sede>.apertura`, `horario.<sede>.cierre` y `contacto.<sede>.email`, con `<sede>` igual a `ushuaia` o `rio_grande`. Los otros módulos los leen con `app.modules.config.service.datos_de_sede(db, sede)` o `datos_de_sedes(db)`, que devuelven `DatosSede(sede, horario_apertura, horario_cierre, correo_contacto)` en una sola consulta y sin `commit` (`correo_contacto` es `None` mientras no se configure). El frontend usa `GET /api/v1/config/sedes`. Las claves globales `horario.apertura` y `horario.cierre` quedan obsoletas y no editables, y se borran cuando `spaces`, `loans` y el portal lean el horario de cada sede (DT-33).

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

**Renovación de la sesión.** El token dura `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (30) y lleva el claim `auth_time` con el momento del login. Mientras el usuario trabaja, el frontend lo cambia por uno nuevo con `POST /api/v1/auth/renovar`, que conserva `auth_time`; pasadas `JWT_SESION_MAX_HORAS` (8) desde el login responde `401 TOKEN_SESION_MAXIMA`. Sin actividad, el token vence y se vuelve al login. No hay refresh token ni cookies: el token sigue en `sessionStorage` y cerrar la pestaña cierra la sesión (ADR-015). `POST /api/v1/auth/me/sesiones/cerrar` cierra las sesiones abiertas en otras computadoras.

**Recuperar la contraseña (USR-02).** `POST /api/v1/auth/recuperacion` con `{"email"}` responde siempre el mismo `202`, exista o no la cuenta, y sólo manda el correo a cuentas activas. El enlace es `{FRONTEND_URL}/#/restablecer?token=…` (el token va en el fragmento, que el navegador no manda al servidor) y vence a los `RECUPERACION_VIGENCIA_MINUTOS`. El frontend manda el token y la contraseña nueva a `POST /api/v1/auth/recuperacion/confirmar`; eso cierra todas las sesiones y no inicia una nueva.

**Correo en desarrollo (Mailpit).** Mailpit recibe los correos sin mandarlos a nadie:

```bash
docker run -d --name mailpit -p 1025:1025 -p 8025:8025 axllent/mailpit
```

Con `SMTP_HOST=localhost`, `SMTP_PORT=1025` y `SMTP_TLS=ninguno` en el `.env`, los correos se ven en http://localhost:8025. Otros módulos mandan correos con `app.core.email.enviar_correo(TipoCorreo.<TIPO>, destinatario, contexto)`; cada tipo tiene su plantilla en `app/core/plantillas_correo/` (`notifications` usa `TipoCorreo.NOTIFICACION` con `titulo` y `mensaje`).

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
| | `POST /api/v1/auth/renovar` | Cambiar el token vigente por uno nuevo, sin pasar el tope de `JWT_SESION_MAX_HORAS` desde el login |
| | `POST /api/v1/auth/me/sesiones/cerrar` | Cerrar todas mis sesiones (devuelve un token nuevo para la pestaña actual) |
| | `POST /api/v1/auth/recuperacion` · `POST /api/v1/auth/recuperacion/confirmar` | Pedir el enlace para restablecer la contraseña y confirmarlo (públicos) |
| | `PUT /api/v1/auth/me/foto` · `DELETE /api/v1/auth/me/foto` | Subir, reemplazar o quitar la foto de perfil (multipart, campo `archivo`; JPEG, PNG o WebP) |
| Usuarios | `GET /api/v1/users` | Directorio con filtros y aislamiento de sede |
| | `GET /api/v1/users/{id}` | Detalle administrativo |
| | `POST /api/v1/users` | Alta directa (Superadministrador) |
| | `PATCH /api/v1/users/{id}` | Editar datos, rol, sede o restablecer la contraseña |
| | `PATCH /api/v1/users/{id}/estado` | Aprobar, rechazar, suspender, dar de baja, reactivar |
| | `DELETE /api/v1/users/{id}/foto` | Quitar la foto de una cuenta (el `ADMIN_LOCAL`, sólo de estudiantes y docentes de su sede) |
| Archivos | `POST /api/v1/files/archivos` | Subir el PDF de aval (estudiantes y docentes; multipart: `archivo` y `proposito=AVAL_PRESTAMO`). Queda sin vincular hasta que `loans` lo asocia a la orden |
| | `GET /api/v1/files/archivos/{id}/contenido` | Descargar un archivo; `404` si no corresponde verlo |
| Configuración | `GET /api/v1/config/parametros[/{clave}]` | Parámetros operativos |
| | `PUT /api/v1/config/parametros/{clave}` | Modificar (Superadministrador, con control de versión) |
| | `GET /api/v1/config/parametros/{clave}/historial` | Historial de cambios |
| | `GET /api/v1/config/sedes` | Horario y correo de contacto de cada sede (cualquier usuario autenticado) |
| Inventario | `GET/POST /api/v1/inventory/categorias` | Categorías del catálogo |
| | `GET /api/v1/inventory/equipamiento[/{id}]` | Catálogo con filtros `sede`, `categoria`, `q`. Estudiantes y docentes reciben una vista reducida (sin unidades ni series); `incluir_inactivos` sólo para administradores |
| | `POST /api/v1/inventory/equipamiento` | Alta de equipamiento (plazo por defecto desde `prestamo.general.max_dias`, o `prestamo.notebook.max_dias` si `es_notebook`) |
| | `PATCH /api/v1/inventory/equipamiento/{id}` · `PATCH …/{id}/estado` | Edición y baja o reactivación lógica |
| | `POST /api/v1/inventory/equipamiento/{id}/unidades` | Alta de unidades físicas (sede automática para `ADMIN_LOCAL`) |
| | `GET /api/v1/inventory/unidades` · `PATCH …/{id}` | Stock de la jurisdicción; edición de serie, código y locker (1–7) |
| | `PATCH /api/v1/inventory/unidades/{id}/estado` | `disponible` ⇄ `mantenimiento`, y `baja` (definitiva). `prestado` lo gestiona sólo `loans` mediante `app/modules/inventory/service.py` |
| Espacios | `GET/POST /api/v1/spaces/espacios` | Espacios reservables |
| | `GET/POST /api/v1/spaces/reservas` · `PATCH …/{id}/estado` | Solicitudes y su ciclo de vida |
| | `GET/POST /api/v1/spaces/bloqueos` | Bloqueos administrativos |
| | `GET /api/v1/spaces/disponibilidad` | Franjas libres y ocupadas por fecha |
| Comunicados | `GET /api/v1/notifications/comunicados[/{id}]` | Comunicados de la sede del usuario más los globales. Estudiantes y docentes ven sólo los vigentes; `sede` sólo para el Superadministrador e `incluir_archivados` sólo para administradores |
| | `POST /api/v1/notifications/comunicados` | Publicar. `ADMIN_LOCAL`: en su sede. `SUPERADMIN`: `sede` o `es_global` (uno de los dos) |
| | `PATCH /api/v1/notifications/comunicados/{id}` · `PATCH …/{id}/estado` | Editar título, contenido y vencimiento; archivar o reactivar |
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
- **Mantenimiento de archivos:** `python -m app.modules.files.cli limpiar-huerfanos [--horas N]` borra los archivos sin vincular más viejos que `ARCHIVO_HUERFANO_HORAS`. Es idempotente; conviene programarlo una vez por día en el despliegue.
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
├── .env.example
├── requirements.txt            # dependencias de ejecución
└── requirements-dev.txt        # + herramientas de test
```

---

## Equipo

Proyecto académico de la asignatura **Laboratorio de Software** (UNTDF, curso 2026).

- Matías Araujo · Joaquín Eberle · Daniel Sardinas · Fabrizio Verdú · Facundo Zamora
- **Referente:** Natalia Ader — Laboratorio de Medios Audiovisuales, ICSE.
