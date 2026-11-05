"""Limitação simples de requisições baseada em cache (por IP + escopo)."""

from django.core.cache import cache


def client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def rate_limited(request, scope: str, *, limit: int, window: int, key: str | None = None) -> bool:
    """Incrementa o contador e retorna True se o limite foi excedido."""
    cache_key = f"rl:{scope}:{key or client_ip(request)}"
    added = cache.add(cache_key, 1, window)
    if added:
        return False
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, window)
        return False
    return count > limit


def reset(request, scope: str, key: str | None = None):
    cache.delete(f"rl:{scope}:{key or client_ip(request)}")


def is_blocked(request, scope: str, *, limit: int, key: str | None = None) -> bool:
    value = cache.get(f"rl:{scope}:{key or client_ip(request)}") or 0
    return value >= limit
