# wallet/urls.py
from django.urls import path
from .views import (
    WalletAPIView,
    TransactionHistoryAPIView,
    TransferAPIView,
    AdjustBalanceView
)

urlpatterns = [
    path('', WalletAPIView.as_view(), name='wallet-detail'),
    path('transactions/', TransactionHistoryAPIView.as_view(), name='wallet-transactions'),
    path('transfer/', TransferAPIView.as_view(), name='wallet-transfer'),
    path('admin/adjust-balance/<int:user_id>/', AdjustBalanceView.as_view(), name='adjust-balance'),
]