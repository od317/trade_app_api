from django.contrib.contenttypes.models import ContentType
from notifications.models import Notification
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .serializers import NotificationSerializer

def send_order_notification(user, order, notification_type):
    messages = {
        'order_created': {
            'ar': f"تم إنشاء طلبك #{order.order_number} بنجاح",
            'en': f"Your order #{order.order_number} has been created successfully"
        },
        'order_processing': {
            'ar': f"طلبك #{order.order_number} قيد المعالجة",
            'en': f"Your order #{order.order_number} is being processed"
        },
        'order_shipped': {
            'ar': f"طلبك #{order.order_number} تم شحنه",
            'en': f"Your order #{order.order_number} has been shipped"
        },
        'order_delivered': {
            'ar': f"طلبك #{order.order_number} تم توصيله",
            'en': f"Your order #{order.order_number} has been delivered"
        },
        'order_completed': {
            'ar': f"طلبك #{order.order_number} اكتمل",
            'en': f"Your order #{order.order_number} has been completed"
        },
        'order_cancelled': {
            'ar': f"طلبك #{order.order_number} تم إلغاؤه",
            'en': f"Your order #{order.order_number} has been cancelled"
        },
        'order_refunded': {
            'ar': f"طلبك #{order.order_number} تم استرداد قيمته",
            'en': f"Your order #{order.order_number} has been refunded"
        },
        'refund_requested': {
            'ar': f"تم تقديم طلب استرداد لطلبك #{order.order_number}",
            'en': f"A refund has been requested for your order #{order.order_number}"
        },
        'refund_approved': {
            'ar': f"تمت الموافقة على استرداد طلبك #{order.order_number}",
            'en': f"Your refund for order #{order.order_number} has been approved"
        },
        'refund_rejected': {
            'ar': f"تم رفض استرداد طلبك #{order.order_number}",
            'en': f"Your refund for order #{order.order_number} has been rejected"
        }
    }
    
    Notification.objects.create(
        user=user,
        notification_type=notification_type,
        message_ar=messages[notification_type]['ar'],
        message_en=messages[notification_type]['en'],
        content_object=order
    )


def send_websocket_notification(user, notification):
    """Send notification via WebSocket to specific user"""
    channel_layer = get_channel_layer()
    group_name = f'notifications_{user.id}'
    
    # Serialize the notification
    serializer = NotificationSerializer(notification)
    notification_data = serializer.data
    
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            'type': 'send_notification',
            'notification': notification_data
        }
    )