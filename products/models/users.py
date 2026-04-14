# pylint: disable=attribute-defined-outside-init,import-outside-toplevel,missing-class-docstring,missing-type-doc,no-member,too-many-positional-arguments
from products.models._validators import _image_ext_validator

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db import models

User = get_user_model()


class UserRole(models.Model):
    """User can have multiple roles"""

    ROLE_CHOICES = [
        ("user", "Regular User"),
        ("lab_incharge", "Lab Incharge"),
        ("admin", "Admin"),
        ("super_admin", "Super Admin"),
        ("app_admin", "Application Admin"),
    ]

    custom_user = models.ForeignKey("CustomUser", on_delete=models.CASCADE, related_name="user_roles")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("custom_user", "role")

    def __str__(self):
        return f"{self.custom_user.user.username} - {self.get_role_display()}"


class UserBUAccess(models.Model):
    """Define which Business Units a user can access.

    This gates BU-level visibility: a user can only enter / view data
    for BUs they have been explicitly granted access to (super-admins
    bypass this).
    """

    custom_user = models.ForeignKey("CustomUser", on_delete=models.CASCADE, related_name="bu_access")
    business_unit = models.ForeignKey("BusinessUnit", on_delete=models.CASCADE, related_name="user_access")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("custom_user", "business_unit")
        verbose_name = "User BU Access"
        verbose_name_plural = "User BU Access"

    def __str__(self):
        return f"{self.custom_user.user.username} can access {self.business_unit}"


class UserStreamAccess(models.Model):
    """Define which streams a user can access"""

    custom_user = models.ForeignKey("CustomUser", on_delete=models.CASCADE, related_name="stream_access")
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("custom_user", "stream")

    def __str__(self):
        return f"{self.custom_user.user.username} can access {self.stream.name}"


class CustomUser(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="custom_profile")
    profile_image = models.ImageField(
        upload_to="profile_images/", null=True, blank=True, validators=[_image_ext_validator]
    )
    requested_streams = models.ManyToManyField("Stream", blank=True, related_name="requested_by_users")
    requested_bus = models.ManyToManyField(  # type: ignore[var-annotated]
        "BusinessUnit",
        blank=True,
        related_name="requested_by_users",
        help_text="BUs the user requested access to during registration",
    )

    # ── Role hierarchy
    _ROLE_HIERARCHY = ["app_admin", "super_admin", "admin", "lab_incharge", "user"]

    @property
    def _roles_set(self):
        """
        Cached set of role strings for this user within the current request.
        Fires ONE query and caches the result, eliminating N+1 on permission checks.
        """
        if not hasattr(self, "_cached_roles"):
            self._cached_roles = set(self.user_roles.values_list("role", flat=True))
        return self._cached_roles

    def clear_roles_cache(self):
        """Call when roles are changed to invalidate the cached set."""
        if hasattr(self, "_cached_roles"):
            del self._cached_roles

    def _has_any_role(self, roles):
        return bool(self._roles_set & set(roles)) or self.user.is_superuser

    def is_app_admin(self):
        return self._has_any_role(["app_admin"])

    def is_super_admin(self):
        return self._has_any_role(["super_admin", "app_admin"])

    def is_admin(self):
        return self._has_any_role(["admin", "super_admin", "app_admin"])

    def is_lab_incharge(self):
        return self._has_any_role(["lab_incharge", "admin", "super_admin", "app_admin"])

    def can_manage_users(self):
        return self._has_any_role(["admin", "super_admin", "app_admin"])

    def can_manage_system_allocation(self):
        return self._has_any_role(["lab_incharge", "admin", "super_admin", "app_admin"])

    def can_edit_products(self):
        return self._has_any_role(["lab_incharge", "admin", "super_admin", "app_admin"])

    def can_delete_products(self):
        return self._has_any_role(["admin", "super_admin", "app_admin"])

    def can_view_analytics(self):
        return self._has_any_role(["lab_incharge", "admin", "super_admin", "app_admin"])

    def highest_role_index(self):
        """Return the index of the user's highest role in _ROLE_HIERARCHY.

        Lower index = higher privilege.  Returns ``len(_ROLE_HIERARCHY)``
        (i.e. lowest possible privilege) if the user holds no roles.
        Django superusers *without any explicit roles* are treated as
        app_admin (index 0); otherwise the actual role set determines
        the level.
        """
        roles = self._roles_set
        if roles:
            indices = [self._ROLE_HIERARCHY.index(r) for r in roles if r in self._ROLE_HIERARCHY]
            return min(indices) if indices else len(self._ROLE_HIERARCHY)
        # Fallback: Django superuser with no explicit roles → app_admin level
        if self.user.is_superuser:
            return 0
        return len(self._ROLE_HIERARCHY)

    def has_role(self, role):
        """Check if user has a specific role"""
        return role in self._roles_set

    def has_any_role(self, roles):
        """Check if user has any of the specified roles"""
        return bool(self._roles_set & set(roles))

    def can_access_stream(self, stream_name):
        """Check if user can access a specific stream"""
        if self.is_super_admin():
            return True
        return self.stream_access.filter(stream__name=stream_name).exists()

    def get_accessible_streams(self, business_unit=None):
        """Get all streams the user can access, optionally filtered by BU.

        Args:
            business_unit: A BusinessUnit instance or ID. If provided, only
                           streams belonging to that BU are returned.
        """
        from products.models.system import Stream

        if self.is_super_admin():
            qs = Stream.objects.all()
        else:
            qs = Stream.objects.filter(id__in=self.stream_access.values_list("stream_id", flat=True))
        if business_unit is not None:
            bu_id = business_unit.id if hasattr(business_unit, "id") else business_unit
            qs = qs.filter(business_unit_id=bu_id)
        return qs

    # ── Business-Unit access helpers ──────────────────────────────
    def can_access_bu(self, business_unit):
        """Check if user can access a specific Business Unit.
        Application Admins can access all BUs.
        Other users must have explicit BU access."""
        if self.is_app_admin():
            return True
        bu_id = business_unit.id if hasattr(business_unit, "id") else business_unit
        return self.bu_access.filter(business_unit_id=bu_id).exists()

    def get_accessible_bus(self):
        """Get all BusinessUnits this user can access.
        Application Admins can access all active BUs.
        Other users must have explicit BU access."""
        from products.models.system import BusinessUnit

        if self.is_app_admin():
            return BusinessUnit.objects.filter(is_active=True)
        return BusinessUnit.objects.filter(
            id__in=self.bu_access.values_list("business_unit_id", flat=True),
            is_active=True,
        )

    def get_roles_display(self):
        """Get comma-separated string of user roles"""
        return ", ".join([role.get_role_display() for role in self.user_roles.all()])

    def save(self, *args, **kwargs):
        try:
            old = CustomUser.objects.get(pk=self.pk)
            if old.profile_image and self.profile_image and old.profile_image != self.profile_image:
                if default_storage.exists(old.profile_image.name):
                    default_storage.delete(old.profile_image.name)
        except CustomUser.DoesNotExist:
            pass
        super().save(*args, **kwargs)

    def __str__(self):
        return self.user.username


class Notification(models.Model):
    # ── Category groupings for the UI ──
    CATEGORY_CHOICES = [
        ("system", "System & Infrastructure"),
        ("support", "Support & Help"),
        ("user_mgmt", "User & Access"),
        ("project", "Projects & Tasks"),
        ("compliance", "Compliance & Quality"),
        ("inventory", "Inventory & Assets"),
        ("communication", "Communication"),
    ]

    # ── Notification types (granular) ──
    NOTIFICATION_TYPES = [
        # System & Infrastructure
        ("allocation", "System Allocation"),
        ("reservation", "Reservation / Booking"),
        ("waitlist", "Waitlist Update"),
        ("downtime", "System Downtime"),
        ("maintenance", "Maintenance Event"),
        ("build_server", "Build Server"),
        ("backup", "Backup / Restore"),
        ("system_event", "System Event"),
        # Support & Help
        ("support", "Support Ticket"),
        ("live_support", "Live Support"),
        # User & Access
        ("user_access", "User Access"),
        ("role_change", "Role Change"),
        ("admin", "Admin Action"),
        # Projects & Tasks
        ("project", "Project Update"),
        # Compliance & Quality
        ("calibration", "Calibration"),
        ("compliance", "Compliance Alert"),
        ("waste", "Waste Management"),
        ("tld", "TLD Badge"),
        # Inventory & Assets
        ("inventory", "Inventory Alert"),
        ("purchase_order", "Purchase Order"),
        ("lifecycle", "Asset Lifecycle"),
        # Communication
        ("chat", "Chat Message"),
        ("note", "Note Shared"),
    ]

    # Auto-map type → category
    CATEGORY_MAP = {
        "allocation": "system",
        "reservation": "system",
        "waitlist": "system",
        "downtime": "system",
        "maintenance": "system",
        "build_server": "system",
        "backup": "system",
        "system_event": "system",
        "support": "support",
        "live_support": "support",
        "user_access": "user_mgmt",
        "role_change": "user_mgmt",
        "admin": "user_mgmt",
        "project": "project",
        "calibration": "compliance",
        "compliance": "compliance",
        "waste": "compliance",
        "tld": "compliance",
        "inventory": "inventory",
        "purchase_order": "inventory",
        "lifecycle": "inventory",
        "chat": "communication",
        "note": "communication",
    }

    # Icon map for the UI
    ICON_MAP = {
        "allocation": "fas fa-desktop",
        "reservation": "fas fa-calendar-check",
        "waitlist": "fas fa-clock",
        "downtime": "fas fa-exclamation-triangle",
        "maintenance": "fas fa-tools",
        "build_server": "fas fa-server",
        "backup": "fas fa-database",
        "system_event": "fas fa-cog",
        "support": "fas fa-ticket-alt",
        "live_support": "fas fa-headset",
        "user_access": "fas fa-user-shield",
        "role_change": "fas fa-user-tag",
        "admin": "fas fa-shield-alt",
        "project": "fas fa-project-diagram",
        "calibration": "fas fa-ruler-combined",
        "compliance": "fas fa-clipboard-check",
        "waste": "fas fa-recycle",
        "tld": "fas fa-id-badge",
        "inventory": "fas fa-boxes",
        "purchase_order": "fas fa-file-invoice",
        "lifecycle": "fas fa-heartbeat",
        "chat": "fas fa-comment-dots",
        "note": "fas fa-sticky-note",
    }

    CATEGORY_ICON_MAP = {
        "system": "fas fa-server",
        "support": "fas fa-headset",
        "user_mgmt": "fas fa-users-cog",
        "project": "fas fa-project-diagram",
        "compliance": "fas fa-clipboard-check",
        "inventory": "fas fa-boxes",
        "communication": "fas fa-comments",
    }

    CATEGORY_COLOR_MAP = {
        "system": "#0066cc",
        "support": "#0B5FFF",
        "user_mgmt": "#059669",
        "project": "#d97706",
        "compliance": "#dc2626",
        "inventory": "#0891b2",
        "communication": "#0B5FFF",
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    message = models.CharField(max_length=512)
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="system", db_index=True)
    link = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.category or self.category == "system":
            self.category = self.CATEGORY_MAP.get(self.notification_type, "system")
        super().save(*args, **kwargs)

    @property
    def icon(self):
        return self.ICON_MAP.get(self.notification_type, "fas fa-bell")

    @property
    def category_color(self):
        return self.CATEGORY_COLOR_MAP.get(self.category, "#64748b")

    def __str__(self):
        return f"{self.user.username}: {self.message[:40]}..."

    @classmethod
    def notify(cls, users, message, notification_type, link=""):
        """Create notification(s) for one or more users.

        Args:
            users: A User, queryset, or list of Users
            message: Notification text (max 512 chars)
            notification_type: One of NOTIFICATION_TYPES keys
            link: Optional URL for click-through
        """
        if users is None:
            return
        if isinstance(users, User):
            users = [users]
        elif hasattr(users, "all"):
            users = list(users)
        if not users:
            return
        category = cls.CATEGORY_MAP.get(notification_type, "system")
        objs = [
            cls(user=u, message=message[:512], notification_type=notification_type, category=category, link=link)
            for u in users
            if u is not None
        ]
        if objs:
            cls.objects.bulk_create(objs)

    @classmethod
    def notify_admins(cls, bu, message, notification_type, link="", exclude_user=None):
        """Notify all app_admin / super_admin users for a Business Unit."""
        admin_profiles = (
            CustomUser.objects.filter(
                user__is_active=True,
                user_roles__role__in=["app_admin", "super_admin"],
            )
            .select_related("user")
            .distinct()
        )
        admin_users = []
        for cp in admin_profiles:
            if cp.user == exclude_user:
                continue
            if bu:
                if cp.stream_access.filter(stream__business_unit=bu).exists() or cp.user.is_superuser:
                    admin_users.append(cp.user)
            else:
                admin_users.append(cp.user)
        # Always include superusers
        for su in User.objects.filter(is_superuser=True, is_active=True):
            if su != exclude_user and su not in admin_users:
                admin_users.append(su)
        cls.notify(admin_users, message, notification_type, link)


# ═══════════════════════════════════════════════════════════════════════════════
#  Feature Access Control — dynamic, role-based feature gate (UI-managed)
# ═══════════════════════════════════════════════════════════════════════════════
