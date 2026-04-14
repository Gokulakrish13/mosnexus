# pylint: disable=broad-exception-caught,import-outside-toplevel,missing-function-docstring,no-else-return,no-member,too-many-return-statements
from datetime import date

from django.conf import settings
from django.db import models


class Project(models.Model):
    """
    Model to track projects with their status, duration, and other details.
    """

    STATUS_CHOICES = [
        ("running", "Running"),
        ("hold", "On Hold"),
        ("planned", "Planned"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    duration = models.CharField(max_length=100, help_text="e.g., '3 months', '6 weeks', etc.")
    start_date = models.DateField()
    initial_release_date = models.DateField(null=True, blank=True, help_text="Initial planned release date")
    final_release_date = models.DateField(null=True, blank=True, help_text="Final/actual release date")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="projects", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_projects"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Additional fields for better project tracking
    team_members = models.ManyToManyField(  # type: ignore[var-annotated]
        settings.AUTH_USER_MODEL, blank=True, related_name="assigned_projects"
    )
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
    progress_percentage = models.IntegerField(default=0, help_text="Actual project completion percentage (0-100)")
    expected_progress = models.IntegerField(default=0, help_text="Expected progress based on timeline (0-100)")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def get_duration_days(self):
        """Calculate duration in days"""
        if self.start_date and self.final_release_date:
            return (self.final_release_date - self.start_date).days
        return 0

    def is_overdue(self):
        """Check if project is overdue"""
        if self.final_release_date and self.status == "running":
            return date.today() > self.final_release_date
        return False

    def is_completed(self):
        """Check if project is completed or cancelled"""
        return self.status in ("completed", "cancelled")

    def days_remaining(self):
        """Calculate days remaining until final release date"""
        if self.final_release_date:
            remaining = (self.final_release_date - date.today()).days
            return remaining if remaining > 0 else 0
        return 0

    def calculate_expected_progress(self):
        """Calculate expected progress based on start date and final release date"""
        if self.status not in ("running",):
            if self.status == "completed":
                return 100
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


class ProjectMilestone(models.Model):
    """Key deliverable/milestone within a project."""

    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="milestones")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    due_date = models.DateField()
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date"]

    def __str__(self):
        return f"{self.name} ({self.project.name})"


class ProjectAttachment(models.Model):
    """File attachment for a project."""

    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="product_images/project_attachments/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.original_filename} ({self.project.name})"

    @property
    def file_extension(self):
        return self.original_filename.rsplit(".", 1)[-1].lower() if "." in self.original_filename else ""

    @property
    def file_size_display(self):
        try:
            size = self.file.size
            if size < 1024:
                return f"{size} B"
            elif size < 1024 * 1024:
                return f"{size / 1024:.1f} KB"
            else:
                return f"{size / (1024 * 1024):.1f} MB"
        except Exception:
            return "N/A"


class ProjectDependency(models.Model):
    """Dependency relationship between two projects."""

    DEPENDENCY_TYPES = [
        ("blocks", "Blocks"),
        ("blocked_by", "Blocked By"),
        ("relates_to", "Relates To"),
    ]
    from_project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="dependencies_from")
    to_project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="dependencies_to")
    dependency_type = models.CharField(max_length=20, choices=DEPENDENCY_TYPES, default="relates_to")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("from_project", "to_project", "dependency_type")]

    def __str__(self):
        return f"{self.from_project.name} {self.get_dependency_type_display()} {self.to_project.name}"


# ── Resource Allocation (FTE Tracking) ────────────────────────────────────────


class ResourceComponentType(models.Model):
    """
    Configurable component/user type for resource allocation (e.g. FE, CBE, SW, HW).
    Admins manage these via the configuration page.
    """

    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="resource_component_types")
    name = models.CharField(max_length=50, help_text="e.g. FE, CBE, SW, HW")
    description = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = [("name", "stream")]

    def __str__(self):
        return self.name


class ResourceAllocationYear(models.Model):
    """Years available for resource allocation. Managed from the configuration page."""

    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="resource_allocation_years")
    year = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["year"]
        unique_together = [("year", "stream")]

    def __str__(self):
        return str(self.year)


class ResourceManager(models.Model):
    """Configurable manager / department names for resource persons."""

    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="resource_managers")
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = [("name", "stream")]

    def __str__(self):
        return self.name


class ResourceLocation(models.Model):
    """Configurable office locations for resource persons."""

    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="resource_locations")
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = [("name", "stream")]

    def __str__(self):
        return self.name


class ResourceRole(models.Model):
    """Configurable role titles for resource persons."""

    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="resource_roles")
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = [("name", "stream")]

    def __str__(self):
        return self.name


class ResourcePerson(models.Model):
    """
    A person tracked in the resource allocation grid.
    Can optionally link to a Django User, but also works standalone for external contractors.
    """

    FTE_TYPE_CHOICES = [
        ("FTE", "FTE"),
        ("Contractor", "Contractor"),
        ("Intern", "Intern"),
        ("Vendor", "Vendor"),
    ]

    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="resource_persons")
    component = models.ForeignKey(
        "ResourceComponentType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="persons",
        help_text="Component / user type e.g. FE, CBE",
    )
    fte_type = models.CharField(max_length=20, choices=FTE_TYPE_CHOICES, default="FTE")
    name = models.CharField(max_length=255)
    emp_id = models.CharField(max_length=50, blank=True, default="")
    manager = models.CharField(max_length=255, blank=True, default="", help_text="Department / Manager name")
    location = models.CharField(max_length=255, blank=True, default="")
    role = models.CharField(max_length=255, blank=True, default="", help_text="e.g. Technical Leader, Senior Developer")
    linked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resource_person_profiles",
    )
    is_active = models.BooleanField(default=True)
    show_in_allocation = models.BooleanField(
        default=False,
        help_text="Whether this person appears in the allocation grid. "
        "Managed from the allocation page, independent of is_active.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_resource_persons",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("emp_id", "stream")]

    def __str__(self):
        return f"{self.name} ({self.emp_id})"


class ResourceAllocation(models.Model):
    """
    Monthly allocation value for a person on a specific project.
    Stores one row per (person, project, year, month) — fully normalised, scalable to any year range.
    Allocation is a decimal from 0.0 to 1.0 (fraction of an FTE).
    """

    person = models.ForeignKey("ResourcePerson", on_delete=models.CASCADE, related_name="allocations")
    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="resource_allocations")
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField(help_text="1-12")
    allocation = models.DecimalField(
        max_digits=4, decimal_places=2, default=0, help_text="FTE fraction, e.g. 0.50 = 50%"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_allocations"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["year", "month"]
        unique_together = [("person", "project", "year", "month")]
        indexes = [
            models.Index(fields=["project", "year", "month"]),
            models.Index(fields=["person", "year"]),
        ]

    def __str__(self):
        return f"{self.person.name} → {self.project.name} ({self.year}-{self.month:02d}: {self.allocation})"


class ResourceWeeklyAllocation(models.Model):
    """
    Weekly allocation value for a person on a specific project.
    Stores one row per (person, project, year, week) — ISO week numbers 1-53.
    """

    person = models.ForeignKey("ResourcePerson", on_delete=models.CASCADE, related_name="weekly_allocations")
    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="resource_weekly_allocations")
    year = models.PositiveIntegerField()
    week = models.PositiveSmallIntegerField(help_text="ISO week number 1-53")
    allocation = models.DecimalField(max_digits=4, decimal_places=2, default=0, help_text="FTE fraction for this week")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_weekly_allocations",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["year", "week"]
        unique_together = [("person", "project", "year", "week")]
        indexes = [
            models.Index(fields=["project", "year", "week"]),
            models.Index(fields=["person", "year"]),
        ]

    def __str__(self):
        return f"{self.person.name} → {self.project.name} ({self.year}-W{self.week:02d}: {self.allocation})"


class ResourceCellNote(models.Model):
    """Note/comment attached to a specific allocation cell (person + project + year + month)."""

    person = models.ForeignKey("ResourcePerson", on_delete=models.CASCADE, related_name="cell_notes")
    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="resource_cell_notes")
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField(help_text="1-12")
    note = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_cell_notes"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("person", "project", "year", "month")]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Note: {self.person.name} → {self.project.name} ({self.year}-{self.month:02d})"


class ResourceAllocationLock(models.Model):
    """Lock a specific month so allocation values cannot be edited."""

    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="allocation_locks")
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField(help_text="1-12")
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="locked_allocations"
    )
    locked_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        unique_together = [("stream", "year", "month")]
        ordering = ["year", "month"]

    def __str__(self):
        return f"Lock: {self.year}-{self.month:02d} ({self.stream})"
