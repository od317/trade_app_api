# orders/services.py
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from itertools import groupby
from operator import attrgetter
from notifications.utils import send_order_notification

# Import models from other apps
from products.models import Cart, CartItem, Product
from accounts.models import User
from wallet.models import Wallet, Transaction
from notifications.models import Notification
from decimal import Decimal, ROUND_HALF_UP
from itertools import groupby
from operator import attrgetter
from django.conf import settings
# Import models from current app
from .models import Order, OrderItem, OrderStatus


POINTS_PER_CURRENCY_UNIT = Decimal('10.00')   # 1 point per 10.00 of revenue
VERIFICATION_THRESHOLD_DEFAULT = 500    

FEE_RATE = Decimal(getattr(settings, 'PLATFORM_FEE_RATE', '0.04'))
MIN_FEE = Decimal(getattr(settings, 'PLATFORM_MIN_FEE', '0.00'))
MAX_FEE = (Decimal(settings.PLATFORM_MAX_FEE)
           if getattr(settings, 'PLATFORM_MAX_FEE', None) else None)
POINTS_PER_CURRENCY_UNIT = Decimal(getattr(settings, 'POINTS_PER_CURRENCY_UNIT', '10.00'))


class CheckoutService:
    @classmethod
    def process_checkout(cls, user, delivery_fee=Decimal('0.00')):
        with transaction.atomic():
            
            profile = getattr(user, 'profile', None)
            lat = getattr(profile, 'latitude', None)
            lng = getattr(profile, 'longitude', None)
            if lat is None or lng is None:
                raise ValueError("Please set your location before placing an order.")
            # Lock the cart and wallet for the transaction
            cart = Cart.objects.select_for_update().get(user=user)
            wallet = Wallet.objects.select_for_update().get(user=user)
            
            # Calculate total (products + delivery fee)
            cart_items = CartItem.objects.filter(cart=cart).select_related('product')
            if not cart_items.exists():
                raise ValueError("Cart has no items")
            
            # Validate stock and availability
            for item in cart_items:
                if item.product.quantity < item.quantity:
                    raise ValueError(
                        f"Not enough stock for {item.product.name_en}. "
                        f"Available: {item.product.quantity}, Requested: {item.quantity}"
                    )

            product_total = sum(
                Decimal(item.product.current_price) * item.quantity 
                for item in cart_items
            )
            total_amount = product_total + Decimal(delivery_fee)
            
            # Check available balance
            if wallet.available_balance < total_amount:
                raise ValueError(
                    f"Insufficient available funds. Available: {wallet.available_balance}, Needed: {total_amount}"
                )
            
            profile = getattr(user, 'profile', None)
            # Create order with delivery fee
            order = Order.objects.create(
                buyer=user,
                total_amount=total_amount,
                delivery_fee=delivery_fee,
                status=OrderStatus.CREATED,
                shipping_latitude=getattr(profile, 'latitude', None),
                shipping_longitude=getattr(profile, 'longitude', None),
                shipping_address_line=getattr(profile, 'address_line', '') or (user.address or ''),
                shipping_city=getattr(profile, 'city', ''),
                shipping_region=getattr(profile, 'region', ''),
                shipping_country=getattr(profile, 'country', ''),
                shipping_postal_code=getattr(profile, 'postal_code', ''),
            )
            
            # Hold funds in escrow
            wallet.hold_funds(total_amount)
            
            # Create transaction record for escrow hold
            Transaction.objects.create(
                wallet=wallet,
                amount=-total_amount,
                transaction_type='escrow_hold',  # Use string value directly
                description=f"Escrow hold for Order #{order.order_number}",
                reference=f"ESCROW_HOLD_{order.order_number}",
                is_successful=True
            )
            
            # Create order items
            for item in cart_items:
                OrderItem.objects.create(
                    order=order,
                    product=item.product,
                    seller=item.product.seller,
                    quantity=item.quantity,
                    price_at_purchase=item.product.current_price,
                    total_price=Decimal(item.product.current_price) * item.quantity
                )
                
                # Update product quantities
                product = Product.objects.select_for_update().get(pk=item.product.pk)
                old_quantity = product.quantity
                product.quantity -= item.quantity
                product.save()

                from products.utils import reconcile_carts_for_product
                reconcile_carts_for_product(product)

                LOW_STOCK_THRESHOLD = 5
                if product.quantity <= LOW_STOCK_THRESHOLD and old_quantity > LOW_STOCK_THRESHOLD:
                    Notification.objects.create(
                        user=product.seller,
                        notification_type='low_stock',
                        message_ar=f"انخفض مخزون منتجك ({product.name_ar}) إلى {product.quantity}. يرجى إعادة التعبئة.",
                        message_en=f"Your product ({product.name_en}) stock is low: {product.quantity} left. Please restock.",
                        content_object=product,
                    )

            # Clear the cart
            cart_items.delete()
            send_order_notification(user, order, 'order_created')
            return order

    @classmethod
    def complete_order(cls, order_id):
        # helpers / config
        def _to_dec(x): return Decimal(str(x))
        FEE_RATE = Decimal(getattr(settings, 'PLATFORM_FEE_RATE', '0.04'))
        MIN_FEE = Decimal(getattr(settings, 'PLATFORM_MIN_FEE', '0.00'))
        MAX_FEE = (Decimal(settings.PLATFORM_MAX_FEE)
                    if getattr(settings, 'PLATFORM_MAX_FEE', None) else None)
        POINTS_PER_CURRENCY_UNIT = Decimal(getattr(settings, 'POINTS_PER_CURRENCY_UNIT', '10.00'))

        def _calc_fee(amount: Decimal) -> Decimal:
            fee = (amount * FEE_RATE).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if MIN_FEE:
                fee = max(fee, MIN_FEE)
            if MAX_FEE is not None:
                fee = min(fee, MAX_FEE)
            return fee

        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order_id)

            # Preconditions
            if order.status != OrderStatus.DELIVERED:
                raise ValueError("Order must be delivered before completion")
            if not order.delivered_at:
                raise ValueError("Delivery timestamp missing")
            if timezone.now() < order.delivered_at + timezone.timedelta(days=3):
                raise ValueError("Refund window still active (3 days after delivery)")

            # Release buyer escrow "held" (bookkeeping)
            buyer_wallet = Wallet.objects.select_for_update().get(user=order.buyer)
            buyer_wallet.held_balance -= order.total_amount
            buyer_wallet.save()

            Transaction.objects.create(
                wallet=buyer_wallet,
                amount=order.total_amount,  # ledger-only release; balance unchanged
                transaction_type=Transaction.TransactionType.ESCROW_RELEASE,
                description=f"Escrow release for Order #{order.order_number}",
                reference=f"ESCROW_RELEASE_{order.order_number}",
                is_successful=True
            )

            # Platform wallet (to collect fees)
            platform_wallet = None
            platform_user_id = getattr(settings, 'PLATFORM_WALLET_USER_ID', None)
            if platform_user_id:
                platform_wallet = Wallet.objects.select_for_update().get(user_id=platform_user_id)

            # Group items by seller once
            items_by_seller = groupby(
                sorted(order.items.all(), key=attrgetter('seller')),
                key=attrgetter('seller')
            )

            for seller, items in items_by_seller:
                items = list(items)
                gross = sum(_to_dec(i.total_price) for i in items)

                fee = _calc_fee(gross)
                net = (gross - fee).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                # Pay seller NET
                seller_wallet = Wallet.objects.select_for_update().get(user=seller)
                seller_wallet.balance += net
                seller_wallet.save()

                Transaction.objects.create(
                    wallet=seller_wallet,
                    amount=net,
                    transaction_type=Transaction.TransactionType.PAYMENT,
                    description=f"Payout for Order #{order.order_number} (after {int(FEE_RATE*100)}% fee)",
                    reference=f"ORDER_PAY_NET_{order.order_number}",
                    is_successful=True
                )

                # Platform commission (FEE)
                if platform_wallet and fee > 0:
                    platform_wallet.balance += fee
                    platform_wallet.save()
                    Transaction.objects.create(
                        wallet=platform_wallet,
                        amount=fee,
                        transaction_type=Transaction.TransactionType.FEE,
                        description=f"Commission from Order #{order.order_number} (seller {seller.id})",
                        reference=f"ORDER_FEE_{order.order_number}",
                        is_successful=True
                    )

                # Award points on NET (e.g., 1 point per 10.00)
                pts = int((net / POINTS_PER_CURRENCY_UNIT)
                            .to_integral_value(rounding=ROUND_HALF_UP))
                if pts > 0 and hasattr(seller, "add_seller_points"):
                    before = getattr(seller, "points", 0)
                    seller.add_seller_points(pts)
                    after = getattr(seller, "points", before + pts)

                    # Optional: verification threshold notification
                    threshold = getattr(seller, "VERIFICATION_THRESHOLD", 500)
                    if (not getattr(seller, "is_verified_seller", False)) and before < threshold <= after:
                        Notification.objects.create(
                            user=seller,
                            notification_type='seller_verified',
                            message_ar='لقد أصبحت بائعًا موثقًا! تهانينا.',
                            message_en='You are now a verified seller! Congratulations.',
                            content_object=seller
                        )

                # Notify seller (gross/fee/net)
                Notification.objects.create(
                    user=seller,
                    notification_type='seller_payment',
                    message_ar=(f"تم إكمال الطلب {order.order_number}. مجموعك {gross}، "
                                f"العمولة {fee}، الصافي {net} أُضيف لمحفظتك."),
                    message_en=(f"Order {order.order_number} completed. Gross {gross}, "
                                f"fee {fee}, net {net} added to your wallet."),
                    content_object=order
                )

            # Finalize order
            order.status = OrderStatus.COMPLETED
            order.completed_at = timezone.now()
            order.save()

            Notification.objects.create(
                user=order.buyer,
                notification_type='order_completed',
                message_ar=f"تم إكمال طلبك رقم {order.order_number}. شكراً لتسوقك معنا.",
                message_en=f"Your order #{order.order_number} has been completed. Thank you for shopping with us!",
                content_object=order
            )

            return order



class OrderService:
    CANCEL_PENALTY = Decimal('0.10')  # 10% penalty

    @classmethod
    def cancel_order(cls, order_id, user):
        with transaction.atomic():
            order = Order.objects.select_for_update().get(
                pk=order_id,
                buyer=user,
                status__in=[OrderStatus.CREATED, OrderStatus.PROCESSING, OrderStatus.SHIPPED]
            )
            
            buyer_wallet = Wallet.objects.select_for_update().get(user=user)
            
            # Calculate refund (total minus penalty and delivery fee)
            refund_amount = (order.total_amount - order.delivery_fee) * (1 - cls.CANCEL_PENALTY)
            
            # Release escrow funds
            buyer_wallet.held_balance -= order.total_amount
            buyer_wallet.balance += refund_amount
            buyer_wallet.save()
            
            # Record transactions
            Transaction.objects.create(
                wallet=buyer_wallet,
                amount=refund_amount,
                transaction_type=Transaction.TransactionType.REFUND,
                description=f"Order cancellation (10% penalty + delivery fee kept)",
                reference=f"ORDER_CANCEL_{order.order_number}",
                is_successful=True
            )
            
            # Restock products
            for item in order.items.all():
                product = Product.objects.select_for_update().get(pk=item.product.pk)
                product.quantity += item.quantity
                product.save()
            
            order.status = OrderStatus.CANCELLED
            order.save()
            return order


class RefundService:
    REFUND_WINDOW_DAYS = 3

    @classmethod
    def process_refund(cls, order_id, user):
        with transaction.atomic():
            # Lock and get the order
            order = Order.objects.select_for_update().get(
                pk=order_id,
                buyer=user,
                status=OrderStatus.DELIVERED
            )
            
            # Validate refund window
            if timezone.now() > order.delivered_at + timezone.timedelta(days=cls.REFUND_WINDOW_DAYS):
                raise ValueError("Refund window expired (3 days after delivery)")
            
            # Get buyer's wallet with lock
            buyer_wallet = Wallet.objects.select_for_update().get(user=user)
            
            # Calculate refund amount (total - delivery fee)
            refund_amount = order.total_amount - order.delivery_fee
            
            
            # 2. Create transaction records
            Transaction.objects.create(
                wallet=buyer_wallet,
                amount=refund_amount,
                transaction_type=Transaction.TransactionType.REFUND,
                description=f"Refund for Order #{order.order_number} (kept {order.delivery_fee} delivery fee)",
                reference=f"REFUND_{order.order_number}",
                is_successful=True
            )
            
            # 3. Restock products
            for item in order.items.all():
                product = Product.objects.select_for_update().get(pk=item.product.pk)
                product.quantity += item.quantity
                product.save()
            
            # 4. Update status
            order.status = OrderStatus.REFUNDED
            order.save()
            send_order_notification(user, order, 'order_created')
            return order