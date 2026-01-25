from django.db import models
from django.contrib.auth import get_user_model
User = get_user_model()
from django.core.files.storage import default_storage
from datetime import date, timedelta
import os

# Create your models here.

class Category(models.Model):
    name = models.CharField(max_length=255, unique=True)
    serial_number = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, related_name='created_categories', on_delete=models.SET_NULL, null=True, blank=True)
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='categories')

    def __str__(self):
        return f"{self.name} ({self.serial_number})"

class Product(models.Model):
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='products')
    category = models.ForeignKey(Category, related_name='products', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    serial_number = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, related_name='created_products', on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, related_name='updated_products', on_delete=models.SET_NULL, null=True, blank=True)
    status_choices = [
        ('Active', 'Active'),
        ('Not Active', 'Not Active'),
        ('Scraped', 'Scraped'),
        ('Hand-Overed', 'Hand-Overed'),
    ]
    status = models.CharField(max_length=20, choices=status_choices, default='Active')
    handover_team_type = models.CharField(max_length=20, blank=True, null=True)  # Internal/External
    handover_external_team = models.CharField(max_length=255, blank=True, null=True)
    handover_owner = models.CharField(max_length=255, blank=True, null=True)
    location = models.ForeignKey('Location', null=True, blank=True, on_delete=models.SET_NULL)
    issue_description = models.TextField(blank=True, null=True)
    twelve_nc = models.CharField(max_length=255, blank=True, null=True)  # 12NC Information

    def __str__(self):
        return f"{self.name} ({self.serial_number})"

class ProductImage(models.Model):
    product = models.ForeignKey(Product, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='product_images/')

    def __str__(self):
        return f"Image for {self.product.name}"

class ProductHistory(models.Model):
    product = models.ForeignKey(Product, related_name='history', on_delete=models.CASCADE)
    action = models.CharField(max_length=32)  # 'created' or 'edited'
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField(blank=True)

    def __str__(self):
        return f"{self.product.name} - {self.action} by {self.user} at {self.timestamp}"

class SystemAllocation(models.Model):
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='system_allocations')
    SYSTEM_CHOICES = [
        ('Z70 Full system', 'Z70 Full system'),
        ('Z50 Table top', 'Z50 Table top'),
        ('Z90 Full system', 'Z90 Full system'),
        ('Z70/90 Rack System', 'Z70/90 Rack System'),
        ('Z70/90 Table top', 'Z70/90 Table top'),
        ('Z90 Table top', 'Z90 Table top'),
        ('Z30 Table top', 'Z30 Table top'),
        ('Z10 Table top', 'Z10 Table top'),
    ]
    system_type = models.CharField(max_length=64, choices=SYSTEM_CHOICES)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    blocked_for_participant = models.ForeignKey('Participant', null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"{self.system_type} blocked by {self.user} from {self.start_date} to {self.end_date}"

class Participant(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.email})"

class Location(models.Model):
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='locations')
    name = models.CharField(max_length=128, unique=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class System(models.Model):
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='systems')
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Not Active', 'Not Active'),
        ('Issue', 'Issue in the system'),
        ('Used', 'Used by other team'),
        ('Removed', 'Removed/Dismantled'),
    ]
    HEALTH_CHOICES = [
        ('Excellent', 'Excellent'),
        ('Good', 'Good'),
        ('Warning', 'Warning'),
        ('Critical', 'Critical'),
    ]    
    name = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    nc_details = models.TextField(blank=True, null=True)  # 12NC Details field
    health = models.CharField(max_length=20, choices=HEALTH_CHOICES, default='good')
    utilization_percentage = models.FloatField(default=0.0)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    
    def get_status_display(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)
    
    def get_health_display(self):
        return dict(self.HEALTH_CHOICES).get(self.health, self.health)
    
    def get_current_downtime(self):
        """Get any ongoing downtime for this system"""
        from django.utils import timezone
        return self.downtime_events.filter(
            status='ongoing',
            end_time__isnull=True
        ).first()
    
    def is_currently_down(self):
        """Check if system is currently experiencing downtime"""
        return self.get_current_downtime() is not None
    
    def get_downtime_metrics(self, days=30):
        """Get downtime metrics for the specified period"""
        from django.utils import timezone
        from datetime import timedelta
        
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Get or create metrics for this period
        metrics, created = SystemDowntimeMetrics.objects.get_or_create(
            system=self,
            period_start=start_date,
            period_end=end_date,
            defaults={'availability_percentage': 100.0}
        )
        
        # Recalculate if needed
        if created or metrics.updated_at < timezone.now() - timedelta(hours=1):
            metrics.calculate_metrics()
        
        return metrics
    
    def get_availability_percentage(self, days=30):
        """Get system availability percentage for the specified period"""
        metrics = self.get_downtime_metrics(days)
        return metrics.availability_percentage
    
    def get_total_downtime_hours(self, days=30):
        """Get total downtime hours for the specified period"""
        metrics = self.get_downtime_metrics(days)
        return metrics.total_downtime_hours
    
    def get_mttr(self, days=30):
        """Get Mean Time To Repair for the specified period"""
        metrics = self.get_downtime_metrics(days)
        return metrics.mean_time_to_repair_hours
    
    def get_mtbf(self, days=30):
        """Get Mean Time Between Failures for the specified period"""
        metrics = self.get_downtime_metrics(days)
        return metrics.mean_time_between_failures_hours

class SystemMetrics(models.Model):
    system = models.ForeignKey('System', related_name='metrics', on_delete=models.CASCADE)
    usage_hours = models.FloatField(default=0.0)
    total_allocations = models.IntegerField(default=0)
    last_allocation_date = models.DateTimeField(null=True, blank=True)
    average_session_duration = models.DurationField(null=True, blank=True)
    uptime_percentage = models.FloatField(default=100.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Metrics for {self.system.name}"

class SystemDowntime(models.Model):
    """
    Track system downtime events for comprehensive downtime metrics and analysis
    """
    DOWNTIME_TYPES = [
        ('planned_maintenance', 'Planned Maintenance'),
        ('unplanned_maintenance', 'Unplanned Maintenance'),
        ('system_failure', 'System Failure'),
        ('hardware_failure', 'Hardware Failure'),
        ('software_issue', 'Software Issue'),
        ('network_issue', 'Network Issue'),
        ('power_outage', 'Power Outage'),
        ('environmental', 'Environmental Issue'),
        ('other', 'Other'),
    ]
    
    IMPACT_LEVELS = [
        ('low', 'Low Impact'),
        ('medium', 'Medium Impact'),
        ('high', 'High Impact'),
        ('critical', 'Critical Impact'),
    ]
    
    STATUS_CHOICES = [
        ('ongoing', 'Ongoing'),
        ('resolved', 'Resolved'),
        ('investigating', 'Under Investigation'),
        ('escalated', 'Escalated'),
    ]
    
    system = models.ForeignKey('System', related_name='downtime_events', on_delete=models.CASCADE)
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='downtime_events')
    
    # Downtime event details
    start_time = models.DateTimeField(help_text="When the downtime started")
    end_time = models.DateTimeField(null=True, blank=True, help_text="When the downtime was resolved")
    downtime_type = models.CharField(max_length=30, choices=DOWNTIME_TYPES, default='other')
    impact_level = models.CharField(max_length=10, choices=IMPACT_LEVELS, default='medium')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='ongoing')
    
    # Description and details
    title = models.CharField(max_length=255, help_text="Brief title describing the downtime")
    description = models.TextField(help_text="Detailed description of the downtime incident")
    root_cause = models.TextField(blank=True, null=True, help_text="Root cause analysis")
    resolution_steps = models.TextField(blank=True, null=True, help_text="Steps taken to resolve the issue")
    
    # People involved
    reported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reported_downtimes')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_downtimes')
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_downtimes')
    
    # Tracking and notification
    users_affected = models.ManyToManyField(User, blank=True, related_name='affected_by_downtimes')
    external_ticket_id = models.CharField(max_length=100, blank=True, null=True, help_text="External ticket system reference")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-start_time']
        verbose_name = 'System Downtime'
        verbose_name_plural = 'System Downtimes'
    
    def __str__(self):
        return f"{self.system.name} - {self.title} ({self.start_time})"
    
    @property
    def duration(self):
        """Calculate the duration of the downtime"""
        if self.end_time:
            return self.end_time - self.start_time
        else:
            # Ongoing downtime
            from django.utils import timezone
            return timezone.now() - self.start_time
    
    @property
    def duration_hours(self):
        """Get duration in hours as float"""
        return self.duration.total_seconds() / 3600
    
    @property
    def is_ongoing(self):
        """Check if downtime is still ongoing"""
        return self.status == 'ongoing' or self.end_time is None
    
    def get_mttr(self):
        """Mean Time To Repair for this incident"""
        if self.end_time:
            return self.duration
        return None
    
    def resolve(self, resolved_by_user=None, resolution_notes=None):
        """Mark downtime as resolved"""
        from django.utils import timezone
        self.end_time = timezone.now()
        self.status = 'resolved'
        if resolved_by_user:
            self.resolved_by = resolved_by_user
        if resolution_notes:
            self.resolution_steps = resolution_notes
        self.save()

class SystemDowntimeMetrics(models.Model):
    """
    Aggregated downtime metrics for systems over specific time periods
    """
    system = models.ForeignKey('System', related_name='downtime_metrics', on_delete=models.CASCADE)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    
    # Calculated metrics
    total_downtime_hours = models.FloatField(default=0.0)
    total_incidents = models.IntegerField(default=0)
    planned_downtime_hours = models.FloatField(default=0.0)
    unplanned_downtime_hours = models.FloatField(default=0.0)
    
    # Availability metrics
    availability_percentage = models.FloatField(default=100.0)
    uptime_percentage = models.FloatField(default=100.0)
    
    # MTTR and MTBF metrics
    mean_time_to_repair_hours = models.FloatField(null=True, blank=True, help_text="Average time to resolve incidents")
    mean_time_between_failures_hours = models.FloatField(null=True, blank=True, help_text="Average time between incidents")
    
    # Most common issues
    most_common_downtime_type = models.CharField(max_length=30, blank=True, null=True)
    most_common_impact_level = models.CharField(max_length=10, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-period_end']
        unique_together = ('system', 'period_start', 'period_end')
        verbose_name = 'Downtime Metrics'
        verbose_name_plural = 'Downtime Metrics'
    
    def __str__(self):
        return f"{self.system.name} metrics ({self.period_start.date()} - {self.period_end.date()})"
    
    def calculate_metrics(self):
        """Recalculate all metrics for this period"""
        from django.db.models import Count
        from django.utils import timezone
        
        downtimes = SystemDowntime.objects.filter(
            system=self.system,
            start_time__gte=self.period_start,
            start_time__lte=self.period_end
        )
        
        # Basic counts
        self.total_incidents = downtimes.count()
        
        # Calculate total downtime hours
        total_hours = 0
        planned_hours = 0
        unplanned_hours = 0
        
        for downtime in downtimes:
            hours = downtime.duration_hours
            total_hours += hours
            
            if 'planned' in downtime.downtime_type:
                planned_hours += hours
            else:
                unplanned_hours += hours
        
        self.total_downtime_hours = total_hours
        self.planned_downtime_hours = planned_hours
        self.unplanned_downtime_hours = unplanned_hours
        
        # Calculate availability (assuming 24/7 operation)
        period_hours = (self.period_end - self.period_start).total_seconds() / 3600
        if period_hours > 0:
            self.availability_percentage = max(0, (period_hours - total_hours) / period_hours * 100)
            self.uptime_percentage = self.availability_percentage
        
        # Calculate MTTR
        resolved_downtimes = downtimes.filter(status='resolved', end_time__isnull=False)
        if resolved_downtimes.exists():
            total_repair_time = 0
            repair_count = 0
            for downtime in resolved_downtimes:
                if downtime.end_time and downtime.start_time:
                    repair_duration = (downtime.end_time - downtime.start_time).total_seconds() / 3600
                    total_repair_time += repair_duration
                    repair_count += 1
            
            if repair_count > 0:
                self.mean_time_to_repair_hours = total_repair_time / repair_count
        
        # Calculate MTBF
        if self.total_incidents > 1:
            self.mean_time_between_failures_hours = period_hours / self.total_incidents
        
        # Find most common issues
        common_type = downtimes.values('downtime_type').annotate(
            count=Count('id')
        ).order_by('-count').first()
        if common_type:
            self.most_common_downtime_type = common_type['downtime_type']
        
        common_impact = downtimes.values('impact_level').annotate(
            count=Count('id')
        ).order_by('-count').first()
        if common_impact:
            self.most_common_impact_level = common_impact['impact_level']
        
        self.save()

class Stream(models.Model):
    name = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Stream-specific settings
    allow_public_registration = models.BooleanField(default=True, help_text="Allow users to request access during registration")
    requires_approval = models.BooleanField(default=True, help_text="Require admin approval for access")

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
    
    def get_active_users_count(self):
        """Get count of users with access to this stream.
        UserStreamAccess links to CustomUser via 'custom_user'; CustomUser links to Django User via 'user'.
        """
        return self.userstreamaccess_set.filter(custom_user__user__is_active=True).count()

class SystemStatusHistory(models.Model):
    system = models.ForeignKey('System', related_name='status_history', on_delete=models.CASCADE)
    status = models.CharField(max_length=20)
    description = models.TextField(blank=True)
    assignee = models.CharField(max_length=255, blank=True, null=True)
    updated_by = models.CharField(max_length=255, blank=True, null=True)
    updated_at = models.DateTimeField(null=True, blank=True)  # Allow setting custom timestamps

    def get_status_display(self):
        # Use System.STATUS_CHOICES for mapping
        choices = dict(System.STATUS_CHOICES)
        return choices.get(self.status, self.status)

    def __str__(self):
        return f"{self.system.name} - {self.status} by {self.updated_by} at {self.updated_at}"

class UserDataVersion(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.CharField(max_length=255, blank=True)
    data_file = models.FileField(upload_to='user_backups/', null=True, blank=True)
    version_number = models.PositiveIntegerField(default=1)
    version_str = models.CharField(max_length=20, default='v1.0.0.1')
    # Optionally, you can store a JSON/text snapshot instead of a file
    # snapshot = models.TextField(blank=True)

    def __str__(self):
        return f"Backup {self.id} at {self.created_at}"

class StreamDeletionHistory(models.Model):
    stream_name = models.CharField(max_length=64)
    deleted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    deleted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.stream_name} deleted by {self.deleted_by} at {self.deleted_at}"

class ZenitionProduct(models.Model):
    name = models.CharField(max_length=255, unique=True)
    # Add other fields if needed
    def __str__(self):
        return self.name

class ProductEntry(models.Model):
    PRODUCT_TYPE_CHOICES = [
        ('OS', 'OS'),
        ('Binaries', 'Binaries'),
    ]
    zenition_product = models.ForeignKey(ZenitionProduct, related_name='entries', on_delete=models.CASCADE)
    entry_type = models.CharField(max_length=20, choices=PRODUCT_TYPE_CHOICES)
    category = models.CharField(max_length=255)  # This is the type (MVS/Stand PC/Apps PC)
    subcategory = models.CharField(max_length=255, blank=True, null=True)
    link = models.URLField(max_length=500)
    os_system_type = models.ForeignKey('OSSystemType', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='OS System Type')
    binaries_system_type = models.ForeignKey('BinariesSystemType', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Binaries System Type')
    
    def __str__(self):
        return f'{self.zenition_product.name} - {self.entry_type} - {self.category} - {self.subcategory}'

class OSSystemType(models.Model):
    name = models.CharField(max_length=255, unique=True, verbose_name='OS System Type')
    description = models.TextField(blank=True, null=True, verbose_name='Description')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, related_name='created_os_system_types', on_delete=models.SET_NULL, null=True, blank=True)
    updated_by = models.ForeignKey(User, related_name='updated_os_system_types', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = 'OS System Type'
        verbose_name_plural = 'OS System Types'
        ordering = ['name']

    def __str__(self):
        return self.name

class BinariesSystemType(models.Model):
    name = models.CharField(max_length=255, unique=True, verbose_name='Binaries System Type')
    description = models.TextField(blank=True, null=True, verbose_name='Description')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, related_name='created_binaries_system_types', on_delete=models.SET_NULL, null=True, blank=True)
    updated_by = models.ForeignKey(User, related_name='updated_binaries_system_types', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = 'Binaries System Type'
        verbose_name_plural = 'Binaries System Types'
        ordering = ['name']

    def __str__(self):
        return self.name

class Communication(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    page = models.CharField(max_length=64, default='build_os_info')

    def __str__(self):
        return f"{self.user.username}: {self.message[:30]}{'...' if len(self.message) > 30 else ''}"

class CommunicationAttachment(models.Model):
    communication = models.ForeignKey(Communication, related_name='attachments', on_delete=models.CASCADE, null=True, blank=True)
    file = models.FileField(upload_to='communication_attachments/%Y/%m/')
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()  # Size in bytes
    content_type = models.CharField(max_length=100)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)  # Track who uploaded it

    def __str__(self):
        return f"{self.original_filename} - {self.uploaded_by.username if self.uploaded_by else 'Unknown'}"

    @property
    def is_image(self):
        return self.content_type.startswith('image/')

    @property
    def file_size_formatted(self):
        """Return formatted file size"""
        size = self.file_size
        if size < 1024:
            return f"{size} Bytes"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"

class UserRole(models.Model):
    """User can have multiple roles"""
    ROLE_CHOICES = [
        ('user', 'Regular User'),
        ('lab_incharge', 'Lab Incharge'),
        ('admin', 'Admin'),
        ('super_admin', 'Super Admin'),
    ]
    
    custom_user = models.ForeignKey('CustomUser', on_delete=models.CASCADE, related_name='user_roles')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('custom_user', 'role')  # Prevent duplicate roles for same user
    
    def __str__(self):
        return f"{self.custom_user.user.username} - {self.get_role_display()}"

class UserStreamAccess(models.Model):
    """Define which streams a user can access"""
    custom_user = models.ForeignKey('CustomUser', on_delete=models.CASCADE, related_name='stream_access')
    stream = models.ForeignKey(Stream, on_delete=models.CASCADE)
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('custom_user', 'stream')  # Prevent duplicate access for same user-stream
    
    def __str__(self):
        return f"{self.custom_user.user.username} can access {self.stream.name}"

class CustomUser(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='custom_profile')
    profile_image = models.ImageField(upload_to='profile_images/', null=True, blank=True)
    requested_streams = models.ManyToManyField(Stream, blank=True, related_name='requested_by_users')
    
    # Permission methods
    def is_super_admin(self):
        return self.user_roles.filter(role='super_admin').exists() or self.user.is_superuser
    
    def is_admin(self):
        return self.user_roles.filter(role__in=['admin', 'super_admin']).exists() or self.user.is_superuser
    
    def is_lab_incharge(self):
        return self.user_roles.filter(role__in=['lab_incharge', 'admin', 'super_admin']).exists() or self.user.is_superuser
    
    def can_manage_users(self):
        return self.user_roles.filter(role__in=['admin', 'super_admin']).exists() or self.user.is_superuser
    
    def can_manage_system_allocation(self):
        return self.user_roles.filter(role__in=['lab_incharge', 'admin', 'super_admin']).exists() or self.user.is_superuser
    
    def can_edit_products(self):
        return self.user_roles.filter(role__in=['lab_incharge', 'admin', 'super_admin']).exists() or self.user.is_superuser
    
    def can_delete_products(self):
        return self.user_roles.filter(role__in=['admin', 'super_admin']).exists() or self.user.is_superuser
    
    def can_view_analytics(self):
        return self.user_roles.filter(role__in=['lab_incharge', 'admin', 'super_admin']).exists() or self.user.is_superuser
    
    def has_role(self, role):
        """Check if user has a specific role"""
        return self.user_roles.filter(role=role).exists()
    
    def has_any_role(self, roles):
        """Check if user has any of the specified roles"""
        return self.user_roles.filter(role__in=roles).exists()
    
    def can_access_stream(self, stream_name):
        """Check if user can access a specific stream"""
        if self.is_super_admin():
            return True
        return self.stream_access.filter(stream__name=stream_name).exists()
    
    def get_accessible_streams(self):
        """Get all streams the user can access"""
        if self.is_super_admin():
            return Stream.objects.all()
        return Stream.objects.filter(id__in=self.stream_access.values_list('stream_id', flat=True))
    
    def get_roles_display(self):
        """Get comma-separated string of user roles"""
        return ', '.join([role.get_role_display() for role in self.user_roles.all()])

    def save(self, *args, **kwargs):
        try:
            old = CustomUser.objects.get(pk=self.pk)
            if old.profile_image and self.profile_image and old.profile_image != self.profile_image:
                if default_storage.exists(old.profile_image.name):
                    default_storage.delete(old.profile_image.name)
        except CustomUser.DoesNotExist:
            pass
        super().save(*args, **kwargs)

    def __str__(self):
        return self.user.username

class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('allocation', 'System Allocation'),
        ('backup', 'Backup Completion'),
        ('admin', 'Admin Action'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.CharField(max_length=512)
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username}: {self.message[:40]}..."

class SubLevel(models.Model):
    name = models.CharField(max_length=255)
    stream = models.CharField(max_length=100, blank=True, null=True)
    in_stock = models.PositiveIntegerField(default=0)
    in_use = models.PositiveIntegerField(default=0)
    scraped = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class SubLevelHistory(models.Model):
    sublevel = models.ForeignKey('SubLevel', on_delete=models.CASCADE, related_name='history')
    action = models.CharField(max_length=32)  # 'Created' or 'Edited'
    by = models.CharField(max_length=255)
    at = models.DateTimeField(auto_now_add=True)
    details = models.TextField()
    def __str__(self):
        return f"{self.action} by {self.by} at {self.at}"

class SubLevelTool(models.Model):
    name = models.CharField(max_length=255)
    stream = models.CharField(max_length=100, blank=True, null=True)
    in_stock = models.PositiveIntegerField(default=0)
    in_use = models.PositiveIntegerField(default=0)
    scraped = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class SubLevelToolHistory(models.Model):
    subleveltool = models.ForeignKey('SubLevelTool', on_delete=models.CASCADE, related_name='history')
    action = models.CharField(max_length=32)  # 'Created' or 'Edited'
    by = models.CharField(max_length=255)
    at = models.DateTimeField(auto_now_add=True)
    details = models.TextField()
    def __str__(self):
        return f"{self.action} by {self.by} at {self.at}"

class LegacyExcelUpload(models.Model):
    stream = models.CharField(max_length=64)
    file = models.FileField(upload_to='legacy_excels/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    preview_data = models.TextField(blank=True, null=True)  # Store preview as JSON or HTML
    def __str__(self):
        return f"Legacy Excel for {self.stream} uploaded at {self.uploaded_at}"

class TestEnvironment(models.Model):
    mvs_binaries = models.CharField(max_length=255, blank=True)
    mvs_os = models.CharField(max_length=255, blank=True)
    stand_binaries = models.CharField(max_length=255, blank=True)
    stand_os = models.CharField(max_length=255, blank=True)
    apps_pc_binaries = models.CharField(max_length=255, blank=True)
    apps_pc_os = models.CharField(max_length=255, blank=True)
    test_environment = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Test Environment ({self.id})"

class PersonalTask(models.Model):
    STATUS_CHOICES = [
        ('todo', 'To Do'),
        ('inprogress', 'In Progress'),
        ('done', 'Done'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='personal_tasks')
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='todo')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

class UsageTracking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='usage_records')
    page_name = models.CharField(max_length=255)
    page_url = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)
    session_id = models.CharField(max_length=64, blank=True, null=True)
    ip_address = models.CharField(max_length=45, blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    session_duration = models.DurationField(blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['page_name']),
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.page_name} - {self.timestamp}"


class SystemStatus(models.Model):
    STATUS_CHOICES = [
        ('online', 'Online'),
        ('maintenance', 'Maintenance'),
        ('offline', 'Offline'),
        ('warning', 'Warning'),
    ]
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='online')
    description = models.CharField(max_length=255, blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    uptime_percentage = models.FloatField(default=99.9)
    active_users = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-last_updated']
    
    def __str__(self):
        return f"System {self.get_status_display()} - {self.description}"

class UserSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    session_key = models.CharField(max_length=40, unique=True)
    login_time = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-last_activity']
    
    def __str__(self):
        return f"{self.user.username} - {self.login_time}"

class Note(models.Model):
    title = models.CharField(max_length=255)
    content = models.TextField()
    created_by = models.ForeignKey(User, related_name='created_notes', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(User, related_name='updated_notes', on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_public = models.BooleanField(default=True)

    def delete(self, *args, **kwargs):
        """Override delete to also remove all attachment files from storage"""
        # Delete all attachment files before deleting the note
        attachments = self.attachments.all()
        for attachment in attachments:
            if attachment.file:
                try:
                    default_storage.delete(attachment.file.name)
                except Exception as e:
                    # Log the error but continue with deletion
                    print(f"Error deleting file {attachment.file.name}: {e}")
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.title} by {self.created_by.username}"

    class Meta:
        ordering = ['-created_at']

class NoteAttachment(models.Model):
    note = models.ForeignKey(Note, related_name='attachments', on_delete=models.CASCADE)
    file = models.FileField(upload_to='note_attachments/')
    original_filename = models.CharField(max_length=255)
    file_size = models.IntegerField()
    content_type = models.CharField(max_length=100)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # File type categories for easy filtering and display
    FILE_TYPE_CHOICES = [
        ('image', 'Image'),
        ('document', 'Document'),
        ('spreadsheet', 'Spreadsheet'),
        ('pdf', 'PDF'),
        ('other', 'Other'),
    ]
    file_type = models.CharField(max_length=20, choices=FILE_TYPE_CHOICES, default='other')
    
    def save(self, *args, **kwargs):
        if self.file:
            # Set file size
            self.file_size = self.file.size
            
            # Set file type based on content type
            if self.content_type.startswith('image/'):
                self.file_type = 'image'
            elif self.content_type in ['application/pdf']:
                self.file_type = 'pdf'
            elif self.content_type in ['application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']:
                self.file_type = 'spreadsheet'
            elif self.content_type in ['application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
                self.file_type = 'document'
            else:
                self.file_type = 'other'
        
        super().save(*args, **kwargs)
    
    def get_file_icon(self):
        """Return appropriate FontAwesome icon based on file type"""
        icons = {
            'image': 'fas fa-image',
            'document': 'fas fa-file-word',
            'spreadsheet': 'fas fa-file-excel',
            'pdf': 'fas fa-file-pdf',
            'other': 'fas fa-file',
        }
        return icons.get(self.file_type, 'fas fa-file')
    def get_formatted_size(self):
        """Return human-readable file size"""
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    def delete(self, *args, **kwargs):
        """Override delete to also remove the file from storage"""
        if self.file:
            try:
                default_storage.delete(self.file.name)
            except Exception as e:
                # Log the error but continue with deletion
                print(f"Error deleting file {self.file.name}: {e}")
        super().delete(*args, **kwargs)
    
    def __str__(self):
        return f"{self.original_filename} - {self.note.title}"
    
    class Meta:
        ordering = ['-uploaded_at']

class SystemTag(models.Model):
    """
    System tags for linking products and sub-level components to systems in allocations.
    This enables tracking which products/components belong to which systems.
    """
    system = models.ForeignKey('System', on_delete=models.CASCADE, related_name='tags')
    tag_name = models.CharField(max_length=255, help_text="Unique tag identifier for this system")
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='system_tags')
    
    # Many-to-many relationships
    products = models.ManyToManyField('Product', blank=True, related_name='system_tags')
    sublevels = models.ManyToManyField('SubLevel', blank=True, related_name='system_tags')
    sublevel_tools = models.ManyToManyField('SubLevelTool', blank=True, related_name='system_tags')
    projects = models.ManyToManyField('Project', blank=True, related_name='system_tags')
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField(blank=True, help_text="Optional description of this system configuration")
    
    class Meta:
        unique_together = ('system', 'tag_name')
        ordering = ['system__name', 'tag_name']
    
    def __str__(self):
        return f"{self.system.name} - {self.tag_name}"
    
    def get_all_components_count(self):
        """Return total count of all tagged items"""
        return self.products.count() + self.sublevels.count() + self.sublevel_tools.count() + self.projects.count()

class SystemTagHistory(models.Model):
    """
    History tracking for SystemTag modifications.
    Records who made changes, when, and what was changed.
    """
    ACTION_CHOICES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('deleted', 'Deleted'),
        ('item_added', 'Item Added'),
        ('item_removed', 'Item Removed'),
    ]
    ITEM_TYPE_CHOICES = [
        ('product', 'Product'),
        ('sublevel', 'Sub Level'),
        ('sublevel_tool', 'Sub Level Tool'),
        ('project', 'Project'),
        ('tag', 'Tag'),
    ]
    system_tag = models.ForeignKey(SystemTag, on_delete=models.CASCADE, related_name='history', null=True, blank=True)
    system_tag_name = models.CharField(max_length=255, help_text="Stored tag name for reference after deletion")
    system_name = models.CharField(max_length=255, help_text="Stored system name for reference")
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='tag_history')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    item_type = models.CharField(max_length=20, choices=ITEM_TYPE_CHOICES, null=True, blank=True)
    item_name = models.CharField(max_length=255, null=True, blank=True, help_text="Name of item added/removed")
    item_id = models.IntegerField(null=True, blank=True, help_text="ID of item added/removed")
    description = models.TextField(blank=True, help_text="Additional details about the change")
    modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    modified_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-modified_at']
        verbose_name_plural = 'System Tag Histories'
    def __str__(self):
        return f"{self.system_tag_name} - {self.get_action_display()} by {self.modified_by} at {self.modified_at}"
class Project(models.Model):
    """
    Model to track projects with their status, duration, and other details.
    """
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('hold', 'On Hold'),
        ('planned', 'Planned'),
    ]
    
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    duration = models.CharField(max_length=100, help_text="e.g., '3 months', '6 weeks', etc.")
    start_date = models.DateField()
    initial_release_date = models.DateField(null=True, blank=True, help_text="Initial planned release date")
    final_release_date = models.DateField(null=True, blank=True, help_text="Final/actual release date")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='projects', null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_projects')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Additional fields for better project tracking
    team_members = models.ManyToManyField(User, blank=True, related_name='assigned_projects')
    priority = models.CharField(max_length=20, choices=[
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ], default='medium')
    progress_percentage = models.IntegerField(default=0, help_text="Actual project completion percentage (0-100)")
    expected_progress = models.IntegerField(default=0, help_text="Expected progress based on timeline (0-100)")
    
    class Meta:
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"
    
    def get_duration_days(self):
        """Calculate duration in days"""
        if self.start_date and self.final_release_date:
            return (self.final_release_date - self.start_date).days
        return 0
    
    def is_overdue(self):
        """Check if project is overdue"""
        if self.final_release_date and self.status == 'running':
            return date.today() > self.final_release_date
        return False
    
    def days_remaining(self):
        """Calculate days remaining until final release date"""
        if self.final_release_date:
            remaining = (self.final_release_date - date.today()).days
            return remaining if remaining > 0 else 0
        return 0
    
    def calculate_expected_progress(self):
        """Calculate expected progress based on start date and final release date"""
        if self.status != 'running':
            return 0
        
        if not self.start_date or not self.final_release_date:
            return 0
        
        today = date.today()
        total_days = (self.final_release_date - self.start_date).days
        
        if total_days <= 0:
            return 100
        
        elapsed_days = (today - self.start_date).days
        
        if elapsed_days < 0:
            return 0
        elif elapsed_days > total_days:
            return 100
        else:
            return int((elapsed_days / total_days) * 100)

class HolisticSystem(models.Model):
    """
    Advanced holistic system tracking with comprehensive allocation and week-wise data.
    Projects are now assigned per week via HolisticWeeklyData, not at system level.
    """
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('allocated', 'Allocated'),
        ('maintenance', 'Maintenance'),
        ('reserved', 'Reserved'),
        ('offline', 'Offline'),
    ]
    
    # Core identification fields
    sr_no = models.CharField(max_length=50, unique=True, verbose_name="Serial Number")
    system_availability = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available', verbose_name="System Availability")
    allocation_to_sl_no = models.CharField(max_length=100, blank=True, null=True, verbose_name="Allocation to Sl No")
    
    # System information
    location_info = models.CharField(max_length=255, blank=True, null=True, verbose_name="Location Info")
    stmi_number = models.CharField(max_length=100, blank=True, null=True, verbose_name="STMi Number")
    system_owner = models.CharField(max_length=255, blank=True, null=True, verbose_name="System Owner")
    ecr_number = models.CharField(max_length=100, blank=True, null=True, verbose_name="ECR#")
    test_engineer = models.CharField(max_length=255, blank=True, null=True, verbose_name="Test Engineer")
    
    # Stream association
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='holistic_systems', null=True, blank=True)
    
    # Additional tracking fields
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    priority = models.CharField(max_length=20, choices=[
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ], default='medium')
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_holistic_systems')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_holistic_systems')
    
    class Meta:
        ordering = ['sr_no']
        verbose_name = 'Holistic System'
        verbose_name_plural = 'Holistic Systems'
    
    def __str__(self):
        return f"{self.sr_no} - {self.get_system_availability_display()}"
    
    def get_current_week_data(self):
        """Get data for current week"""
        current_week = date.today().isocalendar()[1]
        return self.weekly_data.filter(week_number=current_week, year=date.today().year).first()
    
    def get_all_weeks_data(self):
        """Get all weekly data ordered by week"""
        return self.weekly_data.all().order_by('year', 'week_number')
    
    def get_current_project(self):
        """Get the project assigned for the current week"""
        current_week_data = self.get_current_week_data()
        return current_week_data.project if current_week_data else None
    
    def get_project_for_week(self, week_number, year):
        """Get the project assigned for a specific week"""
        weekly_data = self.weekly_data.filter(week_number=week_number, year=year).first()
        return weekly_data.project if weekly_data else None
    
    def get_unique_projects(self):
        """Get all unique projects that have been assigned to this system across all weeks"""
        from .models import Project
        project_ids = self.weekly_data.filter(project__isnull=False).values_list('project_id', flat=True).distinct()
        return Project.objects.filter(id__in=project_ids)
    
    def get_project_timeline(self):
        """Get a timeline of project assignments by week"""
        timeline = []
        for week_data in self.get_all_weeks_data():
            if week_data.project:
                timeline.append({
                    'week': f"W{week_data.week_number}",
                    'year': week_data.year,
                    'project': week_data.project.name,
                    'project_id': week_data.project.id
                })
        return timeline

class HolisticWeeklyData(models.Model):
    """
    Week-wise data tracking for holistic systems (W26, W27, etc.)
    """
    holistic_system = models.ForeignKey(HolisticSystem, on_delete=models.CASCADE, related_name='weekly_data')
    week_number = models.IntegerField(verbose_name="Week Number (e.g., 26 for W26)")
    year = models.IntegerField(verbose_name="Year")
    
    # Week-wise project assignment - NEW: project can change per week
    project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True, blank=True, related_name='weekly_assignments', verbose_name="Project for this week")
    
    # Week-wise tracking fields
    allocation_status = models.CharField(max_length=100, blank=True, null=True, verbose_name="Allocation Status")
    utilization_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name="Utilization %")
    assigned_to = models.CharField(max_length=255, blank=True, null=True, verbose_name="Assigned To")
    task_description = models.TextField(blank=True, null=True, verbose_name="Task Description")
    
    # Additional metrics
    hours_used = models.DecimalField(max_digits=6, decimal_places=2, default=0.00, verbose_name="Hours Used")
    availability_hours = models.DecimalField(max_digits=6, decimal_places=2, default=40.00, verbose_name="Available Hours")
    
    notes = models.TextField(blank=True, null=True, verbose_name="Weekly Notes")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        ordering = ['year', 'week_number']
        unique_together = ('holistic_system', 'week_number', 'year')
        verbose_name = 'Weekly Data'
        verbose_name_plural = 'Weekly Data'
    
    def __str__(self):
        return f"W{self.week_number} {self.year} - {self.holistic_system.sr_no}"
    
    def get_week_label(self):
        """Return week label like W26"""
        return f"W{self.week_number}"

class HolisticSystemHistory(models.Model):
    """
    Track all changes made to holistic systems
    """
    holistic_system = models.ForeignKey(HolisticSystem, on_delete=models.CASCADE, related_name='history')
    action = models.CharField(max_length=50)  # 'created', 'edited', 'status_changed', etc.
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'System History'
        verbose_name_plural = 'System Histories'
    
    def __str__(self):
        return f"{self.holistic_system.sr_no} - {self.action} by {self.user} at {self.timestamp}"


class SharedNote(models.Model):
    """
    Model to track notes shared with users
    """
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name='shares')
    shared_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shared_notes')
    shared_with = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_notes')
    shared_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    message = models.TextField(blank=True, help_text="Optional message from the sender")
    
    class Meta:
        unique_together = ('note', 'shared_by', 'shared_with')
        ordering = ['-shared_at']
        
    def __str__(self):
        return f"{self.note.title} shared by {self.shared_by.username} with {self.shared_with.username}"

class Floor(models.Model):
    """
    Model for managing building floors dynamically per stream
    """
    name = models.CharField(max_length=100, verbose_name="Floor Name")
    description = models.CharField(max_length=255, blank=True, null=True, verbose_name="Description")
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='floors', verbose_name="Stream")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['stream', 'name']
        verbose_name = "Floor"
        verbose_name_plural = "Floors"
        unique_together = ('name', 'stream')  # Floor name must be unique within a stream
    
    def __str__(self):
        return f"{self.name} ({self.stream.name})"


class OperatingSystem(models.Model):
    """
    Model for managing operating systems dynamically per stream
    """
    name = models.CharField(max_length=100, verbose_name="Operating System Name")
    version = models.CharField(max_length=50, blank=True, null=True, verbose_name="Version")
    description = models.CharField(max_length=255, blank=True, null=True, verbose_name="Description")
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='operating_systems', verbose_name="Stream")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['stream', 'name']
        verbose_name = "Operating System"
        verbose_name_plural = "Operating Systems"
        unique_together = ('name', 'version', 'stream')  # OS name+version must be unique within a stream
    def __str__(self):
        if self.version:
            return f"{self.name} {self.version}"
        return self.name
    def full_display(self):
        """Return full display name with stream"""
        if self.version:
            return f"{self.name} {self.version} ({self.stream.name})"
        return f"{self.name} ({self.stream.name})"
class BuildServer(models.Model):
    """
    Model to track Build Servers information separated by stream (PIC/HIC)
    """
    SERVER_TYPES = [
        ('PIC', 'PIC'),
        ('HIC', 'HIC'),
        ('Other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
        ('Maintenance', 'Under Maintenance'),
        ('Offline', 'Offline'),
    ]
    
    # Core identification fields
    hostname = models.CharField(max_length=255, unique=True, verbose_name="Machine Hostname")
    ip_address = models.GenericIPAddressField(verbose_name="IP Address")
    
    # Location and physical details
    location = models.CharField(max_length=255, verbose_name="Location")
    floor = models.ForeignKey('Floor', on_delete=models.SET_NULL, null=True, blank=False, verbose_name="Floor")
    owner = models.CharField(max_length=255, verbose_name="Owner")
    
    # Stream association
    stream_type = models.CharField(max_length=10, choices=SERVER_TYPES, verbose_name="Stream Type")
    stream = models.ForeignKey('Stream', on_delete=models.CASCADE, related_name='build_servers', null=True, blank=True)
    
    # Additional server details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active', verbose_name="Status")
    operating_system = models.CharField(max_length=255, blank=True, null=True, verbose_name="Operating System (Legacy)")
    operating_system_ref = models.ForeignKey('OperatingSystem', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Operating System", related_name='build_servers')
    cpu_cores = models.IntegerField(blank=True, null=True, verbose_name="CPU Cores")
    ram_gb = models.IntegerField(blank=True, null=True, verbose_name="RAM (GB)")
    storage_gb = models.IntegerField(blank=True, null=True, verbose_name="Storage (GB)")
    
    # Network and security details
    mac_address = models.CharField(max_length=17, blank=True, null=True, verbose_name="MAC Address")
    domain = models.CharField(max_length=255, blank=True, null=True, verbose_name="Domain")
    ssh_port = models.IntegerField(default=22, verbose_name="SSH Port")
    
    # Business details
    purpose = models.TextField(blank=True, null=True, verbose_name="Purpose/Description")
    project_allocation = models.CharField(max_length=255, blank=True, null=True, verbose_name="Project Allocation")
    cost_center = models.CharField(max_length=100, blank=True, null=True, verbose_name="Cost Center")
    procurement_date = models.DateField(blank=True, null=True, verbose_name="Procurement Date")
    warranty_expiry = models.DateField(blank=True, null=True, verbose_name="Warranty Expiry")
    
    # Contact information
    primary_contact = models.CharField(max_length=255, blank=True, null=True, verbose_name="Primary Contact")
    secondary_contact = models.CharField(max_length=255, blank=True, null=True, verbose_name="Secondary Contact")
    contact_email = models.EmailField(blank=True, null=True, verbose_name="Contact Email")
    
    # Operational details
    last_maintenance = models.DateField(blank=True, null=True, verbose_name="Last Maintenance Date")
    next_maintenance = models.DateField(blank=True, null=True, verbose_name="Next Maintenance Date")
    uptime_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=99.9, verbose_name="Uptime %")
    
    # Additional metadata
    notes = models.TextField(blank=True, null=True, verbose_name="Additional Notes")
    tags = models.CharField(max_length=500, blank=True, null=True, verbose_name="Tags (comma-separated)")
    
    # Tracking fields
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_build_servers')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_build_servers')
    
    class Meta:
        ordering = ['hostname']
        verbose_name = 'Build Server'
        verbose_name_plural = 'Build Servers'
    
    def __str__(self):
        return f"{self.hostname} ({self.stream_type}) - {self.location}"
    
    def is_active(self):
        """Check if server is active"""
        return self.status == 'Active'
    
    def days_until_warranty_expiry(self):
        """Calculate days until warranty expires"""
        if self.warranty_expiry:
            return (self.warranty_expiry - date.today()).days
        return None
    
    def is_warranty_expiring_soon(self, days=30):
        """Check if warranty is expiring within specified days"""
        days_left = self.days_until_warranty_expiry()
        return days_left is not None and days_left <= days and days_left >= 0
    
    def get_tag_list(self):
        """Get tags as a list"""
        if self.tags:
            return [tag.strip() for tag in self.tags.split(',') if tag.strip()]
        return []

class BuildServerHistory(models.Model):
    """
    Track all changes made to build servers
    """
    ACTION_CHOICES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('status_changed', 'Status Changed'),
        ('maintenance', 'Maintenance Performed'),
        ('relocated', 'Relocated'),
        ('specs_updated', 'Specifications Updated'),
        ('ownership_changed', 'Ownership Changed'),
    ]
    
    build_server = models.ForeignKey(BuildServer, on_delete=models.CASCADE, related_name='history')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='build_server_actions')
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField(blank=True, help_text="Details about what changed")
    old_values = models.JSONField(blank=True, null=True, help_text="Previous values (JSON)")
    new_values = models.JSONField(blank=True, null=True, help_text="New values (JSON)")
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Build Server History'
        verbose_name_plural = 'Build Server Histories'
    
    def __str__(self):
        return f"{self.build_server.hostname} - {self.get_action_display()} by {self.user} at {self.timestamp}"

class BuildServerMaintenanceLog(models.Model):
    """
    Track maintenance activities for build servers
    """
    MAINTENANCE_TYPES = [
        ('routine', 'Routine Maintenance'),
        ('emergency', 'Emergency Repair'),
        ('upgrade', 'Hardware Upgrade'),
        ('software', 'Software Update'),
        ('security', 'Security Patch'),
        ('cleaning', 'Physical Cleaning'),
        ('relocation', 'Physical Relocation'),
        ('other', 'Other'),
    ]
    
    build_server = models.ForeignKey(BuildServer, on_delete=models.CASCADE, related_name='maintenance_logs')
    maintenance_type = models.CharField(max_length=20, choices=MAINTENANCE_TYPES)
    scheduled_date = models.DateTimeField(verbose_name="Scheduled Date/Time")
    actual_date = models.DateTimeField(blank=True, null=True, verbose_name="Actual Date/Time")
    duration_hours = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True, verbose_name="Duration (hours)")
    
    # People involved
    performed_by = models.CharField(max_length=255, verbose_name="Performed By")
    authorized_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='authorized_maintenance')
    
    # Details
    description = models.TextField(verbose_name="Maintenance Description")
    issues_found = models.TextField(blank=True, null=True, verbose_name="Issues Found")
    actions_taken = models.TextField(blank=True, null=True, verbose_name="Actions Taken")
    parts_replaced = models.TextField(blank=True, null=True, verbose_name="Parts Replaced")
    
    # Status and outcome
    completed = models.BooleanField(default=False, verbose_name="Completed Successfully")
    requires_followup = models.BooleanField(default=False, verbose_name="Requires Follow-up")
    next_maintenance_due = models.DateField(blank=True, null=True, verbose_name="Next Maintenance Due")
    
    # Cost tracking
    cost = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, verbose_name="Cost")
    vendor = models.CharField(max_length=255, blank=True, null=True, verbose_name="Vendor/Contractor")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-scheduled_date']
        verbose_name = 'Maintenance Log'
        verbose_name_plural = 'Maintenance Logs'
    
    def __str__(self):
        return f"{self.build_server.hostname} - {self.get_maintenance_type_display()} on {self.scheduled_date.strftime('%Y-%m-%d')}"
