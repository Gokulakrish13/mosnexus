# pylint: disable=no-member
from datetime import date, timedelta

from products.models._validators import _document_ext_validator

from django.conf import settings
from django.db import models


class ComplianceDocument(models.Model):
    """
    Store and manage compliance-related documents with version control.
    """

    DOCUMENT_TYPES = [
        ("policy", "Policy Document"),
        ("procedure", "Procedure/SOP"),
        ("standard", "Standard/Specification"),
        ("certificate", "Certificate"),
        ("audit_report", "Audit Report"),
        ("training", "Training Material"),
        ("checklist", "Checklist"),
        ("guideline", "Guideline"),
        ("form", "Form/Template"),
        ("record", "Record"),
        ("other", "Other"),
    ]

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("pending_review", "Pending Review"),
        ("approved", "Approved"),
        ("archived", "Archived"),
        ("superseded", "Superseded"),
    ]

    # Document identification
    title = models.CharField(max_length=255, verbose_name="Document Title")
    document_id = models.CharField(max_length=50, unique=True, verbose_name="Document ID")
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPES)

    # File
    file = models.FileField(upload_to="compliance_documents/%Y/%m/", validators=[_document_ext_validator])
    original_filename = models.CharField(max_length=255)
    file_size = models.IntegerField(null=True, blank=True)

    # Version control
    version = models.CharField(max_length=20, default="1.0")
    revision_date = models.DateField(verbose_name="Revision Date")
    previous_version = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="newer_versions"
    )

    # Description and scope
    description = models.TextField(blank=True, null=True)
    scope = models.TextField(blank=True, null=True, help_text="Scope of applicability")
    keywords = models.CharField(max_length=500, blank=True, null=True, help_text="Comma-separated keywords for search")

    # Status and validity
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    effective_date = models.DateField(null=True, blank=True, verbose_name="Effective Date")
    expiry_date = models.DateField(null=True, blank=True, verbose_name="Expiry Date")
    review_date = models.DateField(null=True, blank=True, verbose_name="Next Review Date")

    # Stream association
    stream = models.ForeignKey(
        "Stream", on_delete=models.CASCADE, related_name="compliance_documents", null=True, blank=True
    )

    # Regulatory association
    regulatory_requirement = models.ForeignKey(
        "RegulatoryRequirement", on_delete=models.SET_NULL, null=True, blank=True, related_name="documents"
    )

    # Authorship and approval
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_compliance_docs",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_compliance_docs",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_compliance_docs",
    )
    approval_date = models.DateTimeField(null=True, blank=True)

    # Distribution
    distribution_list = models.TextField(blank=True, null=True, help_text="List of roles/users who should have access")
    is_confidential = models.BooleanField(default=False)

    # Change tracking
    change_summary = models.TextField(blank=True, null=True, help_text="Summary of changes in this version")

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_compliance_docs",
    )

    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-revision_date", "title"]
        verbose_name = "Compliance Document"
        verbose_name_plural = "Compliance Documents"

    def __str__(self):
        return f"{self.document_id} - {self.title} (v{self.version})"

    def is_current(self):
        """Check if this is the current/active version"""
        return self.status == "approved" and not self.newer_versions.filter(status="approved").exists()

    def needs_review(self):
        """Check if document needs review"""
        if self.review_date:
            return self.review_date <= date.today()
        return False


class RegulatoryRequirement(models.Model):
    """
    Track regulatory requirements and compliance standards applicable to the organization.
    """

    COMPLIANCE_STATUS = [
        ("compliant", "Compliant"),
        ("partial", "Partially Compliant"),
        ("non_compliant", "Non-Compliant"),
        ("not_applicable", "Not Applicable"),
        ("under_review", "Under Review"),
    ]

    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    # Requirement identification
    requirement_id = models.CharField(max_length=50, unique=True, verbose_name="Requirement ID")
    title = models.CharField(max_length=255, verbose_name="Requirement Title")

    # Source/Authority
    regulatory_body = models.CharField(max_length=255, verbose_name="Regulatory Body/Authority")
    regulation_name = models.CharField(max_length=255, verbose_name="Regulation/Standard Name")
    regulation_section = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="Section/Clause Reference"
    )

    # Description
    description = models.TextField(verbose_name="Requirement Description")
    interpretation = models.TextField(
        blank=True, null=True, help_text="Organization's interpretation of the requirement"
    )

    # Applicability
    applies_to_products = models.BooleanField(default=True)
    applies_to_systems = models.BooleanField(default=True)
    applies_to_processes = models.BooleanField(default=False)
    applicable_streams = models.ManyToManyField(  # type: ignore[var-annotated]
        "Stream", blank=True, related_name="regulatory_requirements"
    )

    # Compliance tracking
    compliance_status = models.CharField(max_length=20, choices=COMPLIANCE_STATUS, default="under_review")
    compliance_evidence = models.TextField(blank=True, null=True, help_text="Evidence of compliance")
    compliance_gap = models.TextField(blank=True, null=True, help_text="Identified gaps in compliance")

    # Priority and dates
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="high")
    effective_date = models.DateField(null=True, blank=True)
    compliance_deadline = models.DateField(null=True, blank=True)
    last_audit_date = models.DateField(null=True, blank=True)
    next_audit_date = models.DateField(null=True, blank=True)

    # Ownership
    responsible_person = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="responsible_regulations",
    )

    # Actions and controls
    control_measures = models.TextField(blank=True, null=True, help_text="Control measures implemented")
    verification_method = models.TextField(blank=True, null=True, help_text="How compliance is verified")

    # External references
    external_url = models.URLField(blank=True, null=True, help_text="Link to official regulation document")

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_requirements"
    )
    updated_at = models.DateTimeField(auto_now=True)

    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["priority", "title"]
        verbose_name = "Regulatory Requirement"
        verbose_name_plural = "Regulatory Requirements"

    def __str__(self):
        return f"{self.requirement_id} - {self.title}"

    def is_deadline_approaching(self, days=30):
        """Check if compliance deadline is approaching"""
        if self.compliance_deadline:
            return self.compliance_deadline <= date.today() + timedelta(days=days)
        return False


class RegulatoryChecklist(models.Model):
    """
    Checklist for regulatory compliance verification.
    """

    STATUS_CHOICES = [
        ("not_started", "Not Started"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("verified", "Verified"),
    ]

    # Checklist identification
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    # Association
    regulatory_requirement = models.ForeignKey(
        "RegulatoryRequirement", on_delete=models.CASCADE, related_name="checklists"
    )
    stream = models.ForeignKey(
        "Stream", on_delete=models.CASCADE, related_name="regulatory_checklists", null=True, blank=True
    )

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="not_started")
    completion_percentage = models.IntegerField(default=0)

    # Dates
    target_date = models.DateField(null=True, blank=True)
    completed_date = models.DateField(null=True, blank=True)

    # Assignment
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_checklists"
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_checklists"
    )
    verification_date = models.DateTimeField(null=True, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_checklists"
    )
    updated_at = models.DateTimeField(auto_now=True)

    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Regulatory Checklist"
        verbose_name_plural = "Regulatory Checklists"

    def __str__(self):
        return f"{self.title} - {self.regulatory_requirement.title}"

    def update_completion_percentage(self):
        """Update completion percentage based on checklist items"""
        total_items = self.items.count()
        if total_items == 0:
            self.completion_percentage = 0
        else:
            completed_items = self.items.filter(is_completed=True).count()
            self.completion_percentage = int((completed_items / total_items) * 100)
        self.save(update_fields=["completion_percentage"])


class RegulatoryChecklistItem(models.Model):
    """
    Individual items in a regulatory checklist.
    """

    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    checklist = models.ForeignKey("RegulatoryChecklist", on_delete=models.CASCADE, related_name="items")

    # Item details
    item_number = models.IntegerField(verbose_name="Item Number")
    description = models.TextField(verbose_name="Requirement/Task Description")
    guidance = models.TextField(blank=True, null=True, help_text="Guidance notes for this item")

    # Status
    is_completed = models.BooleanField(default=False)
    is_not_applicable = models.BooleanField(default=False)

    # Priority
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="medium")

    # Evidence
    evidence_required = models.TextField(blank=True, null=True, help_text="What evidence is needed for compliance")
    evidence_provided = models.TextField(blank=True, null=True, help_text="Evidence that has been provided")
    evidence_file = models.FileField(upload_to="compliance_evidence/%Y/%m/", null=True, blank=True)

    # Completion details
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_checklist_items",
    )
    completed_date = models.DateTimeField(null=True, blank=True)
    completion_notes = models.TextField(blank=True, null=True)

    # Issues/Comments
    issues = models.TextField(blank=True, null=True, help_text="Any issues or non-conformances found")
    corrective_action = models.TextField(blank=True, null=True, help_text="Corrective action taken or planned")

    # Due date
    due_date = models.DateField(null=True, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["item_number"]
        unique_together = ("checklist", "item_number")
        verbose_name = "Checklist Item"
        verbose_name_plural = "Checklist Items"

    def __str__(self):
        return f"{self.checklist.title} - Item {self.item_number}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.checklist.update_completion_percentage()


class ComplianceAlert(models.Model):
    """
    Alerts for compliance-related events (expiring certificates, overdue calibrations, etc.)
    """

    ALERT_TYPES = [
        ("calibration_due", "Calibration Due"),
        ("calibration_overdue", "Calibration Overdue"),
        ("certificate_expiring", "Certificate Expiring"),
        ("certificate_expired", "Certificate Expired"),
        ("document_review", "Document Review Required"),
        ("compliance_deadline", "Compliance Deadline"),
        ("audit_scheduled", "Audit Scheduled"),
        ("checklist_incomplete", "Checklist Incomplete"),
    ]

    SEVERITY_CHOICES = [
        ("info", "Information"),
        ("warning", "Warning"),
        ("critical", "Critical"),
        ("urgent", "Urgent"),
    ]

    STATUS_CHOICES = [
        ("active", "Active"),
        ("acknowledged", "Acknowledged"),
        ("resolved", "Resolved"),
        ("dismissed", "Dismissed"),
    ]

    # Alert details
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default="warning")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    # Related objects (generic relation approach using IDs)
    related_calibration = models.ForeignKey(
        "CalibrationSchedule", on_delete=models.CASCADE, null=True, blank=True, related_name="alerts"
    )
    related_certificate = models.ForeignKey(
        "CalibrationCertificate", on_delete=models.CASCADE, null=True, blank=True, related_name="alerts"
    )
    related_document = models.ForeignKey(
        "ComplianceDocument", on_delete=models.CASCADE, null=True, blank=True, related_name="alerts"
    )
    related_requirement = models.ForeignKey(
        "RegulatoryRequirement", on_delete=models.CASCADE, null=True, blank=True, related_name="alerts"
    )

    # Stream
    stream = models.ForeignKey(
        "Stream", on_delete=models.CASCADE, related_name="compliance_alerts", null=True, blank=True
    )

    # Target user(s)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="compliance_alerts", null=True, blank=True
    )

    # Response tracking
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="acknowledged_alerts"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolved_alerts"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True, null=True)

    # Notification
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    # Auto-dismiss
    auto_dismiss_date = models.DateField(null=True, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-severity", "-created_at"]
        verbose_name = "Compliance Alert"
        verbose_name_plural = "Compliance Alerts"

    def __str__(self):
        return f"[{self.get_severity_display()}] {self.title}"


# =============================================================================
# GLOBAL AUDIT LOG / ACTIVITY TIMELINE
# =============================================================================
