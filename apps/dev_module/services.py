"""
Dev Module – Services
Orchestrates SRS parsing, multi-pass code generation, file writing, and Git push.
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from django.conf import settings

from apps.llm_client import get_llm_client

logger = logging.getLogger("etaa")


# ── SRS Analysis ──────────────────────────────────────────────────────────────


SRS_ANALYSIS_SYSTEM = """You are a senior software architect.
Analyze the provided SRS document and produce a structured JSON project plan.
Return ONLY valid JSON — no markdown, no explanation.

Schema:
{
  "project_name": "<snake_case name>",
  "description": "<one sentence>",
  "tech_stack": "<e.g. django_rest_framework>",
  "apps": [
    {
      "name": "<app_name>",
      "models": ["<ModelName: field descriptions>"],
      "views": ["<ViewName: description>"],
      "endpoints": ["<METHOD /path/ – description>"]
    }
  ],
  "additional_features": ["<feature description>"],
  "requirements": ["<package==version or package>"]
}"""


def analyze_srs(srs_text: str) -> dict:
    """Use LLM to analyze SRS and produce a structured project plan."""
    llm = get_llm_client()
    try:
        raw = llm.complete(
            prompt=f"SRS DOCUMENT:\n{srs_text[:12000]}",
            system=SRS_ANALYSIS_SYSTEM,
            max_tokens=3000,
            temperature=0.1,
        )
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.error("SRS analysis failed: %s", exc)
        raise ValueError(f"SRS analysis failed: {exc}") from exc


# ── Code Generation ───────────────────────────────────────────────────────────


CODE_GEN_SYSTEM = """You are an expert Django developer generating production-ready code.
Respond ONLY with the raw file content — no markdown fences, no explanation.
Follow PEP 8. Add inline comments for non-obvious logic.
No hardcoded secrets. Use os.environ.get() for all configuration."""


def generate_file(prompt: str, max_tokens: int = 3000) -> str:
    """Generate a single source file using LLM."""
    llm = get_llm_client()
    return llm.complete(prompt, system=CODE_GEN_SYSTEM, max_tokens=max_tokens, temperature=0.2)


def write_file(base_dir: str, rel_path: str, content: str) -> str:
    """Write content to a file under base_dir, creating dirs as needed."""
    full_path = os.path.join(base_dir, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("Wrote: %s", full_path)
    return full_path


def generate_project(
    plan: dict,
    srs_text: str,
    output_base: str,
    tech_stack: str = "django",
) -> str:
    """
    Generate a complete project from a plan dict.
    Returns the path to the generated project directory.
    """
    project_name = plan.get("project_name", "generated_project")
    project_dir = os.path.join(output_base, project_name)
    os.makedirs(project_dir, exist_ok=True)

    apps = plan.get("apps", [])
    requirements = plan.get("requirements", [])
    description = plan.get("description", "")

    # ── 1. requirements.txt ───────────────────────────────────────────────────
    base_reqs = [
        "django>=4.2",
        "djangorestframework",
        "celery[redis]",
        "redis",
        "python-dotenv",
        "dj-database-url",
        "gunicorn",
        "whitenoise",
    ]
    all_reqs = list(set(base_reqs + requirements))
    write_file(project_dir, "requirements.txt", "\n".join(sorted(all_reqs)))

    # ── 2. .env.example ───────────────────────────────────────────────────────
    env_example = """# Copy to .env and fill in values
DJANGO_SECRET_KEY=change-me-in-production
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3
REDIS_URL=redis://localhost:6379/0
"""
    write_file(project_dir, ".env.example", env_example)

    # ── 3. Django project core ────────────────────────────────────────────────
    _generate_django_core(project_dir, project_name, apps, description)

    # ── 4. Apps ───────────────────────────────────────────────────────────────
    for app in apps:
        _generate_app(project_dir, project_name, app, srs_text)

    # ── 5. README.md ──────────────────────────────────────────────────────────
    readme = _generate_readme(project_name, description, apps)
    write_file(project_dir, "README.md", readme)

    # ── 6. Dockerfile ─────────────────────────────────────────────────────────
    write_file(project_dir, "Dockerfile", _dockerfile_content(project_name))

    # ── 7. manage.py ──────────────────────────────────────────────────────────
    write_file(project_dir, "manage.py", _manage_py(project_name))

    logger.info("Project generated at: %s", project_dir)
    return project_dir


def _generate_django_core(project_dir: str, project_name: str, apps: list, description: str):
    """Generate settings, urls, wsgi, celery for the Django core package."""
    core_dir = os.path.join(project_dir, project_name)
    os.makedirs(core_dir, exist_ok=True)
    write_file(core_dir, "__init__.py", "")

    app_names = [f"apps.{a['name']}" for a in apps]
    installed_apps_str = "\n    ".join(f'"{n}",' for n in app_names)

    settings_content = f'''"""Django settings for {project_name}."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "change-me")
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    {installed_apps_str}
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
]

ROOT_URLCONF = "{project_name}.urls"
WSGI_APPLICATION = "{project_name}.wsgi.application"

TEMPLATES = [
    {{
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {{
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        }},
    }},
]

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres"):
    import dj_database_url
    DATABASES = {{"default": dj_database_url.parse(DATABASE_URL)}}
else:
    DATABASES = {{
        "default": {{
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }}
    }}

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
'''
    write_file(core_dir, "settings.py", settings_content)

    urls_content = f'''"""URL configuration for {project_name}."""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
'''
    write_file(core_dir, "urls.py", urls_content)

    wsgi = f'''import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "{project_name}.settings")
application = get_wsgi_application()
'''
    write_file(core_dir, "wsgi.py", wsgi)


def _generate_app(project_dir: str, project_name: str, app: dict, srs_text: str):
    """Generate all files for a single Django app."""
    app_name = app["name"]
    app_dir = os.path.join(project_dir, "apps", app_name)
    os.makedirs(app_dir, exist_ok=True)
    write_file(app_dir, "__init__.py", "")

    model_spec  = "\n".join(app.get("models", []))
    view_spec   = "\n".join(app.get("views", []))
    ep_spec     = "\n".join(app.get("endpoints", []))

    # models.py
    models_code = generate_file(
        f"Generate Django models.py for the '{app_name}' app.\n"
        f"Models needed:\n{model_spec}\n"
        f"Context from SRS:\n{srs_text[:2000]}",
        max_tokens=2000,
    )
    write_file(app_dir, "models.py", models_code)

    # serializers.py
    serializers_code = generate_file(
        f"Generate DRF serializers.py for the '{app_name}' app.\n"
        f"The models are:\n{model_spec}",
        max_tokens=1500,
    )
    write_file(app_dir, "serializers.py", serializers_code)

    # views.py
    views_code = generate_file(
        f"Generate Django REST framework views.py for the '{app_name}' app.\n"
        f"Views needed:\n{view_spec}\n"
        f"Endpoints:\n{ep_spec}",
        max_tokens=2500,
    )
    write_file(app_dir, "views.py", views_code)

    # urls.py
    urls_code = generate_file(
        f"Generate urls.py for the '{app_name}' app.\n"
        f"Endpoints to route:\n{ep_spec}",
        max_tokens=800,
    )
    write_file(app_dir, "urls.py", urls_code)

    # admin.py
    admin_code = generate_file(
        f"Generate admin.py for the '{app_name}' app.\n"
        f"Register all models:\n{model_spec}",
        max_tokens=600,
    )
    write_file(app_dir, "admin.py", admin_code)

    # apps.py
    apps_code = f"""from django.apps import AppConfig

class {app_name.title().replace('_', '')}Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.{app_name}"
"""
    write_file(app_dir, "apps.py", apps_code)

    # migrations/__init__.py
    os.makedirs(os.path.join(app_dir, "migrations"), exist_ok=True)
    write_file(os.path.join(app_dir, "migrations"), "__init__.py", "")


def _generate_readme(project_name: str, description: str, apps: list) -> str:
    app_list = "\n".join(f"- `apps/{a['name']}/`" for a in apps)
    return f"""# {project_name.replace('_', ' ').title()}

{description}

## Setup

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your values
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Apps
{app_list}

## Running Celery
```bash
celery -A {project_name} worker -l info
```

## Production
Set `DEBUG=False` and `DATABASE_URL` to a PostgreSQL URL in `.env`.

---
*Generated by ETAA – Enterprise Task Automation Agent*
"""


def _dockerfile_content(project_name: str) -> str:
    return f"""FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn", "{project_name}.wsgi:application", "--bind", "0.0.0.0:8000"]
"""


def _manage_py(project_name: str) -> str:
    return f'''#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "{project_name}.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("Couldn\'t import Django.") from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
'''


# ── Git Operations ────────────────────────────────────────────────────────────


def git_push(
    project_dir: str,
    repo_url: str,
    branch: str = "main",
    commit_message: str = "Initial commit – generated by ETAA",
    ssh_key_path: Optional[str] = None,
) -> bool:
    """Initialize a git repo in project_dir, commit everything, and push."""
    try:
        env = os.environ.copy()
        if ssh_key_path:
            env["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key_path} -o StrictHostKeyChecking=no"

        def run(cmd, **kw):
            return subprocess.run(
                cmd, cwd=project_dir, env=env, capture_output=True, text=True, **kw
            )

        run(["git", "init"])
        run(["git", "checkout", "-b", branch])
        run(["git", "add", "."])

        # Configure git identity for commit
        run(["git", "config", "user.email", "etaa@agent.local"])
        run(["git", "config", "user.name", "ETAA Agent"])

        result = run(["git", "commit", "-m", commit_message])
        if result.returncode != 0:
            logger.error("Git commit failed: %s", result.stderr)
            return False

        result = run(["git", "remote", "add", "origin", repo_url])
        result = run(["git", "push", "-u", "origin", branch, "--force"])

        if result.returncode != 0:
            logger.error("Git push failed: %s", result.stderr)
            return False

        logger.info("Git push successful to %s branch %s", repo_url, branch)
        return True

    except Exception as exc:  # noqa: BLE001
        logger.error("git_push exception: %s", exc)
        return False
