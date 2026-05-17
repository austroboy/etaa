from django.apps import AppConfig

class DevModuleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dev_module"
