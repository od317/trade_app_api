from rest_framework import serializers
from .models import Review
from orders.models import OrderItem, OrderStatus

class ReviewCreateSerializer(serializers.ModelSerializer):
    order_item_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = Review
        fields = ['id', 'order_item_id', 'rating', 'title', 'comment']

    def validate(self, data):
        request = self.context['request']
        oi = OrderItem.objects.select_related('order', 'product').filter(
            id=data['order_item_id'], order__buyer=request.user
        ).first()
        if not oi:
            raise serializers.ValidationError("Order item not found.")

        if oi.order.status not in [OrderStatus.DELIVERED, OrderStatus.COMPLETED]:
            raise serializers.ValidationError("You can review only after delivery.")

        # ensure not already reviewed this product in this order
        if Review.objects.filter(buyer=request.user, product=oi.product, order=oi.order).exists():
            raise serializers.ValidationError("You already reviewed this product for this order.")

        data['_order_item'] = oi
        return data

    def create(self, validated_data):
        request = self.context['request']
        oi = validated_data.pop('_order_item')
        return Review.objects.create(
            buyer=request.user,
            product=oi.product,
            order=oi.order,
            order_item=oi,
            **validated_data
        )

class ReviewSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name_en', read_only=True)
    class Meta:
        model = Review
        fields = ['id', 'product', 'product_name', 'order', 'rating', 'title', 'comment', 'created_at', 'updated_at', 'is_edited']

class ReviewUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ['rating', 'title', 'comment']

    def update(self, instance, validated_data):
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.is_edited = True
        instance.save()
        return instance

class RatingOnlySerializer(serializers.Serializer):
    order_item_id = serializers.IntegerField()
    rating = serializers.IntegerField(min_value=1, max_value=5)

    def validate(self, data):
        from orders.models import OrderItem, OrderStatus
        request = self.context['request']

        oi = OrderItem.objects.select_related('order', 'product').filter(
            id=data['order_item_id'], order__buyer=request.user
        ).first()
        if not oi:
            raise serializers.ValidationError("Order item not found.")

        if oi.order.status not in [OrderStatus.DELIVERED, OrderStatus.COMPLETED]:
            raise serializers.ValidationError("You can rate only after delivery.")

        # one rating per product per order
        from .models import Review
        if Review.objects.filter(buyer=request.user, product=oi.product, order=oi.order).exists():
            raise serializers.ValidationError("You already reviewed/rated this product for this order.")

        data['_oi'] = oi
        return data

    def create(self, validated_data):
        from .models import Review
        oi = validated_data.pop('_oi')
        return Review.objects.create(
            buyer=self.context['request'].user,
            product=oi.product,
            order=oi.order,
            order_item=oi,
            rating=validated_data['rating'],
            title='',
            comment=''
        )