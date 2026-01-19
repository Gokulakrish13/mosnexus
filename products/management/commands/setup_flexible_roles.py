from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from products.models import Stream, CustomUser, UserRole, UserStreamAccess


class Command(BaseCommand):
    help = 'Setup initial streams and migrate existing user data to flexible role system'

    def handle(self, *args, **options):
        self.stdout.write('Setting up initial streams...')
        
        # Create default streams
        hic_stream, created = Stream.objects.get_or_create(
            name='HIC',
            defaults={
                'description': 'Healthcare Informatics and Computing',
                'is_active': True,
                'allow_public_registration': True,
                'requires_approval': True,
            }
        )
        if created:
            self.stdout.write(f'Created stream: {hic_stream.name}')
        
        pic_stream, created = Stream.objects.get_or_create(
            name='PIC',
            defaults={
                'description': 'Personal Health Solutions',
                'is_active': True,
                'allow_public_registration': True,
                'requires_approval': True,
            }
        )
        if created:
            self.stdout.write(f'Created stream: {pic_stream.name}')
        
        # Create additional streams
        example_stream, created = Stream.objects.get_or_create(
            name='Research',
            defaults={
                'description': 'Research and Development',
                'is_active': True,
                'allow_public_registration': False,
                'requires_approval': True,
            }
        )
        if created:
            self.stdout.write(f'Created stream: {example_stream.name}')
        
        self.stdout.write('Migrating existing user data...')
        
        # Migrate existing users to new role system
        for user in User.objects.all():
            custom_user, created = CustomUser.objects.get_or_create(user=user)
            
            if created:
                self.stdout.write(f'Created CustomUser profile for: {user.username}')
            
            # Assign default roles based on existing Django permissions
            if user.is_superuser:
                # Super admin gets super_admin role
                role, role_created = UserRole.objects.get_or_create(
                    custom_user=custom_user,
                    role='super_admin'
                )
                if role_created:
                    self.stdout.write(f'Assigned super_admin role to: {user.username}')
                
                # Super admins get access to all streams
                for stream in Stream.objects.all():
                    access, access_created = UserStreamAccess.objects.get_or_create(
                        custom_user=custom_user,
                        stream=stream
                    )
                    if access_created:
                        self.stdout.write(f'Granted {stream.name} access to: {user.username}')
                        
            elif user.is_staff:
                # Staff users get admin role
                role, role_created = UserRole.objects.get_or_create(
                    custom_user=custom_user,
                    role='admin'
                )
                if role_created:
                    self.stdout.write(f'Assigned admin role to: {user.username}')
                
                # Admins get access to HIC and PIC by default
                for stream in [hic_stream, pic_stream]:
                    access, access_created = UserStreamAccess.objects.get_or_create(
                        custom_user=custom_user,
                        stream=stream
                    )
                    if access_created:
                        self.stdout.write(f'Granted {stream.name} access to: {user.username}')
                        
            else:
                # Regular users get user role
                if not custom_user.user_roles.exists():
                    role, role_created = UserRole.objects.get_or_create(
                        custom_user=custom_user,
                        role='user'
                    )
                    if role_created:
                        self.stdout.write(f'Assigned user role to: {user.username}')
                
                # Regular users get access to HIC by default (if they have an old stream preference)
                if hasattr(custom_user, 'stream'):
                    # If they had a stream preference, honor it
                    old_stream_name = getattr(custom_user, 'stream', 'HIC')
                    try:
                        old_stream = Stream.objects.get(name=old_stream_name)
                        access, access_created = UserStreamAccess.objects.get_or_create(
                            custom_user=custom_user,
                            stream=old_stream
                        )
                        if access_created:
                            self.stdout.write(f'Granted {old_stream.name} access to: {user.username}')
                    except Stream.DoesNotExist:
                        pass
                else:
                    # Give access to HIC by default
                    access, access_created = UserStreamAccess.objects.get_or_create(
                        custom_user=custom_user,
                        stream=hic_stream
                    )
                    if access_created:
                        self.stdout.write(f'Granted {hic_stream.name} access to: {user.username}')
        
        # Update existing categories, products, etc. to use Stream foreign keys
        self.stdout.write('Updating existing data to use Stream references...')
        
        # This would need to be done carefully based on existing data
        # For now, we assume the migration handles the FK changes
        
        self.stdout.write(
            self.style.SUCCESS('Successfully set up flexible role system!')
        )
