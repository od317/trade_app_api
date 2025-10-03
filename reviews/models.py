from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator

from products.models import Product
from orders.models import Order, OrderItem, OrderStatus

class Review(models.Model):
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='reviews')
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='reviews')

    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=120, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_edited = models.BooleanField(default=False)

    class Meta:
        unique_together = ('buyer', 'product', 'order')  # 1 review per product per order
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.product_id} / {self.rating}★ by {self.buyer_id}"

    def clean(self):
        # Optional: enforce review only after delivery/completion
        if self.order.status not in [OrderStatus.DELIVERED, OrderStatus.COMPLETED]:
            raise ValueError("You can only review after the order is delivered.")
