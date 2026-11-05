"""Configuração do Gunicorn (Railway injeta PORT)."""
import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", max(2, min(4, multiprocessing.cpu_count() * 2))))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
forwarded_allow_ips = "*"
access_log_format = '{"ts":"%(t)s","method":"%(m)s","path":"%(U)s","status":%(s)s,"bytes":%(B)s,"ms":%(M)s,"ip":"%({x-forwarded-for}i)s"}'
