# pylint: disable=import-outside-toplevel,missing-class-docstring,no-member
from products.models._validators import _image_ext_validator

from django.conf import settings
from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=255)
    serial_number = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="created_categories", on_delete=models.SET_NULL, null=True, blank=True
    )
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="categories")

    class Meta:
        unique_together = [("name", "stream"), ("serial_number", "stream")]

    def __str__(self):
        return f"{self.name} ({self.serial_number})"


class Product(models.Model):
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey("Category", related_name="products", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    serial_number = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="created_products", on_delete=models.SET_NULL, null=True, blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="updated_products", on_delete=models.SET_NULL, null=True, blank=True
    )
    status_choices = [
        ("Active", "Active"),
        ("Not Active", "Not Active"),
        ("Scraped", "Scraped"),
        ("Hand-Overed", "Hand-Overed"),
    ]
    status = models.CharField(max_length=20, choices=status_choices, default="Active")
    handover_team_type = models.CharField(max_length=20, blank=True, null=True)  # Internal/External
    handover_stream = models.ForeignKey(
        "Stream", null=True, blank=True, on_delete=models.SET_NULL, related_name="handover_products"
    )  # Target stream for Internal handover
    handover_external_team = models.CharField(max_length=255, blank=True, null=True)
    handover_owner = models.CharField(max_length=255, blank=True, null=True)
    location = models.ForeignKey("Location", null=True, blank=True, on_delete=models.SET_NULL)
    issue_description = models.TextField(blank=True, null=True)
    twelve_nc = models.CharField(max_length=255, blank=True, null=True)  # Philips 12-digit ordering code (12NC)
    device_serial_number = models.CharField(max_length=255, blank=True, null=True)  # Device / equipment serial number
    is_draft = models.BooleanField(
        default=False, help_text="Indicates the product entry is incomplete / saved as draft"
    )

    def __str__(self):
        return f"{self.name} ({self.serial_number})"

    class Meta:
        unique_together = ("serial_number", "stream")


class ProductImage(models.Model):
    product = models.ForeignKey("Product", related_name="images", on_delete=models.CASCADE)
    image = models.ImageField(upload_to="product_images/", validators=[_image_ext_validator])

    def __str__(self):
        return f"Image for {self.product.name}"


class ProductHistory(models.Model):
    product = models.ForeignKey("Product", related_name="history", on_delete=models.CASCADE)
    action = models.CharField(max_length=32)  # 'created' or 'edited'
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField(blank=True)

    def __str__(self):
        return f"{self.product.name} - {self.action} by {self.user} at {self.timestamp}"


class SystemAllocation(models.Model):
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="system_allocations")
    SYSTEM_CHOICES = [
        ("Z70 Full system", "Z70 Full system"),
        ("Z50 Table top", "Z50 Table top"),
        ("Z90 Full system", "Z90 Full system"),
        ("Z70/90 Rack System", "Z70/90 Rack System"),
        ("Z70/90 Table top", "Z70/90 Table top"),
        ("Z90 Table top", "Z90 Table top"),
        ("Z30 Table top", "Z30 Table top"),
        ("Z10 Table top", "Z10 Table top"),
    ]
    system_type = models.CharField(max_length=64, choices=SYSTEM_CHOICES)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    blocked_for_participant = models.ForeignKey("Participant", null=True, blank=True, on_delete=models.SET_NULL)
    reason = models.TextField(blank=True, default="", verbose_name="Reservation Reason")

    def __str__(self):
        return f"{self.system_type} blocked by {self.user} from {self.start_date} to {self.end_date}"


class SystemTicket(models.Model):
    """Server-side ticket tracking for system downtime/issues."""

    TICKET_STATUS = [
        ("open", "Open"),
        ("in_progress", "In Progress"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ]
    IMPACT_LEVELS = [
        ("critical", "Critical"),
        ("high", "High"),
        ("medium", "Medium"),
        ("low", "Low"),
    ]
    DOWNTIME_TYPES = [
        ("hardware_failure", "Hardware Failure"),
        ("software_issue", "Software Issue"),
        ("network_problem", "Network Problem"),
        ("maintenance", "Maintenance"),
        ("security_incident", "Security Incident"),
        ("power_outage", "Power Outage"),
        ("environmental", "Environmental"),
        ("other", "Other"),
    ]
    ticket_id = models.CharField(max_length=64, unique=True, db_index=True)
    system = models.ForeignKey("System", on_delete=models.CASCADE, related_name="tickets")
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="system_tickets")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=TICKET_STATUS, default="open")
    impact = models.CharField(max_length=20, choices=IMPACT_LEVELS, default="medium")
    downtime_type = models.CharField(max_length=30, choices=DOWNTIME_TYPES, default="other")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_tickets"
    )
    resolution = models.TextField(blank=True, null=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    sla_due = models.DateTimeField(null=True, blank=True)
    start_time = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.ticket_id} — {self.title}"

    def save(self, *args, **kwargs):
        if not self.sla_due and not self.pk:
            from datetime import timedelta

            from django.utils import timezone

            sla_map = {"critical": 4, "high": 24, "medium": 72, "low": 168}
            hours = sla_map.get(self.impact, 72)
            self.sla_due = timezone.now() + timedelta(hours=hours)
        super().save(*args, **kwargs)

    @property
    def is_sla_breached(self):
        from django.utils import timezone

        if self.sla_due and self.status not in ("resolved", "closed"):
            return timezone.now() > self.sla_due
        return False


class SystemTicketComment(models.Model):
    ticket = models.ForeignKey("SystemTicket", on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    text = models.TextField()
    comment_type = models.CharField(max_length=10, choices=[("user", "User"), ("system", "System")], default="user")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment on {self.ticket.ticket_id} by {self.author}"


class Participant(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.CASCADE,
        related_name="participants",
        null=True,
        blank=True,
        help_text="The Business Unit this participant belongs to",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.email})"


class Location(models.Model):
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="locations")
    name = models.CharField(max_length=128, unique=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
