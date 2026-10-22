from .base import *  # noqa: F401,F403

DEBUG = True
ALLOW_ATTEMPT_RESET = True
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# The SPA runs on Vite's own dev server (default :5173), proxying /api
# requests through to this Django server (see frontend/vite.config.ts) so
# the browser only ever talks to one origin — no CORS needed. Django's CSRF
# middleware still checks the Origin header of the *original* request the
# proxy forwards, though, which names the Vite origin, not this one.
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
