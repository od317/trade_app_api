from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Avg
from .models import Review

def _recalc_product_rating(product):
    agg = product.reviews.aggregate(avg=Avg('rating'))
    product.rating = agg['avg'] or None  # keep None if no reviews
    product.save(update_fields=['rating'])

@receiver(post_save, sender=Review)
def on_review_save(sender, instance, **kwargs):
    _recalc_product_rating(instance.product)

@receiver(post_delete, sender=Review)
def on_review_delete(sender, instance, **kwargs):
    _recalc_product_rating(instance.product)
