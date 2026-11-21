"""/healthz: is the app up and can it reach its database? For Docker, nginx or an uptime
monitor. Says nothing about users or data, so it needs no sign-in.

It runs as the first middleware, before the host check and the HTTPS redirect, so a probe
from inside the server (Host: localhost, plain http) gets a real answer."""

from django.db import connection
from django.http import JsonResponse


def healthz(request=None):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:  # noqa: BLE001 — any failure here means "not healthy"
        return JsonResponse({"ok": False, "database": "unreachable"}, status=503)
    return JsonResponse({"ok": True})


class HealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info in ("/healthz", "/healthz/") and request.method in ("GET", "HEAD"):
            return healthz(request)
        return self.get_response(request)
