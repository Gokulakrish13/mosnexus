# pylint: disable=invalid-name,no-member,too-many-arguments,too-many-positional-arguments
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class AuditLog(models.Model):
    """
    Unified global audit log for tracking all user actions across the entire application.
    Uses Django's ContentType framework for polymorphic references to any model.
    """

    ACTION_CATEGORIES = [
        ("create", "Created"),
        ("update", "Updated"),
        ("delete", "Deleted"),
        ("view", "Viewed"),
        ("login", "Logged In"),
        ("logout", "Logged Out"),
        ("export", "Exported"),
        ("import", "Imported"),
        ("approve", "Approved"),
        ("reject", "Rejected"),
        ("assign", "Assigned"),
        ("unassign", "Unassigned"),
        ("status_change", "Status Changed"),
        ("permission_change", "Permission Changed"),
        ("system_event", "System Event"),
        ("allocation", "Allocation"),
        ("release", "Release"),
        ("reservation", "Reservation"),
        ("calibration", "Calibration"),
        ("compliance", "Compliance"),
        ("maintenance", "Maintenance"),
    ]

    SEVERITY_LEVELS = [
        ("info", "Information"),
        ("warning", "Warning"),
        ("error", "Error"),
        ("critical", "Critical"),
    ]

    MODULE_CHOICES = [
        ("auth", "Authentication"),
        ("users", "User Management"),
        ("products", "Products"),
        ("categories", "Categories"),
        ("systems", "Systems"),
        ("allocation", "System Allocation"),
        ("reservations", "Reservations"),
        ("waitlist", "Waitlist"),
        ("calibration", "Calibration"),
        ("compliance", "Compliance"),
        ("build_servers", "Build Servers"),
        ("holistic", "Holistic Dashboard"),
        ("projects", "Projects"),
        ("notes", "Notes"),
        ("streams", "Streams"),
        ("downtime", "Downtime"),
        ("inventory", "Inventory"),
        ("settings", "Settings"),
        ("admin", "Administration"),
        ("other", "Other"),
    ]

    # Action details
    action = models.CharField(max_length=30, choices=ACTION_CATEGORIES, db_index=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_LEVELS, default="info")
    module = models.CharField(max_length=30, choices=MODULE_CHOICES, default="other", db_index=True)

    # Description
    title = models.CharField(max_length=500, help_text="Human-readable summary of the action")
    description = models.TextField(blank=True, help_text="Detailed description of what changed")

    # Who performed the action
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        db_index=True,
    )
    user_display_name = models.CharField(
        max_length=255, blank=True, help_text="Cached display name in case user is deleted"
    )

    # What was affected (generic relation to any model)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")
    object_repr = models.CharField(max_length=500, blank=True, help_text="String representation of the affected object")

    # Context
    stream = models.ForeignKey("Stream", on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")

    # Change tracking (before/after values as JSON)
    old_values = models.JSONField(null=True, blank=True, help_text="Previous field values")
    new_values = models.JSONField(null=True, blank=True, help_text="New field values")

    # Request metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    request_method = models.CharField(max_length=10, blank=True)
    request_path = models.CharField(max_length=500, blank=True)

    # Timestamps
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        indexes = [
            models.Index(fields=["action", "timestamp"]),
            models.Index(fields=["module", "timestamp"]),
            models.Index(fields=["user", "timestamp"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        user_name = self.user_display_name or (self.user.username if self.user else "System")
        return f"[{self.get_severity_display()}] {user_name} - {self.title} ({self.timestamp})"

    @classmethod
    def log(
        cls,
        action,
        title,
        user=None,
        request=None,
        obj=None,
        module="other",
        severity="info",
        description="",
        old_values=None,
        new_values=None,
        stream=None,
    ):
        """
        Convenience class method to create an audit log entry.

        Usage:
            AuditLog.log('create', 'Created product X', user=request.user,
                         request=request, obj=product, module='products')
        """
        entry = cls(
            action=action,
            title=title,
            severity=severity,
            module=module,
            description=description,
            old_values=old_values,
            new_values=new_values,
            stream=stream,
        )

        if user:
            entry.user = user
            entry.user_display_name = f"{user.first_name} {user.last_name}".strip() or user.username

        if request:
            entry.ip_address = cls._get_client_ip(request)
            entry.user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]
            entry.request_method = request.method
            entry.request_path = request.path[:500]

        if obj:
            entry.content_type = ContentType.objects.get_for_model(obj)
            entry.object_id = obj.pk
            entry.object_repr = str(obj)[:500]

        entry.save()
        return entry

    @staticmethod
    def _get_client_ip(request):
        """Extract client IP from request, handling proxies"""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


# =============================================================================
# DASHBOARD WIDGETS / CUSTOMIZABLE HOME
# =============================================================================


class DashboardWidget(models.Model):
    """
    Defines available dashboard widget types that users can add to their dashboards.
    """

    WIDGET_TYPES = [
        ("stat_card", "Statistics Card"),
        ("chart", "Chart"),
        ("table", "Data Table"),
        ("timeline", "Activity Timeline"),
        ("calendar", "Calendar"),
        ("alerts", "Alerts Panel"),
        ("quick_links", "Quick Links"),
        ("notes", "My Notes"),
        ("reservations", "My Reservations"),
        ("calibration", "Calibration Status"),
        ("compliance", "Compliance Status"),
        ("system_health", "System Health"),
        ("utilization", "Utilization Overview"),
        ("inventory", "Inventory Summary"),
        ("projects", "Project Status"),
        ("custom_html", "Custom HTML"),
    ]

    SIZE_CHOICES = [
        ("small", "Small (1/4 width)"),
        ("medium", "Medium (1/2 width)"),
        ("large", "Large (3/4 width)"),
        ("full", "Full Width"),
    ]

    widget_type = models.CharField(max_length=30, choices=WIDGET_TYPES, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    icon_class = models.CharField(max_length=100, default="fas fa-chart-bar", help_text="FontAwesome icon CSS class")
    default_size = models.CharField(max_length=10, choices=SIZE_CHOICES, default="medium")
    is_active = models.BooleanField(default=True)
    requires_stream = models.BooleanField(default=False, help_text="Whether this widget requires a stream context")
    min_role = models.CharField(
        max_length=20, blank=True, default="user", help_text="Minimum role required to use this widget"
    )
    default_config = models.JSONField(null=True, blank=True, help_text="Default configuration for this widget type")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Dashboard Widget"
        verbose_name_plural = "Dashboard Widgets"

    def __str__(self):
        return f"{self.name} ({self.get_widget_type_display()})"


class UserDashboardLayout(models.Model):
    """
    Stores each user's personalized dashboard layout and widget configuration.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dashboard_layout")
    stream = models.ForeignKey(
        "Stream", on_delete=models.SET_NULL, null=True, blank=True, help_text="Default stream for this layout"
    )
    is_customized = models.BooleanField(default=False)
    theme = models.CharField(
        max_length=20,
        default="light",
        choices=[
            ("light", "Light Mode"),
            ("dark", "Dark Mode"),
            ("auto", "System Default"),
        ],
    )
    sidebar_collapsed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Dashboard Layout"
        verbose_name_plural = "User Dashboard Layouts"

    def __str__(self):
        return f"Dashboard layout for {self.user.username}"

    def get_widgets_ordered(self):
        """Return this user's widgets in display order"""
        return self.widgets.filter(is_visible=True).order_by("position_row", "position_col")

    def reset_to_default(self):
        """Reset all widgets to default configuration"""
        self.widgets.all().delete()
        self.is_customized = False
        self.save()
        UserDashboardWidget.create_default_widgets(self)


class UserDashboardWidget(models.Model):
    """
    Individual widget placement in a user's dashboard, with position and configuration.
    """

    SIZE_CHOICES = [
        ("small", "Small (1/4 width)"),
        ("medium", "Medium (1/2 width)"),
        ("large", "Large (3/4 width)"),
        ("full", "Full Width"),
    ]

    layout = models.ForeignKey("UserDashboardLayout", on_delete=models.CASCADE, related_name="widgets")
    widget = models.ForeignKey("DashboardWidget", on_delete=models.CASCADE, related_name="user_instances")

    # Position (grid system)
    position_row = models.IntegerField(default=0)
    position_col = models.IntegerField(default=0)
    size = models.CharField(max_length=10, choices=SIZE_CHOICES, default="medium")

    # Visibility
    is_visible = models.BooleanField(default=True)
    is_collapsed = models.BooleanField(default=False)

    # Widget-specific configuration (overrides DashboardWidget.default_config)
    config = models.JSONField(
        null=True, blank=True, help_text="Widget-specific settings (chart type, date range, etc.)"
    )

    # Custom title (overrides DashboardWidget.name)
    custom_title = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position_row", "position_col"]
        unique_together = ("layout", "position_row", "position_col")
        verbose_name = "User Dashboard Widget"
        verbose_name_plural = "User Dashboard Widgets"

    def __str__(self):
        return f"{self.layout.user.username} - {self.widget.name} @ ({self.position_row},{self.position_col})"

    def get_title(self):
        return self.custom_title or self.widget.name

    def get_config(self):
        """Merge default config with user overrides"""
        base = self.widget.default_config or {}
        override = self.config or {}
        return {**base, **override}

    @classmethod
    def create_default_widgets(cls, layout):
        """Create a default set of widgets for a new user dashboard"""
        defaults = [
            {
                "widget_type": "stat_card",
                "row": 0,
                "col": 0,
                "size": "full",
                "config": {"cards": ["products", "systems", "users", "online"]},
            },
            {"widget_type": "system_health", "row": 1, "col": 0, "size": "medium"},
            {"widget_type": "timeline", "row": 1, "col": 1, "size": "medium"},
            {"widget_type": "alerts", "row": 2, "col": 0, "size": "medium"},
            {"widget_type": "reservations", "row": 2, "col": 1, "size": "medium"},
            {"widget_type": "calibration", "row": 3, "col": 0, "size": "medium"},
            {"widget_type": "projects", "row": 3, "col": 1, "size": "medium"},
        ]
        for d in defaults:
            widget_def = DashboardWidget.objects.filter(widget_type=d["widget_type"], is_active=True).first()
            if widget_def:
                cls.objects.create(
                    layout=layout,
                    widget=widget_def,
                    position_row=d["row"],
                    position_col=d["col"],
                    size=d.get("size", "medium"),
                    config=d.get("config"),
                )


# =============================================================================
# ASSET LIFECYCLE MANAGEMENT
# =============================================================================
