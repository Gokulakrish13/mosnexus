# pylint: disable=invalid-name
"""Django settings for NexusOps — AI-Powered Unified Operations & Resource Management Portal."""

import os
from pathlib import Path

from inventory.version import __version__ as APP_VERSION  # pylint: disable=wrong-import-position

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── ENVIRONMENT CONFIGURATION ───────────────────────────────────────────────
# Reads from environment variables with sensible defaults for development.
# In production, these MUST be set via .env file or system environment.
PHILIPSNEXUS_ENV = os.environ.get(
    "NEXUSOPS_ENV", os.environ.get("PHILIPSNEXUS_ENV", "dev")
)  # dev | staging | prod | test

_secret = os.environ.get("DJANGO_SECRET_KEY", "")
if not _secret and PHILIPSNEXUS_ENV in ("prod", "staging"):
    raise RuntimeError("DJANGO_SECRET_KEY environment variable is required in production and staging!")
SECRET_KEY = _secret or "django-insecure-dev-only-key-do-not-use-in-production"

DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() in ("true", "1", "yes")

_default_hosts = "localhost,127.0.0.1,130.141.135.225,14.194.95.251,13.49.238.18,philipsnexus.com"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", _default_hosts).split(",")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "whitenoise.runserver_nostatic",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "products",
]

MIDDLEWARE = [
    "products.middleware.MaintenanceMiddleware",  # Must be first
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",  # Global login requirement (Django 5.1+)
    "django.contrib.messages.middleware.MessageMiddleware",
    "products.middleware.LoginRateLimitMiddleware",  # Brute-force login protection
    "products.middleware.BusinessUnitURLMiddleware",  # URL-based BU routing (/bu/<code>/…)
    "products.middleware.FeatureAccessMiddleware",  # Feature-level RBAC from FAC panel
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "products.middleware.NoCacheMiddleware",
    "products.middleware.UsageTrackingMiddleware",  # Track application usage
    "products.middleware.SessionTrackingMiddleware",  # Track user sessions for dashboard
    "products.page_navigation.PageNavigationMiddleware",  # Track page back/forward history
    "products.middleware.InactivityLogoutMiddleware",  # Auto-logout after inactivity (all pages)
    "products.middleware.DevToolsProtectionMiddleware",  # Block right-click & DevTools when enabled
]

# Inactivity timeout before countdown modal appears (in seconds)
INACTIVITY_TIMEOUT_SECONDS = 300  # 5 minutes

ROOT_URLCONF = "inventory.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "products.context_processors.version_context",  # App version in all templates
                "products.context_processors.business_unit_context",  # Selected BU in all templates
                "products.context_processors.site_settings_context",  # Site-wide settings (DevTools protection, etc.)
                "products.context_processors.feature_access_context",  # Feature access control per-user URL set
                "products.page_navigation.page_navigation_context",  # Page navigation toolbar
            ],
        },
    },
]

WSGI_APPLICATION = "inventory.wsgi.application"

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 30,  # seconds — increase wait for locks
        },
    }
}

# Password validation

# Password Hashers - Argon2id is the primary (OWASP recommended)
# Falls back to PBKDF2 for existing passwords
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",  # Primary - uses salt automatically
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",  # Fallback for existing passwords
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": 12,  # OWASP recommends at least 12 characters
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
    # Custom validators for enhanced security
    {
        "NAME": "products.validators.PasswordStrengthValidator",
        "OPTIONS": {
            "min_uppercase": 1,
            "min_lowercase": 1,
            "min_digits": 1,
            "min_special": 1,
        },
    },
    {
        "NAME": "products.validators.NoRepeatingCharactersValidator",
        "OPTIONS": {
            "max_consecutive": 3,
        },
    },
    {
        "NAME": "products.validators.NoCommonPatternsValidator",
    },
]


# Internationalization
LANGUAGE_CODE = "en-us"

TIME_ZONE = "Asia/Kolkata"

USE_I18N = True

USE_TZ = True


# Static files
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "products" / "static",
]

# Media files (uploads)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "product_images"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# =============================================================================
# SECURITY SETTINGS
# =============================================================================

# Cookie Security - Prevents cookies from being accessed by JavaScript
SESSION_COOKIE_HTTPONLY = True
# CSRF_COOKIE_HTTPONLY must be False to allow JavaScript to read the CSRF token
# for AJAX requests. This is safe because CSRF tokens are designed to be readable
# by JavaScript on the same origin.
CSRF_COOKIE_HTTPONLY = False

SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 28800  # 8 hours in seconds

# Login Rate Limiting (brute-force protection)
LOGIN_RATELIMIT_MAX_ATTEMPTS = 5  # Max failed attempts before lockout
LOGIN_RATELIMIT_WINDOW = 300  # Window in seconds (5 minutes)
LOGIN_RATELIMIT_LOCKOUT = 900  # Lockout duration in seconds (15 minutes)

# Login redirect settings
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"

# HTTP Strict Transport Security (HSTS) - Forces HTTPS
# Only enable in production with HTTPS configured
# SECURE_HSTS_SECONDS = 31536000  # 1 year
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# SECURE_HSTS_PRELOAD = True

# Content Security
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Cookie SameSite attributes — prevents CSRF via cross-origin requests
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Proxy SSL header — required when running behind Nginx HTTPS termination
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Content Security Policy — mitigates XSS attacks
# Adjust 'script-src' and 'style-src' if you use additional CDNs
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = (
    "'self'",
    "'unsafe-inline'",
    "https://cdn.jsdelivr.net",
)
CSP_STYLE_SRC = (
    "'self'",
    "'unsafe-inline'",
    "https://cdn.jsdelivr.net",
    "https://fonts.googleapis.com",
)
CSP_IMG_SRC = (
    "'self'",
    "data:",
)
CSP_FONT_SRC = (
    "'self'",
    "https://fonts.gstatic.com",
    "https://cdn.jsdelivr.net",
)
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_SRC = ("'none'",)

# CSRF Settings - Trusted origins for CSRF
CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
    "http://130.141.135.225",
    "http://130.141.135.225:8000",
    "http://localhost",
    "http://localhost:8000",
]

# For production with HTTPS, uncomment these:
# SECURE_SSL_REDIRECT = True
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True

# =============================================================================
# MAINTENANCE MODE
# =============================================================================
# When enabled, all users except superadmins see a maintenance page.
# Toggle via: python manage.py maintenance --on / --off
# Or manually create/delete the file: MAINTENANCE_MODE_FLAG_FILE
MAINTENANCE_MODE = False  # Fallback; the middleware checks the flag file first
MAINTENANCE_MODE_FLAG_FILE = BASE_DIR / "maintenance.flag"
# IPs that can bypass maintenance mode (e.g. your own IP)
# MAINTENANCE_BYPASS_IPS = ['127.0.0.1', '::1']
MAINTENANCE_BYPASS_IPS: list[str] = []  # Empty for now; can be set in production as needed

# =============================================================================
# PRODUCTION-AWARE SECURITY (auto-enable when PHILIPSNEXUS_ENV=prod)
# =============================================================================
if PHILIPSNEXUS_ENV == "prod":
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"
    _csrf_origins = os.environ.get("CSRF_TRUSTED_ORIGINS", "https://philipsnexus.com")
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(",")]

# =============================================================================
# EMAIL
# =============================================================================
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend" if PHILIPSNEXUS_ENV == "prod" else "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.office365.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").lower() in ("true", "1", "yes")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "mostestautomation_2@philips.com")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "NexusOps <mostestautomation_2@philips.com>")

# =============================================================================
# LOGGING
# =============================================================================
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO" if PHILIPSNEXUS_ENV == "prod" else "DEBUG")
FILE_LOGGING = os.environ.get("FILE_LOGGING", "off").lower() in ("1", "true", "on", "yes")
_log_handlers = ["console", "file"] if FILE_LOGGING else ["console"]
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {module}.{funcName}:{lineno} — {message}",
            "style": "{",
        },
        "simple": {
            "format": "[{levelname}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.environ.get("LOG_FILE", str(BASE_DIR / "logs" / "philipsnexus.log")),
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": _log_handlers,
            "level": "WARNING",
            "propagate": False,
        },
        "django.server": {
            "handlers": _log_handlers,
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": _log_handlers,
            "level": "INFO",
            "propagate": False,
        },
        "products": {
            "handlers": _log_handlers,
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
