"""
Management command to clean up audit logs older than a specified number of months.
Run via: python manage.py cleanup_audit_logs
Schedule via cron or Windows Task Scheduler to run periodically (e.g., daily).

If --months or --keep-critical are not specified, defaults are read from SiteSetting.

Examples:
    python manage.py cleanup_audit_logs              # Use SiteSetting defaults
    python manage.py cleanup_audit_logs --months 3   # Override: delete logs older than 3 months
    python manage.py cleanup_audit_logs --dry-run    # Preview what would be deleted
    python manage.py cleanup_audit_logs --keep-critical  # Override: preserve critical logs
"""

# pylint: disable=missing-class-docstring

from datetime import timedelta

from products.models import AuditLog, SiteSetting

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Delete audit log entries older than a specified number of months (reads defaults from SiteSetting)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--months",
            type=int,
            default=None,
            help="Delete audit logs older than this many months (default: from SiteSetting or 6)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many records would be deleted without actually deleting them",
        )
        parser.add_argument(
            "--keep-critical",
            action="store_true",
            default=None,
            help="Keep critical/high severity logs even if older than the cutoff (default: from SiteSetting)",
        )

    def handle(self, *args, **options):
        # Load defaults from SiteSetting
        site_setting = SiteSetting.load()

        months = options["months"]
        if months is None:
            months = getattr(site_setting, "audit_log_retention_months", 6)

        dry_run = options["dry_run"]

        keep_critical = options["keep_critical"]
        if keep_critical is None:
            keep_critical = getattr(site_setting, "audit_log_keep_critical", True)

        cutoff_date = timezone.now() - timedelta(days=months * 30)

        old_logs = AuditLog.objects.filter(timestamp__lt=cutoff_date)

        if keep_critical:
            old_logs = old_logs.exclude(severity__in=["critical", "high"])

        count = old_logs.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY RUN] Would delete {count} audit log entries "
                    f'older than {months} months (before {cutoff_date.strftime("%Y-%m-%d %H:%M")})'
                )
            )
            if keep_critical:
                critical_count = AuditLog.objects.filter(
                    timestamp__lt=cutoff_date, severity__in=["critical", "high"]
                ).count()
                self.stdout.write(self.style.NOTICE(f"  → {critical_count} critical/high entries would be preserved"))
        else:
            if count == 0:
                self.stdout.write(self.style.SUCCESS("No audit log entries to clean up."))
                return

            deleted_count, _ = old_logs.delete()

            # Update last cleanup timestamp in SiteSetting
            site_setting.audit_log_last_cleanup = timezone.now()
            site_setting.save(update_fields=["audit_log_last_cleanup"])

            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully deleted {deleted_count} audit log entries "
                    f'older than {months} months (before {cutoff_date.strftime("%Y-%m-%d %H:%M")})'
                )
            )

            # Log the cleanup action itself
            AuditLog.log(
                action="system_event",
                title=f"Auto-cleanup: Deleted {deleted_count} audit log entries older than {months} months",
                module="settings",
                severity="info",
                description=f'Cutoff date: {cutoff_date.strftime("%Y-%m-%d %H:%M")}. '
                f"Keep critical: {keep_critical}.",
            )
