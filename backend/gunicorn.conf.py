"""How the web process runs outside development (`CMD` in the Dockerfile).

Several worker processes, each with a few threads, sized with env vars; nginx in
front buffers slow clients (docs/architecture.md §13). Load-tested in docs/simbot.md.
"""

import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
workers = int(os.environ.get("WEB_CONCURRENCY", "3"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))  # uploads and large exports
max_requests = 2000  # recycle workers now and then; jitter avoids a synchronized restart
max_requests_jitter = 200
accesslog = "-"
# Include how long each request took (µs), to tell a slow handler from a slow queue.
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sus'
