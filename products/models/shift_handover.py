# pylint: disable=import-outside-toplevel,no-member
"""
Shift Handover Log — structured handoff reports between lab shifts.
Tracks what's running, what's pending, blockers, safety notes, and general
remarks so the incoming shift has full context from day one.
"""

from django.conf import settings
from django.db import models


class ShiftType(models.Model):
    """
    Configurable shift definitions per Business Unit.
    e.g. Morning (06:00-14:00), Afternoon (14:00-22:00), Night (22:00-06:00).
    """

    name = models.CharField(max_length=60, help_text="e.g. 'Morning Shift', 'Night Shift'")
    code = models.CharField(max_length=20, help_text="Short code, e.g. 'morning', 'night'")
    start_time = models.TimeField(help_text="Shift start time")
    end_time = models.TimeField(help_text="Shift end time")
    color = models.CharField(max_length=20, default="#0066cc", help_text="Hex colour for UI badges")
    icon_class = models.CharField(max_length=60, default="fas fa-sun", help_text="FontAwesome icon")
    business_unit = models.ForeignKey(
        "BusinessUnit", on_delete=models.CASCADE, related_name="shift_types"
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "start_time"]
        unique_together = [("code", "business_unit")]
        verbose_name = "Shift Type"
        verbose_name_plural = "Shift Types"

    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}–{self.end_time:%H:%M})"


class ShiftHandoverLog(models.Model):
    """
    Main handover report created by the outgoing shift.
    Contains structured sections — running systems, pending tasks, blockers,
    safety notes, and general remarks.
    """

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("acknowledged", "Acknowledged"),
    ]
    PRIORITY_CHOICES = [
        ("normal", "Normal"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    # Identity
    handover_number = models.CharField(
        max_length=30, unique=True, editable=False,
        help_text="Auto-generated: SHL-YYYYMMDD-XXXX",
    )
    business_unit = models.ForeignKey(
        "BusinessUnit", on_delete=models.CASCADE, related_name="shift_handovers"
    )
    stream = models.ForeignKey(
        "Stream", on_delete=models.CASCADE, related_name="shift_handovers"
    )

    # Shift info
    shift_type = models.ForeignKey(
        ShiftType, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="handovers", help_text="Which shift is ending",
    )
    shift_date = models.DateField(help_text="Date of the shift being handed over")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="draft")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="normal")

    # Structured content sections
    systems_running = models.TextField(
        blank=True,
        help_text="Systems currently running — what tests, ETA, any special notes",
    )
    pending_actions = models.TextField(
        blank=True,
        help_text="Tasks started but not completed — what needs follow-up",
    )
    blockers_issues = models.TextField(
        blank=True,
        help_text="Blocked items, equipment down, parts ordered, escalations",
    )
    safety_notes = models.TextField(
        blank=True,
        help_text="Safety incidents, spills, hazards, PPE alerts",
    )
    bookings_handoff = models.TextField(
        blank=True,
        help_text="Upcoming bookings the next shift should be aware of",
    )
    general_notes = models.TextField(
        blank=True,
        help_text="Visitor schedules, audit info, miscellaneous",
    )

    # Team info
    outgoing_lead = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="led_handovers",
        help_text="Shift lead / person filing the handover",
    )
    outgoing_team = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True,
        related_name="outgoing_handovers",
        help_text="Other team members on the outgoing shift",
    )

    # Acknowledgement
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="acknowledged_handovers",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledgement_notes = models.TextField(
        blank=True, help_text="Notes from incoming shift on acknowledgement",
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_handovers",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="updated_handovers",
    )

    class Meta:
        ordering = ["-shift_date", "-created_at"]
        verbose_name = "Shift Handover Log"
        verbose_name_plural = "Shift Handover Logs"
        unique_together = [("stream", "shift_date", "shift_type")]

    def __str__(self):
        shift = self.shift_type.name if self.shift_type else "General"
        return f"{self.handover_number} — {shift} ({self.shift_date})"

    def save(self, *args, **kwargs):
        if not self.handover_number:
            import datetime as _dt

            today = _dt.date.today().strftime("%Y%m%d")
            last = (
                ShiftHandoverLog.objects.filter(
                    handover_number__startswith=f"SHL-{today}-"
                )
                .order_by("-handover_number")
                .first()
            )
            seq = int(last.handover_number.split("-")[-1]) + 1 if last else 1
            self.handover_number = f"SHL-{today}-{seq:04d}"
        super().save(*args, **kwargs)

    @property
    def is_acknowledged(self):
        return self.status == "acknowledged"

    @property
    def has_critical_items(self):
        """True if blockers or safety notes are non-empty."""
        return bool(self.blockers_issues.strip() or self.safety_notes.strip())

    @property
    def sections_filled(self):
        """Count how many content sections are filled."""
        fields = [
            self.systems_running,
            self.pending_actions,
            self.blockers_issues,
            self.safety_notes,
            self.bookings_handoff,
            self.general_notes,
        ]
        return sum(1 for f in fields if f and f.strip())


class ShiftHandoverComment(models.Model):
    """
    Threaded comments on a handover log — for follow-up discussion
    between outgoing and incoming shifts.
    """

    handover = models.ForeignKey(
        ShiftHandoverLog, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Handover Comment"
        verbose_name_plural = "Handover Comments"

    def __str__(self):
        return f"Comment by {self.author} on {self.handover.handover_number}"


class ShiftHandoverAuditLog(models.Model):
    """
    Immutable audit trail for every handover action.
    """

    ACTION_CHOICES = [
        ("created", "Created"),
        ("updated", "Updated"),
        ("submitted", "Submitted"),
        ("acknowledged", "Acknowledged"),
        ("comment_added", "Comment Added"),
        ("reopened", "Reopened"),
    ]

    handover = models.ForeignKey(
        ShiftHandoverLog, on_delete=models.CASCADE, related_name="audit_logs"
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    details = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    performed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at"]
        verbose_name = "Handover Audit Log"
        verbose_name_plural = "Handover Audit Logs"

    def __str__(self):
        return f"{self.get_action_display()} by {self.performed_by} at {self.performed_at}"
