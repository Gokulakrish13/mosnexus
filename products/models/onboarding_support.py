# pylint: disable=no-member
from django.conf import settings
from django.db import models


class OnboardingProgress(models.Model):
    """
    Tracks which guided tours a user has completed.
    Each row represents one tour the user has finished (or dismissed).
    """

    TOUR_KEY_CHOICES = [
        ("dashboard_main", "Dashboard – Main Tour"),
        ("product_list", "Product List Tour"),
        ("category_list", "Category List Tour"),
        ("lifecycle_dashboard", "Lifecycle Dashboard Tour"),
        ("sub_level_data", "Sub Level Data Tour"),
        ("sub_level_tools", "Sub Level Tools Tour"),
        ("location_list", "Location List Tour"),
        ("system_allocation", "System Allocation Tour"),
        ("calibration_hub", "Calibration Hub Tour"),
        ("vendor_hub", "Vendor Hub Tour"),
        ("team_chat", "Team Chat Tour"),
        ("ai_features", "AI Features Tour"),
        ("compliance_hub", "Compliance Hub Tour"),
        ("reservations_hub", "Reservations Hub Tour"),
        ("build_servers", "Build Servers Tour"),
        ("notes", "Notes Tour"),
        ("analytics", "Analytics Tour"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="onboarding_progress")
    tour_key = models.CharField(max_length=50, choices=TOUR_KEY_CHOICES)
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "tour_key")
        ordering = ["-completed_at"]
        verbose_name = "Onboarding Progress"
        verbose_name_plural = "Onboarding Progress"

    def __str__(self):
        return f"{self.user.username} – {self.tour_key} @ {self.completed_at:%Y-%m-%d %H:%M}"


# =============================================================================
# TLD BADGE MANAGEMENT
# =============================================================================


class TLDBadgeRecord(models.Model):
    """
    Tracks TLD (Thermoluminescent Dosimeter) badge assignments per quarter/year.
    Each record represents one person's TLD badge for a given period.
    """

    QUARTER_CHOICES = [
        ("Q1", "Jan – Mar"),
        ("Q2", "Apr – Jun"),
        ("Q3", "Jul – Sep"),
        ("Q4", "Oct – Dec"),
    ]
    RENEWAL_STATUS_CHOICES = [
        ("active", "Active"),
        ("pending", "Pending Renewal"),
        ("renewed", "Renewed"),
        ("expired", "Expired"),
        ("returned", "Returned"),
        ("lost", "Lost / Replacement Issued"),
    ]

    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.CASCADE,
        related_name="tld_badge_records",
        help_text="Business Unit this TLD badge record belongs to",
    )
    stream = models.ForeignKey(
        "Stream",
        on_delete=models.CASCADE,
        related_name="tld_badge_records",
        null=True,
        blank=True,
        help_text="Stream this TLD badge record belongs to",
    )
    year = models.PositiveIntegerField(help_text="Badge year, e.g. 2025, 2026")
    quarter = models.CharField(max_length=2, choices=QUARTER_CHOICES, help_text="Quarter period")

    # Person details
    name = models.CharField(max_length=255, help_text="Full name of badge holder")
    email = models.EmailField(help_text="Email address of badge holder")
    tld_number = models.CharField(max_length=100, help_text="TLD badge number")
    code1_id = models.CharField(max_length=100, blank=True, help_text="CODE1 identifier")
    employee_id = models.CharField(max_length=100, blank=True, help_text="Employee ID")

    # Status
    renewal_status = models.CharField(
        max_length=20, choices=RENEWAL_STATUS_CHOICES, default="active", help_text="Current renewal status of the badge"
    )
    notes = models.TextField(blank=True, help_text="Additional notes or remarks")

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_tld_badges"
    )

    class Meta:
        ordering = ["year", "quarter", "name"]
        unique_together = [("business_unit", "stream", "tld_number", "year", "quarter")]
        verbose_name = "TLD Badge Record"
        verbose_name_plural = "TLD Badge Records"

    def __str__(self):
        return f"{self.name} – TLD#{self.tld_number} ({self.get_quarter_display()} {self.year})"

    @property
    def quarter_label(self):
        return self.get_quarter_display()


class TLDBadgeAuditLog(models.Model):
    """
    Audit trail for TLD Badge operations – records every create / edit / delete action.
    """

    ACTION_CHOICES = [
        ("create", "Created"),
        ("edit", "Edited"),
        ("delete", "Deleted"),
        ("bulk_import", "Bulk Imported"),
        ("bulk_status", "Bulk Status Update"),
    ]

    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.CASCADE,
        related_name="tld_audit_logs",
    )
    badge_record = models.ForeignKey(
        "TLDBadgeRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tld_audit_actions",
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField(blank=True, help_text="JSON or free-text change description")

    # Snapshot fields so we keep info even if the badge record is deleted
    badge_name = models.CharField(max_length=255, blank=True)
    badge_tld_number = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "TLD Badge Audit Log"
        verbose_name_plural = "TLD Badge Audit Logs"

    def __str__(self):
        return f"{self.get_action_display()} – {self.badge_name} by {self.performed_by} at {self.timestamp}"


# =============================================================================
# SUPPORT TICKETS  (Issues / Feature Requests / Enhancements)
# =============================================================================


class SupportTicket(models.Model):
    """A support ticket raised by a user — can be a bug report, feature request,
    enhancement request, or a general question."""

    CATEGORY_CHOICES = [
        ("bug", "Bug / Issue"),
        ("feature", "Feature Request"),
        ("enhancement", "Enhancement"),
        ("question", "General Question"),
    ]
    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]
    STATUS_CHOICES = [
        ("open", "Open"),
        ("in_progress", "In Progress"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="bug")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="medium")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="support_tickets")
    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.CASCADE,
        related_name="support_tickets",
        null=True,
        blank=True,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_category_display()}] {self.title}"

    @property
    def status_color(self):
        return {
            "open": "#3b82f6",
            "in_progress": "#f59e0b",
            "resolved": "#10b981",
            "closed": "#6b7280",
        }.get(self.status, "#6b7280")

    @property
    def priority_color(self):
        return {
            "low": "#6b7280",
            "medium": "#3b82f6",
            "high": "#f59e0b",
            "critical": "#ef4444",
        }.get(self.priority, "#6b7280")

    @property
    def category_icon(self):
        return {
            "bug": "fa-bug",
            "feature": "fa-lightbulb",
            "enhancement": "fa-wand-magic-sparkles",
            "question": "fa-circle-question",
        }.get(self.category, "fa-ticket")


class SupportTicketReply(models.Model):
    """A reply / comment on a support ticket — from either the user or an admin."""

    ticket = models.ForeignKey("SupportTicket", on_delete=models.CASCADE, related_name="replies")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ticket_replies")
    message = models.TextField()
    is_admin_reply = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Reply by {self.user.username} on {self.ticket.title[:30]}"


class LiveSupportSession(models.Model):
    """A real-time support chat session between a user and an app admin."""

    STATUS_CHOICES = [
        ("waiting", "Waiting"),
        ("active", "Active"),
        ("closed", "Closed"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="support_sessions")
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_support_sessions",
    )
    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.CASCADE,
        related_name="support_sessions",
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="waiting")
    subject = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Support #{self.pk} — {self.user.username} ({self.get_status_display()})"


class LiveSupportMessage(models.Model):
    """A single message inside a live support chat session."""

    session = models.ForeignKey("LiveSupportSession", on_delete=models.CASCADE, related_name="messages")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user.username}: {self.message[:40]}"
