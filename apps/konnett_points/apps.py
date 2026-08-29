from django.apps import AppConfig


class KonnettPointsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.konnett_points'

    def ready(self):
        import apps.konnett_points.signals
