# pylint: disable=import-outside-toplevel,missing-class-docstring,no-member
"""Approval Workflows Engine — generic, configurable multi-level approval system.

Supports attaching approval workflows to any entity: purchase orders,
compliance documents, system decommissioning, vendor onboarding,
high-value inventory changes, etc.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


# ──────────────────────────────────────────────────────────────────────────
# Default system types — used for auto-seeding per BU
# ──────────────────────────────────────────────────────────────────────────
SYSTEM_ENTITY_TYPES = [
    ("purchase_order", "Purchase Order"),
    ("compliance_document", "Compliance Document"),
    ("system_decommission", "System Decommission"),
    ("vendor_onboarding", "Vendor Onboarding"),
    ("inventory_change", "Inventory Change"),
    ("asset_disposal", "Asset Disposal"),
    ("calibration_waiver", "Calibration Waiver"),
    ("custom", "Custom"),
]

SYSTEM_EVENT_TYPES = [
    ("product_scrapped", "Product → Scrapped", "Products"),
    ("product_handovered", "Product → Hand-Overed", "Products"),
    ("product_deleted", "Product → Deleted", "Products"),
    ("product_bulk_delete", "Product → Bulk Delete", "Products"),
    ("product_bulk_status", "Product → Bulk Status Change", "Products"),
    ("server_decommission", "Build Server → Decommissioned (Inactive/Offline)", "Build Servers"),
    ("server_deleted", "Build Server → Deleted", "Build Servers"),
    ("compliance_doc_approved", "Compliance Doc → Approved", "Compliance"),
    ("compliance_doc_archived", "Compliance Doc → Archived / Superseded", "Compliance"),
    ("compliance_doc_deleted", "Compliance Doc → Deleted", "Compliance"),
    ("vendor_onboarded", "Vendor → Onboarded (New)", "Vendors"),
    ("vendor_blacklisted", "Vendor → Blacklisted", "Vendors"),
    ("vendor_deleted", "Vendor → Deleted", "Vendors"),
    ("calibration_waiver", "Calibration → Deferred (Waiver)", "Calibration"),
    ("calibration_cancelled", "Calibration → Cancelled", "Calibration"),
    ("system_downtime_created", "System Downtime → Created", "Systems / Downtime"),
    ("asset_decommission", "Asset → Decommission", "Asset Lifecycle"),
    ("asset_disposal", "Asset → Disposal", "Asset Lifecycle"),
]

_SYSTEM_ENTITY_MAP = {k: v for k, v in SYSTEM_ENTITY_TYPES}
_SYSTEM_EVENT_MAP = {k: v for k, v, _c in SYSTEM_EVENT_TYPES}


# ──────────────────────────────────────────────────────────────────────────
# Discoverable Application Registry
# ──────────────────────────────────────────────────────────────────────────
# Master list of ALL entity types and event types the application knows
# about.  Admins pick from this list (no free-text entry required) when
# adding new entity/event types in the Settings tab.
#
# Layout:
#   DISCOVERABLE_ENTITY_TYPES = [(key, label, description), ...]
#   DISCOVERABLE_EVENT_TYPES  = [(key, label, category, description, is_wired), ...]
#
# ``is_wired`` means there is actual Python code in a view that calls
# fire_approval_trigger / check_approval_required with this event key.
# Un-wired events are still useful to register for future use; the UI
# flags them as "Available (not yet implemented)".
# ──────────────────────────────────────────────────────────────────────────

DISCOVERABLE_ENTITY_TYPES = [
    # ── Currently wired ──
    ("purchase_order", "Purchase Order", "General procurement / PO workflows"),
    ("compliance_document", "Compliance Document", "Regulatory & compliance document lifecycle"),
    ("system_decommission", "System Decommission", "Decommissioning systems or servers"),
    ("vendor_onboarding", "Vendor Onboarding", "New vendor onboarding / registration"),
    ("inventory_change", "Inventory Change", "High-value inventory mutations"),
    ("asset_disposal", "Asset Disposal", "Asset end-of-life / disposal workflows"),
    ("calibration_waiver", "Calibration Waiver", "Calibration deferral or waiver requests"),
    # ── Additional entity scopes ──
    ("product", "Product", "Product lifecycle changes (status, deletion, bulk ops)"),
    ("build_server", "Build Server", "Build server status changes & deletion"),
    ("vendor", "Vendor", "Vendor status changes (blacklist, deletion)"),
    ("project", "Project", "Project status changes (hold, cancel, complete)"),
    ("waste_record", "Waste Record", "Waste disposal & manifest workflows"),
    ("system_downtime", "System Downtime", "System downtime event creation"),
    ("asset_lifecycle", "Asset Lifecycle", "Asset lifecycle stage transitions"),
    ("regulatory_requirement", "Regulatory Requirement", "Regulatory compliance status changes"),
    ("custom", "Custom", "Custom / other entity type"),
]

DISCOVERABLE_EVENT_TYPES = [
    # ── Products ──
    ("product_scrapped", "Product → Scrapped", "Products", "Single product status changed to Scraped", True),
    ("product_handovered", "Product → Hand-Overed", "Products", "Single product status changed to Hand-Overed", True),
    ("product_deleted", "Product → Deleted", "Products", "Single product permanently deleted", True),
    ("product_bulk_delete", "Product → Bulk Delete", "Products", "Multiple products deleted at once", True),
    ("product_bulk_status", "Product → Bulk Status Change", "Products", "Multiple products status changed at once", True),
    ("product_status_inactive", "Product → Deactivated", "Products", "Product status changed to Not Active", True),
    # ── Build Servers ──
    ("server_decommission", "Build Server → Decommissioned", "Build Servers", "Server status set to Inactive/Offline", True),
    ("server_deleted", "Build Server → Deleted", "Build Servers", "Build server permanently deleted", True),
    ("server_maintenance", "Build Server → Under Maintenance", "Build Servers", "Server put into maintenance mode", True),
    # ── Compliance ──
    ("compliance_doc_approved", "Compliance Doc → Approved", "Compliance", "Compliance document approved or reviewed", True),
    ("compliance_doc_archived", "Compliance Doc → Archived / Superseded", "Compliance", "Compliance document archived or superseded", True),
    ("compliance_doc_deleted", "Compliance Doc → Deleted", "Compliance", "Compliance document permanently deleted", True),
    ("compliance_doc_created", "Compliance Doc → Created", "Compliance", "New compliance document created", True),
    # ── Vendors ──
    ("vendor_onboarded", "Vendor → Onboarded (New)", "Vendors", "New vendor registered in the system", True),
    ("vendor_blacklisted", "Vendor → Blacklisted", "Vendors", "Vendor status changed to blacklisted", True),
    ("vendor_deleted", "Vendor → Deleted", "Vendors", "Vendor permanently deleted", True),
    ("vendor_deactivated", "Vendor → Deactivated", "Vendors", "Vendor status set to inactive", True),
    # ── Calibration ──
    ("calibration_waiver", "Calibration → Deferred (Waiver)", "Calibration", "Calibration schedule deferred with waiver", True),
    ("calibration_cancelled", "Calibration → Cancelled", "Calibration", "Calibration schedule cancelled", True),
    ("calibration_overdue", "Calibration → Overdue", "Calibration", "Calibration become overdue without action", True),
    # ── Systems / Downtime ──
    ("system_downtime_created", "System Downtime → Created", "Systems / Downtime", "New system downtime event created", True),
    ("system_downtime_escalated", "System Downtime → Escalated", "Systems / Downtime", "Downtime event escalated", True),
    ("system_removed", "System → Removed / Dismantled", "Systems / Downtime", "System marked as removed or dismantled", True),
    # ── Asset Lifecycle ──
    ("asset_decommission", "Asset → Decommission", "Asset Lifecycle", "Asset moved to decommission stage", True),
    ("asset_disposal", "Asset → Disposal", "Asset Lifecycle", "Asset moved to disposal / scrapped stage", True),
    ("asset_handover", "Asset → Hand-Over", "Asset Lifecycle", "Asset transferred / handed over", True),
    # ── Projects ──
    ("project_cancelled", "Project → Cancelled", "Projects", "Project status changed to cancelled", True),
    ("project_on_hold", "Project → On Hold", "Projects", "Project status changed to on-hold", True),
    ("project_completed", "Project → Completed", "Projects", "Project marked as completed", True),
    # ── Waste Management ──
    ("waste_disposed", "Waste → Disposed", "Waste Management", "Waste record marked as disposed", True),
    ("waste_rejected", "Waste → Rejected / Returned", "Waste Management", "Waste disposal rejected or returned", True),
    # ── Regulatory ──
    ("regulatory_non_compliant", "Regulatory → Non-Compliant", "Regulatory", "Regulatory requirement marked non-compliant", True),
    ("regulatory_under_review", "Regulatory → Under Review", "Regulatory", "Regulatory requirement under review", True),
]

_DISCOVERABLE_ENTITY_MAP = {k: lbl for k, lbl, _d in DISCOVERABLE_ENTITY_TYPES}
_DISCOVERABLE_EVENT_MAP = {k: (lbl, cat, desc, wired) for k, lbl, cat, desc, wired in DISCOVERABLE_EVENT_TYPES}


class ApprovalEntityType(models.Model):
    """Admin-manageable entity type for approval workflow templates.

    System defaults are auto-seeded per BU; admins can add more via the UI.
    """

    business_unit = models.ForeignKey(
        "BusinessUnit", on_delete=models.CASCADE, related_name="approval_entity_types"
    )
    key = models.CharField(max_length=40, help_text="Unique machine key, e.g. purchase_order")
    label = models.CharField(max_length=100, help_text="Display label, e.g. Purchase Order")
    is_system = models.BooleanField(default=False, help_text="System-provided — cannot be deleted")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["label"]
        unique_together = ("business_unit", "key")

    def __str__(self):
        return self.label


class ApprovalEventType(models.Model):
    """Admin-manageable trigger event type for approval auto-triggers.

    System defaults are auto-seeded per BU; admins can add custom events.
    """

    business_unit = models.ForeignKey(
        "BusinessUnit", on_delete=models.CASCADE, related_name="approval_event_types"
    )
    key = models.CharField(max_length=40, help_text="Unique machine key, e.g. product_scrapped")
    label = models.CharField(max_length=100, help_text="Display label, e.g. Product → Scrapped")
    category = models.CharField(max_length=50, blank=True, default="", help_text="Group heading, e.g. Products")
    is_system = models.BooleanField(default=False, help_text="System-provided — cannot be deleted")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "label"]
        unique_together = ("business_unit", "key")

    def __str__(self):
        return self.label


def ensure_system_types(bu):
    """Seed system-default entity types and event types for a BU (idempotent)."""
    for key, label in SYSTEM_ENTITY_TYPES:
        ApprovalEntityType.objects.get_or_create(
            business_unit=bu, key=key,
            defaults={"label": label, "is_system": True},
        )
    for key, label, category in SYSTEM_EVENT_TYPES:
        ApprovalEventType.objects.get_or_create(
            business_unit=bu, key=key,
            defaults={"label": label, "category": category, "is_system": True},
        )


class ApprovalWorkflowTemplate(models.Model):
    """Reusable blueprint that defines an approval pipeline.

    Each template has ordered *steps* (ApprovalStepTemplate) that define
    who must approve and in what order.
    """

    # Kept for backward-compat references; actual choices now live in ApprovalEntityType.
    ENTITY_TYPE_CHOICES = SYSTEM_ENTITY_TYPES

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    entity_type = models.CharField(max_length=40, default="custom")
    business_unit = models.ForeignKey(
        "BusinessUnit", on_delete=models.CASCADE, related_name="approval_templates"
    )
    is_active = models.BooleanField(default=True)
    require_all_steps = models.BooleanField(
        default=True,
        help_text="If True, all steps must approve. If False, approval at any step finalises.",
    )
    auto_approve_timeout_hours = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Auto-approve if no action after this many hours (0 = disabled).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_approval_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def get_entity_type_display(self):
        """Look up label from DB first, fallback to system defaults."""
        if self.entity_type in _SYSTEM_ENTITY_MAP:
            return _SYSTEM_ENTITY_MAP[self.entity_type]
        try:
            return ApprovalEntityType.objects.get(
                business_unit=self.business_unit, key=self.entity_type
            ).label
        except ApprovalEntityType.DoesNotExist:
            return self.entity_type.replace("_", " ").title()

    def __str__(self):
        return f"{self.name} ({self.get_entity_type_display()})"

    @property
    def step_count(self):
        return self.steps.count()


class ApprovalStepTemplate(models.Model):
    """One ordered step in an ApprovalWorkflowTemplate."""

    APPROVER_TYPE_CHOICES = [
        ("role", "Any user with role"),
        ("specific_user", "Specific user"),
        ("manager", "Stream / BU manager"),
    ]

    template = models.ForeignKey(
        ApprovalWorkflowTemplate, on_delete=models.CASCADE, related_name="steps"
    )
    order = models.PositiveSmallIntegerField(
        help_text="1-based step order — lower runs first."
    )
    name = models.CharField(max_length=200)
    approver_type = models.CharField(max_length=20, choices=APPROVER_TYPE_CHOICES, default="role")
    approver_role = models.CharField(
        max_length=20,
        blank=True,
        help_text="Required role (e.g. admin, super_admin) when approver_type = role.",
    )
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_step_assignments",
        help_text="Specific user when approver_type = specific_user.",
    )
    is_mandatory = models.BooleanField(default=True)

    class Meta:
        ordering = ["template", "order"]
        unique_together = ("template", "order")

    def __str__(self):
        return f"Step {self.order}: {self.name}"


class ApprovalRequest(models.Model):
    """A concrete approval request tied to a specific entity via GenericForeignKey."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("in_review", "In Review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
        ("expired", "Expired"),
    ]
    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    template = models.ForeignKey(
        ApprovalWorkflowTemplate, on_delete=models.SET_NULL, null=True, related_name="requests"
    )
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="medium")

    # Generic relation to ANY model instance
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    business_unit = models.ForeignKey(
        "BusinessUnit", on_delete=models.CASCADE, related_name="approval_requests"
    )
    stream = models.ForeignKey(
        "Stream", on_delete=models.CASCADE, null=True, blank=True, related_name="approval_requests"
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="approval_requests_submitted",
    )
    current_step = models.PositiveSmallIntegerField(default=1)
    total_steps = models.PositiveSmallIntegerField(default=1)

    due_date = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # ── Enforcement fields ──
    intended_changes = models.JSONField(
        null=True,
        blank=True,
        help_text="JSON describing the blocked action to execute when approved.",
    )
    is_enforced = models.BooleanField(
        default=False,
        help_text="True = this request blocks a real action until approved/rejected.",
    )
    trigger_event = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text="The event key (e.g. project_completed) that created this request.",
    )
    enforcement_result = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Outcome after enforcement: executed, failed, cancelled, not_applicable.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} — {self.get_status_display()}"

    @property
    def progress_percent(self):
        if self.total_steps == 0:
            return 0
        completed = self.step_actions.filter(action__in=["approved"]).count()
        return int((completed / self.total_steps) * 100)

    @property
    def is_overdue(self):
        if self.due_date and self.status in ("pending", "in_review"):
            from django.utils import timezone
            return timezone.now() > self.due_date
        return False


class ApprovalStepAction(models.Model):
    """Records one approver's decision on a step within an ApprovalRequest."""

    ACTION_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("delegated", "Delegated"),
        ("skipped", "Skipped"),
    ]

    request = models.ForeignKey(
        ApprovalRequest, on_delete=models.CASCADE, related_name="step_actions"
    )
    step_order = models.PositiveSmallIntegerField()
    step_name = models.CharField(max_length=200)
    action = models.CharField(max_length=15, choices=ACTION_CHOICES, default="pending")
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_actions_taken",
    )
    comments = models.TextField(blank=True)
    acted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["request", "step_order"]

    def __str__(self):
        return f"Step {self.step_order} — {self.get_action_display()}"


class ApprovalComment(models.Model):
    """Discussion thread on an approval request."""

    request = models.ForeignKey(
        ApprovalRequest, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="approval_comments"
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment by {self.author} on {self.request}"


class ApprovalAutoTrigger(models.Model):
    """Configurable rule that automatically creates an ApprovalRequest when a
    matching incident / event occurs in the application.

    Admins configure these via the Approval Workflows dashboard → Trigger Rules.
    When an event matches (entity_type + event_action), the linked template is
    instantiated as a new approval request automatically.
    """

    # Kept for backward-compat references; actual choices now live in ApprovalEventType.
    EVENT_CHOICES = [(k, v) for k, v, _c in SYSTEM_EVENT_TYPES]

    PRIORITY_CHOICES = ApprovalRequest.PRIORITY_CHOICES

    business_unit = models.ForeignKey(
        "BusinessUnit", on_delete=models.CASCADE, related_name="approval_auto_triggers"
    )
    name = models.CharField(max_length=200, help_text="Human-readable rule name shown in audit trail")
    event_action = models.CharField(max_length=40)
    template = models.ForeignKey(
        ApprovalWorkflowTemplate,
        on_delete=models.CASCADE,
        related_name="auto_triggers",
        help_text="The workflow template to instantiate when the event fires.",
    )
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="high")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_approval_triggers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("business_unit", "event_action", "template")

    def get_event_action_display(self):
        """Look up label from DB first, fallback to system defaults."""
        if self.event_action in _SYSTEM_EVENT_MAP:
            return _SYSTEM_EVENT_MAP[self.event_action]
        try:
            return ApprovalEventType.objects.get(
                business_unit=self.business_unit, key=self.event_action
            ).label
        except ApprovalEventType.DoesNotExist:
            return self.event_action.replace("_", " ").title()

    def __str__(self):
        return f"{self.name} ({self.get_event_action_display()})"
