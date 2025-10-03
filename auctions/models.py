# auctions/models.py
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
from products.models import Product

class AuctionStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'            # seller created, not submitted
    SUBMITTED = 'submitted', 'Submitted' # waiting admin review
    REJECTED = 'rejected', 'Rejected'
    APPROVED = 'approved', 'Approved'   # scheduled, not yet live (await start_at)
    ACTIVE = 'active', 'Active'         # live
    ENDED = 'ended', 'Ended'
    CANCELLED = 'cancelled', 'Cancelled'

class Auction(models.Model):
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='auctions')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='auctions')
    quantity = models.PositiveIntegerField(default=1)

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    reserve_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    buy_now_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    min_increment = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1.00'))

    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    # anti-sniping
    auto_extend_window_seconds = models.PositiveIntegerField(default=120)  # 2 min
    auto_extend_seconds = models.PositiveIntegerField(default=120)

    status = models.CharField(max_length=20, choices=AuctionStatus.choices, default=AuctionStatus.DRAFT)
    rejection_reason = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='approved_auctions')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='cancelled_auctions')

    class Meta:
        indexes = [
            models.Index(fields=['status', 'start_at']),
            models.Index(fields=['status', 'end_at']),
        ]

    def __str__(self):
        return f"{self.title} (#{self.id})"

    def clean(self):
        delta = self.end_at - self.start_at
        if delta.total_seconds() < 2 * 3600:
            raise ValueError("Minimum auction duration is 2 hours.")
        if delta.days > 14:
            raise ValueError("Maximum auction duration is 14 days.")
        
        # Add buy_now_price validation
        if self.buy_now_price and self.buy_now_price <= self.start_price:
            raise ValueError("Buy now price must be higher than start price.")
        
        if self.reserve_price and self.reserve_price <= self.start_price:
            raise ValueError("Reserve price must be higher than start price.")

    @property
    def is_scheduled(self):
        return self.status == AuctionStatus.APPROVED and timezone.now() < self.start_at

    @property
    def is_live(self):
        now = timezone.now()
        return self.status == AuctionStatus.ACTIVE and self.start_at <= now < self.end_at

class Bid(models.Model):
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='bids')
    bidder = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bids')
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-amount', '-created_at']
        indexes = [
            models.Index(fields=['auction', '-amount', '-created_at']),
        ]

    def __str__(self):
        return f"Bid {self.amount} on {self.auction_id} by {self.bidder_id}"
