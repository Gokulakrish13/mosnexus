# pylint: disable=no-else-return,no-member
from datetime import date, timedelta

from products.models._validators import _document_ext_validator

from django.conf import settings
from django.db import models


class CalibrationSchedule(models.Model):
    """
    Comprehensive calibration schedule tracking for equipment and systems.
    Manages calibration intervals, due dates, and compliance requirements.
    """

    CALIBRATION_TYPES = [
        ("initial", "Initial Calibration"),
        ("periodic", "Periodic Calibration"),
        ("post_repair", "Post-Repair Calibration"),
        ("verification", "Verification Check"),
        ("adjustment", "Adjustment/Alignment"),
        ("full", "Full Calibration"),
    ]

    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("due", "Due"),
        ("overdue", "Overdue"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("deferred", "Deferred"),
    ]

    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    INTERVAL_UNITS = [
        ("days", "Days"),
        ("weeks", "Weeks"),
        ("months", "Months"),
        ("years", "Years"),
    ]

    # Equipment association (can be Product, System, or BuildServer)
    product = models.ForeignKey(
        "Product", on_delete=models.CASCADE, null=True, blank=True, related_name="calibration_schedules"
    )
    system = models.ForeignKey(
        "System", on_delete=models.CASCADE, null=True, blank=True, related_name="calibration_schedules"
    )
    build_server = models.ForeignKey(
        "BuildServer", on_delete=models.CASCADE, null=True, blank=True, related_name="calibration_schedules"
    )

    # Stream association
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="calibration_schedules")

    # Calibration details
    title = models.CharField(max_length=255, verbose_name="Calibration Title")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    calibration_type = models.CharField(max_length=30, choices=CALIBRATION_TYPES, default="periodic")

    # Calibration parameters/procedures
    parameters = models.TextField(blank=True, null=True, help_text="Calibration parameters and acceptable ranges")
    procedures = models.TextField(blank=True, null=True, help_text="Step-by-step calibration procedures")
    equipment_required = models.TextField(blank=True, null=True, help_text="Equipment/tools required for calibration")

    # Schedule settings
    calibration_interval = models.IntegerField(default=12, verbose_name="Calibration Interval")
    interval_unit = models.CharField(max_length=10, choices=INTERVAL_UNITS, default="months")

    # Date tracking
    last_calibration_date = models.DateField(null=True, blank=True, verbose_name="Last Calibration Date")
    next_calibration_date = models.DateField(verbose_name="Next Calibration Due Date")
    reminder_days_before = models.IntegerField(default=30, help_text="Days before due date to send reminder")

    # Status and priority
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="scheduled")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="normal")

    # Compliance requirement link
    regulatory_requirement = models.ForeignKey(
        "RegulatoryRequirement", on_delete=models.SET_NULL, null=True, blank=True, related_name="calibration_schedules"
    )

    # Vendor/Service provider
    service_provider = models.CharField(max_length=255, blank=True, null=True, verbose_name="Service Provider/Vendor")
    service_provider_contact = models.CharField(max_length=255, blank=True, null=True)
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Responsible person
    responsible_person = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="responsible_calibrations",
    )
    backup_person = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="backup_calibrations"
    )

    # Notification settings
    notify_responsible = models.BooleanField(default=True)
    notify_lab_incharge = models.BooleanField(default=True)
    escalate_if_overdue = models.BooleanField(default=True)
    escalation_days = models.IntegerField(default=7, help_text="Days after due date to escalate")

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_calibration_schedules",
    )
    updated_at = models.DateTimeField(auto_now=True)

    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["next_calibration_date"]
        verbose_name = "Calibration Schedule"
        verbose_name_plural = "Calibration Schedules"

    def __str__(self):
        equipment = self.get_equipment_name()
        return f"{self.title} - {equipment} (Due: {self.next_calibration_date})"

    def get_equipment_name(self):
        """Return the name of the associated equipment"""
        if self.product:
            return f"Product: {self.product.name}"
        elif self.system:
            return f"System: {self.system.name}"
        elif self.build_server:
            return f"Server: {self.build_server.hostname}"
        return "Unknown Equipment"

    def get_equipment_object(self):
        """Return the actual equipment object"""
        return self.product or self.system or self.build_server

    def is_overdue(self):
        """Check if calibration is overdue"""
        return self.next_calibration_date < date.today() and self.status not in ["completed", "cancelled"]

    def is_due_soon(self, days=30):
        """Check if calibration is due within specified days"""
        return self.next_calibration_date <= date.today() + timedelta(days=days)

    def days_until_due(self):
        """Calculate days until calibration is due"""
        return (self.next_calibration_date - date.today()).days

    def calculate_next_due_date(self):
        """Calculate the next calibration due date based on interval"""
        if not self.last_calibration_date:
            return self.next_calibration_date

        if self.interval_unit == "days":
            delta = timedelta(days=self.calibration_interval)
        elif self.interval_unit == "weeks":
            delta = timedelta(weeks=self.calibration_interval)
        elif self.interval_unit == "months":
            # Approximate months
            delta = timedelta(days=self.calibration_interval * 30)
        elif self.interval_unit == "years":
            delta = timedelta(days=self.calibration_interval * 365)
        else:
            delta = timedelta(days=self.calibration_interval)

        return self.last_calibration_date + delta

    def update_status(self):
        """Update status based on dates"""
        today = date.today()
        if self.status in ["completed", "cancelled"]:
            return

        if self.next_calibration_date < today:
            self.status = "overdue"
        elif self.next_calibration_date == today:
            self.status = "due"
        elif self.next_calibration_date <= today + timedelta(days=self.reminder_days_before):
            self.status = "due"
        else:
            self.status = "scheduled"
        self.save(update_fields=["status"])


class CalibrationRecord(models.Model):
    """
    Record of completed calibration activities with results and certificates.
    """

    RESULT_CHOICES = [
        ("pass", "Pass"),
        ("pass_adjusted", "Pass (After Adjustment)"),
        ("fail", "Fail"),
        ("limited", "Limited Use"),
        ("refer", "Refer for Repair"),
    ]

    calibration_schedule = models.ForeignKey("CalibrationSchedule", on_delete=models.CASCADE, related_name="records")

    # Calibration execution details
    calibration_date = models.DateField(verbose_name="Calibration Date")
    performed_by = models.CharField(max_length=255, verbose_name="Performed By")
    performed_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="performed_calibrations",
    )

    # Results
    result = models.CharField(max_length=20, choices=RESULT_CHOICES)
    result_details = models.TextField(blank=True, null=True, verbose_name="Result Details")

    measurement_data = models.JSONField(null=True, blank=True, help_text="Calibration measurement data in JSON format")

    # Before/After values
    before_values = models.TextField(blank=True, null=True, help_text="Equipment readings before calibration")
    after_values = models.TextField(blank=True, null=True, help_text="Equipment readings after calibration")

    # Adjustments made
    adjustments_made = models.TextField(blank=True, null=True, help_text="Description of any adjustments made")

    # Equipment condition
    equipment_condition = models.TextField(
        blank=True, null=True, help_text="General condition of equipment during calibration"
    )
    issues_found = models.TextField(blank=True, null=True)
    recommendations = models.TextField(blank=True, null=True)

    # Cost tracking
    actual_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    labor_hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # Duration
    duration_minutes = models.IntegerField(null=True, blank=True)

    # Approval
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_calibrations"
    )
    approval_date = models.DateTimeField(null=True, blank=True)
    approval_notes = models.TextField(blank=True, null=True)

    # Environmental conditions during calibration
    temperature = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, help_text="Temperature in Celsius"
    )
    humidity = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, help_text="Relative humidity percentage"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-calibration_date"]
        verbose_name = "Calibration Record"
        verbose_name_plural = "Calibration Records"

    def __str__(self):
        return f"Calibration Record - {self.calibration_schedule.title} ({self.calibration_date})"


class CalibrationCertificate(models.Model):
    """
    Store and track calibration certificates with expiry management.
    """

    calibration_record = models.ForeignKey("CalibrationRecord", on_delete=models.CASCADE, related_name="certificates")

    # Certificate details
    certificate_number = models.CharField(max_length=100, unique=True, verbose_name="Certificate Number")
    certificate_file = models.FileField(
        upload_to="calibration_certificates/%Y/%m/",
        verbose_name="Certificate File",
        validators=[_document_ext_validator],
    )
    original_filename = models.CharField(max_length=255)

    # Issuing authority
    issued_by = models.CharField(max_length=255, verbose_name="Issued By")
    issuing_organization = models.CharField(max_length=255, verbose_name="Issuing Organization")
    accreditation_number = models.CharField(max_length=100, blank=True, null=True, verbose_name="Accreditation Number")

    # Dates
    issue_date = models.DateField(verbose_name="Issue Date")
    expiry_date = models.DateField(verbose_name="Expiry Date")

    # Scope and limitations
    scope = models.TextField(blank=True, null=True, help_text="Scope of calibration certificate")
    limitations = models.TextField(blank=True, null=True, help_text="Any limitations on the calibration")

    # Traceability
    traceability_info = models.TextField(blank=True, null=True, help_text="Measurement traceability information")
    reference_standards = models.TextField(blank=True, null=True, help_text="Reference standards used")

    # Notification settings
    expiry_reminder_days = models.IntegerField(default=60, help_text="Days before expiry to send reminder")
    reminder_sent = models.BooleanField(default=False)

    # Metadata
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-expiry_date"]
        verbose_name = "Calibration Certificate"
        verbose_name_plural = "Calibration Certificates"

    def __str__(self):
        return f"Certificate {self.certificate_number} (Expires: {self.expiry_date})"

    def is_expired(self):
        """Check if certificate is expired"""
        return self.expiry_date < date.today()

    def is_expiring_soon(self, days=60):
        """Check if certificate is expiring soon"""
        return self.expiry_date <= date.today() + timedelta(days=days)

    def days_until_expiry(self):
        """Calculate days until expiry"""
        return (self.expiry_date - date.today()).days
