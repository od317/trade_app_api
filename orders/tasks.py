# orders/tasks.py
from celery import shared_task
from django.utils import timezone
from .models import Order, OrderStatus  # Added OrderStatus import
from .services import OrderService

@shared_task
def auto_complete_orders():
    # Complete orders where refund window has passed
    orders = Order.objects.filter(
        status=OrderStatus.DELIVERED,  # Now OrderStatus is defined
        delivered_at__lte=timezone.now() - timezone.timedelta(days=3)
    )
    
    for order in orders:
        try:
            OrderService.complete_order(order.id)
        except Exception as e:
            print(f"Failed to complete order {order.id}: {str(e)}")