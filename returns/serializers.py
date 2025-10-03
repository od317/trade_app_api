from rest_framework import serializers
from .models import ReturnRequest, ReturnRequestImage
from .models import ReturnedProduct
from orders.models import OrderStatus, OrderItem

class ReturnRequestImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnRequestImage
        fields = ['id', 'image', 'uploaded_at']

class ReturnRequestSerializer(serializers.ModelSerializer):
    images = ReturnRequestImageSerializer(many=True, read_only=True)

    class Meta:
        model = ReturnRequest
        fields = [
            'id', 'order', 'order_item', 'buyer', 'reason', 'status',
            'requested_at', 'updated_at', 'admin_notes', 'inspection_notes',
            'condition', 'refund_amount', 'inspected_by', 'processed_at', 'images'
        ]
        read_only_fields = [
            'id', 'buyer', 'status', 'requested_at', 'updated_at',
            'admin_notes', 'inspection_notes', 'condition', 'refund_amount',
            'inspected_by', 'processed_at', 'images'
        ]

class ReturnRequestCreateSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(min_value=1)

    class Meta:
        model = ReturnRequest
        fields = ['order', 'order_item', 'reason', 'quantity']

    def validate(self, attrs):
        request = self.context['request']
        user = request.user
        order = attrs['order']
        order_item = attrs['order_item']
        qty = attrs['quantity']

        # Must be the buyer’s order
        if order.buyer_id != user.id:
            raise serializers.ValidationError("You can only return items from your own orders.")

        # The order item must belong to this order
        if order_item.order_id != order.id:
            raise serializers.ValidationError("This order item does not belong to the provided order.")

        # Status gating: only when DELIVERED, never after COMPLETED
        if order.status != OrderStatus.DELIVERED:
            if order.status == OrderStatus.COMPLETED:
                raise serializers.ValidationError("This order is completed and can no longer be refunded.")
            raise serializers.ValidationError("Only delivered orders can be refunded.")

        # Enforce refund window (from your Order.is_refundable property)
        if not order.is_refundable:
            raise serializers.ValidationError("Refund window has expired.")

        # Prevent over-returning across multiple requests
        already_returned = sum(rr.quantity for rr in order_item.return_requests.filter(buyer=user))
        if already_returned + qty > order_item.quantity:
            raise serializers.ValidationError(
                f"Quantity exceeds what you purchased. Already returned: {already_returned}, "
                f"ordered: {order_item.quantity}."
            )

        return attrs
class ReturnRequestImageUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnRequestImage
        fields = ['image']

class ReturnedProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnedProduct
        fields = [
            'id', 'product', 'return_request', 'status', 'quantity',
            'discount_percentage', 'is_sellable', 'seller_approval',
            'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']