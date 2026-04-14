# pylint: disable=import-outside-toplevel,no-member
from products.models._validators import _document_ext_validator

from django.conf import settings
from django.db import models


class ComplianceDocumentVersion(models.Model):
    """
    Stores every revision of a compliance document with full file history,
    enabling diff tracking and rollback capability.
    """

    document = models.ForeignKey("ComplianceDocument", on_delete=models.CASCADE, related_name="versions")

    # Version identification
    version_number = models.CharField(max_length=20, help_text="Semantic version e.g. 1.0, 1.1, 2.0")
    version_label = models.CharField(
        max_length=100, blank=True, help_text="Optional label e.g. 'Draft', 'Final Review', 'Approved'"
    )
    is_current = models.BooleanField(default=False, help_text="Is this the current active version?")

    # File
    file = models.FileField(upload_to="compliance_versions/%Y/%m/", validators=[_document_ext_validator])
    original_filename = models.CharField(max_length=255)
    file_size = models.IntegerField(null=True, blank=True)
    file_hash = models.CharField(
        max_length=64, blank=True, help_text="SHA-256 hash of the file for integrity verification"
    )

    # Metadata at time of version
    status_at_version = models.CharField(
        max_length=20, blank=True, help_text="Document status when this version was created"
    )

    # Change details
    change_summary = models.TextField(blank=True, help_text="What changed in this version compared to previous")
    change_type = models.CharField(
        max_length=20,
        default="minor",
        choices=[
            ("major", "Major Revision"),
            ("minor", "Minor Revision"),
            ("patch", "Patch / Correction"),
            ("initial", "Initial Version"),
        ],
    )

    # Authorship
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_doc_versions"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_doc_versions"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_doc_versions"
    )

    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    review_date = models.DateTimeField(null=True, blank=True)
    approval_date = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("document", "version_number")
        verbose_name = "Document Version"
        verbose_name_plural = "Document Versions"

    def __str__(self):
        return f"{self.document.title} v{self.version_number}"

    def save(self, *args, **kwargs):
        if self.file and not self.file_hash:
            import hashlib

            hasher = hashlib.sha256()
            for chunk in self.file.chunks():
                hasher.update(chunk)
            self.file_hash = hasher.hexdigest()

        # Ensure only one version is marked as current per document
        if self.is_current:
            ComplianceDocumentVersion.objects.filter(document=self.document, is_current=True).exclude(
                pk=self.pk
            ).update(is_current=False)

        super().save(*args, **kwargs)

    def make_current(self):
        """Mark this version as the current one and update the parent document"""
        self.is_current = True
        self.save()

        doc = self.document
        doc.version = self.version_number
        doc.file = self.file
        doc.original_filename = self.original_filename
        doc.file_size = self.file_size
        doc.save(update_fields=["version", "file", "original_filename", "file_size", "updated_at"])


# =============================================================================
# MAINTENANCE CALENDAR VIEW
# =============================================================================


class MaintenanceEvent(models.Model):
    """
    Unified model for all maintenance-related events across the application.
    Aggregates build server maintenance, calibration schedules, system downtime,
    and custom maintenance tasks into a single calendar-viewable model.
    """

    EVENT_TYPES = [
        ("build_server", "Build Server Maintenance"),
        ("calibration", "Calibration"),
        ("system_downtime", "System Downtime"),
        ("preventive", "Preventive Maintenance"),
        ("corrective", "Corrective Maintenance"),
        ("inspection", "Inspection"),
        ("upgrade", "Hardware/Software Upgrade"),
        ("relocation", "Relocation"),
        ("custom", "Custom Event"),
    ]

    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("overdue", "Overdue"),
        ("deferred", "Deferred"),
    ]

    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    RECURRENCE_CHOICES = [
        ("none", "No Recurrence"),
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("bi_weekly", "Bi-Weekly"),
        ("monthly", "Monthly"),
        ("quarterly", "Quarterly"),
        ("semi_annual", "Semi-Annual"),
        ("annual", "Annual"),
    ]

    COLOR_CHOICES = [
        ("#0B5FFF", "Blue"),
        ("#00C4B4", "Teal"),
        ("#dc3545", "Red"),
        ("#d4a017", "Amber"),
        ("#11998e", "Green"),
        ("#0044CC", "Dark Blue"),
        ("#6c757d", "Grey"),
    ]

    # Core details
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, db_index=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="scheduled")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="normal")
    color = models.CharField(
        max_length=10, choices=COLOR_CHOICES, default="#0B5FFF", help_text="Calendar display color"
    )

    # Scheduling
    start_datetime = models.DateTimeField(db_index=True)
    end_datetime = models.DateTimeField()
    all_day = models.BooleanField(default=False)

    # Recurrence
    recurrence = models.CharField(max_length=15, choices=RECURRENCE_CHOICES, default="none")
    recurrence_end_date = models.DateField(null=True, blank=True)

    # Linked objects (generic — at least one should be set for non-custom events)
    build_server = models.ForeignKey(
        "BuildServer", on_delete=models.CASCADE, null=True, blank=True, related_name="maintenance_events"
    )
    system = models.ForeignKey(
        "System", on_delete=models.CASCADE, null=True, blank=True, related_name="maintenance_events"
    )
    calibration_schedule = models.ForeignKey(
        "CalibrationSchedule", on_delete=models.CASCADE, null=True, blank=True, related_name="maintenance_events"
    )
    product = models.ForeignKey(
        "Product", on_delete=models.CASCADE, null=True, blank=True, related_name="maintenance_events"
    )

    # Stream
    stream = models.ForeignKey(
        "Stream", on_delete=models.CASCADE, related_name="maintenance_events", null=True, blank=True
    )

    # People
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_maintenance_events",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_maintenance_events",
    )

    # Completion details
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_maintenance_events",
    )
    completion_notes = models.TextField(blank=True)
    actual_duration_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    # Cost tracking
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    actual_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Notification
    reminder_sent = models.BooleanField(default=False)
    reminder_hours_before = models.IntegerField(default=24)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["start_datetime"]
        verbose_name = "Maintenance Event"
        verbose_name_plural = "Maintenance Events"
        indexes = [
            models.Index(fields=["event_type", "start_datetime"]),
            models.Index(fields=["status", "start_datetime"]),
            models.Index(fields=["stream", "start_datetime"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_event_type_display()}) - {self.start_datetime.strftime('%Y-%m-%d')}"

    @property
    def is_overdue(self):
        from django.utils import timezone

        return self.status == "scheduled" and self.end_datetime < timezone.now()

    @property
    def duration_hours(self):
        delta = self.end_datetime - self.start_datetime
        return delta.total_seconds() / 3600

    def get_linked_object_name(self):
        """Return human-readable name of the linked object"""
        if self.build_server:
            return f"Server: {self.build_server.hostname}"
        if self.system:
            return f"System: {self.system.name}"
        if self.calibration_schedule:
            return f"Calibration: {self.calibration_schedule.title}"
        if self.product:
            return f"Product: {self.product.name}"
        return "—"

    def to_calendar_event(self):
        """Serialize to a dictionary suitable for FullCalendar.js"""
        return {
            "id": self.pk,
            "title": self.title,
            "start": self.start_datetime.isoformat(),
            "end": self.end_datetime.isoformat(),
            "allDay": self.all_day,
            "color": self.color,
            "extendedProps": {
                "event_type": self.event_type,
                "status": self.status,
                "priority": self.priority,
                "description": self.description,
                "notes": self.notes,
                "assigned_to": self.assigned_to.get_full_name() if self.assigned_to else "",
                "assigned_to_id": self.assigned_to_id,
                "linked_object": self.get_linked_object_name(),
                "stream": self.stream.name if self.stream else "",
                "build_server_id": self.build_server_id,
                "system_id": self.system_id,
                "recurrence": self.recurrence,
            },
        }


# =============================================================================
# AI FEATURES — Models
# =============================================================================
