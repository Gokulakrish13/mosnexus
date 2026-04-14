# pylint: disable=import-outside-toplevel,no-else-return,no-member
from datetime import date

from django.conf import settings
from django.db import models


class AssetLifecycleStage(models.Model):
    """
    Defines the stages in an asset's lifecycle with configurable transition rules.
    """

    STAGE_TYPES = [
        ("procurement", "Procurement"),
        ("receiving", "Receiving / Intake"),
        ("commissioning", "Commissioning"),
        ("active", "Active / In Service"),
        ("maintenance", "Under Maintenance"),
        ("repair", "Under Repair"),
        ("idle", "Idle / Standby"),
        ("handover", "Hand-Over"),
        ("decommission", "Decommissioning"),
        ("disposal", "Disposal / Scrapped"),
        ("archived", "Archived"),
    ]

    name = models.CharField(max_length=60, unique=True)
    stage_type = models.CharField(max_length=20, choices=STAGE_TYPES, unique=True)
    description = models.TextField(blank=True)
    icon_class = models.CharField(
        max_length=80, default="fas fa-circle", help_text="FontAwesome icon class for UI display"
    )
    color = models.CharField(max_length=20, default="#6c757d", help_text="Hex color code for badges and timeline")
    order = models.IntegerField(default=0, help_text="Display order in lifecycle timeline")

    # Rules
    requires_approval = models.BooleanField(default=False, help_text="Transition to this stage requires admin approval")
    requires_note = models.BooleanField(default=False, help_text="A note/reason is required to enter this stage")
    auto_notify = models.BooleanField(default=True, help_text="Send notification on stage transition")

    # Allowed transitions (which stages can transition TO this one)
    allowed_from_stages = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="can_transition_to",
        help_text="Stages that are allowed to transition to this stage",
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]
        verbose_name = "Asset Lifecycle Stage"
        verbose_name_plural = "Asset Lifecycle Stages"

    def __str__(self):
        return self.name


class AssetLifecycleRecord(models.Model):
    """
    Tracks the lifecycle of a specific product/asset through its stages,
    including procurement cost, depreciation, and end-of-life tracking.
    """

    CONDITION_CHOICES = [
        ("new", "New / Mint"),
        ("excellent", "Excellent"),
        ("good", "Good"),
        ("fair", "Fair"),
        ("poor", "Poor"),
        ("non_functional", "Non-Functional"),
    ]

    # Link to the product
    product = models.OneToOneField("Product", on_delete=models.CASCADE, related_name="lifecycle")

    # Current stage
    current_stage = models.ForeignKey("AssetLifecycleStage", on_delete=models.PROTECT, related_name="current_assets")

    # Procurement details
    purchase_date = models.DateField(null=True, blank=True)
    purchase_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Purchase Cost (EUR)"
    )
    vendor = models.CharField(max_length=255, blank=True)
    vendor_link = models.ForeignKey(
        "Vendor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lifecycle_records",
        help_text="Link to vendor/supplier record",
    )
    purchase_order_number = models.CharField(max_length=100, blank=True)
    invoice_number = models.CharField(max_length=100, blank=True)

    # Warranty
    warranty_start_date = models.DateField(null=True, blank=True)
    warranty_end_date = models.DateField(null=True, blank=True)
    warranty_provider = models.CharField(max_length=255, blank=True)
    warranty_terms = models.TextField(blank=True)

    # Depreciation
    expected_lifespan_years = models.IntegerField(null=True, blank=True, help_text="Expected useful life in years")
    salvage_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    depreciation_method = models.CharField(
        max_length=30,
        default="straight_line",
        choices=[
            ("straight_line", "Straight-Line"),
            ("declining_balance", "Declining Balance"),
            ("none", "No Depreciation"),
        ],
    )

    # Condition and maintenance
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default="new")
    total_maintenance_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    maintenance_count = models.IntegerField(default=0)
    last_maintenance_date = models.DateField(null=True, blank=True)
    next_maintenance_due = models.DateField(null=True, blank=True)

    # Disposal
    disposal_date = models.DateField(null=True, blank=True)
    disposal_method = models.CharField(
        max_length=50,
        blank=True,
        choices=[
            ("", "---"),
            ("recycled", "Recycled"),
            ("donated", "Donated"),
            ("sold", "Sold"),
            ("scrapped", "Scrapped"),
            ("returned", "Returned to Vendor"),
        ],
    )
    disposal_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    disposal_notes = models.TextField(blank=True)
    disposal_authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="authorized_disposals"
    )

    # Insurance
    insurance_policy = models.CharField(max_length=100, blank=True)
    insured_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_lifecycle_records",
    )

    class Meta:
        verbose_name = "Asset Lifecycle Record"
        verbose_name_plural = "Asset Lifecycle Records"

    def __str__(self):
        return f"{self.product.name} - {self.current_stage.name}"

    @property
    def current_book_value(self):
        """Calculate current depreciated book value"""
        if not self.purchase_cost or not self.purchase_date or not self.expected_lifespan_years:
            return self.purchase_cost

        if self.depreciation_method == "none":
            return self.purchase_cost

        age_days = (date.today() - self.purchase_date).days
        age_years = age_days / 365.25

        if age_years >= self.expected_lifespan_years:
            return self.salvage_value or 0

        if self.depreciation_method == "straight_line":
            annual_depreciation = (
                float(self.purchase_cost) - float(self.salvage_value or 0)
            ) / self.expected_lifespan_years
            return max(float(self.salvage_value or 0), float(self.purchase_cost) - (annual_depreciation * age_years))

        elif self.depreciation_method == "declining_balance":
            rate = 2.0 / self.expected_lifespan_years
            value = float(self.purchase_cost)
            for _ in range(int(age_years)):
                value *= 1 - rate
            return max(float(self.salvage_value or 0), value)

        return self.purchase_cost

    @property
    def warranty_status(self):
        """Get warranty status"""
        if not self.warranty_end_date:
            return "unknown"
        today = date.today()
        if today > self.warranty_end_date:
            return "expired"
        elif (self.warranty_end_date - today).days <= 90:
            return "expiring_soon"
        return "active"

    @property
    def total_cost_of_ownership(self):
        """Calculate TCO: purchase + maintenance"""
        purchase = float(self.purchase_cost or 0)
        maintenance = float(self.total_maintenance_cost or 0)
        return purchase + maintenance

    def transition_to(self, new_stage, user=None, note="", approved_by=None):
        """
        Transition the asset to a new lifecycle stage with validation.
        Creates a history record and optionally an audit log entry.
        """
        old_stage = self.current_stage

        if new_stage.allowed_from_stages.exists() and old_stage not in new_stage.allowed_from_stages.all():
            raise ValueError(f"Cannot transition from '{old_stage.name}' to '{new_stage.name}'")

        if new_stage.requires_approval and not approved_by:
            raise ValueError(f"Transition to '{new_stage.name}' requires admin approval")

        if new_stage.requires_note and not note:
            raise ValueError(f"Transition to '{new_stage.name}' requires a note/reason")

        self.current_stage = new_stage
        self.save()

        AssetLifecycleTransition.objects.create(
            lifecycle=self,
            from_stage=old_stage,
            to_stage=new_stage,
            transitioned_by=user,
            approved_by=approved_by,
            note=note,
        )

        return True


class AssetLifecycleTransition(models.Model):
    """
    Records individual stage transitions for a complete audit trail.
    """

    lifecycle = models.ForeignKey("AssetLifecycleRecord", on_delete=models.CASCADE, related_name="transitions")
    from_stage = models.ForeignKey("AssetLifecycleStage", on_delete=models.PROTECT, related_name="transitions_from")
    to_stage = models.ForeignKey("AssetLifecycleStage", on_delete=models.PROTECT, related_name="transitions_to")
    transitioned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="lifecycle_transitions"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_transitions"
    )
    note = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Lifecycle Transition"
        verbose_name_plural = "Lifecycle Transitions"

    def __str__(self):
        return f"{self.lifecycle.product.name}: {self.from_stage.name} → {self.to_stage.name}"


# =============================================================================
# INVENTORY ALERTS & THRESHOLDS
# =============================================================================


class InventoryThreshold(models.Model):
    """
    Configurable low-stock and over-stock thresholds for SubLevel inventory items.
    When inventory crosses a threshold, an alert is generated automatically.
    """

    ALERT_TYPES = [
        ("low_stock", "Low Stock Warning"),
        ("critical_stock", "Critical Stock Alert"),
        ("over_stock", "Over Stock Warning"),
        ("reorder", "Reorder Point Reached"),
    ]

    APPLIES_TO_CHOICES = [
        ("sublevel", "Sub Level"),
        ("sublevel_tool", "Sub Level Tool"),
        ("category", "Product Category"),
    ]

    name = models.CharField(max_length=255, help_text="Descriptive name for this threshold rule")
    applies_to = models.CharField(max_length=20, choices=APPLIES_TO_CHOICES)

    # Specific item references (at least one should be set)
    sublevel = models.ForeignKey("SubLevel", on_delete=models.CASCADE, null=True, blank=True, related_name="thresholds")
    sublevel_tool = models.ForeignKey(
        "SubLevelTool", on_delete=models.CASCADE, null=True, blank=True, related_name="thresholds"
    )
    category = models.ForeignKey("Category", on_delete=models.CASCADE, null=True, blank=True, related_name="thresholds")

    # Stream scope
    stream = models.ForeignKey(
        "Stream", on_delete=models.CASCADE, related_name="inventory_thresholds", null=True, blank=True
    )

    # Threshold values
    minimum_quantity = models.IntegerField(default=5, help_text="Alert when stock falls below this value")
    critical_quantity = models.IntegerField(default=2, help_text="Critical alert when stock falls below this value")
    maximum_quantity = models.IntegerField(null=True, blank=True, help_text="Alert when stock exceeds this value")
    reorder_point = models.IntegerField(null=True, blank=True, help_text="Point at which to reorder")
    reorder_quantity = models.IntegerField(null=True, blank=True, help_text="Suggested reorder quantity")

    # Notification settings
    notify_lab_incharge = models.BooleanField(default=True)
    notify_admin = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=False)
    auto_create_alert = models.BooleanField(
        default=True, help_text="Automatically create InventoryAlert when threshold is crossed"
    )

    # Status
    is_active = models.BooleanField(default=True)
    last_checked = models.DateTimeField(null=True, blank=True)
    last_alert_sent = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Inventory Threshold"
        verbose_name_plural = "Inventory Thresholds"

    def __str__(self):
        target = self.sublevel or self.sublevel_tool or self.category
        return f"{self.name} - {target}"

    def get_current_stock(self):
        """Get the current in_stock value for the monitored item"""
        if self.sublevel:
            return self.sublevel.in_stock
        elif self.sublevel_tool:
            return self.sublevel_tool.in_stock
        elif self.category:
            from products.models import Product

            return Product.objects.filter(category=self.category, status="Active").count()
        return 0

    def check_threshold(self):
        """Check current stock against thresholds and return alert type if triggered"""
        current = self.get_current_stock()

        if current <= self.critical_quantity:
            return "critical_stock"
        elif current <= self.minimum_quantity:
            return "low_stock"
        elif self.reorder_point and current <= self.reorder_point:
            return "reorder"
        elif self.maximum_quantity and current > self.maximum_quantity:
            return "over_stock"
        return None


class InventoryAlert(models.Model):
    """
    Generated alerts when inventory thresholds are crossed.
    """

    SEVERITY_CHOICES = [
        ("info", "Information"),
        ("warning", "Warning"),
        ("critical", "Critical"),
        ("resolved", "Resolved"),
    ]

    STATUS_CHOICES = [
        ("active", "Active"),
        ("acknowledged", "Acknowledged"),
        ("resolved", "Resolved"),
        ("dismissed", "Dismissed"),
    ]

    threshold = models.ForeignKey(
        "InventoryThreshold", on_delete=models.CASCADE, related_name="alerts", null=True, blank=True
    )
    alert_type = models.CharField(max_length=20, choices=InventoryThreshold.ALERT_TYPES)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="warning")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="active")

    # Alert details
    title = models.CharField(max_length=300)
    message = models.TextField()
    item_name = models.CharField(max_length=255, help_text="Name of the item that triggered the alert")
    current_quantity = models.IntegerField()
    threshold_value = models.IntegerField()

    # Stream
    stream = models.ForeignKey(
        "Stream", on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_alerts"
    )

    # Response
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_inventory_alerts",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_inventory_alerts",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Inventory Alert"
        verbose_name_plural = "Inventory Alerts"

    def __str__(self):
        return f"[{self.get_severity_display()}] {self.title}"


# =============================================================================
# FILE VERSIONING FOR COMPLIANCE DOCUMENTS
# =============================================================================
