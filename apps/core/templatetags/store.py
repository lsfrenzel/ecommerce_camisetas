from urllib.parse import urlencode

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.core.utils import format_brl

register = template.Library()

_ICONS = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "bag": '<path d="M5 8h14l-1 12H6L5 8Z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "menu": '<path d="M3 7h18M3 12h18M3 17h12"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z"/>',
    "arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "arrow-up-right": '<path d="M7 17 17 7M8 7h9v9"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "check": '<path d="m5 12 5 5L20 7"/>',
    "truck": '<path d="M3 6h11v10H3zM14 10h4l3 3v3h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
    "whatsapp": '<path d="M20 12a8 8 0 0 1-11.8 7L4 20l1.1-4A8 8 0 1 1 20 12Z"/><path d="M9 9.5c0 3 2.5 5.5 5.5 5.5l1-1.5-2-1-1 .8a4 4 0 0 1-2.3-2.3l.8-1-1-2L9 9.5Z"/>',
    "instagram": '<rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r=".8" fill="currentColor"/>',
    "tiktok": '<path d="M14 3v11a3.5 3.5 0 1 1-3.5-3.5"/><path d="M14 3c.5 2.5 2.5 4.5 5 4.5"/>',
    "youtube": '<rect x="2.5" y="5.5" width="19" height="13" rx="3"/><path d="m10 9 5 3-5 3V9Z"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "lock": '<rect x="5" y="11" width="14" height="10"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "zoom": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M11 8v6M8 11h6"/>',
    "ruler": '<path d="M3 17 17 3l4 4L7 21l-4-4Z"/><path d="m7 13 2 2M10 10l2 2M13 7l2 2"/>',
    "chart": '<path d="M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-3"/>',
    "box": '<path d="m3 7 9-4 9 4-9 4-9-4Z"/><path d="M3 7v10l9 4 9-4V7M12 11v10"/>',
    "tag": '<path d="M3 12V3h9l9 9-9 9-9-9Z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6"/>',
    "file": '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7 7 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2L10 21h4l.5-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z"/>',
    "brush": '<path d="M14 4 20 10 11 19H5v-6l9-9Z"/><path d="m12 6 6 6"/>',
    "home": '<path d="M3 11 12 4l9 7v9h-6v-6H9v6H3z"/>',
    "shield": '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3Z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>',
    "heart": '<path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.5-7 10-7 10Z"/>',
    "logout": '<path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10"/>',
    "alert": '<path d="M12 3 2 20h20L12 3Z"/><path d="M12 10v4M12 17v.5"/>',
}


@register.simple_tag
def icon(name, size=20, cls="", stroke=1.8, label=""):
    body = _ICONS.get(name, "")
    aria = f'role="img" aria-label="{label}"' if label else 'aria-hidden="true"'
    return mark_safe(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="{stroke}" stroke-linecap="square" stroke-linejoin="miter" '
        f'class="{cls}" {aria} focusable="false">{body}</svg>'
    )


@register.filter
def brl(value):
    if value is None or value == "":
        return ""
    return format_brl(value)


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Gera querystring preservando filtros atuais: {% qs page=2 %}"""
    request = context["request"]
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    if "page" not in kwargs:
        params.pop("page", None)
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag(takes_context=True)
def qs_toggle(context, key, value):
    """Alterna um valor em um parâmetro multi-valor (filtros)."""
    request = context["request"]
    params = request.GET.copy()
    values = params.getlist(key)
    value = str(value)
    if value in values:
        values.remove(value)
    else:
        values.append(value)
    params.setlist(key, values)
    params.pop("page", None)
    return "?" + params.urlencode()


@register.filter
def in_list(value, values):
    return str(value) in [str(v) for v in values]


@register.simple_tag
def status_badge(status, label=""):
    tone = {
        "awaiting_payment": "warn", "pending": "warn", "in_process": "warn", "submitted": "warn",
        "in_review": "info", "paid": "success", "approved": "success", "delivered": "success",
        "customizing": "info", "in_production": "info", "ready_to_ship": "info", "shipped": "info",
        "cancelled": "danger", "rejected": "danger", "refunded": "neutral", "charged_back": "danger",
        "ordered": "success", "in_cart": "info", "posted": "info", "in_transit": "info",
        "out_for_delivery": "info", "ready_for_pickup": "info", "returned": "danger", "open": "warn",
        "answered": "success", "closed": "neutral", "done": "success", "denied": "neutral",
    }.get(str(status), "neutral")
    return format_html('<span class="badge badge-{}">{}</span>', tone, label or status)


@register.filter
def split_paragraphs(text):
    """Converte texto simples em parágrafos/subtítulos seguros (escapados)."""
    from django.utils.html import escape

    html = []
    for block in str(text or "").replace("\r\n", "\n").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("## "):
            html.append(f"<h2>{escape(block[3:])}</h2>")
        else:
            html.append("<p>" + escape(block).replace("\n", "<br>") + "</p>")
    return mark_safe("".join(html))


@register.filter
def urlencode_dict(d):
    return urlencode(d)


@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None
