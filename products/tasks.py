from celery import shared_task
from django.utils import timezone
from products.models import SaleEvent, ProductSale

@shared_task
def expire_sales():
    now = timezone.now()
    
    # Update sale events
    SaleEvent.objects.filter(
        end_date__lt=now,
        is_active=True
    ).update(is_active=False)
    
    # Update product sales
    ProductSale.objects.filter(
        end_date__lt=now,
        is_active=True
    ).update(is_active=False)
    
    return f"Checked sales at {now}"