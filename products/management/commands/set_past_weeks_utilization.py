# pylint: disable=missing-class-docstring
from datetime import date

from products.models import HolisticWeeklyData

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Set utilization_percentage to 100 for all past weeks in the current year."

    def handle(self, *args, **options):
        today = date.today()
        current_week = today.isocalendar()[1]
        current_year = today.year

        updated_count = (
            HolisticWeeklyData.objects.filter(year=current_year, week_number__lt=current_week)
            .exclude(utilization_percentage=100)
            .update(utilization_percentage=100)
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully updated {updated_count} records to 100% utilization for past weeks in {current_year}."
            )
        )
