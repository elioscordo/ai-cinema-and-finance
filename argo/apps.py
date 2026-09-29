from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ArgoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'argo'
    verbose_name = _('Argo Trading')
