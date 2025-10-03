# products/management/commands/deactivate_expired_discounts.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from products.models import Product

class Command(BaseCommand):
    help = 'Deactivates expired standalone discounts on products'

    def handle(self, *args, **options):
        now = timezone.now()
        
        # Find products with expired standalone discounts
        expired_products = Product.objects.filter(
            has_standalone_discount=True,
            standalone_discount_end__lt=now
        )

        count = expired_products.count()
        
        # Deactivate them
        expired_products.update(
            has_standalone_discount=False,
            standalone_discount_start=None,
            standalone_discount_end=None
        )
        
        if count:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully deactivated {count} expired standalone discounts'
                )
            )
        else:
            self.stdout.write("No expired standalone discounts found")