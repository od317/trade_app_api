from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from products.models import SaleEvent
from accounts.models import User

class Command(BaseCommand):
    help = 'Creates test sales for development'

    def handle(self, *args, **options):
        admin = User.objects.filter(is_superuser=True).first()
        if not admin:
            self.stdout.write(self.style.ERROR('No admin user found'))
            return

        # Expired sale
        SaleEvent.objects.create(
            name="TEST - Expired Sale",
            description="Should be inactive",
            start_date=timezone.now() - timedelta(days=2),
            end_date=timezone.now() - timedelta(days=1),
            created_by=admin
        )

        # Current sale
        SaleEvent.objects.create(
            name="TEST - Active Sale",
            description="Should be active",
            start_date=timezone.now() - timedelta(hours=1),
            end_date=timezone.now() + timedelta(days=1),
            created_by=admin
        )

        self.stdout.write(self.style.SUCCESS('Created test sales'))