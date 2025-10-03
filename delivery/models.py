# delivery/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from orders.models import Order

class DeliveryAssignment(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='delivery_assignment')
    courier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='delivery_assignments')
    claimed_at = models.DateTimeField(default=timezone.now)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['courier', 'claimed_at'])]

    
class DeliveryProof(models.Model):
    METHOD_CHOICES = (('qr', 'QR'), ('pin', 'PIN'))

    order = models.OneToOneField('orders.Order', on_delete=models.CASCADE, related_name='delivery_proof')
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default='qr')

    # store raw token for simplicity in dev; in prod store a hash
    token = models.CharField(max_length=128, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    used_at = models.DateTimeField(null=True, blank=True)
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='deliveries_confirmed'
    )

    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)

    def is_active(self):
        return self.used_at is None and (self.expires_at is None or timezone.now() <= self.expires_at)