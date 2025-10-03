# delivery/views.py
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response

from orders.models import Order, OrderStatus, OrderItem
from notifications.models import Notification
from .permissions import IsDelivery
from .serializers import DeliveryOrderSerializer
from .models import DeliveryProof
from .utils import generate_delivery_token, default_expiry

# These are only for generating a base64 QR image in dev/testing.
# If qrcode isn't installed, we’ll just skip the image.
import io, base64
try:
    import qrcode
except Exception:  # pragma: no cover
    qrcode = None


ACTIVE_FOR_DELIVERY = {OrderStatus.CREATED, OrderStatus.PROCESSING, OrderStatus.SHIPPED}
MAX_ACTIVE_ORDERS = 5

class AvailableOrdersView(APIView):
    """
    GET /api/delivery/orders/available/
    List orders that are not claimed and are in a claimable state.
    """
    permission_classes = [permissions.IsAuthenticated, IsDelivery]

    def get(self, request):
        qs = (Order.objects
              .filter(assigned_delivery__isnull=True, status__in=[OrderStatus.CREATED])
              .order_by('-created_at'))
        return Response(DeliveryOrderSerializer(qs, many=True).data)

class MyActiveOrdersView(APIView):
    """
    GET /api/delivery/orders/my/
    Orders assigned to me, not yet delivered (counts towards the 5 limit).
    """
    permission_classes = [permissions.IsAuthenticated, IsDelivery]

    def get(self, request):
        qs = (Order.objects
              .filter(assigned_delivery=request.user, status__in=ACTIVE_FOR_DELIVERY)
              .order_by('-assigned_at'))
        return Response(DeliveryOrderSerializer(qs, many=True).data)

class ClaimOrderView(APIView):
    """
    POST /api/delivery/orders/<order_id>/claim/
    Claim an order (if not taken). Sets status -> PROCESSING.
    Enforces max 5 active per courier.
    """
    permission_classes = [permissions.IsAuthenticated, IsDelivery]

    @transaction.atomic
    def post(self, request, order_id):
        # Enforce the 5-active limit
        active_count = Order.objects.select_for_update().filter(
            assigned_delivery=request.user, status__in=ACTIVE_FOR_DELIVERY
        ).count()
        if active_count >= MAX_ACTIVE_ORDERS:
            return Response(
                {'error': f'Limit reached. You can work on up to {MAX_ACTIVE_ORDERS} orders at a time.'},
                status=status.HTTP_403_FORBIDDEN
            )

        order = Order.objects.select_for_update().get(pk=order_id)

        if order.assigned_delivery_id:
            if order.assigned_delivery_id == request.user.id:
                return Response({'message': 'You already claimed this order.'})
            return Response(
                {'error': 'This order is already taken by another delivery agent.'},
                status=status.HTTP_409_CONFLICT
            )

        if order.status != OrderStatus.CREATED:
            return Response({'error': 'Order is not available to claim.'}, status=400)

        # Claim it
        order.assigned_delivery = request.user
        order.assigned_at = timezone.now()
        order.status = OrderStatus.PROCESSING
        order.save(update_fields=['assigned_delivery', 'assigned_at', 'status'])

        # (optional) create DeliveryAssignment row
        try:
            from .models import DeliveryAssignment
            DeliveryAssignment.objects.create(order=order, courier=request.user)
        except Exception:
            pass

        # Notify buyer
        Notification.objects.create(
            user=order.buyer,
            notification_type='order_claimed',
            message_ar=f"تم استلام طلبك {order.order_number} من قبل مندوب التوصيل.",
            message_en=f"Your order {order.order_number} was claimed by a courier.",
            content_object=order,
        )

        return Response(DeliveryOrderSerializer(order).data, status=200)

class AdvanceOrderStatusView(APIView):
    """
    POST /api/delivery/orders/<order_id>/advance/
    Move order forward: PROCESSING -> SHIPPED -> DELIVERED
    Only the assigned courier can do it.
    - On SHIPPED: auto-generate a DeliveryProof token (QR/PIN) and notify the buyer (with token/QR for dev).
    - On DELIVERED: requires `delivery_token` in the request body; validates and marks proof as used.
    """
    permission_classes = [permissions.IsAuthenticated, IsDelivery]

    @transaction.atomic
    def post(self, request, order_id):
        order = get_object_or_404(Order.objects.select_for_update(), pk=order_id)

        if order.assigned_delivery_id != request.user.id:
            return Response({'error': 'This order is not assigned to you.'},
                            status=status.HTTP_403_FORBIDDEN)

        # Already delivered?
        if order.status == OrderStatus.DELIVERED:
            return Response({'message': 'Already delivered.'})

        # Determine next status
        if order.status == OrderStatus.PROCESSING:
            next_status = OrderStatus.SHIPPED
        elif order.status == OrderStatus.SHIPPED:
            next_status = OrderStatus.DELIVERED
        else:
            return Response({'error': f'Cannot advance from status {order.status}.'}, status=400)

        # Apply transition logic
        if next_status == OrderStatus.SHIPPED:
            order.status = OrderStatus.SHIPPED

            # --- Auto-generate/refresh delivery token & QR ---
            proof, created = DeliveryProof.objects.get_or_create(
                order=order,
                defaults={
                    'method': 'qr',
                    'token': generate_delivery_token(),
                    'expires_at': default_expiry(hours=24),  # adjust as you like
                }
            )
            # Refresh token if not used yet (new trip)
            if not created and proof.used_at is None:
                proof.token = generate_delivery_token()
                proof.expires_at = default_expiry(hours=24)
                proof.attempts = 0
                proof.save(update_fields=['token', 'expires_at', 'attempts'])

            qr_b64 = None
            if qrcode is not None:
                img = qrcode.make(proof.token)
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                qr_b64 = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"

            # Notify buyer with token info (dev convenience; in prod send link)
            Notification.objects.create(
                user=order.buyer,
                notification_type='order_shipped',
                message_ar=f"طلبك {order.order_number} في الطريق. هذا رمز التأكيد للتسليم.",
                message_en=f"Your order {order.order_number} is on the way. Here’s your delivery confirmation code.",
                content_object=order,
                extra_data={
                    "delivery_token": proof.token,
                    "qr_png_base64": qr_b64,  # may be None if qrcode not installed
                    "expires_at": proof.expires_at.isoformat(),
                }
            )

        elif next_status == OrderStatus.DELIVERED:
            # Require proof
            delivery_token = (request.data.get('delivery_token') or '').strip()
            if not delivery_token:
                return Response(
                    {'error': 'delivery_token is required to confirm delivery.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                proof = DeliveryProof.objects.select_for_update().get(order=order)
            except DeliveryProof.DoesNotExist:
                return Response({'error': 'No delivery proof exists for this order.'},
                                status=status.HTTP_400_BAD_REQUEST)

            # Attempts limit
            if proof.attempts >= proof.max_attempts:
                return Response({'error': 'Maximum verification attempts exceeded.'},
                                status=status.HTTP_403_FORBIDDEN)

            # Token match + active
            proof.attempts += 1
            if proof.token != delivery_token:
                proof.save(update_fields=['attempts'])
                return Response({'error': 'Invalid delivery token.'}, status=status.HTTP_400_BAD_REQUEST)

            if not proof.is_active():
                proof.save(update_fields=['attempts'])
                return Response({'error': 'Delivery token expired or already used.'},
                                status=status.HTTP_400_BAD_REQUEST)

            # Mark proof used and finish delivery
            proof.used_at = timezone.now()
            proof.delivered_by = request.user
            proof.save(update_fields=['attempts', 'used_at', 'delivered_by'])

            order.status = OrderStatus.DELIVERED
            order.delivered_at = timezone.now()

            # Optional: mark assignment released
            try:
                from .models import DeliveryAssignment
                if hasattr(order, 'delivery_assignment') and order.delivery_assignment:
                    order.delivery_assignment.released_at = timezone.now()
                    order.delivery_assignment.save(update_fields=['released_at'])
            except Exception:
                pass

            # Notify buyer
            Notification.objects.create(
                user=order.buyer,
                notification_type='order_delivered',
                message_ar=f"تم تسليم طلبك {order.order_number}. نتمنى لك يوماً سعيداً!",
                message_en=f"Your order {order.order_number} has been delivered. Enjoy!",
                content_object=order,
            )

        # Persist status changes
        order.save()
        return Response(DeliveryOrderSerializer(order).data, status=200)
    
class OrderDetailForDeliveryView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsDelivery]

    def get(self, request, order_id):
        order = get_object_or_404(Order, pk=order_id)
        if order.assigned_delivery_id != request.user.id:
            return Response({'error': 'Not your order.'}, status=status.HTTP_403_FORBIDDEN)
        data = DeliveryOrderSerializer(order, context={'include_buyer_location': True}).data
        return Response(data)

class MyDeliveredOrdersView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsDelivery]

    def get(self, request):
        qs = (Order.objects
              .filter(assigned_delivery=request.user, status=OrderStatus.DELIVERED)
              .order_by('-delivered_at'))
        return Response(DeliveryOrderSerializer(qs, many=True).data)