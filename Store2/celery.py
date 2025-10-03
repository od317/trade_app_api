import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Store2.settings')

app = Celery('Store2')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'check-sale-expirations': {
        'task': 'products.tasks.expire_sales',
        'schedule': 3600.0,  # Every hour (in seconds)
    },
}

app.conf.beat_schedule = {
    'auto-complete-orders': {
        'task': 'orders.tasks.auto_complete_orders',
        'schedule': crontab(hour=3, minute=0),  # Runs daily at 3 AM
    },
}