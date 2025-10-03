# orders/serializers.py
from rest_framework import serializers
from .models import Order, OrderItem
from products.models import Product
from products.serializers import ProductLanguageSerializer

class ProductOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ['id', 'name_en', 'name_ar', 'price','images']

class OrderItemSerializer(serializers.ModelSerializer):
    product = serializers.SerializerMethodField()
    seller = serializers.StringRelatedField()
    
    class Meta:
        model = OrderItem
        fields = ['id', 'product', 'seller', 'quantity', 'price_at_purchase', 'total_price']
    
    def get_product(self, obj):
        # Use ProductLanguageSerializer for product details
        return ProductLanguageSerializer(
            obj.product,
            context=self.context
        ).data

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, source='items.all')
    status_display = serializers.CharField(source='get_status_display')
    
    class Meta:
        model = Order
        fields = [
            'order_number',
            'id',
            'total_amount',
            'status',
            'status_display',
            'created_at',
            'updated_at',
            'items'
        ]

class ProductOrderSerializer(serializers.ModelSerializer):
    current_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    has_active_discount = serializers.BooleanField(read_only=True)
    active_discount_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True, allow_null=True
    )
    
    class Meta:
        model = Product
        fields = [
            'id', 'name_en', 'name_ar', 'price', 'current_price', 
            'has_active_discount', 'active_discount_percentage', 'images'
        ]

class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, source='items.all')
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    buyer = serializers.StringRelatedField()
    delivery_address = serializers.StringRelatedField()
    
    class Meta:
        model = Order
        fields = [
            'order_number',
            'id',
            'buyer',
            'total_amount',
            'delivery_fee',
            'status',
            'status_display',
            'delivery_address',
            'created_at',
            'updated_at',
            'delivered_at',
            'completed_at',
            'items'
        ]
        read_only_fields = fields