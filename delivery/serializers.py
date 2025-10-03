# delivery/serializers.py
from rest_framework import serializers
from orders.models import Order

class BuyerMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    phone_number = serializers.CharField()
    # omit password, email, tokens, permissions, etc.

class LocationSerializer(serializers.Serializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    address_line = serializers.CharField(allow_blank=True)

class DeliveryOrderSerializer(serializers.ModelSerializer):
    # show only minimal buyer info
    buyer = serializers.SerializerMethodField()
    buyer_location = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "order_number", "status", "created_at", "assigned_at",
            "buyer", "buyer_location", "total_amount", "delivery_fee"
        ]

    def get_buyer(self, obj):
        u = obj.buyer
        # return only non-sensitive basics
        return {
            "id": u.id,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "phone_number": getattr(u, "phone_number", None),
        }

    def get_buyer_location(self, obj):
        """
        Only include precise coordinates if the delivery person
        is assigned to THIS order (or the view explicitly asks for it).
        Otherwise return None.
        """
        request = self.context.get("request")
        include_precise = self.context.get("include_buyer_location", False)

        if not hasattr(obj.buyer, "profile"):
            return None
        loc = getattr(obj.buyer.profile, "location", None)
        if not loc:
            return None

        # Only the assigned courier OR when explicitly requested in the
        # detail endpoint should see the exact location.
        if include_precise and request and obj.assigned_delivery_id == request.user.id:
            return {
                "latitude": loc.get("latitude"),
                "longitude": loc.get("longitude"),
                "address_line": loc.get("address_line"),
            }
        # Otherwise, hide it
        return None
