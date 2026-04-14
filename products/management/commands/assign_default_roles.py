# pylint: disable=missing-class-docstring
from products.models import CustomUser

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = "Assign default roles to existing users"

    def handle(self, *args, **options):
        users = User.objects.all()
        created_count = 0
        updated_count = 0

        for user in users:
            custom_profile, created = CustomUser.objects.get_or_create(user=user)

            if created:
                created_count += 1
                # Assign role based on existing Django permissions
                if user.is_superuser:
                    custom_profile.role = "super_admin"
                elif user.is_staff:
                    custom_profile.role = "admin"
                else:
                    custom_profile.role = "user"

                custom_profile.stream = "HIC"  # Default stream
                custom_profile.save()

                self.stdout.write(
                    self.style.SUCCESS(f"Created profile for {user.username} with role: {custom_profile.role}")
                )
            elif not custom_profile.role:
                updated_count += 1
                if user.is_superuser:
                    custom_profile.role = "super_admin"
                elif user.is_staff:
                    custom_profile.role = "admin"
                else:
                    custom_profile.role = "user"

                if not custom_profile.stream:
                    custom_profile.stream = "HIC"

                custom_profile.save()

                self.stdout.write(
                    self.style.WARNING(f"Updated profile for {user.username} with role: {custom_profile.role}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully processed {users.count()} users. "
                f"Created {created_count} profiles, updated {updated_count} profiles."
            )
        )
