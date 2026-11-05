#!/bin/sh
# Inicialização do container em produção (Railway).
# 1) Aplica migrações pendentes (idempotente) e atualiza os papéis da equipe.
# 2) Sobe o Gunicorn. Se a migração falhar, o container não sobe e o deploy anterior continua no ar.
set -e

echo "[start] Aplicando migrações do banco..."
python manage.py migrate --noinput

echo "[start] Atualizando papéis da equipe..."
python manage.py setup_roles

echo "[start] Iniciando Gunicorn..."
exec gunicorn config.wsgi:application -c gunicorn.conf.py
