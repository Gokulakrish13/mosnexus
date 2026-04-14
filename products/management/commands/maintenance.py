"""
Management command to toggle maintenance mode on/off.

Usage:
    python manage.py maintenance --on                                        # Enable (indefinite)
    python manage.py maintenance --on --message "Back by 5 PM IST"           # With custom message
    python manage.py maintenance --on --duration 3d                          # For 3 days
    python manage.py maintenance --on --duration 6h --message "Quick patch"  # For 6 hours + message
    python manage.py maintenance --on --duration 30m                         # For 30 minutes
    python manage.py maintenance --off                                       # Disable immediately
    python manage.py maintenance --status                                    # Check current status

Duration format:  <number><unit>  where unit is  m (minutes), h (hours), or d (days).
                  Examples: 30m, 2h, 3d, 1.5h
"""

# pylint: disable=inconsistent-return-statements,missing-class-docstring,no-else-return,too-complex,too-many-branches,too-many-locals,too-many-statements,unspecified-encoding
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Toggle maintenance mode for the entire application"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--on",
            action="store_true",
            help="Enable maintenance mode",
        )
        group.add_argument(
            "--off",
            action="store_true",
            help="Disable maintenance mode",
        )
        group.add_argument(
            "--status",
            action="store_true",
            help="Show current maintenance mode status",
        )
        parser.add_argument(
            "--message",
            "-m",
            type=str,
            default="",
            help="Custom message to display on the maintenance page",
        )
        parser.add_argument(
            "--duration",
            "-d",
            type=str,
            default="",
            help="Duration for maintenance mode (e.g. 30m, 2h, 3d). Omit for indefinite.",
        )

    def _parse_duration(self, value):
        """Parse a duration string like '3d', '6h', '30m' into a timedelta."""
        match = re.match(r"^(\d+(?:\.\d+)?)\s*([mhd])$", value.strip().lower())
        if not match:
            raise CommandError(
                f'Invalid duration "{value}". Use format: <number><unit> '
                f"where unit is m (minutes), h (hours), or d (days). Examples: 30m, 2h, 3d"
            )
        amount = float(match.group(1))
        unit = match.group(2)
        if unit == "m":
            return timedelta(minutes=amount)
        elif unit == "h":
            return timedelta(hours=amount)
        elif unit == "d":
            return timedelta(days=amount)

    def handle(self, *args, **options):
        flag_file = Path(getattr(settings, "MAINTENANCE_MODE_FLAG_FILE", settings.BASE_DIR / "maintenance.flag"))

        if options["status"]:
            if flag_file.exists():
                try:
                    data = json.loads(flag_file.read_text())
                    msg = data.get("message", "")
                    end_time = data.get("end_time")
                    if end_time:
                        end_dt = datetime.fromisoformat(end_time)
                        now = timezone.now()
                        if timezone.is_naive(end_dt):
                            end_dt = timezone.make_aware(end_dt)
                        remaining = end_dt - now
                        if remaining.total_seconds() <= 0:
                            flag_file.unlink()
                            self.stdout.write(
                                self.style.SUCCESS("Maintenance mode has EXPIRED and has been automatically disabled.")
                            )
                            return
                        hours, remainder = divmod(int(remaining.total_seconds()), 3600)
                        minutes, _ = divmod(remainder, 60)
                        self.stdout.write(
                            self.style.WARNING(
                                f'Maintenance mode is ON — Ends: {end_dt.strftime("%b %d, %Y %I:%M %p %Z")} '
                                f"({hours}h {minutes}m remaining)"
                                f'{" — Message: " + msg if msg else ""}'
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Maintenance mode is ON (indefinite)" f'{" — Message: " + msg if msg else ""}'
                            )
                        )
                except (json.JSONDecodeError, KeyError):
                    # Legacy plain-text flag file
                    msg = flag_file.read_text().strip()
                    self.stdout.write(
                        self.style.WARNING(
                            f"Maintenance mode is ON (indefinite)" f'{" — Message: " + msg if msg else ""}'
                        )
                    )
            else:
                self.stdout.write(self.style.SUCCESS("Maintenance mode is OFF"))
            return

        if options["on"]:
            message = options.get("message", "")
            duration_str = options.get("duration", "")

            data = {"message": message}

            if duration_str:
                delta = self._parse_duration(duration_str)
                end_time = timezone.now() + delta
                data["end_time"] = end_time.isoformat()
                data["duration"] = duration_str

            flag_file.write_text(json.dumps(data, indent=2))

            duration_info = ""
            if duration_str:
                end_display = (timezone.now() + self._parse_duration(duration_str)).strftime("%b %d, %Y %I:%M %p %Z")
                duration_info = f" Duration: {duration_str} (until {end_display})."

            self.stdout.write(
                self.style.WARNING(
                    f"✅ Maintenance mode ENABLED.{duration_info}" f'{" Message: " + message if message else ""}'
                )
            )
            self.stdout.write(
                self.style.NOTICE("All users (except superadmins and bypass IPs) will see the maintenance page.")
            )
            if duration_str:
                self.stdout.write(self.style.NOTICE("Maintenance will auto-expire when the timer runs out."))
            return

        if options["off"]:
            if flag_file.exists():
                flag_file.unlink()
                self.stdout.write(self.style.SUCCESS("✅ Maintenance mode DISABLED. The site is now live."))
            else:
                self.stdout.write(self.style.SUCCESS("Maintenance mode was already off."))
