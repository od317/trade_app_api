from rest_framework import serializers
from decimal import Decimal
from .models import Auction, Bid, AuctionStatus
from products.models import Product


class AuctionCreateSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = Auction
        fields = [
            'id', 'title', 'description', 'product_id', 'quantity',
            'start_price', 'reserve_price', 'buy_now_price',
            'min_increment', 'start_at', 'end_at',
        ]

    def validate(self, data):
        start_at = data.get('start_at')
        end_at = data.get('end_at')
        buy_now_price = data.get('buy_now_price')
        start_price = data.get('start_price')
        
        if buy_now_price and start_price and buy_now_price <= start_price:
            raise serializers.ValidationError("Buy now price must be higher than start price.")
        if start_at and end_at and end_at <= start_at:
            raise serializers.ValidationError("end_at must be after start_at.")
        if start_at and end_at:
            delta = end_at - start_at
            if delta.total_seconds() < 2 * 3600:
                raise serializers.ValidationError("Minimum duration is 2 hours.")
            if delta.days > 14:
                raise serializers.ValidationError("Maximum duration is 14 days.")
        return data

    def create(self, validated_data):
        request = self.context['request']
        product_id = validated_data.pop('product_id')
        product = Product.objects.get(pk=product_id, seller=request.user)

        if product.quantity < 1:
            raise serializers.ValidationError("Not enough stock to start auction.")

        # Reserve one unit immediately so it can’t be sold normally
        product.quantity -= 1
        product.save()

        return Auction.objects.create(
            seller=request.user,
            product=product,
            status=AuctionStatus.SUBMITTED,
            **validated_data
        )


class AuctionDetailSerializer(serializers.ModelSerializer):
    product = serializers.SerializerMethodField()
    highest_bid = serializers.SerializerMethodField()
    current_price = serializers.SerializerMethodField()

    class Meta:
        model = Auction
        fields = [
            'id', 'title', 'description', 'status', 'rejection_reason',
            'product', 'quantity',
            'start_price', 'reserve_price', 'buy_now_price',
            'min_increment', 'start_at', 'end_at',
            'auto_extend_window_seconds', 'auto_extend_seconds',
            'approved_at',
            'highest_bid', 'current_price'
        ]

    def get_product(self, obj):
        p = obj.product
        return {
            "id": p.id,
            "name_en": p.name_en,
            "name_ar": p.name_ar,
            "price": str(p.price)
        }

    def get_highest_bid(self, obj):
        top = obj.bids.order_by('-amount', '-created_at').first()
        return str(top.amount) if top else None

    def get_current_price(self, obj):
        top = obj.bids.order_by('-amount', '-created_at').first()
        return str(top.amount if top else obj.start_price)


class PlaceBidSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class AdminDecisionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=[('approve', 'approve'), ('reject', 'reject')])
    reason = serializers.CharField(required=False, allow_blank=True)


class BidSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bid
        fields = ['id', 'auction', 'bidder', 'amount', 'created_at']


class AuctionListSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name_en', read_only=True)
    product_id = serializers.IntegerField(source='product.id', read_only=True)
    subcategory_id = serializers.IntegerField(source='product.category_id', read_only=True)
    seller_id = serializers.IntegerField(source='seller.id', read_only=True)
    seller_email = serializers.EmailField(source='seller.email', read_only=True)
    top_bid = serializers.SerializerMethodField()

    class Meta:
        model = Auction
        fields = [
            'id', 'status', 'start_at', 'end_at',
            'start_price', 'min_increment',
            'created_at',
            'product_id', 'product_name', 'subcategory_id',
            'seller_id', 'seller_email',
            'top_bid',
        ]

    def get_top_bid(self, obj):
        top = obj.bids.order_by('-amount', '-created_at').first()
        return str(top.amount) if top else None