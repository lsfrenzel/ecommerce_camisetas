"""Registro de auditoria de ações administrativas."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .models import AuditLog


def _client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def log_action(*, actor=None, action: str, obj=None, object_type: str = "", object_id: str = "",
               changes: dict | None = None, message: str = "", request=None) -> AuditLog:
    if obj is not None:
        object_type = object_type or obj._meta.label
        object_id = object_id or str(obj.pk)
        object_repr = str(obj)[:255]
    else:
        object_repr = ""
    if actor is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
        actor = request.user
    return AuditLog.objects.create(
        actor=actor if (actor and getattr(actor, "pk", None)) else None,
        action=action,
        object_type=object_type,
        object_id=object_id,
        object_repr=object_repr,
        changes=_jsonable(changes or {}),
        message=message[:255],
        ip_address=_client_ip(request),
    )


def diff_instance(old: dict, new: dict) -> dict:
    """Retorna somente os campos alterados: {campo: [antes, depois]}."""
    return {k: [old.get(k), new.get(k)] for k in new if old.get(k) != new.get(k)}
