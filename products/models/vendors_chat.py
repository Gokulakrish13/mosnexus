# pylint: disable=import-outside-toplevel,no-else-return,no-member
from products.models._validators import _document_ext_validator, _image_ext_validator

from django.conf import settings
from django.db import models


class Vendor(models.Model):
    """Vendor / Supplier linked to a Business Unit and optionally a Stream."""

    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("blacklisted", "Blacklisted"),
        ("pending", "Pending Approval"),
    ]
    RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]  # 1-5 stars

    business_unit = models.ForeignKey("BusinessUnit", on_delete=models.CASCADE, related_name="vendors")
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="vendors", null=True, blank=True)

    # Identity
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=30, unique=True, editable=False, help_text="Auto-generated vendor code")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    # Contact
    contact_person = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    website = models.URLField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)

    # Business details
    category = models.CharField(
        max_length=120, blank=True, help_text="e.g. Hardware, Software, Calibration, Consumables"
    )
    tax_id = models.CharField(max_length=50, blank=True, verbose_name="Tax / VAT ID")
    payment_terms = models.CharField(max_length=100, blank=True, help_text="e.g. Net 30, Net 60")
    currency = models.CharField(max_length=10, default="EUR", blank=True)
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES, null=True, blank=True)

    # Notes & docs
    notes = models.TextField(blank=True)
    logo = models.ImageField(upload_to="vendor_logos/%Y/", null=True, blank=True, validators=[_image_ext_validator])

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_vendors"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="updated_vendors"
    )

    class Meta:
        ordering = ["name"]
        unique_together = [("name", "business_unit")]
        verbose_name = "Vendor"
        verbose_name_plural = "Vendors"

    def save(self, *args, **kwargs):
        if not self.code:
            import datetime as _dt

            today = _dt.date.today().strftime("%Y%m%d")
            last = Vendor.objects.filter(code__startswith=f"VND-{today}-").order_by("-code").first()
            seq = int(last.code.split("-")[-1]) + 1 if last else 1
            self.code = f"VND-{today}-{seq:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"


class VendorContract(models.Model):
    """Service contract or agreement linked to a vendor."""

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("expired", "Expired"),
        ("terminated", "Terminated"),
    ]
    vendor = models.ForeignKey("Vendor", on_delete=models.CASCADE, related_name="contracts")
    title = models.CharField(max_length=255)
    contract_number = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, default="EUR")
    document = models.FileField(
        upload_to="vendor_contracts/%Y/%m/", null=True, blank=True, validators=[_document_ext_validator]
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-start_date"]

    @property
    def is_expired(self):
        if self.end_date:
            import datetime as _dt

            return self.end_date < _dt.date.today()
        return False

    @property
    def days_until_expiry(self):
        if self.end_date:
            import datetime as _dt

            return (self.end_date - _dt.date.today()).days
        return None

    def __str__(self):
        return f"{self.title} – {self.vendor.name}"


class VendorPerformanceLog(models.Model):
    """Track vendor performance over time."""

    vendor = models.ForeignKey("Vendor", on_delete=models.CASCADE, related_name="performance_logs")
    date = models.DateField()
    rating = models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 6)])
    delivery_on_time = models.BooleanField(default=True)
    quality_ok = models.BooleanField(default=True)
    comments = models.TextField(blank=True)
    logged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.vendor.name} – {self.date} – {self.rating}/5"


# =============================================================================
# TEAM CHAT / COLLABORATION
# =============================================================================


class ChatRoom(models.Model):
    """Chat room — global, stream-specific, or private group."""

    ROOM_TYPE_CHOICES = [
        ("global", "Global"),
        ("stream", "Stream"),
        ("group", "Group"),
    ]
    name = models.CharField(max_length=120)
    room_type = models.CharField(max_length=10, choices=ROOM_TYPE_CHOICES, default="global")
    business_unit = models.ForeignKey("BusinessUnit", on_delete=models.CASCADE, related_name="chat_rooms")
    stream = models.ForeignKey(
        "Stream",
        on_delete=models.CASCADE,
        related_name="chat_rooms",
        null=True,
        blank=True,
        help_text="If set, limits this room to a specific stream",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    avatar_color = models.CharField(max_length=7, default="#0B5FFF", help_text="Hex colour for group avatar")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_chat_rooms"
    )

    class Meta:
        ordering = ["room_type", "name"]

    def __str__(self):
        if self.room_type == "group":
            return f"[Group] {self.name}"
        prefix = f"[{self.stream.name}]" if self.stream else "[Global]"
        return f"{prefix} {self.name}"

    @property
    def is_group(self):
        return self.room_type == "group"


class ChatRoomMember(models.Model):
    """Membership for group chat rooms. Only members can see/send messages."""

    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("member", "Member"),
    ]
    room = models.ForeignKey("ChatRoom", on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_memberships")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="member")
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of last read — for unread counts")
    is_muted = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    can_see_history = models.BooleanField(
        default=True, help_text="If False, member can only see messages sent after they joined"
    )

    class Meta:
        unique_together = ("room", "user")
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.user.username} in {self.room.name}"

    @property
    def unread_count(self):
        qs = self.room.messages.filter(is_deleted=False)
        if self.last_read_at:
            qs = qs.filter(created_at__gt=self.last_read_at)
        return qs.exclude(user=self.user).count()


class ChatMessage(models.Model):
    """Individual message inside a chat room."""

    MESSAGE_TYPE_CHOICES = [
        ("text", "Text"),
        ("system", "System"),
        ("file", "File"),
    ]
    room = models.ForeignKey("ChatRoom", on_delete=models.CASCADE, related_name="messages")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="chat_messages"
    )
    message = models.TextField()
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPE_CHOICES, default="text")
    is_deleted = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replies",
        help_text="Reply-to message for threading",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user.username}: {self.message[:40]}"


class ChatReaction(models.Model):
    """Emoji reaction on a message (like Teams)."""

    message = models.ForeignKey("ChatMessage", on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_reactions")
    emoji = models.CharField(max_length=10, help_text="Emoji character, e.g. 👍 😂 ❤️")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user", "emoji")

    def __str__(self):
        return f"{self.user.username} reacted {self.emoji}"


class ChatReadReceipt(models.Model):
    """Track which messages a user has seen — for 'seen by' indicators."""

    room = models.ForeignKey("ChatRoom", on_delete=models.CASCADE, related_name="read_receipts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_read_receipts")
    last_read_message = models.ForeignKey("ChatMessage", on_delete=models.CASCADE, null=True, blank=True)
    last_read_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("room", "user")

    def __str__(self):
        return f"{self.user.username} read {self.room.name}"


class ChatAttachment(models.Model):
    """File attachment on a chat message."""

    message = models.ForeignKey("ChatMessage", on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="chat_attachments/%Y/%m/", validators=[_document_ext_validator])
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=100)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_filename

    @property
    def is_image(self):
        return self.content_type.startswith("image/")

    @property
    def file_size_formatted(self):
        size = self.file_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"


# =============================================================================
# VENDOR PURCHASE ORDERS
# =============================================================================


class VendorPurchaseOrder(models.Model):
    """Purchase order / item request sent to a vendor."""

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("acknowledged", "Acknowledged"),
        ("in_progress", "In Progress"),
        ("partially_delivered", "Partially Delivered"),
        ("delivered", "Delivered"),
        ("cancelled", "Cancelled"),
        ("closed", "Closed"),
    ]
    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
        ("urgent", "Urgent"),
    ]
    vendor = models.ForeignKey("Vendor", on_delete=models.CASCADE, related_name="purchase_orders")
    po_number = models.CharField(max_length=40, unique=True, editable=False, help_text="Auto-generated PO number")
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default="draft")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="normal")
    order_date = models.DateField()
    expected_delivery_date = models.DateField(null=True, blank=True)
    actual_delivery_date = models.DateField(null=True, blank=True)
    shipping_address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="EUR")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_pos"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_pos"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Purchase Order"
        verbose_name_plural = "Purchase Orders"

    def save(self, *args, **kwargs):
        if not self.po_number:
            import datetime as _dt

            today = _dt.date.today().strftime("%Y%m%d")
            last = (
                VendorPurchaseOrder.objects.filter(po_number__startswith=f"PO-{today}-").order_by("-po_number").first()
            )
            seq = int(last.po_number.split("-")[-1]) + 1 if last else 1
            self.po_number = f"PO-{today}-{seq:04d}"
        super().save(*args, **kwargs)

    def recalculate_total(self):
        """Recalculate total from line items."""
        from django.db.models import F, Sum

        total = self.items.aggregate(total=Sum(F("quantity") * F("unit_price")))["total"] or 0
        self.total_amount = total
        self.save(update_fields=["total_amount"])

    @property
    def delivery_status_summary(self):
        """Return counts of ordered vs received quantities."""
        items = self.items.all()
        total_ordered = sum(i.quantity for i in items)
        total_received = sum(i.quantity_received for i in items)
        return {"ordered": total_ordered, "received": total_received, "pending": total_ordered - total_received}

    @property
    def is_overdue(self):
        import datetime as _dt

        if self.expected_delivery_date and self.status not in ("delivered", "closed", "cancelled"):
            return self.expected_delivery_date < _dt.date.today()
        return False

    def __str__(self):
        return f"{self.po_number} — {self.title}"


class VendorPurchaseOrderItem(models.Model):
    """Individual line item in a purchase order."""

    purchase_order = models.ForeignKey("VendorPurchaseOrder", on_delete=models.CASCADE, related_name="items")
    item_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    part_number = models.CharField(max_length=80, blank=True, help_text="Manufacturer / catalog part number")
    quantity = models.PositiveIntegerField(default=1)
    unit = models.CharField(max_length=30, default="pcs", help_text="e.g. pcs, kg, m, box")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity_received = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]

    @property
    def line_total(self):
        return self.quantity * self.unit_price

    @property
    def is_fully_received(self):
        return self.quantity_received >= self.quantity

    @property
    def remaining(self):
        return max(0, self.quantity - self.quantity_received)

    def __str__(self):
        return f"{self.item_name} x{self.quantity}"


class VendorDeliveryReceipt(models.Model):
    """Record of goods received against a purchase order."""

    purchase_order = models.ForeignKey("VendorPurchaseOrder", on_delete=models.CASCADE, related_name="deliveries")
    receipt_number = models.CharField(max_length=40, blank=True)
    received_date = models.DateField()
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_date"]
        verbose_name = "Delivery Receipt"
        verbose_name_plural = "Delivery Receipts"

    def __str__(self):
        return f"DR-{self.id} for {self.purchase_order.po_number}"


class VendorDeliveryReceiptItem(models.Model):
    """Individual line item in a delivery receipt."""

    delivery = models.ForeignKey("VendorDeliveryReceipt", on_delete=models.CASCADE, related_name="items")
    po_item = models.ForeignKey("VendorPurchaseOrderItem", on_delete=models.CASCADE, related_name="delivery_items")
    quantity_received = models.PositiveIntegerField(default=0)
    condition_ok = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update PO item received quantity from all delivery receipts
        total = self.po_item.delivery_items.aggregate(total=models.Sum("quantity_received"))["total"] or 0
        self.po_item.quantity_received = total
        self.po_item.save(update_fields=["quantity_received"])

    def __str__(self):
        return f"{self.po_item.item_name}: {self.quantity_received} received"


# ════════════════════════════════════════════════════════════════
# Onboarding / Guided-Tour Progress
# ════════════════════════════════════════════════════════════════
