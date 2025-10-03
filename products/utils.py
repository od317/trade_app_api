# products/utils.py
from django.db import transaction
from .models import CartItem, Product
from notifications.models import Notification

@transaction.atomic
def reconcile_carts_for_product(product: Product):
    """
    Clamp or remove this product in *all* carts when its stock changes.
    Sends a notification to affected users.
    """
    # Lock all cart items for this product
    items = (CartItem.objects
             .select_for_update()
             .filter(product=product)
             .select_related('cart__user'))

    for ci in items:
        user = ci.cart.user

        # If product is out of stock, remove from cart
        if product.quantity <= 0:
            ci.delete()
            Notification.objects.create(
                user=user,
                notification_type='system_alert',
                message_ar=f"للأسف، نفد مخزون المنتج ({product.name_ar}) وتمت إزالته من سلة التسوق.",
                message_en=f"Unfortunately, {product.name_en} is out of stock and was removed from your cart.",
                content_object=product
            )
            continue

        # If requested qty > available, clamp it
        if ci.quantity > product.quantity:
            ci.quantity = product.quantity
            ci.save(update_fields=['quantity'])
            Notification.objects.create(
                user=user,
                notification_type='system_alert',
                message_ar=f"تم تعديل الكمية لمنتج ({product.name_ar}) في سلتك إلى {product.quantity} بسبب انخفاض المخزون.",
                message_en=f"The quantity of {product.name_en} in your cart was reduced to {product.quantity} due to low stock.",
                content_object=product
            )
