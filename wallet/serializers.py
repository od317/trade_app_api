# wallet/serializers.py
from rest_framework import serializers
from decimal import Decimal
from .models import Wallet, Transaction
from django.contrib.auth import get_user_model
from decimal import Decimal

User = get_user_model()

class WalletSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Wallet
        fields = ['id', 'user', 'balance','held_balance', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'user', 'balance', 'created_at', 'updated_at']

class TransactionSerializer(serializers.ModelSerializer):
    wallet = serializers.StringRelatedField(read_only=True)
    recipient = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Transaction
        fields = [
            'id', 'wallet', 'amount', 'transaction_type',
            'recipient', 'description', 'created_at',
            'is_successful', 'reference'
        ]
        read_only_fields = ['is_successful', 'reference']

class TransferSerializer(serializers.Serializer):
    recipient_email = serializers.EmailField()
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01')
    )
    description = serializers.CharField(max_length=255, required=False)

    def validate_amount(self, value):
        wallet = self.context['request'].user.wallet
        if value > wallet.balance:
            raise serializers.ValidationError("Insufficient funds")
        return value

    def validate_recipient_email(self, value):
        if value == self.context['request'].user.email:
            raise serializers.ValidationError("Cannot transfer to yourself")
        return value
    
class BalanceAdjustmentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01')
    )
    reason = serializers.CharField(max_length=255, required=False)