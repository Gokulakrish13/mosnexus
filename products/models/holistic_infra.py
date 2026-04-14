# pylint: disable=chained-comparison,duplicate-code,import-outside-toplevel,no-member,too-many-lines
from datetime import date

from django.conf import settings
from django.db import models


class HolisticSystem(models.Model):
    """
    Advanced holistic system tracking with comprehensive allocation and week-wise data.
    Projects are now assigned per week via HolisticWeeklyData, not at system level.
    """

    STATUS_CHOICES = [
        ("available", "Available"),
        ("allocated", "Allocated"),
        ("maintenance", "Maintenance"),
        ("reserved", "Reserved"),
        ("offline", "Offline"),
    ]

    # Core identification fields
    sr_no = models.CharField(max_length=50, unique=True, verbose_name="Serial Number")
    system_availability = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="available", verbose_name="System Availability"
    )
    allocation_to_sl_no = models.CharField(max_length=100, blank=True, null=True, verbose_name="Allocation to Sl No")

    # System information
    location_info = models.CharField(max_length=255, blank=True, null=True, verbose_name="Location Info")
    stmi_number = models.CharField(max_length=100, blank=True, null=True, verbose_name="STMi Number")
    system_owner = models.CharField(max_length=255, blank=True, null=True, verbose_name="System Owner")
    ecr_number = models.CharField(max_length=100, blank=True, null=True, verbose_name="ECR#")
    test_engineer = models.CharField(max_length=255, blank=True, null=True, verbose_name="Test Engineer")

    # Stream association
    stream = models.ForeignKey(
        "Stream", on_delete=models.CASCADE, related_name="holistic_systems", null=True, blank=True
    )

    # Additional tracking fields
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    notes = models.TextField(blank=True, null=True, verbose_name="Notes")
    priority = models.CharField(
        max_length=20,
        choices=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("critical", "Critical"),
        ],
        default="medium",
    )

    # Allocation period tracking
    allocation_start_date = models.DateField(blank=True, null=True, verbose_name="Allocation Start Date")
    allocation_end_date = models.DateField(blank=True, null=True, verbose_name="Allocation End Date")
    allocation_project = models.ForeignKey(
        "Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="allocated_systems",
        verbose_name="Allocated Project",
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_holistic_systems",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_holistic_systems",
    )

    class Meta:
        ordering = ["sr_no"]
        verbose_name = "Holistic System"
        verbose_name_plural = "Holistic Systems"

    def __str__(self):
        return f"{self.sr_no} - {self.get_system_availability_display()}"

    def get_current_week_data(self):
        """Get data for current week"""
        current_week = date.today().isocalendar()[1]
        return self.weekly_data.filter(week_number=current_week, year=date.today().year).first()

    def get_all_weeks_data(self):
        """Get all weekly data ordered by week"""
        return self.weekly_data.all().order_by("year", "week_number")

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
        from products.models import Project

        project_ids = self.weekly_data.filter(project__isnull=False).values_list("project_id", flat=True).distinct()
        return Project.objects.filter(id__in=project_ids)

    def get_project_timeline(self):
        """Get a timeline of project assignments by week"""
        timeline = []
        for week_data in self.get_all_weeks_data():
            if week_data.project:
                timeline.append(
                    {
                        "week": f"W{week_data.week_number}",
                        "year": week_data.year,
                        "project": week_data.project.name,
                        "project_id": week_data.project.id,
                    }
                )
        return timeline

    def get_allocation_status_display_text(self):
        """Get formatted allocation period display"""
        if self.allocation_start_date and self.allocation_end_date:
            remaining = (self.allocation_end_date - date.today()).days
            return {
                "start": self.allocation_start_date.isoformat(),
                "end": self.allocation_end_date.isoformat(),
                "project": self.allocation_project.name if self.allocation_project else None,
                "project_id": self.allocation_project.id if self.allocation_project else None,
                "remaining_days": remaining,
                "is_active": self.allocation_start_date <= date.today() <= self.allocation_end_date,
                "is_expired": date.today() > self.allocation_end_date,
            }
        return None


class HolisticWeeklyData(models.Model):
    """
    Week-wise data tracking for holistic systems (W26, W27, etc.)
    """

    holistic_system = models.ForeignKey("HolisticSystem", on_delete=models.CASCADE, related_name="weekly_data")
    week_number = models.IntegerField(verbose_name="Week Number (e.g., 26 for W26)")
    year = models.IntegerField(verbose_name="Year")

    # Project assigned for this specific week (can differ week-to-week)
    project = models.ForeignKey(
        "Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="weekly_assignments",
        verbose_name="Project for this week",
    )

    # Week-wise tracking fields
    allocation_status = models.CharField(max_length=100, blank=True, null=True, verbose_name="Allocation Status")
    utilization_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00, verbose_name="Utilization %"
    )
    assigned_to = models.CharField(max_length=255, blank=True, null=True, verbose_name="Assigned To")
    task_description = models.TextField(blank=True, null=True, verbose_name="Task Description")

    # Additional metrics
    hours_used = models.DecimalField(max_digits=6, decimal_places=2, default=0.00, verbose_name="Hours Used")
    availability_hours = models.DecimalField(
        max_digits=6, decimal_places=2, default=40.00, verbose_name="Available Hours"
    )

    notes = models.TextField(blank=True, null=True, verbose_name="Weekly Notes")

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["year", "week_number"]
        unique_together = ("holistic_system", "week_number", "year")
        verbose_name = "Weekly Data"
        verbose_name_plural = "Weekly Data"

    def __str__(self):
        return f"W{self.week_number} {self.year} - {self.holistic_system.sr_no}"

    def get_week_label(self):
        """Return week label like W26"""
        return f"W{self.week_number}"


class HolisticSystemHistory(models.Model):
    """
    Track all changes made to holistic systems
    """

    holistic_system = models.ForeignKey("HolisticSystem", on_delete=models.CASCADE, related_name="history")
    action = models.CharField(max_length=50)  # 'created', 'edited', 'status_changed', etc.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField(blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "System History"
        verbose_name_plural = "System Histories"

    def __str__(self):
        return f"{self.holistic_system.sr_no} - {self.action} by {self.user} at {self.timestamp}"


class SharedNote(models.Model):
    """
    Model to track notes shared with users
    """

    note = models.ForeignKey("Note", on_delete=models.CASCADE, related_name="shares")
    shared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shared_notes")
    shared_with = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="received_notes")
    shared_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    message = models.TextField(blank=True, help_text="Optional message from the sender")

    class Meta:
        unique_together = ("note", "shared_by", "shared_with")
        ordering = ["-shared_at"]

    def __str__(self):
        return f"{self.note.title} shared by {self.shared_by.username} with {self.shared_with.username}"


class Floor(models.Model):
    """
    Model for managing building floors dynamically per stream
    """

    name = models.CharField(max_length=100, verbose_name="Floor Name")
    description = models.CharField(max_length=255, blank=True, null=True, verbose_name="Description")
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="floors", verbose_name="Stream")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["stream", "name"]
        verbose_name = "Floor"
        verbose_name_plural = "Floors"
        unique_together = ("name", "stream")

    def __str__(self):
        return f"{self.name} ({self.stream.name})"


class OperatingSystem(models.Model):
    """
    Model for managing operating systems dynamically per stream
    """

    name = models.CharField(max_length=100, verbose_name="Operating System Name")
    version = models.CharField(max_length=50, blank=True, null=True, verbose_name="Version")
    description = models.CharField(max_length=255, blank=True, null=True, verbose_name="Description")
    stream = models.ForeignKey(
        "Stream", on_delete=models.CASCADE, related_name="operating_systems", verbose_name="Stream"
    )
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["stream", "name"]
        verbose_name = "Operating System"
        verbose_name_plural = "Operating Systems"
        unique_together = ("name", "version", "stream")

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
        ("PIC", "PIC"),
        ("HIC", "HIC"),
        ("Other", "Other"),
    ]

    STATUS_CHOICES = [
        ("Active", "Active"),
        ("Inactive", "Inactive"),
        ("Maintenance", "Under Maintenance"),
        ("Offline", "Offline"),
    ]

    # Core identification fields
    hostname = models.CharField(max_length=255, unique=True, verbose_name="Machine Hostname")
    ip_address = models.GenericIPAddressField(verbose_name="IP Address")

    # Location and physical details
    location = models.CharField(max_length=255, verbose_name="Location")
    floor = models.ForeignKey("Floor", on_delete=models.SET_NULL, null=True, blank=False, verbose_name="Floor")
    owner = models.CharField(max_length=255, verbose_name="Owner")

    # Stream association
    stream_type = models.CharField(max_length=10, choices=SERVER_TYPES, verbose_name="Stream Type")
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="build_servers", null=True, blank=True)

    # Additional server details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Active", verbose_name="Status")
    operating_system = models.CharField(max_length=255, blank=True, null=True, verbose_name="Operating System (Legacy)")
    operating_system_ref = models.ForeignKey(
        "OperatingSystem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Operating System",
        related_name="build_servers",
    )
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
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_build_servers"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="updated_build_servers"
    )

    class Meta:
        ordering = ["hostname"]
        verbose_name = "Build Server"
        verbose_name_plural = "Build Servers"

    def __str__(self):
        return f"{self.hostname} ({self.stream_type}) - {self.location}"

    def is_active(self):
        """Check if server is active"""
        return self.status == "Active"

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
            return [tag.strip() for tag in self.tags.split(",") if tag.strip()]
        return []


class BuildServerHistory(models.Model):
    """
    Track all changes made to build servers
    """

    ACTION_CHOICES = [
        ("created", "Created"),
        ("updated", "Updated"),
        ("status_changed", "Status Changed"),
        ("maintenance", "Maintenance Performed"),
        ("relocated", "Relocated"),
        ("specs_updated", "Specifications Updated"),
        ("ownership_changed", "Ownership Changed"),
    ]

    build_server = models.ForeignKey("BuildServer", on_delete=models.CASCADE, related_name="history")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="build_server_actions"
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField(blank=True, help_text="Details about what changed")
    old_values = models.JSONField(blank=True, null=True, help_text="Previous values (JSON)")
    new_values = models.JSONField(blank=True, null=True, help_text="New values (JSON)")

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Build Server History"
        verbose_name_plural = "Build Server Histories"

    def __str__(self):
        return f"{self.build_server.hostname} - {self.get_action_display()} by {self.user} at {self.timestamp}"


class BuildServerMaintenanceLog(models.Model):
    """
    Track maintenance activities for build servers
    """

    MAINTENANCE_TYPES = [
        ("routine", "Routine Maintenance"),
        ("emergency", "Emergency Repair"),
        ("upgrade", "Hardware Upgrade"),
        ("software", "Software Update"),
        ("security", "Security Patch"),
        ("cleaning", "Physical Cleaning"),
        ("relocation", "Physical Relocation"),
        ("other", "Other"),
    ]

    build_server = models.ForeignKey("BuildServer", on_delete=models.CASCADE, related_name="maintenance_logs")
    maintenance_type = models.CharField(max_length=20, choices=MAINTENANCE_TYPES)
    scheduled_date = models.DateTimeField(verbose_name="Scheduled Date/Time")
    actual_date = models.DateTimeField(blank=True, null=True, verbose_name="Actual Date/Time")
    duration_hours = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True, verbose_name="Duration (hours)"
    )

    # People involved
    performed_by = models.CharField(max_length=255, verbose_name="Performed By")
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authorized_maintenance",
    )

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
        ordering = ["-scheduled_date"]
        verbose_name = "Maintenance Log"
        verbose_name_plural = "Maintenance Logs"

    def __str__(self):
        return (
            f"{self.build_server.hostname} - {self.get_maintenance_type_display()}"
            f" on {self.scheduled_date.strftime('%Y-%m-%d')}"
        )


# =============================================================================
# RECURRING RESERVATIONS & WAITLIST MANAGEMENT
# =============================================================================
