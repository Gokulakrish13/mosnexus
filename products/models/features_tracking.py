# pylint: disable=broad-exception-caught,import-outside-toplevel,missing-class-docstring,no-member,protected-access
from products.models._validators import _excel_ext_validator
from products.models.users import UserRole

from django.conf import settings
from django.db import models


class Feature(models.Model):
    """Registry of every application feature that can be gated per role."""

    MODULE_CHOICES = [
        ("dashboard", "Dashboard & Navigation"),
        ("user_mgmt", "User Management"),
        ("stream_admin", "Stream & BU Administration"),
        ("inventory", "Inventory & Products"),
        ("sys_alloc", "System Allocation"),
        ("reservations", "Reservations & Booking"),
        ("calibration", "Calibration & Maintenance"),
        ("compliance", "Compliance & Regulatory"),
        ("analytics", "Analytics & Tracking"),
        ("collaboration", "Collaboration"),
        ("support", "Support & Help"),
        ("vendors", "Vendors & Supply Chain"),
        ("ai", "AI Features"),
        ("approvals", "Approval Workflows"),
        ("operations", "Operations"),
        ("search", "Global Search"),
        ("admin", "Administration & Audit"),
    ]

    code = models.CharField(max_length=80, unique=True, db_index=True, help_text='Unique slug, e.g. "product_manage"')
    name = models.CharField(max_length=120)
    module = models.CharField(max_length=30, choices=MODULE_CHOICES, db_index=True)
    description = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=60, default="fas fa-cube")
    url_names = models.JSONField(default=list, blank=True, help_text="List of Django URL names this feature covers")
    is_active = models.BooleanField(
        default=True, db_index=True, help_text="Inactive features are hidden from the matrix"
    )
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["module", "sort_order", "name"]

    def __str__(self):
        return f"[{self.module}] {self.name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._invalidate_fac_cache()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self._invalidate_fac_cache()

    @staticmethod
    def _invalidate_fac_cache():
        try:
            from products.middleware import FeatureAccessMiddleware

            FeatureAccessMiddleware.invalidate_cache()
        except Exception:
            pass


class FeatureRoleAccess(models.Model):
    """Per-role toggle for a single Feature.  app_admin is always granted."""

    feature = models.ForeignKey("Feature", on_delete=models.CASCADE, related_name="role_access")
    role = models.CharField(max_length=20, choices=UserRole.ROLE_CHOICES)
    has_access = models.BooleanField(default=False)

    class Meta:
        unique_together = ("feature", "role")
        ordering = ["feature", "role"]

    def __str__(self):
        state = "ON" if self.has_access else "OFF"
        return f"{self.feature.code} × {self.role} = {state}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        Feature._invalidate_fac_cache()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        Feature._invalidate_fac_cache()


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
    sublevel = models.ForeignKey("SubLevel", on_delete=models.CASCADE, related_name="history")
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
    subleveltool = models.ForeignKey("SubLevelTool", on_delete=models.CASCADE, related_name="history")
    action = models.CharField(max_length=32)  # 'Created' or 'Edited'
    by = models.CharField(max_length=255)
    at = models.DateTimeField(auto_now_add=True)
    details = models.TextField()

    def __str__(self):
        return f"{self.action} by {self.by} at {self.at}"


def zenition_upload_path(instance, filename):
    """Store zenition excels under zenition_excels/<product_name>/"""
    if instance.zenition_product:
        safe_name = instance.zenition_product.name.replace(" ", "_").replace("/", "_")
        return f"zenition_excels/{safe_name}/{filename}"
    return f"legacy_excels/{filename}"


class LegacyExcelUpload(models.Model):
    stream = models.CharField(max_length=64)
    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="legacy_excel_uploads",
        help_text="Business Unit this upload belongs to",
    )
    file = models.FileField(upload_to=zenition_upload_path, validators=[_excel_ext_validator])
    zenition_product = models.ForeignKey(
        "ZenitionProduct",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="excel_uploads",
        help_text="Zenition product this upload belongs to (null for legacy uploads)",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    preview_data = models.TextField(blank=True, null=True)  # Store preview as JSON or HTML

    def __str__(self):
        if self.zenition_product:
            return f"Zenition Excel for {self.zenition_product.name} uploaded at {self.uploaded_at}"
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
        ("todo", "To Do"),
        ("inprogress", "In Progress"),
        ("done", "Done"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="personal_tasks")
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="todo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"


class UsageTracking(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="usage_records")
    page_name = models.CharField(max_length=255)
    page_url = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)
    session_id = models.CharField(max_length=64, blank=True, null=True)
    ip_address = models.CharField(max_length=45, blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    session_duration = models.DurationField(blank=True, null=True)
    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_records",
        help_text="BU context in which this page view occurred",
    )

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["page_name"]),
            models.Index(fields=["timestamp"]),
            models.Index(fields=["business_unit"]),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.page_name} - {self.timestamp}"


class SystemStatus(models.Model):
    STATUS_CHOICES = [
        ("online", "Online"),
        ("maintenance", "Maintenance"),
        ("offline", "Offline"),
        ("warning", "Warning"),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="online")
    description = models.CharField(max_length=255, blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    uptime_percentage = models.FloatField(default=99.9)
    active_users = models.IntegerField(default=0)

    class Meta:
        ordering = ["-last_updated"]

    def __str__(self):
        return f"System {self.get_status_display()} - {self.description}"


class UserSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    session_key = models.CharField(max_length=40, unique=True)
    login_time = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-last_activity"]

    def __str__(self):
        return f"{self.user.username} - {self.login_time}"
