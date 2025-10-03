from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('product_approved', 'Product Approved'),
        ('product_rejected', 'Product Rejected'),
        ('order_created', 'Order Created'),
        ('order_shipped', 'Order Shipped'),
        ('system_alert', 'System Alert'),
        ('wishlist_discount', 'Wishlist Discount'),
        ('order_created', 'Order Created'),
        ('order_processing', 'Order Processing'),
        ('order_shipped', 'Order Shipped'),
        ('order_delivered', 'Order Delivered'),
        ('order_completed', 'Order Completed'),
        ('order_cancelled', 'Order Cancelled'),
        ('order_refunded', 'Order Refunded'),
        ('refund_requested', 'Refund Requested'),
        ('refund_approved', 'Refund Approved'),
        ('refund_rejected', 'Refund Rejected'),
        ('seller_payment', 'Seller Payment'),
        ('seller_verified', 'Seller Verified'),
        ('seller_points_penalty', 'Seller Points Penalty'),
        ('low_stock', 'Low Stock'),
        ('return_status_update', 'Return Status Update'),
        ('return_status_update_buyer', 'Return Status Update (Buyer)'),
        ('brand_approved','Brand Approved'),
        ('brand_rejected','Brand Rejected'),
        ('brand_request_submitted','Brand Request Submitted'),
        ('auction_new_bid', 'Auction New Bid'),
        ('auction_outbid', 'Auction Outbid'),
        ('auction_won', 'Auction Won'),
        ('auction_ended_no_winner', 'Auction Ended No Winner'),
        ('auction_order_created', 'Auction Order Created'),
        ('auction_submitted', 'Auction Submitted'),
        ('auction_approved', 'Auction Approved'),
        ('auction_rejected', 'Auction Rejected'),
        ('auction_cancelled', 'Auction Cancelled')
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_notifications'  # Changed to unique name
    )
    
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    message_ar = models.TextField()
    message_en = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    extra_data = models.JSONField(null=True, blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        ordering = ['-created_at']
        db_table = 'notifications_notification'

    def mark_as_read(self):
        """Mark notification as read with timestamp"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save()