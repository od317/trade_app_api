from django.db import models

# Create your models here.
# wallet/models.py
from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
from django.conf import settings
from returns.models import ReturnRequest

class Wallet(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet'
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    held_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    @property
    def available_balance(self):
        return self.balance - self.held_balance

    def __str__(self):
        return f"{self.user.email}'s Wallet (${self.balance})"
    
    def hold_funds(self, amount):
        if self.balance < amount:
            raise ValueError("Insufficient funds")
        self.balance -= amount
        self.held_balance += amount
        self.save()
    
class Transaction(models.Model):
    class TransactionType(models.TextChoices):
        DEPOSIT = 'deposit', 'Deposit'
        WITHDRAWAL = 'withdrawal', 'Withdrawal'
        TRANSFER = 'transfer', 'Transfer'
        PAYMENT = 'payment', 'Payment'
        REFUND = 'refund', 'Refund'
        FEE = 'fee', 'Fee'
        ESCROW_HOLD = 'escrow_hold', 'Escrow Hold'
        ESCROW_RELEASE = 'escrow_release', 'Escrow Release'
        SELLER_DEBIT = 'seller_debit', 'Seller Debit'
        PENALTY = 'penalty','Penalty'
        
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices
    )
    recipient = models.ForeignKey(
        Wallet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_transactions'
    )
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_successful = models.BooleanField(default=True)
    reference = models.CharField(max_length=100, blank=True)

    return_request = models.ForeignKey(
        ReturnRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='transactions'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.transaction_type} of ${self.amount} ({self.reference})"