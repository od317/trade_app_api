# delivery/views_qr.py
import io, base64, qrcode
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from .models import DeliveryProof
from .utils import generate_delivery_token, default_expiry
from orders.models import Order, OrderStatus

class GenerateDeliveryQRView(APIView):
    """Buyer-only: create/refresh a one-time token + QR for their order."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, order_id):
        order = get_object_or_404(Order, pk=order_id, buyer=request.user)

        if order.status not in [OrderStatus.SHIPPED]:
            return Response({"error": "QR available only after order is shipped."}, status=400)

        # create or refresh token (single active proof per order)
        proof, _ = DeliveryProof.objects.get_or_create(order=order, defaults={
            'method': 'qr',
            'token': generate_delivery_token(),
            'expires_at': default_expiry(24),
        })
        if proof.used_at is None:
            # refresh token each time (optional)
            proof.token = generate_delivery_token()
            proof.expires_at = default_expiry(24)
            proof.attempts = 0
            proof.save(update_fields=['token','expires_at','attempts'])

        # encode QR content (keep it simple: just the token)
        qr = qrcode.make(proof.token)
        buf = io.BytesIO()
        qr.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

        return Response({
            "order_id": order.id,
            "order_number": order.order_number,
            "token": proof.token,                 # for testing without scanner
            "qr_png_base64": f"data:image/png;base64,{b64}",
            "expires_at": proof.expires_at
        }, status=200)

# delivery/views_qr.py (continued)
from rest_framework.permissions import IsAuthenticated
from .permissions import IsDelivery

class ConfirmDeliveryByQRView(APIView):
    """Courier-only: confirm delivery by posting QR token."""
    permission_classes = [IsAuthenticated, IsDelivery]

    def post(self, request, order_id):
        token = request.data.get('token', '').strip()
        if not token:
            return Response({"error": "token is required"}, status=400)

        order = get_object_or_404(Order.objects.select_for_update(), pk=order_id)

        if order.assigned_delivery_id != request.user.id:
            return Response({"error": "This order is not assigned to you."}, status=403)

        if order.status != OrderStatus.SHIPPED:
            return Response({"error": f"Order must be in SHIPPED to confirm. Current: {order.status}"}, status=400)

        proof = DeliveryProof.objects.filter(order=order, method='qr').first()
        if not proof:
            return Response({"error": "No active delivery proof found."}, status=404)

        if not proof.is_active():
            return Response({"error": "Token expired or already used."}, status=400)

        if proof.attempts >= proof.max_attempts:
            return Response({"error": "Too many invalid attempts. Please regenerate QR."}, status=429)

        if token != proof.token:
            proof.attempts += 1
            proof.save(update_fields=['attempts'])
            return Response({"error": "Invalid token."}, status=400)

        # OK → mark used and complete delivery
        proof.used_at = timezone.now()
        proof.delivered_by = request.user
        proof.save(update_fields=['used_at','delivered_by'])

        order.status = OrderStatus.DELIVERED
        order.delivered_at = timezone.now()
        order.save(update_fields=['status','delivered_at'])

        # optional: notify buyer
        from notifications.models import Notification
        Notification.objects.create(
            user=order.buyer,
            notification_type='order_delivered',
            message_ar=f"تم تسليم طلبك {order.order_number}.",
            message_en=f"Your order {order.order_number} has been delivered.",
            content_object=order
        )

        return Response({"message": "Delivery confirmed."}, status=200)
