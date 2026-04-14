"""Products app — Booking views."""

# pylint: disable=broad-exception-caught,no-else-return


from ._helpers import (
    AuditLog,
    Count,
    JsonResponse,
    Q,
    RecurringReservation,
    RecurringReservationInstance,
    ReservationWaitlist,
    System,
    SystemAllocation,
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
from .recurring import generate_recurring_instances

__all__ = [
    "unified_booking_hub",
    "quick_book_system",
    "check_system_availability",
    "my_bookings",
]


@login_required
def unified_booking_hub(request, stream=None):
    # pylint: disable=too-many-locals
    """Unified booking interface combining allocations, recurring reservations, and waitlist."""
    stream_obj = get_stream_or_404(stream)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        messages.error(request, error_message)
        return redirect("dashboard")

    systems = System.objects.filter(stream=stream_obj, status="Active").order_by("name")

    user_allocations = (
        SystemAllocation.objects.filter(stream=stream_obj, user=request.user, end_date__gte=timezone.now())
        .select_related("stream")
        .order_by("start_date")[:5]
    )

    user_recurring = RecurringReservation.objects.filter(
        stream=stream_obj, created_by=request.user, status__in=["active", "paused"]
    ).select_related("system")[:5]

    user_waitlist = (
        ReservationWaitlist.objects.filter(stream=stream_obj, user=request.user, status__in=["waiting", "notified"])
        .select_related("system")
        .order_by("desired_date")[:5]
    )

    for entry in user_waitlist:
        if entry.status == "waiting" and entry.is_slot_passed():
            entry.status = "not_allocated"
            entry.save(update_fields=["status", "updated_at"])

    today = date.today()
    todays_bookings = SystemAllocation.objects.filter(stream=stream_obj, start_date__date=today).select_related("user")

    total_systems = systems.count()
    booked_today = todays_bookings.values("system_type").distinct().count()
    available_today = total_systems - booked_today

    upcoming_days = []
    for i in range(7):
        check_date = today + timedelta(days=i)
        day_bookings = (
            SystemAllocation.objects.filter(stream=stream_obj, start_date__date=check_date)
            .values("system_type")
            .distinct()
            .count()
        )
        upcoming_days.append(
            {
                "date": check_date,
                "booked": day_bookings,
                "available": total_systems - day_bookings,
                "day_name": check_date.strftime("%a"),
                "is_today": i == 0,
            }
        )

    context = {
        "stream": stream,
        "selected_stream": stream,
        "systems": systems,
        "user_allocations": user_allocations,
        "user_recurring": user_recurring,
        "user_waitlist": user_waitlist,
        "todays_bookings": todays_bookings,
        "total_systems": total_systems,
        "booked_today": booked_today,
        "available_today": available_today,
        "upcoming_days": upcoming_days,
        "today": today,
    }
    return render(request, "products/unified_booking_hub.html", context)


@login_required
@require_POST
def quick_book_system(request, stream=None):  # noqa: CCR001
    # pylint: disable=too-many-locals,too-many-return-statements
    """Quick booking endpoint for unified booking hub."""
    stream_obj = get_stream_or_404(stream)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        return JsonResponse({"success": False, "error": error_message}, status=403)

    try:
        data = json.loads(request.body)
        system_id = data.get("system_id")
        booking_type = data.get("booking_type", "single")  # single, recurring, waitlist
        start_date_str = data.get("start_date")
        end_date_str = data.get("end_date")
        start_time_str = data.get("start_time", "09:00")
        end_time_str = data.get("end_time", "17:00")

        recurrence_type = data.get("recurrence_type", "daily")
        days_of_week = data.get("days_of_week", [])

        is_flexible = data.get("is_flexible", False)
        flexibility_days = data.get("flexibility_days", 3)
        reason = data.get("reason", "").strip()

        system = get_object_or_404(System, id=system_id, stream=stream_obj)

        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.strptime(end_time_str, "%H:%M").time()

        if booking_type == "single":
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else start_date

            start_datetime = timezone.make_aware(datetime.combine(start_date, start_time))
            end_datetime = timezone.make_aware(datetime.combine(end_date, end_time))

            conflicts = SystemAllocation.objects.filter(
                stream=stream_obj, system_type=system.name, start_date__lt=end_datetime, end_date__gt=start_datetime
            )

            if conflicts.exists():
                return JsonResponse(
                    {
                        "success": False,
                        "has_conflict": True,
                        "conflict_message": f"System {system.name} is already booked during this time.",
                        "offer_waitlist": True,
                        "conflicts": [
                            {"user": c.user.username, "start": c.start_date.isoformat(), "end": c.end_date.isoformat()}
                            for c in conflicts[:3]
                        ],
                    }
                )

            allocation = SystemAllocation.objects.create(
                stream=stream_obj,
                system_type=system.name,
                user=request.user,
                start_date=start_datetime,
                end_date=end_datetime,
                reason=reason,
            )

            AuditLog.log(
                "reservation",
                f"Quick booked system: {system.name}",
                request=request,
                obj=allocation,
                module="reservations",
                severity="info",
                description=f"Single booking from {start_date} to {end_date}",
                stream=stream_obj,
            )

            return JsonResponse(
                {
                    "success": True,
                    "message": f"Successfully booked {system.name} from {start_date} to {end_date}",
                    "booking_id": allocation.id,
                    "booking_type": "confirmed",
                }
            )

        if booking_type == "recurring":
            end_date = (
                datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None  # type: ignore[assignment]
            )

            recurring = RecurringReservation.objects.create(
                title=f"{system.name} - {request.user.username}",
                system=system,
                stream=stream_obj,
                created_by=request.user,
                recurrence_type=recurrence_type,
                days_of_week=",".join(str(d) for d in days_of_week) if days_of_week else None,
                start_time=start_time,
                end_time=end_time,
                start_date=start_date,
                end_date=end_date,
                status="active",
                description=reason if reason else None,
            )

            try:
                _instances_created = generate_recurring_instances(recurring)
            except Exception:
                _instances_created = 0  # noqa: F841

            confirmed = recurring.instances.filter(status="confirmed").count()
            waitlisted = recurring.instances.filter(status="conflict").count()

            AuditLog.log(
                "reservation",
                f"Quick booked recurring reservation: {system.name}",
                request=request,
                obj=recurring,
                module="reservations",
                severity="info",
                description=f"Recurring {recurrence_type} booking, {confirmed} confirmed, {waitlisted} waitlisted",
                stream=stream_obj,
            )

            return JsonResponse(
                {
                    "success": True,
                    "message": f"Recurring reservation created: {confirmed} confirmed, {waitlisted} waitlisted",
                    "booking_id": recurring.id,
                    "booking_type": "recurring",
                    "confirmed_count": confirmed,
                    "waitlist_count": waitlisted,
                }
            )

        elif booking_type == "waitlist":
            max_position = (
                ReservationWaitlist.objects.filter(system=system, desired_date=start_date, status="waiting").aggregate(
                    models.Max("queue_position")
                )["queue_position__max"]
                or 0
            )

            waitlist_entry = ReservationWaitlist.objects.create(
                system=system,
                stream=stream_obj,
                user=request.user,
                desired_date=start_date,
                desired_start_time=start_time,
                desired_end_time=end_time,
                is_flexible_date=is_flexible,
                flexibility_days=flexibility_days if is_flexible else 0,
                queue_position=max_position + 1,
                reason=data.get("reason", ""),
                status="waiting",
            )

            AuditLog.log(
                "reservation",
                f"Joined waitlist for system: {system.name}",
                request=request,
                obj=waitlist_entry,
                module="waitlist",
                severity="info",
                description=f"Waitlist entry for {start_date}, queue position: {max_position + 1}",
                stream=stream_obj,
            )

            return JsonResponse(
                {
                    "success": True,
                    "message": f"Added to waitlist for {system.name} on {start_date}. Queue position: {max_position + 1}",  # noqa: E501
                    "booking_id": waitlist_entry.id,
                    "booking_type": "waitlist",
                    "queue_position": max_position + 1,
                }
            )

        return JsonResponse({"success": False, "error": "Invalid booking type"}, status=400)

    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=400)


@login_required
def check_system_availability(request, stream=None):
    # pylint: disable=too-many-locals
    """Check system availability for a date range or week overview."""
    stream_obj = get_stream_or_404(stream)

    week_offset = request.GET.get("week_offset")
    if week_offset is not None:
        try:
            week_offset = int(week_offset)
            today = date.today()
            start_of_week = today + timedelta(days=week_offset * 7)

            total_systems = System.objects.filter(stream=stream_obj, status="Active").count()

            days = []
            for i in range(7):
                check_date = start_of_week + timedelta(days=i)
                day_bookings = (
                    SystemAllocation.objects.filter(stream=stream_obj, start_date__date=check_date)
                    .values("system_type")
                    .distinct()
                    .count()
                )

                days.append(
                    {
                        "date": check_date.strftime("%Y-%m-%d"),
                        "day_name": check_date.strftime("%a"),
                        "booked": day_bookings,
                        "available": total_systems - day_bookings,
                        "is_today": check_date == today,
                    }
                )

            return JsonResponse({"success": True, "days": days, "total_systems": total_systems})
        except Exception:
            logger.exception("Operation failed")
            return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=400)

    system_id = request.GET.get("system_id")
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    try:

        system = get_object_or_404(System, id=system_id, stream=stream_obj)
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else start_date

        bookings = SystemAllocation.objects.filter(
            stream=stream_obj, system_type=system.name, start_date__date__lte=end_date, end_date__date__gte=start_date
        ).select_related("user")

        availability = []
        current = start_date
        while current <= end_date:
            day_bookings = [b for b in bookings if b.start_date.date() <= current <= b.end_date.date()]

            waitlist_count = ReservationWaitlist.objects.filter(
                system=system, desired_date=current, status="waiting"
            ).count()

            availability.append(
                {
                    "date": current.strftime("%Y-%m-%d"),
                    "display_date": current.strftime("%b %d"),
                    "day_name": current.strftime("%A"),
                    "is_available": len(day_bookings) == 0,
                    "bookings": [
                        {
                            "user": b.user.username,
                            "start_time": b.start_date.strftime("%H:%M"),
                            "end_time": b.end_date.strftime("%H:%M"),
                        }
                        for b in day_bookings
                    ],
                    "waitlist_count": waitlist_count,
                }
            )
            current += timedelta(days=1)

        available_count = sum(1 for a in availability if a["is_available"])

        return JsonResponse(
            {
                "success": True,
                "system_name": system.name,
                "availability": availability,
                "total_days": len(availability),
                "available_days": available_count,
                "booked_days": len(availability) - available_count,
            }
        )

    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=400)


@login_required
def my_bookings(request, stream=None):
    # pylint: disable=too-many-locals
    """View all of user's bookings, recurring reservations, and waitlist entries."""
    stream_obj = get_stream_or_404(stream)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        messages.error(request, error_message)
        return redirect("dashboard")

    status_filter = request.GET.get("status", "all")

    allocations = SystemAllocation.objects.filter(stream=stream_obj, user=request.user).order_by("-start_date")

    if status_filter == "active":
        allocations = allocations.filter(end_date__gte=timezone.now())
    elif status_filter == "past":
        allocations = allocations.filter(end_date__lt=timezone.now())

    recurring = (
        RecurringReservation.objects.filter(stream=stream_obj, created_by=request.user)
        .annotate(
            confirmed_count=Count("instances", filter=Q(instances__status="confirmed")),
            conflict_count=Count("instances", filter=Q(instances__status="conflict")),
        )
        .order_by("-created_at")
    )

    waitlist = (
        ReservationWaitlist.objects.filter(stream=stream_obj, user=request.user)
        .select_related("system")
        .order_by("-created_at")
    )

    for entry in waitlist:
        if entry.status == "waiting" and entry.is_slot_passed():
            entry.status = "not_allocated"
            entry.save(update_fields=["status", "updated_at"])

    active_bookings = SystemAllocation.objects.filter(
        stream=stream_obj, user=request.user, end_date__gte=timezone.now()
    ).count()

    active_recurring = RecurringReservation.objects.filter(
        stream=stream_obj, created_by=request.user, status="active"
    ).count()

    pending_waitlist = ReservationWaitlist.objects.filter(
        stream=stream_obj, user=request.user, status__in=["waiting", "notified"]
    ).count()

    not_allocated_count = ReservationWaitlist.objects.filter(
        stream=stream_obj, user=request.user, status="not_allocated"
    ).count()

    completed_count = SystemAllocation.objects.filter(
        stream=stream_obj, user=request.user, end_date__lt=timezone.now()
    ).count()

    scheduled_count = RecurringReservationInstance.objects.filter(
        recurring_reservation__stream=stream_obj, recurring_reservation__created_by=request.user, status="scheduled"
    ).count()

    total_count = active_bookings + active_recurring + pending_waitlist

    context = {
        "stream": stream,
        "selected_stream": stream,
        "allocations": allocations[:50],
        "recurring": recurring,
        "waitlist": waitlist,
        "status_filter": status_filter,
        "active_bookings": active_bookings,
        "active_recurring": active_recurring,
        "pending_waitlist": pending_waitlist,
        "not_allocated_count": not_allocated_count,
        "completed_count": completed_count,
        "scheduled_count": scheduled_count,
        "total_count": total_count,
        "now": timezone.now(),
    }
    return render(request, "products/my_bookings.html", context)
