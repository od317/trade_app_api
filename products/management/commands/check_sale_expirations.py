from django.core.management.base import BaseCommand
from django.utils import timezone
from products.models import SaleEvent, ProductSale,Product

class Command(BaseCommand):
    help = 'Deactivates expired sales and sale events'

    def handle(self, *args, **options):
        now = timezone.now()
        
        # Expire sale events
        expired_events = SaleEvent.objects.filter(
            end_date__lt=now,
            is_active=True
        )
        event_count = expired_events.count()
        expired_events.update(is_active=False)
        
        # Expire product sales
        expired_sales = ProductSale.objects.filter(
            end_date__lt=now,
            is_active=True
        )
        sale_count = expired_sales.count()
        expired_sales.update(is_active=False)
        
        if event_count or sale_count:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Deactivated {event_count} events and {sale_count} product sales'
                )
            )
        else:
            self.stdout.write("No expired sales found")