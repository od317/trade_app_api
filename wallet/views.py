from django.shortcuts import render

# Create your views here.
# wallet/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db import transaction
from decimal import Decimal
from .models import Wallet, Transaction
from .serializers import WalletSerializer, TransactionSerializer, TransferSerializer,BalanceAdjustmentSerializer
from django.contrib.auth import get_user_model
from rest_framework.permissions import IsAdminUser
import time 

User = get_user_model()

class WalletAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = get_object_or_404(Wallet, user=request.user)
        serializer = WalletSerializer(wallet)
        return Response(serializer.data)

class TransactionHistoryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = get_object_or_404(Wallet, user=request.user)
        transactions = wallet.transactions.all().select_related('recipient')
        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data)

class TransferAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TransferSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            sender_wallet = request.user.wallet
            recipient = get_object_or_404(User, email=serializer.validated_data['recipient_email'])
            recipient_wallet = recipient.wallet
            amount = serializer.validated_data['amount']
            description = serializer.validated_data.get('description', '')

            # Generate a unique reference
            reference = f"TRF-{request.user.id}-{recipient.id}-{int(time.time())}"

            with transaction.atomic():
                # Deduct from sender
                sender_wallet.balance -= amount
                sender_wallet.save()

                # Add to recipient
                recipient_wallet.balance += amount
                recipient_wallet.save()

                # Record transactions
                Transaction.objects.create(
                    wallet=sender_wallet,
                    amount=amount,
                    transaction_type=Transaction.TransactionType.TRANSFER,
                    recipient=recipient_wallet,
                    description=description,
                    reference=reference
                )

                Transaction.objects.create(
                    wallet=recipient_wallet,
                    amount=amount,
                    transaction_type=Transaction.TransactionType.TRANSFER,
                    description=f"Received from {request.user.email}: {description}",
                    reference=reference
                )

            return Response(
                {
                    'message': 'Transfer successful',
                    'reference': reference,
                    'new_balance': sender_wallet.balance
                },
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class AdjustBalanceView(APIView):
    permission_classes = [IsAuthenticated]  # Only allow admins to adjust balances
    
    def post(self, request, user_id):
        user = get_object_or_404(User, id=user_id)
        wallet = get_object_or_404(Wallet, user=user)
        
        serializer = BalanceAdjustmentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        amount = serializer.validated_data['amount']
        reason = serializer.validated_data.get('reason', 'Balance adjustment')
        
        with transaction.atomic():
            # Update balance
            wallet.balance += amount
            wallet.save()
            
            # Record transaction
            Transaction.objects.create(
                wallet=wallet,
                amount=amount,
                transaction_type=Transaction.TransactionType.DEPOSIT,
                description=f"Admin adjustment: {reason}",
                reference=f"ADJ-{user.id}-{int(time.time())}",
                is_successful=True
            )
        
        return Response({
            'message': 'Balance updated successfully',
            'new_balance': wallet.balance,
            'user_id': user.id,
            'user_email': user.email
        }, status=status.HTTP_200_OK)