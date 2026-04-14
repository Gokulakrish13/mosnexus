# pylint: disable=import-outside-toplevel,no-else-return,no-member,too-complex,too-many-branches,too-many-return-statements
from datetime import date

from django.conf import settings
from django.db import models


class RecurringReservation(models.Model):
    """
    Model for managing recurring system reservations with flexible scheduling patterns.
    Supports daily, weekly, bi-weekly, and monthly recurrence with customizable time slots.
    """

    RECURRENCE_TYPES = [
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("bi_weekly", "Bi-Weekly"),
        ("monthly", "Monthly"),
        ("custom", "Custom Pattern"),
    ]

    STATUS_CHOICES = [
        ("active", "Active"),
        ("paused", "Paused"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    # Core identification
    title = models.CharField(max_length=255, verbose_name="Reservation Title")
    description = models.TextField(blank=True, null=True, verbose_name="Description")

    # System and stream association
    system = models.ForeignKey("System", on_delete=models.CASCADE, related_name="recurring_reservations")
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="recurring_reservations")

    # User associations
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_recurring_reservations",
    )
    reserved_for = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_recurring_reservations",
        null=True,
        blank=True,
        help_text="User this reservation is for (if different from creator)",
    )

    # Recurrence settings
    recurrence_type = models.CharField(max_length=20, choices=RECURRENCE_TYPES, default="weekly")

    # Days of week for weekly/bi-weekly recurrence (stored as comma-separated: "0,1,2" for Mon,Tue,Wed)
    days_of_week = models.CharField(
        max_length=20, blank=True, null=True, help_text="Comma-separated day numbers (0=Monday, 6=Sunday)"
    )

    # Day of month for monthly recurrence
    day_of_month = models.IntegerField(null=True, blank=True, help_text="Day of month for monthly recurrence (1-31)")

    custom_pattern = models.JSONField(null=True, blank=True, help_text="Custom recurrence pattern in JSON format")

    # Time slot settings
    start_time = models.TimeField(verbose_name="Start Time")
    end_time = models.TimeField(verbose_name="End Time")

    # Date range for the recurrence
    start_date = models.DateField(verbose_name="Recurrence Start Date")
    end_date = models.DateField(
        null=True, blank=True, verbose_name="Recurrence End Date", help_text="Leave blank for indefinite recurrence"
    )

    # Maximum occurrences (alternative to end_date)
    max_occurrences = models.IntegerField(
        null=True, blank=True, help_text="Maximum number of occurrences (alternative to end date)"
    )
    occurrences_created = models.IntegerField(default=0, verbose_name="Occurrences Created")

    # Status and priority
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="normal")

    # Project association (optional)
    project = models.ForeignKey(
        "Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="recurring_reservations"
    )

    # Conflict handling
    allow_conflicts = models.BooleanField(default=False, help_text="Allow booking even if conflicts exist")
    auto_resolve_conflicts = models.BooleanField(
        default=False, help_text="Automatically find next available slot if conflict exists"
    )

    # Notification settings
    notify_on_creation = models.BooleanField(
        default=True, help_text="Send notification when individual reservations are created"
    )
    notify_on_conflict = models.BooleanField(default=True, help_text="Send notification when conflicts are detected")
    reminder_hours_before = models.IntegerField(default=24, help_text="Hours before reservation to send reminder")

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_generated_date = models.DateField(
        null=True, blank=True, help_text="Last date for which reservations were generated"
    )

    # Notes
    notes = models.TextField(blank=True, null=True, verbose_name="Additional Notes")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Recurring Reservation"
        verbose_name_plural = "Recurring Reservations"

    def __str__(self):
        return f"{self.title} - {self.system.name} ({self.get_recurrence_type_display()})"

    def get_days_of_week_display(self):
        """Return human-readable days of week"""
        if not self.days_of_week:
            return "Not set"
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        days = [int(d) for d in self.days_of_week.split(",") if d.strip().isdigit()]
        return ", ".join([day_names[d] for d in days if 0 <= d <= 6])

    def get_next_occurrence(self):  # noqa: C901
        """Calculate the next occurrence date based on recurrence pattern"""
        from datetime import timedelta

        today = date.today()

        if self.status != "active":
            return None

        if self.end_date and today > self.end_date:
            return None

        if self.max_occurrences and self.occurrences_created >= self.max_occurrences:
            return None

        start = max(today, self.start_date)

        if self.recurrence_type == "daily":
            return start

        elif self.recurrence_type == "weekly":
            if self.days_of_week:
                days = [int(d) for d in self.days_of_week.split(",")]
                current_weekday = start.weekday()
                for i in range(7):
                    check_day = (current_weekday + i) % 7
                    if check_day in days:
                        return start + timedelta(days=i)
            return start

        elif self.recurrence_type == "monthly":
            if self.day_of_month:
                import calendar

                current_month = start.month
                current_year = start.year

                last_day = calendar.monthrange(current_year, current_month)[1]
                target_day = min(self.day_of_month, last_day)

                if start.day <= target_day:
                    return start.replace(day=target_day)
                else:
                    if current_month == 12:
                        next_month = 1
                        next_year = current_year + 1
                    else:
                        next_month = current_month + 1
                        next_year = current_year
                    last_day = calendar.monthrange(next_year, next_month)[1]
                    target_day = min(self.day_of_month, last_day)
                    return date(next_year, next_month, target_day)
            return start

        return start

    def is_active(self):
        """Check if the recurring reservation is currently active"""
        if self.status != "active":
            return False

        today = date.today()

        if self.end_date and today > self.end_date:
            return False

        if self.max_occurrences and self.occurrences_created >= self.max_occurrences:
            return False

        return True


class RecurringReservationInstance(models.Model):
    """
    Individual instances generated from a recurring reservation.
    Each instance represents a single booking created from the pattern.
    """

    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("confirmed", "Confirmed"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("conflict", "Conflict Detected"),
        ("skipped", "Skipped"),
        ("not_allocated", "Not Allocated"),
    ]

    recurring_reservation = models.ForeignKey(
        "RecurringReservation", on_delete=models.CASCADE, related_name="instances"
    )

    # Actual reservation details
    reservation_date = models.DateField(verbose_name="Reservation Date")
    start_time = models.TimeField(verbose_name="Start Time")
    end_time = models.TimeField(verbose_name="End Time")

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="scheduled")

    # Link to the actual SystemAllocation if created
    system_allocation = models.ForeignKey(
        "SystemAllocation", on_delete=models.SET_NULL, null=True, blank=True, related_name="recurring_instance"
    )

    # Conflict information
    has_conflict = models.BooleanField(default=False)
    conflict_details = models.TextField(blank=True, null=True)
    conflict_resolved = models.BooleanField(default=False)

    # Alternative slot (if auto-resolved)
    alternative_date = models.DateField(null=True, blank=True)
    alternative_start_time = models.TimeField(null=True, blank=True)
    alternative_end_time = models.TimeField(null=True, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Cancellation info
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_reservation_instances",
    )
    cancellation_reason = models.TextField(blank=True, null=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["reservation_date", "start_time"]
        unique_together = ("recurring_reservation", "reservation_date")
        verbose_name = "Recurring Reservation Instance"
        verbose_name_plural = "Recurring Reservation Instances"

    def __str__(self):
        return f"{self.recurring_reservation.title} - {self.reservation_date}"

    def is_slot_passed(self):
        """
        Check if the reservation slot time has already passed.
        Returns True if reservation_date + end_time is in the past.
        """
        from datetime import datetime

        from django.utils import timezone

        now = timezone.now()
        slot_end = timezone.make_aware(datetime.combine(self.reservation_date, self.end_time))
        return now > slot_end

    def auto_expire_if_slot_passed(self):
        """
        Transition from 'conflict'/'scheduled' to 'not_allocated'
        if the slot time has passed without being confirmed/resolved.
        Returns True if the status was changed.
        """
        if self.status in ("conflict", "scheduled") and self.is_slot_passed():
            self.status = "not_allocated"
            self.save(update_fields=["status", "updated_at"])
            return True
        return False


class ReservationWaitlist(models.Model):
    """
    Waitlist for system reservations when the desired time slot is not available.
    Users can join a waitlist and get notified when the slot becomes available.
    """

    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("normal", "Normal"),
        ("high", "High"),
        ("urgent", "Urgent"),
    ]

    STATUS_CHOICES = [
        ("waiting", "Waiting"),
        ("notified", "Notified"),
        ("accepted", "Accepted"),
        ("declined", "Declined"),
        ("expired", "Expired"),
        ("fulfilled", "Fulfilled"),
        ("not_allocated", "Not Allocated"),
    ]

    # System and stream
    system = models.ForeignKey("System", on_delete=models.CASCADE, related_name="waitlist_entries")
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="waitlist_entries")

    # User requesting the slot
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="waitlist_entries")

    # Desired time slot
    desired_date = models.DateField(verbose_name="Desired Date")
    desired_start_time = models.TimeField(verbose_name="Desired Start Time")
    desired_end_time = models.TimeField(verbose_name="Desired End Time")

    # Flexibility settings
    is_flexible_date = models.BooleanField(default=False, help_text="Accept alternative dates")
    is_flexible_time = models.BooleanField(default=False, help_text="Accept alternative times")
    flexibility_days = models.IntegerField(default=3, help_text="Days before/after desired date to consider")
    earliest_acceptable_time = models.TimeField(null=True, blank=True)
    latest_acceptable_time = models.TimeField(null=True, blank=True)

    # Priority and status
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="normal")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="waiting")

    # Project association
    project = models.ForeignKey("Project", on_delete=models.SET_NULL, null=True, blank=True)

    # Reason for request
    reason = models.TextField(blank=True, null=True, verbose_name="Reason for Request")

    # Position in queue
    queue_position = models.IntegerField(default=0, help_text="Position in the waitlist queue")

    # Notification settings
    notify_via_email = models.BooleanField(default=True)
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    response_deadline = models.DateTimeField(
        null=True, blank=True, help_text="Deadline to respond when slot becomes available"
    )

    # Fulfillment tracking
    fulfilled_allocation = models.ForeignKey(
        "SystemAllocation", on_delete=models.SET_NULL, null=True, blank=True, related_name="waitlist_fulfillment"
    )
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="When this waitlist entry expires")

    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["priority", "created_at"]
        verbose_name = "Reservation Waitlist"
        verbose_name_plural = "Reservation Waitlists"

    def __str__(self):
        return f"{self.user.username} waiting for {self.system.name} on {self.desired_date}"

    def is_expired(self):
        """Check if the waitlist entry has expired"""
        from django.utils import timezone

        if self.expires_at and timezone.now() > self.expires_at:
            return True
        if self.desired_date < date.today():
            return True
        return False

    def is_slot_passed(self):
        """
        Check if the booked time slot has already passed.
        Returns True if the desired_date + desired_end_time is in the past,
        meaning the user did not reschedule before their slot.
        """
        from datetime import datetime

        from django.utils import timezone

        now = timezone.now()
        slot_end = timezone.make_aware(datetime.combine(self.desired_date, self.desired_end_time))
        return now > slot_end

    def auto_expire_if_slot_passed(self):
        """
        Automatically transition from 'waiting' to 'not_allocated'
        if the booked slot time has passed without the user rescheduling.
        Returns True if the status was changed.
        """
        if self.status == "waiting" and self.is_slot_passed():
            self.status = "not_allocated"
            self.save(update_fields=["status", "updated_at"])
            return True
        return False

    def get_priority_weight(self):
        """Return numeric weight for priority sorting"""
        weights = {"urgent": 4, "high": 3, "normal": 2, "low": 1}
        return weights.get(self.priority, 2)


class ReservationConflict(models.Model):
    """
    Track and manage reservation conflicts with resolution suggestions.
    """

    CONFLICT_TYPES = [
        ("overlap", "Time Overlap"),
        ("maintenance", "Scheduled Maintenance"),
        ("system_unavailable", "System Unavailable"),
        ("capacity", "Capacity Exceeded"),
        ("priority", "Priority Conflict"),
    ]

    RESOLUTION_STATUS = [
        ("pending", "Pending Resolution"),
        ("resolved", "Resolved"),
        ("escalated", "Escalated"),
        ("dismissed", "Dismissed"),
    ]

    # The conflicting allocations/reservations
    primary_allocation = models.ForeignKey(
        "SystemAllocation", on_delete=models.CASCADE, related_name="primary_conflicts"
    )
    conflicting_allocation = models.ForeignKey(
        "SystemAllocation", on_delete=models.CASCADE, related_name="secondary_conflicts", null=True, blank=True
    )

    # System and stream
    system = models.ForeignKey("System", on_delete=models.CASCADE, related_name="conflicts")
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="conflicts")

    # Conflict details
    conflict_type = models.CharField(max_length=30, choices=CONFLICT_TYPES)
    conflict_date = models.DateField()
    conflict_start_time = models.TimeField()
    conflict_end_time = models.TimeField()

    # Resolution
    resolution_status = models.CharField(max_length=20, choices=RESOLUTION_STATUS, default="pending")
    resolution_notes = models.TextField(blank=True, null=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolved_conflicts"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    suggested_alternatives = models.JSONField(null=True, blank=True, help_text="JSON array of alternative time slots")

    # Affected users
    affected_users = models.ManyToManyField(  # type: ignore[var-annotated]
        settings.AUTH_USER_MODEL, blank=True, related_name="affected_by_conflicts"
    )

    # Metadata
    detected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-detected_at"]
        verbose_name = "Reservation Conflict"
        verbose_name_plural = "Reservation Conflicts"

    def __str__(self):
        return f"Conflict on {self.system.name} - {self.conflict_date} ({self.get_conflict_type_display()})"


# =============================================================================
# CALIBRATION & COMPLIANCE TRACKING
# =============================================================================
