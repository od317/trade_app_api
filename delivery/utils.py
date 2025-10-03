# delivery/utils.py
import secrets
from django.utils import timezone
from datetime import timedelta

def generate_delivery_token():
    # URL-safe, short; good enough for dev
    return secrets.token_urlsafe(16)

def default_expiry(hours=24):
    return timezone.now() + timedelta(hours=hours)
