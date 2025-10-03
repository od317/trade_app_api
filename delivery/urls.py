# delivery/urls.py
from django.urls import path
from .views import (
    AvailableOrdersView, MyActiveOrdersView,
    ClaimOrderView, AdvanceOrderStatusView,
    OrderDetailForDeliveryView,MyDeliveredOrdersView,
)
from .views_qr import GenerateDeliveryQRView, ConfirmDeliveryByQRView


urlpatterns = [
    path('orders/available/', AvailableOrdersView.as_view(), name='delivery-available-orders'),
    path('orders/my/', MyActiveOrdersView.as_view(), name='delivery-my-orders'),
    path('orders/<int:order_id>/claim/', ClaimOrderView.as_view(), name='delivery-claim'),
    path('orders/<int:order_id>/advance/', AdvanceOrderStatusView.as_view(), name='delivery-advance'),
    path('orders/<int:order_id>/', OrderDetailForDeliveryView.as_view(), name='delivery-order-detail'),
    path('orders/history/', MyDeliveredOrdersView.as_view(), name='delivery-history'), 
    path('orders/<int:order_id>/qr/', GenerateDeliveryQRView.as_view(), name='delivery-generate-qr'),
    path('orders/<int:order_id>/confirm-qr/', ConfirmDeliveryByQRView.as_view(), name='delivery-confirm-qr'),
]
