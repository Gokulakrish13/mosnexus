from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from products.models import UserSession


class Command(BaseCommand):
    help = 'Clean up old and inactive user sessions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Remove sessions inactive for more than this many hours (default: 24)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cleaned up without actually deleting'
        )

    def handle(self, *args, **options):
        hours = options['hours']
        dry_run = options['dry_run']
        
        # Calculate cutoff time
        cutoff_time = timezone.now() - timedelta(hours=hours)
        
        # Find sessions to clean up
        old_sessions = UserSession.objects.filter(
            last_activity__lt=cutoff_time
        )
        
        count = old_sessions.count()
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'DRY RUN: Would clean up {count} sessions older than {hours} hours'
                )
            )
            if count > 0:
                self.stdout.write('Sessions to be cleaned:')
                for session in old_sessions[:10]:  # Show first 10
                    self.stdout.write(
                        f'  - {session.user.username}: last active {session.last_activity}'
                    )
                if count > 10:
                    self.stdout.write(f'  ... and {count - 10} more')
        else:
            # Mark old sessions as inactive
            old_sessions.update(is_active=False)
            
            # Also delete sessions older than 7 days to keep database clean
            very_old_cutoff = timezone.now() - timedelta(days=7)
            deleted_count = UserSession.objects.filter(
                last_activity__lt=very_old_cutoff
            ).delete()[0]
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully marked {count} sessions as inactive and deleted {deleted_count} very old sessions'
                )
            )
            
        # Show current active user count
        active_count = UserSession.objects.filter(
            last_activity__gte=timezone.now() - timedelta(minutes=15),
            is_active=True
        ).count()
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Current active users (last 15 minutes): {active_count}'
            )
        )
