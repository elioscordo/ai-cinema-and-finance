from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ArgoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'argo'
    verbose_name = _('Argo Trading')

    def ready(self) -> None:
        from argo.ib.ib_download import patch_nautilus_historic_client_logging
        patch_nautilus_historic_client_logging()

