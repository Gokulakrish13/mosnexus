# pylint: disable=missing-class-docstring,unused-variable

from products.models import SystemStatus

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = "Populate initial dashboard data for demo purposes"

    def handle(self, *args, **options):
        system_status, created = SystemStatus.objects.get_or_create(
            pk=1,
            defaults={
                "status": "online",
                "description": "System operational",
                "uptime_percentage": 99.9,
                "active_users": 0,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Created system status record"))

        self.stdout.write(self.style.SUCCESS("Successfully populated dashboard data"))
