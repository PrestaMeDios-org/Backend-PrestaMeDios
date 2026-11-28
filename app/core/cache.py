"""Respuestas de la API sin caché (SPEC-12 §4.1, RN-90).

Sin ``Cache-Control``, el navegador guarda las respuestas atadas sólo a la URL, sin
distinguir el token, y al restaurar una pestaña duplicada prefiere la caché: una pestaña
podía recibir el ``/auth/me`` de otro usuario y mostrar su vista y sus datos (P6).
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

PREFIJO_API = "/api/"
_CACHE_CONTROL = b"cache-control"
_NO_STORE = b"no-store"


class SinCacheMiddleware:
    """Agrega ``Cache-Control: no-store`` a toda respuesta de ``/api/`` (RN-90).

    Middleware ASGI puro: sólo toca el inicio de la respuesta, sin leer ni copiar el
    cuerpo. Respeta el ``Cache-Control`` que ya haya fijado el endpoint (la descarga de
    archivos usa ``private, no-store``). Registrado con ``add_middleware``, queda por
    fuera de los manejadores de excepciones: también cubre las respuestas de error.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(PREFIJO_API):
            await self.app(scope, receive, send)
            return

        async def enviar(mensaje: Message) -> None:
            if mensaje["type"] == "http.response.start":
                encabezados = list(mensaje.get("headers", []))
                if not any(nombre.lower() == _CACHE_CONTROL for nombre, _ in encabezados):
                    encabezados.append((_CACHE_CONTROL, _NO_STORE))
                    mensaje = {**mensaje, "headers": encabezados}
            await send(mensaje)

        await self.app(scope, receive, enviar)
