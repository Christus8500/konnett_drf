from django.apps import AppConfig


class ProvidersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.providers'

    def ready(self):
        import apps.providers.signals
