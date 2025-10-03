from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from wallet.models import Wallet

User = get_user_model()

class Command(BaseCommand):
    help = 'Creates wallet for all users without one'

    def handle(self, *args, **options):
        users_without_wallets = User.objects.filter(wallet__isnull=True)
        count = users_without_wallets.count()
        
        self.stdout.write(f'Creating wallets for {count} users...')
        
        created = 0
        for user in users_without_wallets:
            Wallet.objects.get_or_create(user=user)
            created += 1
        
        self.stdout.write(self.style.SUCCESS(f'Successfully created {created} wallets'))