"""
Configurações do projeto.

Toda configuração sensível ou dependente de ambiente vem de variáveis de ambiente.
Veja `.env.example` e `README.md`.
"""

from __future__ import annotations

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Carrega um `.env` simples (KEY=VALUE) sem sobrescrever variáveis já definidas."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


DEBUG = env_bool("DJANGO_DEBUG", False)
TESTING = env_bool("DJANGO_TESTING", False)
# Etapa de build (collectstatic no Docker): não há banco nem segredos disponíveis.
BUILDING = env_bool("DJANGO_BUILD", False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or TESTING or BUILDING:
        SECRET_KEY = "dev-only-insecure-key-never-use-in-production"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY é obrigatória quando DJANGO_DEBUG=False."
        )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
# Railway injeta o domínio público nesta variável.
if env("RAILWAY_PUBLIC_DOMAIN"):
    ALLOWED_HOSTS.append(env("RAILWAY_PUBLIC_DOMAIN"))
# Health check interno do Railway.
ALLOWED_HOSTS.append("healthcheck.railway.app")

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
if env("RAILWAY_PUBLIC_DOMAIN"):
    CSRF_TRUSTED_ORIGINS.append(f"https://{env('RAILWAY_PUBLIC_DOMAIN')}")

SITE_URL = env("SITE_URL", "http://localhost:8000").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django.contrib.humanize",
    "storages",
    # Apps do projeto
    "apps.core",
    "apps.accounts",
    "apps.content",
    "apps.catalog",
    "apps.inventory",
    "apps.promotions",
    "apps.shipping",
    "apps.cart",
    "apps.orders",
    "apps.payments",
    "apps.personalization",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.store",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Banco de dados — PostgreSQL via DATABASE_URL (ou variáveis PG* do Railway).
# ---------------------------------------------------------------------------
DATABASE_URL = env("DATABASE_URL")
if not DATABASE_URL and env("PGHOST"):
    DATABASE_URL = (
        f"postgres://{env('PGUSER')}:{env('PGPASSWORD')}@{env('PGHOST')}:"
        f"{env('PGPORT', '5432')}/{env('PGDATABASE')}"
    )

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=env_int("DB_CONN_MAX_AGE", 60),
            conn_health_checks=True,
        )
    }
elif DEBUG or TESTING or BUILDING:
    # Apenas para desenvolvimento rápido sem PostgreSQL. Produção exige PostgreSQL.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured("DATABASE_URL (PostgreSQL) é obrigatória em produção.")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
LOGOUT_REDIRECT_URL = "core:home"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Arquivos estáticos e mídia
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
PRIVATE_MEDIA_ROOT = BASE_DIR / "private_media"
# Sem S3 em produção, só sirva mídia do disco se houver um Railway Volume montado em MEDIA_ROOT.
SERVE_MEDIA_FROM_DISK = env_bool("SERVE_MEDIA_FROM_DISK", False)
if env("MEDIA_ROOT"):
    MEDIA_ROOT = Path(env("MEDIA_ROOT"))
    PRIVATE_MEDIA_ROOT = MEDIA_ROOT.parent / "private_media"


S3_BUCKET_NAME = env("S3_BUCKET_NAME")
USE_S3 = bool(S3_BUCKET_NAME)

if USE_S3:
    _s3_common = {
        "bucket_name": S3_BUCKET_NAME,
        "endpoint_url": env("S3_ENDPOINT_URL") or None,
        "access_key": env("S3_ACCESS_KEY_ID"),
        "secret_key": env("S3_SECRET_ACCESS_KEY"),
        "region_name": env("S3_REGION") or None,
        "signature_version": "s3v4",
        "addressing_style": env("S3_ADDRESSING_STYLE", "virtual"),
        "file_overwrite": False,
    }
    _public_media_signed = env_bool("S3_PUBLIC_MEDIA_SIGNED", True)
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **_s3_common,
                "location": "media",
                # Railway Buckets são privados: por padrão usamos URLs assinadas de longa duração.
                "querystring_auth": _public_media_signed,
                "querystring_expire": env_int("S3_PUBLIC_URL_EXPIRE", 60 * 60 * 24 * 6),
                "custom_domain": env("S3_CUSTOM_DOMAIN") or None,
                "object_parameters": {"CacheControl": "public, max-age=31536000, immutable"},
            },
        },
        "private": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **_s3_common,
                "location": "private",
                "default_acl": "private",
                "querystring_auth": True,
                "querystring_expire": 300,
                "custom_domain": None,
            },
        },
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(PRIVATE_MEDIA_ROOT), "base_url": "/arquivo-privado-indisponivel/"},
        },
        "staticfiles": {
            "BACKEND": (
                "django.contrib.staticfiles.storage.StaticFilesStorage"
                if (DEBUG or TESTING)
                else "whitenoise.storage.CompressedManifestStaticFilesStorage"
            )
        },
    }

FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
PERSONALIZATION_MAX_UPLOAD_MB = env_int("PERSONALIZATION_MAX_UPLOAD_MB", 10)
PRODUCT_IMAGE_MAX_UPLOAD_MB = env_int("PRODUCT_IMAGE_MAX_UPLOAD_MB", 12)

# ---------------------------------------------------------------------------
# Cache — Redis opcional; LocMem por padrão.
# ---------------------------------------------------------------------------
if env("REDIS_URL"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": env("REDIS_URL")}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "store"}}

# ---------------------------------------------------------------------------
# Segurança
# ---------------------------------------------------------------------------
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

if not DEBUG and not TESTING:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_REDIRECT_EXEMPT = [r"^healthz/?$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", 60 * 60 * 24 * 30)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_HSTS_PRELOAD = False

LOGIN_RATE_LIMIT_ATTEMPTS = env_int("LOGIN_RATE_LIMIT_ATTEMPTS", 5)
LOGIN_RATE_LIMIT_WINDOW = env_int("LOGIN_RATE_LIMIT_WINDOW", 15 * 60)

# ---------------------------------------------------------------------------
# E-mail
# ---------------------------------------------------------------------------
if env("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("EMAIL_HOST")
    EMAIL_PORT = env_int("EMAIL_PORT", 587)
    EMAIL_HOST_USER = env("EMAIL_HOST_USER")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
    EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
    EMAIL_TIMEOUT = 15
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "loja@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# ---------------------------------------------------------------------------
# Loja / integrações
# ---------------------------------------------------------------------------
STORE_NAME = env("STORE_NAME", "NOME DA MARCA")
STORE_ORIGIN_ZIPCODE = env("STORE_ORIGIN_ZIPCODE")
STORE_WHATSAPP = env("STORE_WHATSAPP")
STORE_INSTAGRAM = env("STORE_INSTAGRAM")

MERCADOPAGO_ACCESS_TOKEN = env("MERCADOPAGO_ACCESS_TOKEN")
MERCADOPAGO_PUBLIC_KEY = env("MERCADOPAGO_PUBLIC_KEY")
MERCADOPAGO_WEBHOOK_SECRET = env("MERCADOPAGO_WEBHOOK_SECRET")
MERCADOPAGO_ENVIRONMENT = env("MERCADOPAGO_ENVIRONMENT", "sandbox").lower()
MERCADOPAGO_MAX_INSTALLMENTS = env_int("MERCADOPAGO_MAX_INSTALLMENTS", 6)
# Permite criar pedidos (aguardando pagamento) sem gateway configurado.
# Útil apenas em desenvolvimento: o pedido NUNCA é marcado como pago automaticamente.
ALLOW_ORDERS_WITHOUT_GATEWAY = env_bool("ALLOW_ORDERS_WITHOUT_GATEWAY", False)

MELHORENVIO_TOKEN = env("MELHORENVIO_TOKEN")
MELHORENVIO_ENVIRONMENT = env("MELHORENVIO_ENVIRONMENT", "sandbox").lower()
MELHORENVIO_USER_AGENT = env("MELHORENVIO_USER_AGENT", "Loja Streetwear (contato@exemplo.com)")

STOCK_RESERVATION_MINUTES = env_int("STOCK_RESERVATION_MINUTES", 60)

# ---------------------------------------------------------------------------
# Logs estruturados (JSON em produção)
# ---------------------------------------------------------------------------
LOG_LEVEL = env("LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact": {"()": "apps.core.logging.RedactSensitiveFilter"}},
    "formatters": {
        "json": {"()": "apps.core.logging.JsonFormatter"},
        "plain": {"format": "%(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain" if DEBUG else "json",
            "filters": ["redact"],
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.db.backends": {"level": "WARNING"},
    },
}

if TESTING:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    LOGGING["root"]["level"] = "CRITICAL"
    LOGGING["loggers"]["django"]["level"] = "CRITICAL"
