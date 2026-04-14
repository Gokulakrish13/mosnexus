# pylint: disable=import-outside-toplevel,no-member
from products.models._validators import _document_ext_validator

from django.conf import settings
from django.db import models


class WasteCategory(models.Model):
    """
    Predefined waste categories (hazardous, non-hazardous, electronic, etc.).
    Scoped to a Business Unit so each BU can have its own waste taxonomy.
    """

    HAZARD_LEVELS = [
        ("non_hazardous", "Non-Hazardous"),
        ("hazardous", "Hazardous"),
        ("mixed", "Mixed / Conditional"),
    ]
    name = models.CharField(max_length=120, help_text="e.g. 'Electronic Waste', 'Chemical Solvents'")
    hazard_level = models.CharField(max_length=20, choices=HAZARD_LEVELS, default="non_hazardous")
    description = models.TextField(blank=True)
    icon_class = models.CharField(
        max_length=60, default="fas fa-trash-alt", help_text="FontAwesome icon for UI display"
    )
    color = models.CharField(max_length=20, default="#6c757d", help_text="Hex colour for badges")
    handling_instructions = models.TextField(blank=True, help_text="Safety / handling guidance for this waste type")
    regulatory_code = models.CharField(max_length=60, blank=True, help_text="EPA / RCRA / local regulatory waste code")
    business_unit = models.ForeignKey("BusinessUnit", on_delete=models.CASCADE, related_name="waste_categories")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["hazard_level", "name"]
        unique_together = [("name", "business_unit")]
        verbose_name = "Waste Category"
        verbose_name_plural = "Waste Categories"

    def __str__(self):
        return f"{self.name} ({self.get_hazard_level_display()})"


class WasteRecord(models.Model):
    """
    Individual waste record — tracks a batch of waste generated in a stream.
    Links to Product/SubLevel when items are scrapped through the existing flow.
    """

    STATUS_CHOICES = [
        ("generated", "Generated"),
        ("stored", "In Storage"),
        ("scheduled", "Disposal Scheduled"),
        ("manifested", "Manifest Created"),
        ("collected", "Collected / Picked Up"),
        ("disposed", "Disposed"),
        ("rejected", "Rejected / Returned"),
    ]
    UNIT_CHOICES = [
        ("kg", "Kilograms"),
        ("lbs", "Pounds"),
        ("liters", "Liters"),
        ("gallons", "Gallons"),
        ("units", "Units / Pieces"),
        ("bags", "Bags"),
        ("drums", "Drums"),
        ("boxes", "Boxes"),
    ]
    SOURCE_CHOICES = [
        ("manual", "Manual Entry"),
        ("product_scrap", "Product Scrapped"),
        ("sublevel_scrap", "SubLevel Scrapped"),
        ("lifecycle_disposal", "Asset Lifecycle Disposal"),
        ("maintenance", "Maintenance Activity"),
        ("calibration", "Calibration Waste"),
        ("general", "General Lab Waste"),
    ]

    # Identity
    tracking_number = models.CharField(
        max_length=30, unique=True, editable=False, help_text="Auto-generated: WR-YYYYMMDD-XXXX"
    )
    business_unit = models.ForeignKey("BusinessUnit", on_delete=models.CASCADE, related_name="waste_records")
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="waste_records")
    category = models.ForeignKey("WasteCategory", on_delete=models.PROTECT, related_name="waste_records")

    # Waste details
    description = models.TextField(help_text="Description of waste generated")
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default="units")
    weight_kg = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Estimated weight in kg (for regulatory reporting)",
    )

    # Source linking — connects to existing scrap system
    source = models.CharField(max_length=25, choices=SOURCE_CHOICES, default="manual")
    source_product = models.ForeignKey(
        "Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="waste_records",
        help_text="Product that was scrapped",
    )
    source_sublevel = models.ForeignKey(
        "SubLevel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="waste_records",
        help_text="SubLevel items that were scrapped",
    )
    source_reference = models.CharField(max_length=255, blank=True, help_text="Free-text reference (e.g. work order #)")

    # Storage location
    storage_location = models.CharField(max_length=200, blank=True, help_text="Where this waste is currently stored")
    container_type = models.CharField(max_length=100, blank=True, help_text="Container description, e.g. '55-gal drum'")
    container_id = models.CharField(max_length=50, blank=True, help_text="Container label / ID number")

    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="generated")
    generated_date = models.DateField(help_text="Date waste was generated")
    disposal_deadline = models.DateField(null=True, blank=True, help_text="Regulatory deadline for disposal")

    # Disposal details
    disposal_date = models.DateField(null=True, blank=True)
    disposal_method = models.CharField(
        max_length=60,
        blank=True,
        choices=[
            ("", "---"),
            ("incineration", "Incineration"),
            ("landfill", "Landfill (licensed)"),
            ("recycling", "Recycling"),
            ("chemical_treatment", "Chemical Treatment"),
            ("autoclave", "Autoclave / Sterilisation"),
            ("return_to_vendor", "Return to Vendor"),
            ("donation", "Donation"),
            ("other", "Other"),
        ],
    )
    disposal_vendor = models.CharField(max_length=200, blank=True, help_text="Licensed waste disposal company")
    disposal_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    disposal_certificate = models.FileField(
        upload_to="waste_documents/certificates/%Y/%m/", null=True, blank=True, validators=[_document_ext_validator]
    )

    # Manifest (for hazardous waste regulatory compliance)
    manifest_number = models.CharField(max_length=50, blank=True, help_text="Waste manifest or consignment number")
    manifest_document = models.FileField(
        upload_to="waste_documents/manifests/%Y/%m/", null=True, blank=True, validators=[_document_ext_validator]
    )

    # Notes & compliance
    notes = models.TextField(blank=True)
    is_compliant = models.BooleanField(default=True, help_text="Passes regulatory compliance check")
    compliance_notes = models.TextField(blank=True)

    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_waste_records"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="updated_waste_records"
    )

    class Meta:
        ordering = ["-generated_date", "-created_at"]
        verbose_name = "Waste Record"
        verbose_name_plural = "Waste Records"

    def __str__(self):
        return f"{self.tracking_number} — {self.category.name} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.tracking_number:
            import datetime as _dt

            today = _dt.date.today().strftime("%Y%m%d")
            last = (
                WasteRecord.objects.filter(tracking_number__startswith=f"WR-{today}-")
                .order_by("-tracking_number")
                .first()
            )
            seq = int(last.tracking_number.split("-")[-1]) + 1 if last else 1
            self.tracking_number = f"WR-{today}-{seq:04d}"
        super().save(*args, **kwargs)

    @property
    def is_overdue(self):
        import datetime as _dt

        if self.disposal_deadline and self.status not in ("disposed", "collected"):
            return self.disposal_deadline < _dt.date.today()
        return False

    @property
    def days_until_deadline(self):
        import datetime as _dt

        if self.disposal_deadline:
            return (self.disposal_deadline - _dt.date.today()).days
        return None


class WasteDisposalSchedule(models.Model):
    """
    Recurring or one-time disposal pickup schedule for a stream/BU.
    """

    FREQUENCY_CHOICES = [
        ("one_time", "One-Time"),
        ("weekly", "Weekly"),
        ("biweekly", "Bi-Weekly"),
        ("monthly", "Monthly"),
        ("quarterly", "Quarterly"),
    ]
    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("confirmed", "Confirmed"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]
    business_unit = models.ForeignKey("BusinessUnit", on_delete=models.CASCADE, related_name="waste_schedules")
    stream = models.ForeignKey(
        "Stream", on_delete=models.CASCADE, related_name="waste_schedules", null=True, blank=True
    )
    category = models.ForeignKey(
        "WasteCategory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disposal_schedules",
        help_text="Optional — limit to specific waste category",
    )
    vendor = models.CharField(max_length=200, help_text="Licensed disposal company")
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField(null=True, blank=True)
    frequency = models.CharField(max_length=15, choices=FREQUENCY_CHOICES, default="one_time")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="scheduled")
    contact_name = models.CharField(max_length=120, blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)
    waste_records = models.ManyToManyField(
        "WasteRecord", blank=True, related_name="disposal_schedules", help_text="Waste records included in this pickup"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["scheduled_date"]
        verbose_name = "Waste Disposal Schedule"
        verbose_name_plural = "Waste Disposal Schedules"

    def __str__(self):
        return f"{self.vendor} — {self.scheduled_date} ({self.get_status_display()})"


class WasteAuditLog(models.Model):
    """
    Immutable audit trail for every waste-related action.
    """

    ACTION_CHOICES = [
        ("created", "Created"),
        ("updated", "Updated"),
        ("status_changed", "Status Changed"),
        ("disposed", "Disposed"),
        ("schedule_created", "Schedule Created"),
        ("schedule_completed", "Schedule Completed"),
        ("manifest_uploaded", "Manifest Uploaded"),
        ("compliance_flagged", "Compliance Flagged"),
        ("auto_generated", "Auto-Generated from Scrap"),
    ]
    waste_record = models.ForeignKey(
        "WasteRecord", on_delete=models.CASCADE, related_name="audit_logs", null=True, blank=True
    )
    schedule = models.ForeignKey(
        "WasteDisposalSchedule", on_delete=models.CASCADE, related_name="audit_logs", null=True, blank=True
    )
    action = models.CharField(max_length=25, choices=ACTION_CHOICES)
    details = models.TextField(blank=True)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    performed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at"]
        verbose_name = "Waste Audit Log"
        verbose_name_plural = "Waste Audit Logs"

    def __str__(self):
        return f"{self.get_action_display()} by {self.performed_by} at {self.performed_at}"


# =============================================================================
# VENDOR / SUPPLIER MANAGEMENT
# =============================================================================
