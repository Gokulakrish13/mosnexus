# pylint: disable=no-member
from products.models._validators import _image_ext_validator

from django.conf import settings
from django.db import models


class BUDeletionRequest(models.Model):
    """
    Two-step deletion approval for Business Units.
    Step 1: An app-admin requests deletion (password-verified).
    Step 2: A *different* app-admin/superuser approves (password-verified) → BU is hard-deleted.
    """

    STATUS_CHOICES = [
        ("pending", "Pending Approval"),
        ("approved", "Approved & Deleted"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
    ]

    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deletion_requests",
    )
    bu_snapshot = models.JSONField(
        default=dict,
        help_text="Snapshot of BU data at request time (name, slug, streams, users) for audit.",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="bu_delete_requests",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    request_reason = models.TextField(blank=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="pending")

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bu_delete_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]
        verbose_name = "BU Deletion Request"
        verbose_name_plural = "BU Deletion Requests"

    def __str__(self):
        bu_label = self.bu_snapshot.get("slug", "(deleted)")
        return f"Delete '{bu_label}' – {self.get_status_display()}"


# ─── Site-wide Settings (singleton) ──────────────────────────────────────────
class SiteSetting(models.Model):
    """
    Singleton model for site-wide configuration toggles.
    Only one row should ever exist (pk=1).
    """

    devtools_protection = models.BooleanField(
        default=False,
        help_text="Block right-click context menu, F12, Ctrl+Shift+I/J/C, and Ctrl+U to prevent DevTools access.",
    )

    # Audit log retention settings
    audit_log_auto_cleanup = models.BooleanField(
        default=True,
        help_text="Automatically delete audit logs older than the retention period.",
    )
    audit_log_retention_months = models.PositiveIntegerField(
        default=6,
        help_text="Number of months to retain audit log entries.",
    )
    audit_log_keep_critical = models.BooleanField(
        default=True,
        help_text="Preserve critical severity logs even when auto-cleanup runs.",
    )
    audit_log_last_cleanup = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the last automatic audit log cleanup.",
    )

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="site_setting_updates",
    )

    class Meta:
        verbose_name = "Site Setting"
        verbose_name_plural = "Site Settings"

    def __str__(self):
        return "Site Settings"

    def save(self, *args, **kwargs):
        # Enforce singleton: always use pk=1
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        """Return the singleton instance, creating it if needed."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class DemoRequest(models.Model):
    """
    Demo requests submitted from the public home page.
    Visible only to application admins.
    """

    STATUS_CHOICES = [
        ("new", "New"),
        ("contacted", "Contacted"),
        ("scheduled", "Scheduled"),
        ("completed", "Completed"),
        ("declined", "Declined"),
    ]

    full_name = models.CharField(max_length=200)
    email = models.EmailField()
    organization = models.CharField(max_length=255)
    preferred_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")
    admin_notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_demo_requests",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Demo Request"
        verbose_name_plural = "Demo Requests"

    def __str__(self):
        return f"{self.full_name} — {self.organization} ({self.get_status_display()})"


class VulnerabilityReport(models.Model):
    """
    Vulnerability reports submitted from the public home page Security modal.
    Visible only to application admins.
    """

    SEVERITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    STATUS_CHOICES = [
        ("new", "New"),
        ("investigating", "Investigating"),
        ("confirmed", "Confirmed"),
        ("resolved", "Resolved"),
        ("dismissed", "Dismissed"),
    ]

    reporter_name = models.CharField(max_length=200)
    reporter_email = models.EmailField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default="medium")
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")
    admin_notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_vulnerability_reports",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Vulnerability Report"
        verbose_name_plural = "Vulnerability Reports"

    def __str__(self):
        return f"{self.reporter_name} — {self.get_severity_display()} ({self.get_status_display()})"


def bu_showcase_image_path(instance, filename):
    """Upload showcase images to media/bu_showcase/<bu_slug>/"""
    return f"bu_showcase/{instance.business_unit.slug}/{filename}"


class BUShowcaseProduct(models.Model):
    """
    Editable product showcase cards displayed on the dashboard per BU.
    Only Application Admins can create/edit/delete these.
    """

    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.CASCADE,
        related_name="showcase_products",
        help_text="The Business Unit this showcase card belongs to.",
    )
    title = models.CharField(max_length=100, help_text='Product title, e.g. "Z10"')
    description = models.CharField(
        max_length=255, help_text='Short description, e.g. "High-Performance Imaging System"'
    )
    badge = models.CharField(
        max_length=40, blank=True, default="Featured", help_text='Badge label, e.g. "Featured", "Popular", "Pro"'
    )
    image = models.ImageField(
        upload_to=bu_showcase_image_path,
        blank=True,
        null=True,
        help_text="Product showcase image",
        validators=[_image_ext_validator],
    )
    spec_1 = models.CharField(max_length=60, blank=True, help_text='First spec tag, e.g. "4K Display"')
    spec_2 = models.CharField(max_length=60, blank=True, help_text='Second spec tag, e.g. "Real-time"')
    display_order = models.PositiveIntegerField(default=0, help_text="Lower numbers appear first")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["display_order", "title"]
        verbose_name = "BU Showcase Product"
        verbose_name_plural = "BU Showcase Products"

    def __str__(self):
        return f"{self.business_unit.slug} – {self.title}"


# =============================================================================
# LAB WASTE MANAGEMENT
# =============================================================================
