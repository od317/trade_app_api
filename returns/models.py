from django.db import models
from django.conf import settings
from orders.models import Order, OrderItem
from products.models import Product

class ReturnStatus(models.TextChoices):
    REQUESTED = 'requested', 'Requested'
    PICKUP_SCHEDULED = 'pickup_scheduled', 'Pickup Scheduled'
    PICKED_UP = 'picked_up', 'Picked Up'
    UNDER_INSPECTION = 'under_inspection', 'Under Inspection'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'
    COMPLETED = 'completed', 'Completed'

class ProductCondition(models.TextChoices):
    NEW = 'new', 'New'
    LIKE_NEW = 'like_new', 'Like New'
    USED = 'used', 'Used'
    DAMAGED = 'damaged', 'Damaged'
    MISSING_PARTS = 'missing_parts', 'Missing Parts'
    UNSALEABLE = 'unsaleable', 'Unsaleable'

class ReturnRequest(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='return_requests')
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='return_requests')
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reason = models.TextField()
    status = models.CharField(max_length=30, choices=ReturnStatus.choices, default=ReturnStatus.REQUESTED)
    requested_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    admin_notes = models.TextField(blank=True, null=True)
    inspection_notes = models.TextField(blank=True, null=True)
    condition = models.CharField(max_length=20, choices=ProductCondition.choices, blank=True, null=True)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    inspected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='inspected_returns')
    processed_at = models.DateTimeField(null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    
    def __str__(self):
        return f"ReturnRequest #{self.pk} for OrderItem #{self.order_item_id}"

class ReturnRequestImage(models.Model):
    return_request = models.ForeignKey(ReturnRequest, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='returns/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

class ReturnedProduct(models.Model):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('open_box', 'Open Box'),
        ('used', 'Used'),
        ('damaged', 'Damaged'),
        ('missing_parts', 'Missing Parts')
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='returned_products')
    return_request = models.ForeignKey('ReturnRequest', on_delete=models.CASCADE, related_name='returned_products')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    quantity = models.PositiveIntegerField()
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    is_sellable = models.BooleanField(default=False)
    seller_approval = models.BooleanField(null=True, blank=True)  # None = pending
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('product', 'return_request', 'status')

    def __str__(self):
        return f"{self.quantity} x {self.product.name_en} ({self.get_status_display()})"