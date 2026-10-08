import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project_argo.settings')

app = Celery('argo')
app.config_from_object('project_argo.settings', namespace='CELERY')
app.autodiscover_tasks()
