# accounts/models.py
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.conf import settings
from .managers import CustomUserManager


POINTS_PENALTY_DAMAGED_PER_UNIT = 5
POINTS_PENALTY_MISSING_PARTS_PER_UNIT = 3
POINTS_PENALTY_UNSALEABLE_PER_UNIT = 7

def deduct_seller_points(self, amount: int):
    """
    Deduct points from seller but do not go below zero.
    """
    if amount <= 0:
        return
    new_points = max(0, int(getattr(self, "points", 0)) - int(amount))
    self.points = new_points
    self.save(update_fields=["points"])

class Role(models.TextChoices):
    USER = 'user', 'User'
    SELLER = 'seller', 'Seller'
    DELIVERY = 'delivery', 'Delivery'
    ADMIN = 'admin', 'Admin'
    SUPERADMIN = 'superadmin', 'Super Admin'

class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=150, unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=15)
    address = models.TextField(blank=True, null=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.USER)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    current_token_user = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    points = models.PositiveIntegerField(default=0)
    is_verified_seller = models.BooleanField(default=False)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']

    def get_unread_notifications(self):
        return self.user_notifications.filter(is_read=False)  # Updated related_name

    def mark_all_notifications_read(self):
        return self.user_notifications.filter(is_read=False).update(is_read=True)  # Updated

    def send_notification(self, notification_type, message_ar, message_en, content_object=None):
          from notifications.models import Notification
          return Notification.objects.create(
                user=self,
                notification_type=notification_type,
                message_ar=message_ar,
                message_en=message_en,
                content_object=content_object
            )
    
    VERIFICATION_THRESHOLD = 500  # Example threshold

    def add_seller_points(self, amount):
        if self.role != Role.SELLER:
            return
        self.points += amount
        # Auto-verify if threshold reached
        if self.points >= self.VERIFICATION_THRESHOLD and not self.is_verified_seller:
            self.is_verified_seller = True
        self.save()

    def __str__(self):
        return self.email

class Purpose(models.TextChoices):
    EMAIL_VERIFICATION = 'email_verification'
    PASSWORD_RESET = 'password_reset'
    EMAIL_CHANGE = "ChangeEmail"

class EmailVerification(models.Model):
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Role.choices)
    purpose = models.CharField(max_length=30, choices=Purpose.choices)
    encrypted_code = models.BinaryField()
    send_count_today = models.PositiveIntegerField(default=0)
    first_sent_today = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    has_user = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    current_token = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    new_email = models.EmailField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['email', 'purpose'], name='unique_email_purpose')
        ]

    def __str__(self):
        return f"{self.email} - {self.purpose}"

class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    bio = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='profiles/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_certified = models.BooleanField(default=False)
    #location
    latitude = models.DecimalField(max_digits=25, decimal_places=20, null=True, blank=True)
    longitude = models.DecimalField(max_digits=25, decimal_places=20, null=True, blank=True)
    address_line = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    region = models.CharField(max_length=120, blank=True)   # state/province/governorate
    country = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    def __str__(self):
        return f"{self.user.email}'s Profile"