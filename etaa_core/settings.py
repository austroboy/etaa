"""
ETAA - Enterprise Task Automation Agent
Django Settings
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── Security ───────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "change-me-in-production")
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# ─── Installed Apps ──────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "django_celery_beat",
    # ETAA modules
    "apps.messaging",
    "apps.email_module",
    "apps.cv_module",
    "apps.job_post_module",
    "apps.dev_module",
    "apps.agent",
    "apps.authz",
    "apps.confirmation",
    "apps.logger_module",
    "apps.notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "etaa_core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "etaa_core.wsgi.application"

# ─── Database ────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL and DATABASE_URL.startswith("postgres"):
    import dj_database_url
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ─── Static Files ────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ─── Auth ────────────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── Celery ──────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Asia/Dhaka"

# ─── Celery Beat Schedule ────────────────────────────────────────────────────
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    "expire-stale-confirmations": {
        "task": "apps.confirmation.tasks.expire_confirmations_task",
        "schedule": 300,
    },
    "purge-old-logs": {
        "task": "apps.logger_module.tasks.purge_old_logs_task",
        "schedule": crontab(hour=2, minute=0),
    },
}

# ─── ETAA Configuration ──────────────────────────────────────────────────────

# Authorized core operators. These three phone numbers (digits only,
# country code included, no '+') are individually authorized everywhere –
# DMs to the bot and every group the bot is in. They are the ONLY people
# who can grant in-group access to other members.
#
# Anyone NOT in this list can only message the bot inside a group where
# one of the three has explicitly authorized them via `apps.authz`.
AUTHORIZED_OPERATORS = {
    os.environ.get("OPERATOR_1_PHONE", "8801700000001"):
        os.environ.get("OPERATOR_1_NAME", "Zihad Milon"),
    os.environ.get("OPERATOR_2_PHONE", "8801700000002"):
        os.environ.get("OPERATOR_2_NAME", "Mohibur Rahman"),
    os.environ.get("OPERATOR_3_PHONE", "8801700000003"):
        os.environ.get("OPERATOR_3_NAME", "Shafiqur Rahman"),
}

# Optional default group JID. Used only as a fallback target for
# unsolicited bot messages (e.g. the periodic inbox monitor's status
# updates). Conversational replies always go back to whichever chat the
# instruction came from – they do not depend on this value.
WHATSAPP_GROUP_JID  = os.environ.get("WHATSAPP_GROUP_JID", "")
WHATSAPP_BRIDGE_URL = os.environ.get("WHATSAPP_BRIDGE_URL",
                                     "http://localhost:3000")
WHATSAPP_API_TOKEN  = os.environ.get("WHATSAPP_API_TOKEN", "")

# Email / SMTP
EMAIL_HOST          = os.environ.get("SMTP_HOST", "smtp.gmail.com")
EMAIL_PORT          = int(os.environ.get("SMTP_PORT", "587"))
EMAIL_HOST_USER     = os.environ.get("SMTP_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_USE_TLS       = True
DEFAULT_FROM_EMAIL  = os.environ.get("COMPANY_EMAIL", "")
COMPANY_NAME        = os.environ.get("COMPANY_NAME", "The Company")
IMAP_HOST           = os.environ.get("IMAP_HOST", "imap.gmail.com")
IMAP_PORT           = int(os.environ.get("IMAP_PORT", "993"))

# AI APIs
OPENAI_API_KEY      = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
PRIMARY_LLM_PROVIDER = os.environ.get("PRIMARY_LLM_PROVIDER", "openai")  # 'openai' or 'anthropic'

# Google Drive
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_OAUTH_CREDENTIALS    = os.environ.get("GOOGLE_OAUTH_CREDENTIALS", "")

# Canva
CANVA_API_KEY       = os.environ.get("CANVA_API_KEY", "")
CANVA_TEMPLATE_ID   = os.environ.get("CANVA_JOB_POST_TEMPLATE_ID", "")

# Git
GIT_DEFAULT_REMOTE  = os.environ.get("GIT_REMOTE_URL", "")
GIT_SSH_KEY_PATH    = os.environ.get("GIT_SSH_KEY_PATH", "~/.ssh/id_rsa")
GIT_PAT             = os.environ.get("GIT_PAT", "")

# Output directories
OUTPUT_DIR   = os.environ.get("OUTPUT_DIR", str(BASE_DIR / "outputs"))
CV_TEMP_DIR  = os.environ.get("CV_TEMP_DIR", str(BASE_DIR / "temp" / "cvs"))
CODE_OUT_DIR = os.environ.get("CODE_OUT_DIR", str(BASE_DIR / "outputs" / "code"))

# Email templates directory
EMAIL_TEMPLATES_DIR = os.environ.get("EMAIL_TEMPLATES_DIR", str(BASE_DIR / "templates" / "email_templates"))

# Confirmation timeout (seconds)
CONFIRMATION_TIMEOUT = int(os.environ.get("CONFIRMATION_TIMEOUT", "300"))

# Log retention
LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", "90"))
LOG_MAX_FILE_SIZE_MB = int(os.environ.get("LOG_MAX_FILE_SIZE_MB", "50"))

# Logging
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "etaa.log",
            "maxBytes": 50 * 1024 * 1024,  # 50 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "etaa": {
            "handlers": ["file", "console"],
            "level": "INFO",
            "propagate": True,
        },
    },
}
