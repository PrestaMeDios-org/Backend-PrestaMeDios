# PrestaMeDios

**Sistema de Gestión de Recursos y Reservas para el Laboratorio de Medios Audiovisuales**

**Laboratorio de Software**
**Curso 2026**

* Matías Araujo
* Joaquín Eberle
* Daniel Sardinas
* Fabrizio Verdú
* Facundo Zamora

**Entrega parcial**
09/10/2026

---

## ÍNDICE

* INTRODUCCIÓN (4)
* ESPECIFICACIÓN DE REQUERIMIENTOS (6)
* Introducción y ámbito del sistema (6)
* Definiciones, siglas y abreviaturas (7)
* Referencias (8)
* Descripción general (8)
* Funciones del producto (8)
* Características de los usuarios (9)
* Restricciones (10)
* Suposiciones y Dependencias (11)
* Requisitos futuros (11)
* Requisitos específicos (11)
* Subsistema 1: Gestión de Usuarios y sus Historiales (11)
* Subsistema 2: Préstamos de Equipamiento y Computadoras (12)
* Subsistema 3: Reserva de Espacios (15)
* Subsistema 4: Novedades y Notificaciones (16)
* Subsistema 5: Configuración Global y Entorno (17)
* Subsistema 6: Integración de IA (límite de alcance) (18)




* CRONOGRAMA DE TRABAJO (19)
* METODOLOGÍA DE DESARROLLO (20)
* HERRAMIENTAS UTILIZADAS (21)
* ANÁLISIS (22)
* Casos de Uso (22)


* DISEÑO (40)
* Diagrama Entidad-Relación (DER) (40)
* Principales Pantallas de la Aplicación (40)
* Arquitectura del Sistema (45)


* SOBRE LAS ITERACIONES (47)
* SOBRE LOS ENTREGABLES (49)
* PRESENTACIÓN VISUAL PARA APROBAR FINAL (50)

---

## INTRODUCCIÓN

En el presente documento se detalla el análisis, diseño y especificación para el desarrollo del sistema PrestaMeDios, concebido para el Laboratorio de Medios Audiovisuales del Instituto de Cultura, Sociedad y Estado (ICSE) de la Universidad Nacional de Tierra del Fuego, Antártida e Islas del Atlántico Sur (UNTDF), abarcando sus sedes de Ushuaia y Rio Grande. Este sistema buscará simplificar y acelerar la gestión de recursos y bienes tecnológicos como préstamos de cámaras y computadoras o reservas de Laboratorios para edición.

### Problema a resolver

Actualmente, el Laboratorio de Medios Audiovisuales gestiona las solicitudes de préstamo de equipamiento técnico, computadoras portátiles y las reservas del aula-estudio e islas de edición mediante correos electrónicos y formularios de Google.

Se identificaron falencias operativas y de usabilidad. Existe una ausencia total de visibilidad sobre el stock e inventario en tiempo real; los estudiantes completan sus solicitudes a ciegas sin conocer si los insumos están efectivamente disponibles para las fechas requeridas. A esto se le suma un flujo de aprobación asincrónico y manual que requiere que se reenvíen correos a los docentes para validar las solicitudes.

### Descripción del proyecto

El proyecto PrestaMeDios consiste en una plataforma integral de software orientada a digitalizar, centralizar y optimizar todos los procesos del Laboratorio de Medios Audiovisuales.

La solución permitirá a estudiantes y docentes:

* Consultar disponibilidad en tiempo real antes de solicitar un préstamo.
* Programar reservas y turnos para el aula-estudio e islas de edición usando un calendario interactivo.
* Acceder a información institucional y recibir notificaciones sobre cursos, talleres y novedades respecto al Laboratorio.

### Motivación

Nuestra motivación principal radica en desarrollar e implementar un producto de software con aplicación e impacto real en la comunidad de la UNTDF. Al desarrollarse dentro del ámbito académico de la sede, se cuenta con la cercanía diaria con los usuarios finales y administradores del laboratorio, lo que facilita un ciclo continuo de retroalimentación, validación directa de requerimientos y ajuste permanente del sistema.

**Referente (Cliente):** Natalia Ader

---

## ESPECIFICACIÓN DE REQUERIMIENTOS

### Introducción y ámbito del sistema

#### Identificación y nombre del sistema

PrestaMeDios será una plataforma integradora de gestión de bienes, herramientas, espacios físicos y control y solicitud de préstamos de equipamiento técnico y tecnológico para el Laboratorio de Medios Audiovisuales, dependiente del Instituto de Cultura, Sociedad y Estado (ICSE) de la Universidad Nacional de Tierra del Fuego, Antártida e Islas del Atlántico Sur (UNTDF).

#### Contexto y problemática actual

En la actualidad, el Laboratorio de Medios Audiovisuales de la UNTDF coordina sus actividades y recursos a través de dos sedes académicas: la sede Ushuaia (Yrigoyen 879) y la sede Río Grande (Thorne 302). En ambas instalaciones se administran recursos pedagógicos, que van desde equipamiento de rodaje (cámaras, trípodes, micrófonos, sistemas de iluminación) y computadoras portátiles, a infraestructuras como el Aula-Estudio para puestas en escena e Isla de Edición.

El mecanismo operativo vigente para gestionar estos recursos presenta deficiencias organizativas y limitaciones operativas:

* **Falta de visibilidad de inventario y disponibilidad:** Todas las reservas se realizan mediante formularios y correos electrónicos. Esto significa un constante intercambio manual de mensajes entre los solicitantes y el personal técnico para consultar si un equipo o turno está libre.
* **Riesgo de solapamientos y pérdidas de tiempo:** Al no existir un calendario sincronizado, se producen duplicaciones de reservas o demoras en la reserva y devolución del equipamiento.

#### ¿Para qué va a servir el sistema?

El objetivo primordial de PrestaMeDios es digitalizar, unificar y automatizar los flujos de préstamos, devoluciones y reservas del Laboratorio de medios. El sistema centraliza todas las operaciones de la institución mediante las funciones fundamentales mencionadas en "Funciones del producto".

#### Destinatarios

El sistema estará destinado a estudiantes, docentes y al personal del Laboratorio de Medios Audiovisuales.

#### Plataformas

PrestaMeDios se concibe como una aplicación web cuya arquitectura posibilitará la expansión futura hacia una aplicación móvil.

### Definiciones, siglas y abreviaturas

* **UNTDF:** Universidad Nacional de Tierra del Fuego, Antártida e Islas del Atlántico Sur.
* **ICSE:** Instituto de Cultura, Sociedad y Estado.
* **CICSE:** Consejo del Instituto de Cultura, Sociedad y Estado.
* **LMA o Laboratorio:** Laboratorio de Medios Audiovisuales.
* **Trabajo de Integración Final (TIF):** Instancia académica de graduación requerida para la obtención del título de grado universitario, pueden solicitar préstamos especiales.
* **Préstamo General:** Solicitud estándar de equipamiento audiovisual (cámaras, sonido, iluminación) para uso fuera del establecimiento por un plazo máximo estipulado de 4 días corridos al administrador.
* **Préstamo Especial:** Préstamo de equipamiento de alta gama o de duración extendida destinado exclusivamente a docentes investigadores o estudiantes en etapa de TIF, el cual requiere aprobación jerárquica del ICSE.
* **Préstamo de Notebooks:** Cesión temporal de computadoras portátiles institucionales por un plazo reglamentario de hasta 15 días corridos, sujeto a renovación según disponibilidad.
* **Aula-Estudio:** Espacio físico e infraestructura del laboratorio acondicionado acústica y técnicamente para grabaciones de sonido, puestas en escena, iluminación y rodajes de estudio.
* **Isla de Edición:** Estación de trabajo informática para montaje audiovisual.
* **ERS:** Especificación de Requisitos Software.

### Referencias

* International Scrum Institute: The Scrum Framework. International Scrum Institute (2020).
* Especificación de Requisitos según el estándar de IEEE 830. Institute of Electrical and Electronics Engineers (2008).
* Resolución CICSE N° 056/2023: Reglamento del Laboratorio de Medios Audiovisuales. Ushuaia (2023). Se adjunta en pdf.
* Ader, N.: Primera entrevista y relevamiento de requerimientos para el sistema PrestaMeDios. Ushuaia (27/08/2026).
* Ader, N.: Segunda entrevista y relevamiento de requerimientos para el sistema PrestaMeDios. Ushuaia (04/09/2026).

### Descripción general

#### Funciones del producto

* **Gestión de Préstamos Generales de Equipamiento:** Permite a los estudiantes y docentes de la Licenciatura en Medios Audiovisuales consultar el catálogo de insumos y equipos con su estado en tiempo real, solicitar préstamos bajo el límite reglamentario de permanencia máxima fuera del establecimiento (hasta 4 días corridos) y registrar la entrega/recepción en el Laboratorio.
* **Visualización Docente Automatizada:** Automatiza el circuito de visualización mediante el cual el sistema reenvía la solicitud del alumno al docente de la materia correspondiente para que pueda ver las solicitudes de préstamos activos y pendientes de los estudiantes de su asignatura.
* **Gestión de Préstamos Especiales (Alta Gama y TIF):** Canaliza las solicitudes de equipamiento avanzado orientadas a docentes investigadores y a estudiantes en etapa de elaboración de sus Trabajos de Integración Final (TIF), las cuales exigen una aprobación jerárquica directa por parte de las autoridades del ICSE.
* **Gestión de Computadoras Portátiles:** Administra el inventario de laptops institucionales disponibles para toda la comunidad académica del ICSE, permitiendo préstamos por un plazo de hasta 15 días de corrido, con posibilidad de renovación sujeta a disponibilidad.
* **Reserva de Espacios Técnicos:** Los usuarios reservan franjas horarias específicas para el Aula-Estudio (grabaciones y puestas en escena) y la Isla de Edición (postproducción audiovisual).
* **Calendario digital:** Cada proceso de préstamo involucra el despliegue del calendario en el que aparecerán los días en los que el equipo o infraestructura estará reservado o disponible.
* **Comunicación:** Se enviarán novedades institucionales, normativas, avisos varios y cualquier comunicación pertinente a los usuarios.

#### Características de los usuarios

**Contacto con los usuarios:**
Al tratarse de un desarrollo para la universidad, el equipo de PrestaMeDios tiene contacto directo y continuo con los usuarios clave del sistema. Lo que permite realizar entrevistas, pruebas y validaciones funcionales directamente con el personal del Laboratorio.

**Nivel de conocimiento técnico:**
Los estudiantes y docentes cuentan con un nivel de conocimiento digital medio en el manejo de páginas y aplicaciones web. La interfaz priorizará la simplicidad, accesibilidad y navegación intuitiva.
El personal del Laboratorio tiene un perfil de usuario de conocimiento digital avanzado a la navegación por plataformas web institucionales.

**Tipos de usuario:**
El sistema tiene 3 perfiles de usuarios, cada uno con roles y responsabilidades propias:

* **Estudiante:** Consulta los elementos disponibles para reserva, solicita préstamos generales y/o especiales, préstamos de computadoras y reserva el Aula-Estudio y la Isla de Edición y recibe notificaciones.
* **Docente:** Visualiza las solicitudes de préstamos iniciadas por los alumnos de su asignatura y puede hacer comentarios, solicita recursos técnicos e instalaciones para dictar clases y equipamiento de alta gama para TIF e investigación.
* **Personal del Laboratorio (Superadministrador y Administradores Locales):** Gestión general del inventario (altas, bajas, modificaciones y registro de estado), control de entrega y recepción física del equipamiento o infraestructura, administración de turnos y disponibilidad de espacios físicos y publicación de avisos institucionales, cursos, o cualquier notificación pertinente.

#### Restricciones

Las siguientes restricciones delimitan el alcance de PrestaMeDios, establecen los límites operacionales, normativos y de infraestructura que el software debe cumplir.

* **Diferenciación entre sedes:** El sistema debe diferenciar de manera estricta el inventario y espacios entre la sede Ushuaia y la sede Río Grande. No permitirá solicitar, reservar ni retirar bienes físicos de una sede desde la otra.
* **Ocultamiento del historial de préstamos:** Ningún usuario estudiante podrá visualizar el historial de préstamos, solicitudes activas ni la identidad de otros solicitantes. Cada usuario tendrá visibilidad únicamente sobre sus propios movimientos, excepto los usuarios administradores que tienen acceso total al historial de préstamos y los docentes que tienen acceso a los préstamos solicitados para su asignatura.
* **Tiempos límites de préstamo:** Para cada tipo de solicitud, el sistema no permitirá registrar solicitudes que excedan los plazos máximos y mínimos fijados por el Laboratorio de Medios (24 horas).
* **Horarios fijos:** El sistema no gestiona automáticamente reservas por fuera de los horarios 9:00 a 16:00 hs. Las reservas del Aula-Estudio y de la Isla de Edición en las sedes de Ushuaia y Río Grande estarán acotadas por defecto a un horario estático de 9:00 a 16:00 hs. Esta restricción garantiza la presencia obligatoria de un docente o no-docente a cargo de la supervisión física.

#### Suposiciones y Dependencias

Debido a que las operaciones del laboratorio requieren la intervención directa del personal, no resulta factible implementar la devolución automatizada de insumos mediante lockers con candados inteligentes.

#### Requisitos futuros

* **Reserva de Isla de Digitalización de Archivos Físicos:** El subsistema de reserva de espacios incorporará en su catálogo interactivo un nuevo espacio físico denominado "Isla de Digitalización de Archivos Físicos". Permitirá a los usuarios agendar bloques horarios específicos para utilizar el equipamiento de recuperación de material de archivo (reproductoras analógicas de formatos VHS, S-VHS, Beta y Hi8).

### Requisitos específicos

#### Subsistema 1: Gestión de Usuarios y sus Historiales

**Módulo 1: Información de la Cuenta del Usuario**

* **USR-01 - Registro e inicio de sesión:** El sistema permitirá a estudiantes, docentes y administradores registrarse e iniciar sesión, determinando sus permisos y vistas en base a su rol específico.
* **USR-02 - Recuperación de contraseña:** Si el usuario olvida su clave, debe tener una opción en la pantalla de login para restablecerla mediante un correo electrónico.
* **USR-03 - Actualización de datos de contacto:** El estudiante y el docente podrán mantener actualizados su teléfono, correo y foto en su perfil. Los demás datos estarán bloqueados para su edición.
* **USR-04 - Gestión de usuarios y accesos:** El Superadministrador tendrá acceso a un directorio general de todos los usuarios (estudiantes, docentes y administradores locales). Contará con permisos para editar perfiles, dar de baja o alta usuarios y buscar perfiles mediante filtros por rol y sede.
* **USR-05 - Registro con validación manual:** El sistema permitirá a los nuevos usuarios completar un formulario de registro. Las cuentas creadas ingresarán en estado "Pendiente en aprobación". El Superadministrador podrá validar, editar o dar de baja perfiles de ambas sedes, mientras que los Administradores Locales sólo tendrán jurisdicción para accionar sobre las cuentas que pertenezcan a su sede asignada.

**Módulo 2: Historial del Usuario**

* **USR-06 - Panel de solicitudes:** El usuario podrá visualizar el estado de sus peticiones (Pendientes / Aprobadas / Rechazadas), ver las fechas límite de devolución y cancelar solicitudes en curso.
* **USR-07 - Historial de actividad:** El sistema mantendrá un registro accesible para el estudiante o docente donde podrá consultar todos sus equipos utilizados o aulas reservadas previamente.
* **USR-08 - Logs de auditoría global:** El administrador tendrá acceso a un registro global sobre las reservas de equipamientos y aulas para auditar los movimientos del sistema.
* **USR-09 - Métricas de comportamiento:** El sistema permitirá al administrador asignar etiquetas visuales ("chips" verdes, amarillos o rojos) al perfil de los estudiantes, formando un historial acumulativo. El administrador gestionará estas incidencias mediante contadores ajustables (+/-), mientras que el docente solo tendrá acceso de lectura a través de un indicador emergente (tooltip) sobre el perfil del alumno.

#### Subsistema 2: Préstamos de Equipamiento y Computadoras

**Módulo 1: Catálogo y Búsqueda de Recursos**

* **PRE-01 - Visualización del inventario:** Catálogo interactivo para estudiantes y docentes. Mostrará la descripción técnica, el manual/reglas de cuidado, un botón de video instructivo y un mini-calendario de disponibilidad. El estado se calculará dinámicamente mediante la disponibilidad en la base de datos.
* **PRE-02 - Búsqueda con filtros:** Implementación de una barra de búsqueda y filtros por categoría y por Sede (Ushuaia / Río Grande).

**Módulo 2: Solicitud y Reserva de Ítems**

* **PRE-03 - Modalidades de solicitud (individual y carrito):** El sistema permitirá generar reservas de dos formas: de manera directa por un único ítem ("forma simple" desde el catálogo) o agrupando múltiples elementos a través del carrito. En ambos casos, el sistema disparará un único formulario unificado para generar la "Orden de Pedido". En dicho formulario, el estudiante deberá indicar obligatoriamente la Asignatura para la cual requiere el préstamo y aceptar una casilla de Términos y Condiciones antes de procesar el pedido. Estas solicitudes irán directo al Administrador.
* **PRE-04 - Validación de formularios:** El sistema marcará en rojo las casillas obligatorias faltantes. ej materia, bloqueando el envío si el campo está incompleto.
* **PRE-05 - Solicitudes especiales:** Los equipos "Alta Gama" (especiales) podrán mezclarse en el carrito con equipos comunes. El sistema permitirá agrupar múltiples equipos de Alta Gama en un formulario común donde el estudiante deberá adjuntar obligatoriamente un archivo PDF de validación. Esta solicitud irá directo al Administrador.
* **PRE-06 - Selección de fechas y franjas horarias:** Al solicitar un recurso, el usuario deberá seleccionar mediante un calendario la fecha de retiro y devolución, incluyendo obligatoriamente la hora de retiro y hora de devolución estimadas. Estos selectores de hora estarán restringidos a la franja operativa del laboratorio.
* **PRE-07 - Límite de reserva temporal:** El sistema restringirá las fechas seleccionables en el calendario de préstamos, permitiendo un límite máximo de 4 días por solicitud para los estudiantes.
* **PRE-08 - Cancelación automática:** Si un estudiante no se presenta a retirar un equipo reservado dentro de un margen de tolerancia predefinido (ej. 2 horas tras el inicio del turno), el sistema cancelará la reserva automáticamente, liberando el ítem para otros usuarios.
* **PRE-09 - Solicitudes de docentes:** El sistema habilitará a los docentes a generar solicitudes de equipamiento para uso de cátedra. Estas peticiones ingresarán directamente a la bandeja del Administrador para su validación.
* **PRE-10 - Aprobación o Rechazo de Solicitudes de Préstamos de Ítems:** El Administrador confirma la aprobación o rechazo de la solicitud de Ítems. La confirmación de las reservas no son automáticas, se confirman manualmente por el Administrador.

**Módulo 3: Operaciones de Panel y Control de Stock**

* **PRE-11 - Renovación de computadoras:** La extensión de préstamos de notebooks se realizará exclusivamente de manera presencial. El administrador contará con un botón en su panel operativo para extender la fecha de devolución.
* **PRE-12 - Gestión de inventario (stock):** El Administrador contará con una vista tipo tabla interactiva filtrable por Sede. Las columnas incluirán flechas de ordenamiento (ascendente/descendente) y mostrarán: Nombre, Categoría, Locker (1-7), Tipo (Especial/Común) y unidades disponibles. Permitirá desplegar los ítems para visualizar las unidades físicas individuales (ej. CAM-S-01) y su historial de usuarios.
* **PRE-13 - Registro de entrega y devolución:** El Administrador contará con una función en el mostrador para confirmar la entrega física del recurso (cambiando automáticamente su estado a "En Uso") y registrar su retorno (cambiando el estado a "Disponible"). El sistema alertará visualmente en rojo los préstamos demorados. Al momento de registrar esta devolución, el sistema habilitará un campo de texto para añadir observaciones sobre el estado físico del recurso, las cuales quedarán guardadas en el historial particular de esa unidad.
* **PRE-14 - Bloqueo por mantenimiento:** El administrador podrá cambiar manualmente el estado de una unidad física a "En Mantenimiento" o "Fuera de Servicio", ajustando el stock lógico y bloqueando su reserva.
* **PRE-15 - Historial de solicitudes y bandeja centralizada:** Panel operativo central para el administrador con el listado global de todas las órdenes. La bandeja filtrará automáticamente los trámites pendientes según la jurisdicción del usuario (limitado a su sede para administradores locales, o con vista consolidada para el Superadministrador).
* **PRE-16 - Calendario maestro de operaciones:** Vista global de monitoreo para el Administrador que mostrará todos los recursos físicos agrupados por estado ("En Uso" y "En Reserva") para organizar la logística diaria.
* **PRE-17 - Resolución de conflictos:** Si la reducción de stock físico (por rotura) genera un conflicto con reservas futuras aprobadas, el Administrador podrá ejecutar una "Cancelación Forzada". El sistema exigirá ingresar un motivo obligatorio y enviará una alerta al usuario.
* **PRE-18 - Modificación horaria en aprobación:** Al momento de evaluar una solicitud pendiente, el Administrador tendrá la facultad de editar la hora de retiro y/o devolución sugerida por el usuario antes de cambiar el estado a "Aprobada", con el fin de optimizar la logística del mostrador y evitar cuellos de botella.
* **PRE-19 - Alta de nuevo equipamiento:** Al registrar equipos, el sistema asignará la sede automáticamente para administradores locales. Los administradores con acceso global deberán seleccionar obligatoriamente el destino (Ushuaia o Río Grande).

**Módulo 4: Validación y Monitoreo Docente**

* **PRE-20 - Panel de validación docente:** Las solicitudes de estudiantes vinculadas a una asignatura aparecerán en una vista exclusiva para el docente a cargo. Este rol solo tendrá permisos de lectura/observación, no de aprobación.

#### Subsistema 3: Reserva de Espacios

**Módulo 1: Gestión de Turnos de Espacios (Isla de Edición y Aula-Estudio)**

* **RES-01 - Calendario interactivo:** El sistema proveerá un calendario visible para mostrar los bloques horarios y la disponibilidad operativa de los espacios físicos del laboratorio (Isla de Edición y Aula-Estudio).
* **RES-02 - Asignación de turnos:** El sistema permitirá al estudiante o docente enviar una solicitud para reservar un bloque horario, registrando el trámite en estado "Pendiente". El sistema admitirá múltiples solicitudes concurrentes para una misma franja horaria, delegando el bloqueo definitivo del recurso y la actualización del estado a "Ocupado" a la posterior aprobación manual del Administrador.
* **RES-03 - Cancelación de reserva:** El usuario podrá anular una reserva de espacio previamente asignada a través de su panel, liberando la disponibilidad para el resto de los estudiantes.
* **RES-04 - Bloqueo administrativo de espacios:** El administrador tendrá permisos para inhabilitar la disponibilidad de las Isla de Edición seleccionando días completos (por mantenimiento o feriados) o franjas horarias específicas, impidiendo que los usuarios generen nuevas reservas en esos periodos bloqueados.
* **RES-05 - Aprobación o Rechazo de Solicitudes de Reservas de Espacios:** La confirmación de las reservas de espacios físicos no es automática. El Administrador Local o el Superadministrador evaluarán las peticiones y confirmarán la aprobación o rechazo de la solicitud de manera manual. En caso de registrarse solicitudes concurrentes para un mismo bloque horario, la aprobación de una de ellas adjudicará el espacio al usuario seleccionado y descartará las peticiones superpuestas.

#### Subsistema 4: Novedades y Notificaciones

**Módulo 1: Tablón Informativo y Comunicados**

* **NOV-01 - Portal estático:** El sistema debe contar con una sección donde se publiquen de forma estática las normativas, horarios y datos institucionales del laboratorio.
* **NOV-02 - Gestión de novedades y comunicados:** El sistema proveerá una interfaz para publicar comunicados. Incorporará la capacidad de segmentar los avisos: un administrador local publicará novedades visibles solo para los estudiantes y docentes de su sede, mientras que el Superadministrador podrá emitir comunicados globales para ambas.

**Módulo 2: Centro de Notificaciones**

* **NOV-03 - Alertas de devolución:** El sistema enviará automáticamente una notificación al usuario 24 horas antes del vencimiento de su préstamo, y emitirá alertas si se excede la fecha.
* **NOV-04 - Notificaciones internas:** El sistema incluirá un indicador visual (campanita) para avisar cambios de estado en solicitudes. Emitirá una alerta crítica inmediata si el Administrador cancela una reserva por fuerza mayor, o si aprueba una solicitud modificando el horario original propuesto por el usuario, detallando la nueva franja horaria asignada.

#### Subsistema 5: Configuración Global y Entorno

**Módulo 1: Filtros Operativos y Geográficos**

* **GLO-01 - Filtro geográfico por sede y jerarquía de administración:** El sistema diferenciará el nivel de acceso geográfico en los perfiles. Los estudiantes, docentes y Administradores Locales operarán bajo una restricción estricta de sede (Ushuaia o Río Grande), visualizando, aprobando y gestionando únicamente los recursos y solicitudes correspondientes a su locación. Se incorpora el rol de "Superadministrador", el cual poseerá privilegios globales para visualizar, filtrar e intervenir en las bandejas de validación, inventarios y calendarios de ambas sedes (de forma individual o combinada). Al momento de crear una cuenta de administrador, el sistema requerirá asignar obligatoriamente su alcance: "Ushuaia", "Río Grande" o "Ambas sedes".
* **GLO-02 - Restricción de horarios operativos:** El sistema bloqueara en el calendario los días y horarios en los que el laboratorio se encuentre cerrado, impidiendo realizar reservas en esos periodos.

**Módulo 2: Panel de Control del Administrador**

* **GLO-03 - Panel de parámetros:** El sistema provee una interfaz para el administrador que le permite modificar variables operativas sin necesidad de alterar el código.
* **GLO-04 - Gestión dinámica del calendario:** El administrador dispondrá de un control interactivo para inhabilitar fechas específicas manualmente ante imprevistos, bloqueando la posibilidad de generar nuevas reservas en esos días y permitiendo rehabilitarlas si la situación se normaliza.
* **GLO-05 - Anotaciones privadas e internas:** El administrador dispondrá de un panel de notas privadas con título, contenido y etiquetas. Las notas podrán configurarse como personales o compartirse globalmente con los demás administradores mediante tags institucionales.

**Módulo 3: Preferencias de Interfaz**

* **GLO-06 - Accesibilidad y preferencias de interfaz:** EL sistema integrará controles de navegación global que permitirán al usuario alternar entre un tema claro y oscuro, y colapsar el menú lateral.

#### Subsistema 6: Integración de IA (límite de alcance)

**Módulo 1: Interfaz y Consultas en Lenguaje Natural**

* **IA-01 - Interfaz del asistente:** El sistema integrará un botón de acceso rápido en la interfaz principal para desplegar el asistente virtual.
* **IA-02 - Consulta de disponibilidad (Lectura):** El chatbot deberá tener acceso de lectura a la base de datos para responder consultas en lenguaje natural sobre el stock y las fechas disponibles de los equipos y aulas.
* **IA-03 - Procesamiento conversacional de reservas:** El chatbot permitirá al usuario interactuar mediante lenguaje natural para consultar la disponibilidad del catálogo, y ejecutar reservas guiadas directamente en el sistema utilizando la sesión activa del usuario.

---

## CRONOGRAMA DE TRABAJO

### Visión general

| Actividad / Semana | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Def. del tema del trabajo | ◉ | ◉ |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| Especif. requerimientos |  | ◉ | ◉ | ◉ |  |  |  |  |  |  |  |  |  |  |  |  |
| Def. de metodología |  |  | ◉ | ◉ | ◉ |  |  |  |  |  |  |  |  |  |  |  |
| Análisis y diseño |  |  |  |  | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ |  |  |  |  |
| Desarrollo y codificación |  |  |  |  |  |  |  | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ | ◉ |  |
| Validación |  |  |  |  |  |  |  |  |  | ◉ |  |  |  | ◉ | ◉ |  |
| Entrega |  | ◉ |  | ◉ | ◉ |  |  |  |  | ◉ |  | ◉ |  |  |  | ◉ |

### Cronograma por requerimientos

| Requerimiento / Semana | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Requerimiento 1 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| Requerimiento 2 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| ... |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| Requerimiento n |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |

---

## METODOLOGÍA DE DESARROLLO

### Resumen de la metodología elegida

El desarrollo de PrestaMeDios se regirá bajo un marco de trabajo Ágil basado fuertemente en los principios de Scrum, adaptado para un entorno académico. Esta metodología iterativa e incremental permite la entrega de software funcional en ciclos cortos (Sprints), garantizando la flexibilidad ante los cambios en los requerimientos del cliente (el Laboratorio de Medios Audiovisuales) y priorizando la funcionalidad sobre la documentación exhaustiva.

### Adecuación de la metodología

Dado que el equipo consta de 5 integrantes y un plazo limitado de 16 semanas, Scrum resulta ideal. La gestión de los entregables se orquestará utilizando ClickUp, mediante flujos de trabajo personalizados con estados como Backlog, En Desarrollo, Code Review y QA. Las ceremonias de Scrum (Planning y Reviews) se alinearán con las entregas parciales exigidas por la cátedra, garantizando demos funcionales progresivas al 40% y 80% del avance del software.

*(18/09/2026: Para futuras entregas escribir cómo nosotros nos adaptamos a la metodología)*

---

## HERRAMIENTAS UTILIZADAS

* **Lenguaje:**
* Backend: Python.
* Frontend: Javascript, Typescript.


* **Base de datos:** PostgreSQL.
* **Framework de Frontend:** React.
* **Framework de backend:** FastAPI.
* **Control de versiones:** Git, Github.
* **Gestión del proyecto:** ClickUp.
* **Diseño de Prototipos y Diagramación:**
* Figma.
* Diagrams.
* PlantText.


* **Comunicación interna de Grupo:**
* Discord.
* WhatsApp.



---

## ANÁLISIS

### Casos de Uso

#### Subsistema 1: Gestión de Usuarios y sus Historiales

##### Módulo 1: Información de la Cuenta del Usuario

**Caso de uso:** Registro y validación de cuentas (USR-01, USR-05)

* **Actor:** Estudiante, Docente, Administrador
* **Precondiciones:** El usuario no posee una cuenta activa en el sistema.
* **Flujo principal:**
1. El usuario accede a la pantalla de registro y completa el formulario con sus datos.
2. El usuario envía la solicitud de creación de cuenta.
3. El sistema registra el perfil en estado "Pendiente en aprobación", asociándolo a la sede elegida, y bloquea el inicio de sesión.
4. El Administrador Local (de la sede correspondiente) o el Superadministrador accede a su bandeja de directorio.
5. El administrador valida los datos de forma manual y aprueba la solicitud.
6. El sistema habilita la cuenta para su uso.


* **Postcondiciones:** El usuario queda registrado y puede iniciar sesión con los permisos de su rol.
* **Flujo alternativo:**
* **Condición:** El administrador detecta que los datos son incorrectos o la identidad no es válida.
* **Acciones:**
1. El administrador selecciona la opción de rechazar la solicitud.


* **Respuesta del sistema:** El sistema elimina la petición e impide el acceso del usuario.



**Caso de uso:** Inicio de sesión (USR-01, GLO-01)

* **Actor:** Estudiante, Docente, Administrador
* **Precondiciones:** El usuario posee una cuenta registrada en el sistema.
* **Flujo principal:**
1. El usuario ingresa sus datos de acceso en el formulario correspondiente.
2. El sistema identifica las atribuciones y la sede asociadas a su perfil.
3. El sistema dirige al usuario hacia la interfaz principal de su rol.


* **Postcondiciones:** El usuario inicia sesión correctamente y accede a la interfaz correspondiente a su rol.
* **Flujo alternativo - 01:**
* **Condición:** Las credenciales ingresadas no son válidas.
* **Acciones:**
1. El usuario ingresa credenciales incorrectas.


* **Respuesta del sistema:** El sistema informa que las credenciales ingresadas no son válidas y permite al usuario volver a intentarlo.


* **Flujo alternativo - 02:**
* **Condición:** El usuario no recuerda su contraseña.
* **Acciones:**
1. El usuario selecciona la opción "Olvidé mi contraseña".


* **Respuesta del sistema:** El sistema Inicia caso de uso USR-02 - Recuperación de contraseña.



**Caso de uso:** Recuperación de contraseña (USR-02)

* **Actor:** Estudiante, Docente, Administrador
* **Precondiciones:**
1. El usuario posee una cuenta registrada en el sistema.
2. La cuenta tiene una dirección de correo electrónico asociada.


* **Flujo principal:**
1. El sistema solicita la dirección de correo electrónico asociada a la cuenta.
2. El usuario ingresa su dirección de correo electrónico.
3. El sistema verifica que exista una cuenta asociada a la dirección proporcionada.
4. El sistema genera un enlace de recuperación de contraseña.
5. El sistema envía el enlace de recuperación al correo electrónico del usuario.
6. El usuario accede al enlace recibido.
7. El sistema muestra un formulario para establecer una nueva contraseña.
8. El usuario ingresa y confirma su nueva contraseña.
9. El sistema valida la nueva contraseña y actualiza las credenciales de la cuenta.
10. El sistema informa que la contraseña fue actualizada correctamente.


* **Postcondiciones:**
1. La contraseña del usuario ha sido actualizada.
2. El usuario puede iniciar sesión utilizando la nueva contraseña.


* **Flujo alternativo:**
* **Condición:** Correo electrónico no registrado.
* **Acciones:**
1. El usuario ingresa una dirección de correo electrónico que no está asociada a una cuenta.


* **Respuesta del sistema:** El sistema informa que no existe una cuenta asociada a la dirección ingresada y permite al usuario volver a ingresar una dirección de correo electrónico o regresar a la pantalla de inicio de sesión.



**Caso de uso:** Edición de información personal (USR-03)

* **Actor:** Estudiante, Docente
* **Precondiciones:** El usuario ha autenticado su sesión en la plataforma.
* **Flujo principal:**
1. El usuario entra a la sección de ajustes de su cuenta.
2. Modifica sus datos de contacto o imagen personal.
3. El usuario confirma y aplica las modificaciones.


* **Postcondiciones:** La información actualizada queda asentada en la base del sistema.
* **Flujo alternativo:**
* **Condición:** El usuario busca alterar datos no modificables (ej. DNI, Rol).
* **Acciones:**
1. El usuario intenta cambiar atributos protegidos del sistema.


* **Respuesta del sistema:** El sistema bloquea la modificación dejando los campos inhabilitados.



**Caso de uso:** Gestión administrativa de usuarios (USR-04)

* **Actor:** Administrador
* **Precondiciones:** El administrador ha autenticado su sesión en la plataforma.
* **Flujo principal:**
1. El administrador accede al directorio general de usuarios.
2. El sistema despliega únicamente los perfiles de la sede correspondiente (o de ambas si es Superadministrador).
3. Utiliza los filtros por rol y sede para ubicar un perfil específico.
4. Selecciona un perfil y modifica sus atributos o procede a darlo de baja.


* **Postcondiciones:** La información del perfil queda modificada o se remueve del registro del sistema.
* **Flujo alternativo:**
* **Condición:** El perfil a modificar o dar de baja posee restricciones de seguridad.
* **Acciones:**
1. El administrador intenta modificar o dar de baja un usuario protegido.


* **Respuesta del sistema:** El sistema emite un mensaje de error impidiendo la acción.



##### Módulo 2: Historial del Usuario

**Caso de uso:** Gestión del panel de solicitudes (USR-06)

* **Actor:** Estudiante, Docente
* **Precondiciones:** El usuario ha autenticado su sesión y posee reservas previas.
* **Flujo principal:**
1. El usuario entra a su panel general de peticiones.
2. Observa el listado según su estado ("Pendiente", "Aprobada" o "Rechazada") y las fechas límite para la devolución.


* **Postcondiciones:** El usuario conoce la situación actual de sus solicitudes.
* **Flujo alternativo:**
* **Condición:** El usuario requiere dar de baja una petición.
* **Acciones:**
1. El usuario marca una solicitud en curso.
2. Confirma la cancelación del trámite.


* **Respuesta del sistema:** El sistema invalida la solicitud y deja libre el recurso.



**Caso de uso:** Consultas de historial y auditoría (USR-07, USR-08)

* **Actor:** Estudiante, Docente, Administrador
* **Precondiciones:** Existen eventos asentados previamente en la plataforma.
* **Flujo principal:**
1. El usuario accede a la sección de su historial personal.
2. Revisa los elementos utilizados y espacios reservados con anterioridad.


* **Postcondiciones:** El usuario visualiza sus registros históricos dentro de la plataforma.
* **Flujo alternativo:**
* **Condición:** El administrador requiere supervisar la actividad global.
* **Acciones:**
1. El administrador ingresa al panel general de auditoría.


* **Respuesta del sistema:** El sistema expone la totalidad de movimientos, solicitudes y registros para su verificación.



**Caso de uso:** Asignación de métricas de comportamiento (USR-09)

* **Actor:** Administrador, Docente
* **Precondiciones:** El alumno cuenta con un reporte por falta o desempeño destacado.
* **Flujo principal:**
1. El administrador ubica la ficha del alumno o se encuentra en el registro de devoluciones.
2. Ajusta los indicadores para asignar los "chips" correspondientes (verde, amarillo o rojo) con el contador numérico (+/-).
3. El sistema consolida la información en el expediente del estudiante.


* **Postcondiciones:** La métrica disciplinaria queda asentada en la ficha individual.
* **Flujo alternativo:**
* **Condición:** El docente requiere consultar las métricas de un alumno.
* **Acciones:**
1. El docente coloca el puntero sobre la ficha del usuario.


* **Respuesta del sistema:** El sistema despliega una ventana informativa (tooltip) no editable con las etiquetas asociadas.



#### Subsistema 2: Préstamos de Equipamiento y Computadoras

##### Módulo 1: Catálogo y Búsqueda de Recursos

**Caso de uso:** Búsqueda y visualización de catálogo (PRE-01, PRE-02)

* **Actor:** Estudiante, Docente
* **Precondiciones:** El usuario ha autenticado su sesión en la plataforma.
* **Flujo principal:**
1. El usuario entra al catálogo interactivo de recursos.
2. Aplica los filtros por categoría y por Sede (Ushuaia / Río Grande) desde la barra de búsqueda.
3. Examina la especificación técnica, el número de Locker asignado, pautas de uso, material instructivo y el visor de disponibilidad.


* **Postcondiciones:** El usuario identifica el equipamiento requerido y verifica su disponibilidad.
* **Flujo alternativo:**
* **Condición:** No se encuentran resultados para la búsqueda realizada.
* **Acciones:**
1. El usuario ingresa un término de búsqueda inexistente o aplica filtros incompatibles.


* **Respuesta del sistema:** El sistema despliega un aviso indicando que no hay recursos disponibles para el criterio seleccionado.



##### Módulo 2: Solicitud y Reserva de Ítems

**Caso de uso:** Solicitud de equipamiento estándar (PRE-03, PRE-06, PRE-07, PRE-09, PRE-10)

* **Actor:** Estudiante, Docente
* **Precondiciones:** El usuario seleccionó la sede correspondiente e ingresó al catálogo.
* **Flujo principal:**
1. El usuario selecciona uno o varios ítems agregándolos a su lista de pedido mediante el carrito.
2. El sistema genera la solicitud unificada (Orden de Pedido).
3. Determina en el calendario la fecha y hora específica de retiro, y la fecha y hora específica de devolución (respetando el máximo de 4 días y la franja operativa).
4. Si el actor es Estudiante, completa obligatoriamente el selector condicional de asignatura (sin necesidad de indicar año o cuatrimestre). Si es Docente, emite el pedido para uso de cátedra.
5. Acepta la normativa vigente y efectúa el envío del trámite.


* **Postcondiciones:** La reserva queda registrada en estado "Pendiente" y se deriva directamente al Administrador.
* **Flujo alternativo:**
* **Condición:** Faltan datos obligatorios (PRE-04).
* **Acciones:**
1. El usuario intenta enviar el formulario incompleto.


* **Respuesta del sistema:** El sistema resalta los campos faltantes e impide el despacho del formulario.



**Caso de uso:** Solicitud de equipos de Alta Gama (PRE-05)

* **Actor:** Estudiante, Docente
* **Precondiciones:** El usuario requiere tramitar la reserva de un recurso especial.
* **Flujo principal:**
1. El usuario selecciona unidades clasificadas como "Alta Gama" (permitiendo combinarlas con recursos comunes en el carrito).
2. El sistema unifica estos elementos en la Orden de Pedido.
3. El usuario adjunta en forma obligatoria el archivo de validación en formato PDF.
4. Confirma y envía la solicitud.


* **Postcondiciones:** La petición se encamina de manera directa a la bandeja del Administrador.
* **Flujo alternativo:**
* **Condición:** El usuario no adjunta el comprobante de aprobación en formato PDF.
* **Acciones:**
1. El usuario intenta enviar la solicitud sin adjuntar el documento requerido.


* **Respuesta del sistema:** El sistema mantiene el botón de envío en estado deshabilitado (bloqueado) hasta que se cargue el PDF.



##### Módulo 3: Operaciones de Pañol y Control de Stock

**Caso de uso:** Validación administrativa y logística (PRE-15, PRE-18)

* **Actor:** Administrador
* **Precondiciones:** Existen peticiones registradas en estado "Pendiente".
* **Flujo principal:**
1. El administrador accede a la bandeja de validaciones, la cual filtra automáticamente los trámites pendientes según su jurisdicción (Sede local, o vista global para Superadministrador).
2. Revisa las solicitudes de estudiantes (incluyendo comentarios previos del docente si los hubiera) o solicitudes especiales.
3. Otorga la conformidad (estado "Aprobada") o rechaza el pedido del recurso (estado "Rechazada").


* **Postcondiciones:** La orden modifica su estado y se remite la notificación al solicitante.
* **Flujo alternativo:**
* **Condición:** El rango horario elegido provoca alta congestión en la entrega (PRE-18).
* **Acciones:**
1. Durante la revisión, el Administrador rectifica el horario programado para el retiro o la devolución.
2. Actualiza el registro al estado "Aprobada".


* **Respuesta del sistema:** El sistema guarda la nueva franja asignada para optimizar la operativa y notifica al usuario del cambio.



**Caso de uso:** Registro de entregas y devoluciones en mostrador (PRE-13, PRE-08)

* **Actor:** Administrador
* **Precondiciones:** Un usuario con solicitud en estado "Aprobada" acude al sector de entregas.
* **Flujo principal:**
1. El Administrador ubica el trámite y efectúa la entrega presencial del elemento.
2. El sistema actualiza el estado a "En Uso".
3. Cumplido el período, el usuario efectúa la restitución del bien y el Administrador asienta el reingreso, modificando el estado a "Disponible".
4. El Administrador consigna las anotaciones del estado del material y asigna los chips contables de comportamiento al alumno.


* **Postcondiciones:** Se da por concluido el circuito del préstamo y el historial queda actualizado.
* **Flujo alternativo 1:**
* **Condición:** El usuario no retira el equipamiento asignado en el tiempo estipulado (PRE-08).
* **Acciones:**
1. Se excede la ventana de tolerancia establecida desde la hora de retiro pactada.


* **Respuesta del sistema:** El sistema invalida la reserva automáticamente y restaura la disponibilidad del bien.


* **Flujo alternativo 2:**
* **Condición:** El usuario omite la devolución del equipo en el plazo fijado.
* **Acciones:**
1. El usuario no entrega el equipo en el plazo pactado.


* **Respuesta del sistema:** El sistema modifica el estado a "Demorado" y emite una alerta visual en rojo.



**Caso de uso:** Extensión de préstamos de portátiles (PRE-11)

* **Actor:** Administrador
* **Precondiciones:** Se tramita la prórroga en el plazo de devolución de un equipo informático.
* **Flujo principal:**
1. El usuario acude personalmente al sector de mostrador.
2. El Administrador accede a la herramienta de administración.
3. Ejecuta la modificación para extender el término límite de entrega.


* **Postcondiciones:** Se registra la nueva fecha límite de devolución en la plataforma.
* **Flujo alternativo:**
* **Condición:** El equipo posee una reserva previa asignada a otro usuario.
* **Acciones:**
1. El administrador solicita extender el período sobre un recurso reservado.


* **Respuesta del sistema:** El sistema rechaza la solicitud de extensión por solapamiento de reservas.



**Caso de uso:** Gestión de inventario y estado físico (PRE-12, PRE-14, PRE-17, PRE-19)

* **Actor:** Administrador
* **Precondiciones:** El perfil cuenta con facultades de administración de existencias.
* **Flujo principal:**
1. Selecciona la alternativa de alta para un nuevo equipamiento (PRE-19).
2. Si la cuenta es de un Administrador Local, el sistema asigna la Sede a la herramienta de forma automática y oculta el selector.
3. Si la cuenta es del Superadministrador, el sistema exige seleccionar obligatoriamente el destino (Ushuaia o Río Grande).
4. El sistema crea la entrada correspondiente dentro del registro, habilitando su visualización en el catálogo (PRE-12).


* **Postcondiciones:** El nuevo recurso queda incorporado con su ubicación correcta en el inventario del sistema.
* **Flujo alternativo:**
* **Condición:** Un elemento presenta desperfectos o averías (PRE-14).
* **Acciones:**
1. El Administrador modifica el estado a "En Mantenimiento".


* **Respuesta del sistema:** Ajusta las existencias lógicas e inhabilita la unidad para nuevas reservas.
* **Condición:** La inoperatividad genera un conflicto con compromisos futuros aprobados (PRE-17).
* **Acciones:**
1. El Administrador aplica la cancelación forzada asentando la justificación pertinente.


* **Respuesta del sistema:** El sistema anula el trámite e informa al usuario afectado mediante un aviso.



**Caso de uso:** Monitoreo en Calendario Maestro (PRE-16)

* **Actor:** Administrador
* **Precondiciones:** El Administrador requiere planificar la operativa diaria del área.
* **Flujo principal:**
1. Accede a la pantalla general de control.
2. Revisa la totalidad de bienes agrupados según su estado ("En Uso" y "En Reserva").


* **Postcondiciones:** El Administrador coordina los despachos y recepciones en el mostrador.
* **Flujo alternativo:**
* **Condición:** Se aplican filtros sin coincidencias en el calendario maestro.
* **Acciones:**
1. El Administrador filtra la vista por un estado o rango de fechas sin actividades.


* **Respuesta del sistema:** El sistema despliega el calendario sin eventos marcados para el período o estado seleccionado.



##### Módulo 4: Validación y Monitoreo Docente

**Caso de uso:** Monitoreo de solicitudes en curso (PRE-20)

* **Actor:** Docente
* **Precondiciones:** Un estudiante ha registrado una petición asociada a la asignatura del docente.
* **Flujo principal:**
1. El docente ingresa a su panel de supervisión específico.
2. Revisa el trámite emitido por el alumno en relación con su materia.
3. (Opcional) El docente ingresa un comentario u observación dirigida a la administración.


* **Postcondiciones:** El docente audita los trámites mediante atribuciones exclusivas de lectura y observación, sin aprobar ni rechazar la petición.
* **Flujo alternativo:**
* **Condición:** No hay solicitudes en curso registradas para la asignatura.
* **Acciones:**
1. El docente ingresa al panel de supervisión sin solicitudes asociadas.


* **Respuesta del sistema:** El sistema informa que no existen solicitudes registradas para la materia seleccionada.



#### Subsistema 3: Reserva de Espacios

##### Módulo 1: Gestión de Turnos de Isla de Edición y Aula-Estudio

**Caso de uso:** Reserva de bloques horarios (RES-01, RES-02)

* **Actor:** Estudiante, Docente
* **Precondiciones:** El usuario ha autenticado su sesión y seleccionó la sede correspondiente.
* **Flujo principal:**
1. El usuario entra al apartado de reserva de espacios.
2. El sistema despliega el calendario dinámico con los bloques horarios libres.
3. El usuario determina el tramo deseado y envía la petición.
4. El sistema registra el trámite en estado "Pendiente" sin bloquear el espacio para otros usuarios, permitiendo que ingresen múltiples peticiones para el mismo bloque.


* **Postcondiciones:** La orden de reserva queda asentada a la espera de la validación del administrador.
* **Flujo alternativo:**
* **Condición:** El bloque horario ya ha sido aprobado para otro usuario previamente.
* **Acciones:**
1. El usuario intenta seleccionar un bloque que figura en gris o rojo en la grilla.


* **Respuesta del sistema:** El sistema inhabilita la selección de la celda y bloquea el envío del formulario.



**Caso de uso:** Aprobación o Rechazo manual de espacios (RES-05)

* **Actor:** Administrador Local, Superadministrador
* **Precondiciones:** Existen peticiones de espacios registradas en estado "Pendiente".
* **Flujo principal:**
1. El administrador accede a su panel operativo y visualiza las solicitudes de espacios.
2. Revisa las peticiones concurrentes emitidas por diferentes usuarios para una misma franja horaria.
3. El administrador decide a quién otorgar la prioridad y aprueba la solicitud seleccionada de manera manual.
4. El sistema actualiza el estado de esa solicitud a "Aprobada" y marca el bloque horario como "Ocupado" en el calendario general.


* **Postcondiciones:** El turno queda adjudicado oficialmente a un único usuario.
* **Flujo alternativo:**
* **Condición:** Quedan peticiones "Pendientes" que solapan con la reserva recién aprobada.
* **Acciones:**
1. El administrador aprueba una solicitud para un bloque en disputa.


* **Respuesta del sistema:** El sistema rechaza automáticamente el resto de las solicitudes concurrentes para esa misma franja, cambia su estado a "Rechazada" y notifica la denegación a los usuarios afectados.



**Caso de uso:** Cancelación de reserva de espacios (RES-03)

* **Actor:** Estudiante, Docente
* **Precondiciones:** El usuario cuenta con una reserva de espacio vigente.
* **Flujo principal:**
1. El usuario accede al panel de peticiones o historial.
2. Marca la reserva asignada y procede a dar de baja la solicitud.
3. El sistema procesa la anulación del trámite.


* **Postcondiciones:** La reserva queda invalidada y el espacio restaura su disponibilidad de forma inmediata en el calendario general.

**Caso de uso:** Bloqueo administrativo de espacios (RES-04, GLO-02)

* **Actor:** Administrador
* **Precondiciones:** El administrador ha autenticado su sesión en el entorno de gestión.
* **Flujo principal:**
1. El administrador ingresa a la herramienta de control de calendario y disponibilidad.
2. Marca jornadas completas por feriados, paros o tareas de mantenimiento, o tramos específicos.
3. Aplica la restricción sobre las Islas de Edición.


* **Postcondiciones:** El sistema deshabilita las fechas indicadas impidiendo la emisión de nuevas peticiones en esos lapsos.

#### Subsistema 4: Novedades y Notificaciones

##### Módulo 1: Tablón Informativo y Comunicados

**Caso de uso:** Visualización del portal estático (NOV-01)

* **Actor:** Estudiante, Docente, Administrador
* **Precondiciones:** El usuario ingresa a la plataforma.
* **Flujo principal:**
1. El usuario accede al sector principal de la plataforma.
2. Consulta la información institucional, reglamentaciones y horarios operativos del laboratorio.


* **Postcondiciones:** El usuario toma conocimiento sobre las normativas vigentes.

**Caso de uso:** Gestión de novedades y comunicados (NOV-02)

* **Actor:** Administrador
* **Precondiciones:** El administrador ha autenticado su sesión en la herramienta de administración.
* **Flujo principal:**
1. El administrador entra a la sección de comunicados.
2. Completa el encabezado, el cuerpo del mensaje, opcionalmente adjunta un archivo gráfico, y define el alcance geográfico de la publicación (Sede local obligatoria, o Global si posee el nivel de Superadministrador).
3. Despacha la publicación general para avisos, talleres o cursos.
4. El sistema refresca el tablón general en forma inmediata para los usuarios de la sede o sedes seleccionadas.


* **Postcondiciones:** La novedad queda expuesta para los usuarios en la pantalla principal.
* **Flujo alternativo:**
* **Condición:** El administrador requiere modificar o remover una publicación antigua.
* **Acciones:**
1. Ubica el comunicado en el directorio y escoge modificar o dar de baja el registro.


* **Respuesta del sistema:** El sistema actualiza el portal asentando las modificaciones de manera instantánea.



##### Módulo 2: Centro de Notificaciones

**Caso de uso:** Emisión de alertas automáticas de devolución (NOV-03)

* **Actor:** Sistema
* **Precondiciones:** Existen préstamos de material en estado "En Uso".
* **Flujo principal:**
1. El sistema realiza verificaciones automáticas de las fechas de vencimiento.
2. Al verificar la proximidad de 24 horas para la restitución, confecciona un aviso automático.
3. El sistema transmite la alerta al perfil correspondiente.


* **Postcondiciones:** El usuario recibe el recordatorio con anterioridad al término fijado.
* **Flujo alternativo:**
* **Condición:** Transcurre la fecha límite sin asentarse la entrega del bien.
* **Respuesta del sistema:** El sistema modifica el registro a "Demorado", dispara un indicador visual en rojo dentro del mostrador para el administrador y remite una notificación por falta al solicitante.



**Caso de uso:** Notificaciones internas y avisos críticos (NOV-04)

* **Actor:** Sistema, Administrador
* **Precondiciones:** Ocurre una actualización en el estado del trámite o un ajuste por parte del administrador.
* **Flujo principal:**
1. El usuario nota un indicador en el ícono de la campana dentro de la interfaz.
2. Despliega el menú para verificar las variaciones en la situación de sus peticiones.


* **Postcondiciones:** El usuario realiza el seguimiento de sus trámites.
* **Flujo alternativo:**
* **Condición:** El administrador anula la solicitud por imprevistos o ajusta la franja programada al momento de validar.
* **Respuesta del sistema:** El sistema despacha un aviso de alta prioridad detallando la justificación o el nuevo horario fijado.



#### Subsistema 5: Configuración Global y Entorno

##### Módulo 1: Filtros Operativos y Geográficos

**Caso de uso:** Selección de sede, filtrado geográfico y administración global (GLO-01)

* **Actor:** Estudiante, Docente, Administrador
* **Precondiciones:** El usuario ha autenticado su sesión en la plataforma.
* **Flujo principal:**
1. El sistema lee las atribuciones y el alcance geográfico asociado a la cuenta del usuario.
2. Si el actor es Estudiante, Docente o Administrador Local, el sistema procesa la restricción en forma automática fijando su entorno a su sede de origen (Ushuaia o Río Grande).
3. El sistema oculta toda información, peticiones e inventario de la sede ajena, impidiendo la interacción cruzada.
4. Si el actor es Superadministrador, el sistema despliega un selector global en el panel superior con las opciones "Ushuaia", "Río Grande" o "Ambas sedes".
5. El Superadministrador define la vista deseada para operar.


* **Postcondiciones:** Las bandejas de validación de préstamos, el directorio de usuarios, el calendario y los catálogos despliegan únicamente la información y los permisos correspondientes a la ubicación habilitada o escogida.
* **Flujo alternativo:**
* **Condición:** El Superadministrador requiere auditar las solicitudes o stock general de todo el laboratorio.
* **Acciones:**
1. El Superadministrador selecciona la opción "Ambas sedes" en el selector global.


* **Respuesta del sistema:** El sistema consolida y unifica las vistas operativas mostrando los recursos y trámites pendientes tanto de Ushuaia como de Río Grande en una misma pantalla.



##### Módulo 2: Panel de Control del Administrador

**Caso de uso:** Configuración mediante panel de parámetros (GLO-03, GLO-04)

* **Actor:** Administrador
* **Precondiciones:** El administrador posee privilegios activos en el entorno.
* **Flujo principal:**
1. El administrador entra al área de parámetros del sistema.
2. Altera las variables de funcionamiento (tiempos de tolerancia, ventanas de anticipación) o inactiva fechas específicas ante eventos de fuerza mayor.
3. Confirma y aplica los cambios.


* **Postcondiciones:** La lógica de la plataforma se actualiza de forma dinámica sin requerir ajustes en la estructura.
* **Flujo alternativo:**
* **Condición:** La contingencia finaliza y se restablece el servicio.
* **Acciones:**
1. El administrador accede al panel de control y remueve el bloqueo de los días afectados.





**Caso de uso:** Gestión de anotaciones privadas e internas (GLO-05)

* **Actor:** Administrador
* **Precondiciones:** El administrador se encuentra operando en su panel central.
* **Flujo principal:**
1. El administrador selecciona la alternativa para ingresar una nota interna.
2. Establece un título, redacta el contenido y asigna los identificadores (Tags).
3. Define el carácter de la nota como personal o de acceso público para el equipo mediante etiquetas institucionales.
4. Asienta el registro.


* **Postcondiciones:** La nota queda registrada y visible para el personal autorizado según el tag vinculado.

##### Módulo 3: Preferencias de Interfaz

**Caso de uso:** Personalización de interfaz y accesibilidad (GLO-06)

* **Actor:** Estudiante, Docente, Administrador
* **Precondiciones:** El usuario ha autenticado su sesión en la plataforma.
* **Flujo principal:**
1. El usuario interactúa con los ajustes de navegación visual de la pantalla.
2. Modifica la apariencia entre modo claro u oscuro, o contrae la barra lateral según su preferencia.


* **Postcondiciones:** La apariencia del entorno se ajusta a las preferencias seleccionadas por el usuario.

#### Subsistema 6: Integración de IA (límite de alcance)

##### Módulo 1: Interfaz y Consultas en Lenguaje Natural

**Caso de uso:** Interacción con el asistente virtual (IA-01, IA-02, IA-03)

* **Actor:** Estudiante, Docente
* **Precondiciones:** El usuario ha autenticado su sesión en el entorno.
* **Flujo principal:**
1. El usuario selecciona la opción de acceso directo para desplegar la ventana del asistente virtual.
2. Realiza una consulta mediante lenguaje coloquial consultando disponibilidades de recursos o salas.
3. El sistema procesa la consulta mediante lecturas de la base de datos y responde la inquietud planteada.
4. Si el usuario decide avanzar, solicita al asistente proseguir con la reserva.
5. El chatbot toma de forma automática la información del perfil (ID, Rol, Sede) y tramita la solicitud, asentándose en estado "Pendiente".


* **Postcondiciones:** La orden asistida queda asentada correctamente en la plataforma.
* **Flujo alternativo:**
* **Condición:** El bien solicitado no cuenta con unidades disponibles para el período fijado.
* **Acciones:**
1. El chatbot identifica la falta de stock en los registros, informa la situación al usuario y sugiere opciones o fechas alternativas.





> **Figura 1.** Diagrama de casos de uso del sistema PrestaMeDios.
> Para el Diagrama de Casos de Uso nos abstraemos de los casos de uso secundarios, solo mostramos la funcionalidad del sistema a través de los casos de uso principales o más significativos. Omitimos la diferenciación entre Superadministradores y Administradores Locales, agrupándolos en Administradores.

---

## DISEÑO

### Diagrama Entidad-Relación (DER)

A partir del análisis de los casos de uso, se procedió a modelar la persistencia de datos relacional para el sistema PrestaMeDios.

> **Figura 2.** Diagrama Entidad-Relación del sistema PrestaMeDios.
> **Link:** DER-PrestaMeDios

### Principales Pantallas de la Aplicación

Como parte de la documentación técnica de la etapa de diseño, se elaboraron los prototipos de interfaz de usuario en Figma para los flujos operativos centrales del sistema. A continuación se detallan las vistas representativas correspondientes a los tres roles clave de la plataforma:

#### Rol Estudiante: Formulario de Solicitud de Recursos (Orden de Préstamo)

Esta pantalla materializa el requerimiento de solicitud unificada (PRE-03), desplegándose tanto para pedidos de ítems individuales como para aquellos consolidados a través del carrito de recursos.

**Componentes de la interfaz:**

* **Resumen de recursos:** Lista interactiva que detalla los equipos técnicos o computadoras agregadas al pedido, junto con su categoría y locker asignado.
* **Selectores temporales restringidos:** Controles de fecha y hora para el retiro y la devolución acotados a la franja operativa del laboratorio (PRE-06), aplicando de forma estricta la restricción de permanencia máxima de cuatro (4) días corridos para estudiantes (PRE-07).
* **Encuadre académico:** Selector obligatorio de la asignatura curricular que motiva la petición, requisito indispensable para el posterior seguimiento docente (PRE-03).
* **Adjunto condicional (Alta Gama):** Sección para la carga de comprobantes en formato PDF, habilitada y exigida en caso de incorporar equipos clasificados como de Alta Gama (PRE-05).
* **Controles de validación:** Casilla de verificación para la aceptación de Términos y Condiciones, complementada con alertas visuales en rojo que bloquean el envío en caso de existir campos obligatorios vacíos (PRE-04).

> **Figura 3 y 4.** Interfaz de formulario unificado para la solicitud de préstamos (Rol Estudiante).

#### Rol Docente: Panel de Supervisión y Observación de Solicitudes

Refleja la vista exclusiva de supervisión para el docente a cargo (PRE-20). A diferencia del perfil de estudiante, este panel segrega la información para exhibir las peticiones tramitadas por alumnos matriculados específicamente en su asignatura.

**Componentes de la interfaz:**

* **Atribuciones de solo lectura:** La interfaz no cuenta con botones de aprobación o rechazo definitivo, respondiendo a la regla de negocio acordada donde la confirmación del préstamo compete exclusivamente a la administración del laboratorio.
* **Módulo de observaciones a la administración:** Campo de texto interactivo donde el docente puede ingresar comentarios, avales académicos o advertencias pedagógicas sobre la pertinencia del pedido.
* **Trazabilidad de comentarios:** Las observaciones registradas quedan asociadas a la orden de pedido y son visibles en tiempo real para el personal del pañol al momento de evaluar el trámite (PRE-15, PRE-20).

> **Figura 5.** Vista de monitoreo y carga de observaciones sobre solicitudes de cursada (Rol Docente).
> **Figura 6.** Formulario de carga de observaciones sobre solicitudes de cursada (Rol Docente).

#### Rol Administrador: Bandeja Centralizada y Listado de Órdenes

Constituye el panel operativo central para el personal del laboratorio y superadministradores (PRE-15), permitiendo auditar y gestionar el universo de trámites del sistema.

**Componentes de la interfaz:**

* **Filtros por tipo de orden:** Pestañas superiores y selectores para segmentar las solicitudes de manera rápida entre "Estudiantes", "Docentes" y "Especiales".
* **Grilla de datos:** Columnas ordenables que exponen el número de orden, usuario solicitante, fecha y hora prevista de retiro/devolución, asignatura y el registro de comentarios docentes adjuntos.
* **Acciones de resolución logística:** Botones para aprobar o rechazar manualmente la orden (PRE-10).

> **Figura 7.** Bandeja centralizada de solicitudes operativas (Rol Administrador).

### Arquitectura del Sistema

Se implementará una Arquitectura Intermedia (Monolito Modular por Dominio / API-First). A diferencia de una arquitectura por capas tradicionales que genera cuellos de botella en equipos de 5 personas, la estructura Feature-First aislará el código verticalmente en dominios de negocio específicos: users, inventory, loans, spaces y assistant. Esto permitirá integración sin fricción para la futura incorporación del Agente MCP de Inteligencia Artificial podrá consumir los esquemas OpenAPI de manera nativa sin acoplarse a la interfaz visual.

**Justificación técnica de la infraestructura:**

* **Capa de Presentación (Frontend):** Representa la aplicación de interfaz visual desarrollada con la biblioteca React y tipado estricto mediante TypeScript. Al estar totalmente desacoplada del servidor (enfoque API-First), esta capa se encarga exclusivamente del renderizado (formularios, calendarios interactivos) y puede alojarse en plataformas optimizadas para contenido estático.
* **Capa de Aplicación (Backend):** Constituye el núcleo central del sistema, operando bajo un servidor asincrónico construido con Python y FastAPI. Su arquitectura interna organiza el código verticalmente por dominios del negocio (usuarios, inventario, préstamos y espacios) para permitir el desarrollo en paralelo de los 5 integrantes del equipo. Este nodo expone automáticamente las reglas de negocio hacia el exterior mediante documentación estandarizada OpenAPI/Swagger.
* **Capa de Persistencia (Base de Datos):** El motor relacional PostgreSQL se sitúa en una capa aislada. Su función es fundamental no solo para el almacenamiento persistente, sino para garantizar la integridad transaccional (ACID): se encarga de abortar las peticiones concurrentes y evitar los solapamientos temporales sobre un mismo recurso físico mediante restricciones de exclusión.
* **Integración Externa (Agente MCP - Subsistema 6):** El chatbot con inteligencia artificial se despliega como un servicio o cliente independiente. Para preservar la seguridad del sistema y no eludir las validaciones de negocio (como el límite de préstamos de 4 o 15 días), el Agente MCP no se conecta a PostgreSQL de forma directa. En su lugar, lee los contratos OpenAPI expuestos por FastAPI y ejecuta las reservas mediante peticiones REST, exactamente de la misma manera que lo hace el cliente web de React.

En el módulo `spaces`, las reservas pendientes no ocupan el espacio hasta ser aprobadas; las aprobadas y las que están en uso no pueden solaparse. Las transiciones válidas son `Pendiente` → `Aprobada`/`Rechazada`/`Cancelada`, `Aprobada` → `En_Uso`/`Cancelada` y `En_Uso` → `Finalizada`. Los bloqueos pueden cubrir días completos o una franja diaria con ambas horas entre las 09:00 y las 16:00. La consulta de disponibilidad devuelve los intervalos libres por espacio, calculados restando las reservas activas y los bloqueos al horario operativo; las escrituras incompatibles responden con HTTP 409.

> **Figura 8.** Borrador de Diagrama de Infraestructura de PrestaMeDios
> **Link v1:** Diagrama de Infraestructura v1

---

## SOBRE LAS ITERACIONES

Un capítulo donde se reflexione sobre los cambios que haya sufrido el proyecto, por ejemplo en sus iteraciones, pero también es de interés analizar el error en las estimaciones de tiempo y todo lo que haga a la evolución del proceso de desarrollo.

### Iteración 1

Primera entrevista con Natalia Ader (cliente) 27/08/2026: conversamos para sacarnos dudas principales de los requerimientos. Conocimos el Laboratorio de Medios. Conversamos acerca de las falencias del procedimientos y le mostramos un diseño aproximado de lo que podríamos ofrecerle como solución, de ahí surgieron nuevas necesidades y ampliaciones del proyecto, como la gestión de inventario en los lockers, la restricción que nuestro sistema sólo funcionará para reservas en horarios habilitados (09hs -16hs), nos comentó sobre la implementación futura de la isla de Digitalización.

### Iteración 2

Segunda entrevista con Natalia Ader 04/09/2026: Entrevista con preguntas puntuales de cuestiones claves par el funcionamiento de la app, por ejemplo, pensábamos que en las aprobaciones participaban Docentes en primera instancia y luego los Admins, pero resultó que no es así, el proceso de aprobación fue reestructurado a que el estudiante solicita directamente al Admin (Natalia encargada de ambas sedes, Victoria en Ushuaia o Facundo en Rio Grande, que son los no-docentes encargados del Laboratorio de Medios Audiovisuales). Otra cosa que se modificó fue que se eliminó el usuario admin ICSE, y que no deberán ingresar a la plataforma, sino que ellos aprueban los préstamos mediante resoluciones del CICSE.

### Iteración 3

18/09/2026 - 21/09/2026: Natalia solicitó una diferenciación estricta en los permisos, ya que ella es la única persona que requiere acceso y visibilidad total sobre los laboratorios de Ushuaia y Río Grande. En contraste, los administradores locales (Victoria en Ushuaia y Facundo en Río Grande) únicamente deben visualizar y gestionar las operaciones de sus respectivas locaciones para evitar la interacción cruzada con información ajena.

A raíz de este planteo, se agregó el concepto del rol de "Superadministrador". Este perfil exclusivo cuenta con privilegios globales para visualizar, filtrar e intervenir en las bandejas de validación, los inventarios y los calendarios de ambas sedes, pudiendo operar de forma individual o combinada. Esta decisión modificó la estructura de los requerimientos globales (GLO-01), definiendo una jerarquía clara al momento de crear cuentas de administrador e impactando en el diseño de las vistas para separar la administración local de la global.

### Iteración 4

Durante esta etapa, el enfoque principal del equipo transitó desde el relevamiento hacia el modelado de datos y la estructuración técnica y visual del sistema. A partir del análisis de los casos de uso, se elaboró el Diagrama Entidad-Relación (DER) para definir la persistencia relacional, modelando las entidades del negocio y garantizando la base para la integridad transaccional. En paralelo, se diseñaron los prototipos de interfaz de usuario en Figma para las principales pantallas, abarcando los flujos operativos de los tres roles clave: el rol Estudiante (con el formulario unificado de reservas), el rol Docente (con el panel exclusivo de supervisión y carga de observaciones) y el rol Administrador (con la bandeja centralizada de validaciones y gestión logística).

En cuanto a las decisiones técnicas y de diseño, se estableció la adopción de una Arquitectura Intermedia (Monolito Modular por Dominio / API-First) apalancada en Python con FastAPI y PostgreSQL.

De cara al desarrollo definimos cómo nos dividiremos las tareas.

---

## SOBRE LOS ENTREGABLES

*[Esta sección es requerida para aprobar la materia, no para la regularidad]*

### Aplicaciones y plataformas que forman al sistema

### Requerimientos técnicos para la instalación

Descripción técnica de los requerimientos y pasos necesarios para la instalación del software desarrollado.

Copia del software desarrollado al menos en un 80% de su funcionalidad, según los requerimientos definidos para dicho trabajo.

---

## PRESENTACIÓN VISUAL PARA APROBAR FINAL

*[Esta sección es requerida para aprobar la materia, no para la regularidad]*