# orders/urls.py
from django.urls import path
from .views import (
    CheckoutView,
    OrderListView,
    UpdateOrderStatusView,
    CancelOrderView,
    RequestRefundView,
    ProcessRefundView,
    OverdueOrdersView,
    CompleteOrderView,
    OrderDetailView,
    force_complete_order
)

urlpatterns = [
    # Order creation and management
    path('checkout/', CheckoutView.as_view(), name='checkout'),
    path('', OrderListView.as_view(), name='order-list'),
    path('<int:pk>/status/', UpdateOrderStatusView.as_view(), name='update-order-status'),
    path('<int:pk>/complete/', CompleteOrderView.as_view(), name='complete-order'),
    path('<int:pk>/cancel/', CancelOrderView.as_view(), name='cancel-order'),
    path('<int:pk>/', OrderDetailView.as_view(), name='order-detail'),
    # Refund endpoints
    path('<int:pk>/request-refund/', RequestRefundView.as_view(), name='request-refund'),
    path('refunds/<int:pk>/process/', ProcessRefundView.as_view(), name='process-refund'),
    
    # Admin endpoints (if needed)
    path('admin/overdue/', OverdueOrdersView.as_view(), name='overdue-orders'),

    # force complete order for testing 
    path('<int:order_id>/force-complete/', force_complete_order, name='force-complete-order'),
]