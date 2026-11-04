from .celery import app as celery_app


# This makes sure the Celery app is loaded when Django starts
__all__ = ('celery_app',)