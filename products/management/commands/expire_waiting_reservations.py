"""
Management command to automatically transition waitlist entries from 'waiting' to 'not_allocated'
when the booked time slot has passed without the user rescheduling.

Usage:
    python manage.py expire_waiting_reservations

    # Dry run (no changes, just report)
    python manage.py expire_waiting_reservations --dry-run

Schedule this command to run periodically (e.g., every 15 minutes via cron or scheduler):
    */15 * * * * cd /path/to/project && python manage.py expire_waiting_reservations
"""

# pylint: disable=missing-class-docstring

from products.models import RecurringReservationInstance, ReservationWaitlist

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Expire waitlist/conflict entries whose booked time slot has already passed. "
        'Changes ReservationWaitlist "waiting" → "not_allocated" and '
        'RecurringReservationInstance "conflict"/"scheduled" → "not_allocated".'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be expired without making changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        waiting_entries = ReservationWaitlist.objects.filter(status="waiting")
        expired_count = 0

        for entry in waiting_entries:
            if entry.is_slot_passed():
                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            f"[DRY RUN] Would expire: {entry} "
                            f"(slot: {entry.desired_date} {entry.desired_start_time}-{entry.desired_end_time})"
                        )
                    )
                else:
                    entry.status = "not_allocated"
                    entry.save(update_fields=["status", "updated_at"])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Expired: {entry} → not_allocated "
                            f"(slot: {entry.desired_date} {entry.desired_start_time}-{entry.desired_end_time})"
                        )
                    )
                expired_count += 1

        if expired_count == 0:
            self.stdout.write(self.style.SUCCESS("No waiting waitlist entries have passed their booked slot."))
        else:
            action = "would be" if dry_run else "were"
            self.stdout.write(
                self.style.SUCCESS(f'\n{expired_count} waitlist entries {action} marked as "not_allocated".')
            )

        # Recurring reservation instances: transition conflict/scheduled → not_allocated
        self.stdout.write(self.style.MIGRATE_HEADING("\nChecking recurring reservation instances..."))
        instance_entries = RecurringReservationInstance.objects.filter(status__in=["conflict", "scheduled"])
        instance_expired_count = 0

        for instance in instance_entries:
            if instance.is_slot_passed():
                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            f"[DRY RUN] Would expire instance: {instance} "
                            f"(slot: {instance.reservation_date} {instance.start_time}-{instance.end_time}, "
                            f"status: {instance.status})"
                        )
                    )
                else:
                    instance.status = "not_allocated"
                    instance.save(update_fields=["status", "updated_at"])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Expired instance: {instance} → not_allocated "
                            f"(slot: {instance.reservation_date} {instance.start_time}-{instance.end_time})"
                        )
                    )
                instance_expired_count += 1

        if instance_expired_count == 0:
            self.stdout.write(self.style.SUCCESS("No recurring instances have passed their booked slot."))
        else:
            action = "would be" if dry_run else "were"
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n{instance_expired_count} recurring instances {action} marked as "not_allocated".'
                )
            )
