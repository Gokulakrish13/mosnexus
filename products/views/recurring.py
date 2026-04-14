"""Products app - Recurring Reservations, Waitlist, Utilization, and Conflicts views."""

# pylint: disable=broad-exception-caught,inconsistent-return-statements,logging-too-many-args
# pylint: disable=redefined-outer-name,too-many-lines

from datetime import date as date_type

from django.db.models import Q as DQ
from django.utils import timezone as dj_timezone

from ._helpers import (
    AuditLog,
    Count,
    JsonResponse,
    Notification,
    Project,
    Q,
    RecurringReservation,
    RecurringReservationInstance,
    ReservationWaitlist,
    System,
    SystemAllocation,
    User,
    check_user_access,
    date,
    datetime,
    get_object_or_404,
    get_stream_or_404,
    json,
    logger,
    login_required,
    messages,
    models,
    redirect,
    render,
    require_POST,
    timedelta,
    timezone,
)

__all__ = [
    "recurring_reservations_list",
    "check_recurring_conflicts",
    "recurring_reservation_create",
    "generate_recurring_instances",
    "create_waitlist_from_conflict",
    "create_allocation_from_instance",
    "check_reservation_conflict",
]


@login_required
def recurring_reservations_list(request, stream=None):
    """List all recurring reservations for a stream."""
    # pylint: disable=too-many-locals
    stream_obj = get_stream_or_404(stream)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        messages.error(request, error_message)
        return redirect("dashboard")

    status_filter = request.GET.get("status", "")
    system_filter = request.GET.get("system", "")
    search_query = request.GET.get("q", "").strip()
    sort_by = request.GET.get("sort", "-created_at")

    valid_sorts = {
        "-created_at": "Newest First",
        "created_at": "Oldest First",
        "start_date": "Start Date (Earliest)",
        "-start_date": "Start Date (Latest)",
        "end_date": "End Date (Earliest)",
        "-end_date": "End Date (Latest)",
        "title": "Title (A-Z)",
        "-title": "Title (Z-A)",
        "-start_time": "Time Slot (Latest)",
        "start_time": "Time Slot (Earliest)",
    }
    if sort_by not in valid_sorts:
        sort_by = "-created_at"

    recurring_reservations = RecurringReservation.objects.filter(stream=stream_obj)

    # Status filtering is now handled client-side via JavaScript for instant pill filtering

    if system_filter:
        recurring_reservations = recurring_reservations.filter(system_id=system_filter)

    if search_query:
        recurring_reservations = recurring_reservations.filter(
            Q(title__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(system__name__icontains=search_query)
        )

    # Get statistics (before status filter is applied)
    all_reservations = RecurringReservation.objects.filter(stream=stream_obj)
    if system_filter:
        all_reservations = all_reservations.filter(system_id=system_filter)
    if search_query:
        all_reservations = all_reservations.filter(
            Q(title__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(system__name__icontains=search_query)
        )

    status_counts = {
        "total": all_reservations.count(),
        "active": all_reservations.filter(status="active").count(),
        "paused": all_reservations.filter(status="paused").count(),
        "completed": all_reservations.filter(status="completed").count(),
        "cancelled": all_reservations.filter(status="cancelled").count(),
    }
    total_active = status_counts["active"]
    total_paused = status_counts["paused"]

    # Auto-expire instances whose slot has passed (conflict/scheduled → not_allocated)
    _now = timezone.now()  # noqa: F841
    passed_instances = RecurringReservationInstance.objects.filter(
        recurring_reservation__stream=stream_obj,
        status__in=["conflict", "scheduled"],
        reservation_date__lte=date.today(),
    )
    for instance in passed_instances:
        instance.auto_expire_if_slot_passed()

    systems = System.objects.filter(stream=stream_obj, status="Active")

    recurring_reservations = recurring_reservations.annotate(
        confirmed_count=Count("instances", filter=DQ(instances__status="confirmed")),
        conflict_count=Count("instances", filter=DQ(instances__status="conflict")),
        scheduled_count=Count("instances", filter=DQ(instances__status="scheduled")),
        not_allocated_count=Count("instances", filter=DQ(instances__status="not_allocated")),
        total_instances=Count("instances"),
    )

    context = {
        "recurring_reservations": recurring_reservations.select_related(
            "system", "created_by", "reserved_for", "project"
        ).order_by(sort_by),
        "systems": systems,
        "stream": stream,
        "selected_stream": stream,
        "status_filter": status_filter,
        "system_filter": system_filter,
        "search_query": search_query,
        "sort_by": sort_by,
        "valid_sorts": valid_sorts,
        "status_counts": status_counts,
        "total_active": total_active,
        "total_paused": total_paused,
        "total_count": recurring_reservations.count(),
    }
    return render(request, "products/recurring_reservations_list.html", context)


@login_required
@require_POST
def check_recurring_conflicts(request, stream=None):  # noqa: C901, CCR001
    """Check for conflicts before creating a recurring reservation (AJAX endpoint)."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-statements
    stream_obj = get_stream_or_404(stream)

    try:
        data = json.loads(request.body)
        system_id = data.get("system_id")
        recurrence_type = data.get("recurrence_type")
        days_of_week = data.get("days_of_week", [])
        day_of_month = data.get("day_of_month")
        start_time_str = data.get("start_time")
        end_time_str = data.get("end_time")
        start_date_str = data.get("start_date")
        end_date_str = data.get("end_date")

        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.strptime(end_time_str, "%H:%M").time()

        # If no end date, use a reasonable default based on recurrence type
        if not end_date:
            if recurrence_type == "daily":
                end_date = start_date + timedelta(days=30)
            elif recurrence_type in ("weekly", "bi_weekly"):
                end_date = start_date + timedelta(days=60)
            elif recurrence_type == "monthly":
                end_date = start_date + timedelta(days=180)
            else:
                end_date = start_date + timedelta(days=30)

        system = get_object_or_404(System, id=system_id, stream=stream_obj)

        dates_to_check: list = []
        current = start_date
        while current <= end_date and len(dates_to_check) < 365:  # Limit for performance
            should_check = False

            if recurrence_type == "daily":
                should_check = True
            elif recurrence_type == "weekly":
                if days_of_week:
                    should_check = current.weekday() in [int(d) for d in days_of_week]
            elif recurrence_type == "bi_weekly":
                if days_of_week:
                    week_diff = (current - start_date).days // 7
                    should_check = current.weekday() in [int(d) for d in days_of_week] and week_diff % 2 == 0
            elif recurrence_type == "monthly":
                if day_of_month:
                    should_check = current.day == int(day_of_month)

            if should_check:
                dates_to_check.append(current)
            current += timedelta(days=1)

        conflicts = []
        available = []

        for check_date in dates_to_check:
            has_conflict, conflict_details = check_reservation_conflict(system, check_date, start_time, end_time)

            date_info = {
                "date": check_date.strftime("%Y-%m-%d"),
                "display_date": check_date.strftime("%b %d, %Y"),
                "day_name": check_date.strftime("%A"),
            }

            if has_conflict:
                date_info["conflict_details"] = conflict_details
                conflicts.append(date_info)
            else:
                available.append(date_info)

        return JsonResponse(
            {
                "success": True,
                "total_dates": len(dates_to_check),
                "conflicts_count": len(conflicts),
                "available_count": len(available),
                "conflicts": conflicts[:20],  # Limit to first 20 conflicts for UI
                "available": available[:10],  # Show first 10 available
                "has_conflicts": len(conflicts) > 0,
                "all_conflict": len(conflicts) == len(dates_to_check),
                "system_name": system.name,
            }
        )

    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=400)


@login_required
def recurring_reservation_create(request, stream=None):  # noqa: CCR001
    """Create a new recurring reservation."""
    # pylint: disable=too-many-locals
    stream_obj = get_stream_or_404(stream)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        messages.error(request, error_message)
        return redirect("dashboard")

    systems = System.objects.filter(stream=stream_obj, status="Active")
    projects = Project.objects.filter(stream=stream_obj, status="running")
    users = User.objects.filter(is_active=True)

    if request.method == "POST":
        try:
            title = request.POST.get("title", "").strip()
            description = request.POST.get("description", "").strip()
            system_id = request.POST.get("system")
            recurrence_type = request.POST.get("recurrence_type")
            days_of_week = ",".join(request.POST.getlist("days_of_week"))
            day_of_month = request.POST.get("day_of_month") or None
            start_time = request.POST.get("start_time")
            end_time = request.POST.get("end_time")
            start_date = request.POST.get("start_date")
            end_date = request.POST.get("end_date") or None
            max_occurrences = request.POST.get("max_occurrences") or None
            priority = request.POST.get("priority", "normal")
            reserved_for_id = request.POST.get("reserved_for") or None
            project_id = request.POST.get("project") or None
            allow_conflicts = request.POST.get("allow_conflicts") == "on"
            auto_resolve_conflicts = request.POST.get("auto_resolve_conflicts") == "on"
            notify_on_creation = request.POST.get("notify_on_creation") == "on"
            notify_on_conflict = request.POST.get("notify_on_conflict") == "on"
            reminder_hours = request.POST.get("reminder_hours_before", 24)
            notes = request.POST.get("notes", "").strip()

            system = get_object_or_404(System, id=system_id, stream=stream_obj)

            recurring = RecurringReservation.objects.create(
                title=title,
                description=description,
                system=system,
                stream=stream_obj,
                created_by=request.user,
                reserved_for_id=reserved_for_id,
                recurrence_type=recurrence_type,
                days_of_week=days_of_week if days_of_week else None,
                day_of_month=int(day_of_month) if day_of_month else None,
                start_time=start_time,
                end_time=end_time,
                start_date=start_date,
                end_date=end_date,
                max_occurrences=int(max_occurrences) if max_occurrences else None,
                priority=priority,
                project_id=project_id,
                allow_conflicts=allow_conflicts,
                auto_resolve_conflicts=auto_resolve_conflicts,
                notify_on_creation=notify_on_creation,
                notify_on_conflict=notify_on_conflict,
                reminder_hours_before=int(reminder_hours),
                notes=notes,
            )

            # Generate instances; errors won't block reservation creation
            try:
                generate_recurring_instances(recurring)
            except Exception as gen_error:
                # Log error but don't fail the creation
                logger.warning("Could not generate recurring instances: %s", gen_error)

            AuditLog.log(
                "create",
                f"Created recurring reservation: {recurring.title}",
                request=request,
                obj=recurring,
                module="reservations",
                severity="info",
                stream=stream_obj,
            )

            messages.success(request, f'Recurring reservation "{title}" created successfully!')
            return redirect("recurring_reservations_list", stream=stream)

        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "systems": systems,
        "projects": projects,
        "users": users,
        "stream": stream,
        "selected_stream": stream,
        "recurrence_types": RecurringReservation.RECURRENCE_TYPES,
        "priority_choices": RecurringReservation.PRIORITY_CHOICES,
        "form_error": form_error,
    }
    return render(request, "products/recurring_reservation_form.html", context)


def generate_recurring_instances(recurring, days_ahead=90):  # noqa: C901, CCR001
    """Generate reservation instances for a recurring reservation."""
    # pylint: disable=inconsistent-return-statements,too-complex,too-many-branches,too-many-locals
    # pylint: disable=too-many-nested-blocks,too-many-statements
    # Refresh from database to ensure proper date types
    recurring.refresh_from_db()

    if not recurring.is_active():
        return

    start_date = recurring.start_date
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()

    end_date = recurring.end_date
    if end_date and isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    start = recurring.last_generated_date + timedelta(days=1) if recurring.last_generated_date else start_date
    end = date_type.today() + timedelta(days=days_ahead)

    if end_date:
        end = min(end, end_date)

    notify_user = recurring.reserved_for or recurring.created_by
    current = start
    instances_created = 0
    conflicts_found = 0
    auto_resolved = 0

    while current <= end:
        if recurring.max_occurrences and recurring.occurrences_created >= recurring.max_occurrences:
            break

        should_create = False

        if recurring.recurrence_type == "daily":
            should_create = True

        elif recurring.recurrence_type == "weekly":
            if recurring.days_of_week:
                days = [int(d) for d in recurring.days_of_week.split(",") if d.strip().isdigit()]
                should_create = current.weekday() in days

        elif recurring.recurrence_type == "bi_weekly":
            if recurring.days_of_week:
                days = [int(d) for d in recurring.days_of_week.split(",") if d.strip().isdigit()]
                week_diff = (current - start_date).days // 7
                should_create = current.weekday() in days and week_diff % 2 == 0

        elif recurring.recurrence_type == "monthly":
            if recurring.day_of_month:
                should_create = current.day == recurring.day_of_month

        if should_create and current >= start_date:
            if not RecurringReservationInstance.objects.filter(
                recurring_reservation=recurring, reservation_date=current
            ).exists():
                has_conflict, conflict_details = check_reservation_conflict(
                    recurring.system, current, recurring.start_time, recurring.end_time
                )

                resolved_start = recurring.start_time
                resolved_end = recurring.end_time

                # --- auto_resolve_conflicts: try shifting time to find a free slot ---
                if has_conflict and recurring.auto_resolve_conflicts:
                    duration = datetime.combine(current, recurring.end_time) - datetime.combine(
                        current, recurring.start_time
                    )
                    if duration.total_seconds() < 0:
                        duration += timedelta(days=1)  # overnight

                    # Try 30-min increments from original start, up to 23:30
                    attempt_start = datetime.combine(current, recurring.start_time)
                    max_attempts = 48  # cover full 24h in 30-min steps
                    _found_slot = False  # noqa: F841

                    for _ in range(max_attempts):
                        attempt_start += timedelta(minutes=30)
                        attempt_end = attempt_start + duration

                        # Don't go past midnight (next day)
                        if attempt_end.date() > current:
                            break

                        alt_conflict, _ = check_reservation_conflict(
                            recurring.system, current, attempt_start.time(), attempt_end.time()
                        )

                        if not alt_conflict:
                            resolved_start = attempt_start.time()
                            resolved_end = attempt_end.time()
                            has_conflict = False
                            conflict_details = None
                            auto_resolved += 1
                            break

                # --- allow_conflicts: force-book even with conflicts ---
                if has_conflict and recurring.allow_conflicts:
                    instance = RecurringReservationInstance.objects.create(
                        recurring_reservation=recurring,
                        reservation_date=current,
                        start_time=resolved_start,
                        end_time=resolved_end,
                        status="confirmed",
                        has_conflict=True,
                        conflict_details=conflict_details,
                    )
                    create_allocation_from_instance(instance)
                    conflicts_found += 1

                    # notify_on_conflict: alert user about the forced booking with conflict
                    if recurring.notify_on_conflict and notify_user:
                        Notification.notify(
                            notify_user,
                            f"⚠️ Recurring '{recurring.title}': Booked {recurring.system.name} on "
                            f"{current.strftime('%b %d')} despite conflict. {conflict_details}",
                            "allocation",
                        )

                    # notify_on_creation: alert user about the booking
                    if recurring.notify_on_creation and notify_user:
                        Notification.notify(
                            notify_user,
                            f"📅 Recurring '{recurring.title}': {recurring.system.name} booked on "
                            f"{current.strftime('%b %d, %Y')} "
                            f"{resolved_start.strftime('%H:%M')}-{resolved_end.strftime('%H:%M')} (with conflict).",
                            "allocation",
                        )

                elif has_conflict:
                    # Default behavior: conflict → waitlist
                    instance = RecurringReservationInstance.objects.create(
                        recurring_reservation=recurring,
                        reservation_date=current,
                        start_time=resolved_start,
                        end_time=resolved_end,
                        status="conflict",
                        has_conflict=True,
                        conflict_details=conflict_details,
                    )
                    create_waitlist_from_conflict(instance)
                    conflicts_found += 1

                    # notify_on_conflict: alert user about the conflict
                    if recurring.notify_on_conflict and notify_user:
                        Notification.notify(
                            notify_user,
                            f"⚠️ Recurring '{recurring.title}': Conflict on {current.strftime('%b %d')} for "
                            f"{recurring.system.name}. Added to waitlist. {conflict_details}",
                            "allocation",
                        )

                else:
                    # No conflict - create allocation normally
                    instance = RecurringReservationInstance.objects.create(
                        recurring_reservation=recurring,
                        reservation_date=current,
                        start_time=resolved_start,
                        end_time=resolved_end,
                        status="scheduled",
                        has_conflict=False,
                        conflict_details=None,
                    )
                    create_allocation_from_instance(instance)

                    # notify_on_creation: alert user about the booking
                    if recurring.notify_on_creation and notify_user:
                        Notification.notify(
                            notify_user,
                            f"📅 Recurring '{recurring.title}': {recurring.system.name} booked on "
                            f"{current.strftime('%b %d, %Y')} "
                            f"{resolved_start.strftime('%H:%M')}-{resolved_end.strftime('%H:%M')}.",
                            "allocation",
                        )

                recurring.occurrences_created += 1
                instances_created += 1

        current += timedelta(days=1)

    recurring.last_generated_date = end
    recurring.save()

    # Summary notification if auto-resolve was used
    if auto_resolved > 0 and notify_user:
        Notification.notify(
            notify_user,
            f"🔄 Recurring '{recurring.title}': {auto_resolved} slot(s) auto-shifted to avoid conflicts.",
            "allocation",
        )

    return instances_created


def create_waitlist_from_conflict(instance):
    """Automatically create a waitlist entry for a conflicting reservation instance."""
    recurring = instance.recurring_reservation

    existing = ReservationWaitlist.objects.filter(
        system=recurring.system,
        user=recurring.reserved_for or recurring.created_by,
        desired_date=instance.reservation_date,
        desired_start_time=instance.start_time,
        status="waiting",
    ).exists()

    if existing:
        return None

    max_position = (
        ReservationWaitlist.objects.filter(
            system=recurring.system, desired_date=instance.reservation_date, status="waiting"
        ).aggregate(models.Max("queue_position"))["queue_position__max"]
        or 0
    )

    expiry_date = datetime.combine(instance.reservation_date, datetime.min.time()) + timedelta(days=7)

    waitlist_entry = ReservationWaitlist.objects.create(
        system=recurring.system,
        stream=recurring.stream,
        user=recurring.reserved_for or recurring.created_by,
        desired_date=instance.reservation_date,
        desired_start_time=instance.start_time,
        desired_end_time=instance.end_time,
        is_flexible_date=False,
        is_flexible_time=False,
        flexibility_days=0,
        priority=recurring.priority,
        project=recurring.project,
        reason=f"Auto-added from recurring reservation: {recurring.title}",
        queue_position=max_position + 1,
        notify_via_email=recurring.notify_on_conflict,
        expires_at=timezone.make_aware(expiry_date),
        notes=f"Linked to recurring reservation #{recurring.pk}",
    )

    return waitlist_entry


def create_allocation_from_instance(instance):
    """Create a SystemAllocation entry from a RecurringReservationInstance."""
    recurring = instance.recurring_reservation

    start_datetime = datetime.combine(instance.reservation_date, instance.start_time)
    end_datetime = datetime.combine(instance.reservation_date, instance.end_time)

    # Handle overnight reservations (when end time is earlier than start time)
    if instance.end_time < instance.start_time:
        end_datetime = datetime.combine(instance.reservation_date + timedelta(days=1), instance.end_time)

    # Make timezone-aware
    start_datetime = dj_timezone.make_aware(start_datetime)
    end_datetime = dj_timezone.make_aware(end_datetime)

    allocation = SystemAllocation.objects.create(
        stream=recurring.stream,
        system_type=recurring.system.name,
        user=recurring.reserved_for or recurring.created_by,
        start_date=start_datetime,
        end_date=end_datetime,
    )

    instance.system_allocation = allocation
    instance.status = "confirmed"
    instance.save()

    return allocation


def check_reservation_conflict(system, date, start_time, end_time):
    """Check for conflicts with existing allocations (including multi-day bookings)."""
    # Find allocations where the date falls within the booking range
    # A multi-day booking with start_date=Apr 15, end_date=Apr 30 should
    # conflict with any date between Apr 15 and Apr 30
    conflicts = SystemAllocation.objects.filter(
        system_type=system.name,
        start_date__date__lte=date,  # booking starts on or before this date
        end_date__date__gte=date,  # booking ends on or after this date
    ).filter(
        # Time overlap: the requested slot overlaps with existing allocation's time window
        Q(start_date__time__lt=end_time, end_date__time__gt=start_time)
    )

    # Also filter by stream if system has a stream
    if hasattr(system, "stream") and system.stream:
        conflicts = conflicts.filter(stream=system.stream)

    if conflicts.exists():
        conflict_list = [
            f"{c.user.username}: {c.start_date.strftime('%H:%M')}-{c.end_date.strftime('%H:%M')}" for c in conflicts[:3]
        ]
        return True, f"Conflicts with: {', '.join(conflict_list)}"

    return False, None
