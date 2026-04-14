"""Products app — Allocation views."""

# pylint: disable=too-many-lines,broad-exception-caught

from calendar import monthrange
from datetime import datetime as dt_class

from ._helpers import (
    AuditLog,
    JsonResponse,
    Notification,
    OnboardingProgress,
    Participant,
    System,
    SystemAllocation,
    SystemStatusHistory,
    User,
    can_manage_system_allocation,
    can_manage_users,
    check_user_access,
    date,
    datetime,
    get_default_stream_name,
    get_stream_or_404,
    localtime,
    logger,
    login_required,
    logout,
    make_aware,
    messages,
    redirect,
    render,
    require_GET,
    require_POST,
    timedelta,
    timezone,
    transaction,
)

__all__ = [
    "system_allocation",
    "allocate_system",
    "get_blocked_systems",
    "release_system",
    "cancel_booking_day",
    "cancel_booking_days",
]


@login_required
def system_allocation(request, stream=None):  # noqa: C901, CCR001
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-complex
    """System allocation."""
    if not request.user.is_authenticated:
        return render(request, "products/please_login.html")

    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    if not can_manage_system_allocation(request.user):
        messages.error(
            request, "Access denied. You need Lab Incharge or higher privileges to access system allocation."
        )
        return redirect("dashboard")

    combined_participants = {}
    if can_manage_users(request.user):
        users = list(User.objects.filter(is_active=True).values("id", "username", "email"))
        participants = list(Participant.objects.all().values("id", "name", "email"))
        combined_participants = {"users": users, "participants": participants}

    view_date_str = request.GET.get("view_date")
    if view_date_str:
        try:
            view_date = datetime.strptime(view_date_str, "%Y-%m-%d").date()
        except ValueError:
            view_date = timezone.now().date()
    else:
        view_date = timezone.now().date()

    stream_obj = get_stream_or_404(stream, request=request)

    systems = System.objects.filter(stream=stream_obj).order_by("name")

    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)

    for system in systems:
        # Convert view_date to timezone-aware datetime at the END of the day
        # This ensures we include all status changes that happened on view_date
        _view_datetime_end = timezone.make_aware(datetime.combine(view_date, datetime.max.time()))  # noqa: F841

        # Find the most recent status change that occurred on or before the view_date
        # We compare the DATE part of updated_at with view_date
        historical_status = (
            SystemStatusHistory.objects.filter(
                system=system,
                updated_at__isnull=False,  # Ensure updated_at is not None
                updated_at__date__lte=view_date,  # Compare only the date part
            )
            .order_by("-updated_at")
            .first()
        )

        if historical_status:
            system.historical_status = historical_status.status
            system.historical_status_display = historical_status.get_status_display()
            system.historical_description = historical_status.description
            system.historical_assignee = historical_status.assignee
            system.historical_updated_by = historical_status.updated_by
            system.historical_updated_at = historical_status.updated_at
        else:
            # No historical record found before view_date, assume Active
            system.historical_status = "Active"
            system.historical_status_display = "Active"
            system.historical_description = ""
            system.historical_assignee = ""
            system.historical_updated_by = ""
            system.historical_updated_at = None

    for system in systems:
        recent_allocations = SystemAllocation.objects.filter(system_type=system.name, start_date__gte=thirty_days_ago)

        recent_allocations = SystemAllocation.objects.filter(system_type=system.name, start_date__gte=thirty_days_ago)

        total_hours = 0
        for allocation in recent_allocations:
            start = max(allocation.start_date, thirty_days_ago)
            end = min(allocation.end_date, now)
            if end > start:
                duration = end - start
                total_hours += duration.total_seconds() / 3600

        # Calculate utilization percentage based on business hours (8 hours/day, 5 days/week)
        # More realistic than 24/7 for most business systems
        business_days = 22  # Average business days per month
        business_hours_per_day = 8
        max_business_hours = business_days * business_hours_per_day  # ~176 hours per month

        business_utilization = (total_hours / max_business_hours) * 100 if max_business_hours > 0 else 0
        _full_time_utilization = (total_hours / (24 * 30)) * 100 if (24 * 30) > 0 else 0  # noqa: F841

        # Use business hours utilization as primary metric (more realistic)
        # Cap at 100% to prevent unrealistic values
        utilization = min(business_utilization, 100.0)

        system.utilization_percentage = round(utilization, 1)
        system.save(update_fields=["utilization_percentage"])

        if system.historical_status == "Active":
            if utilization > 100:
                system.health = "Critical"
            elif utilization > 80:
                system.health = "Warning"
            elif utilization > 95:
                system.health = "Warning"
            else:
                system.health = "Excellent" if utilization < 50 else "Good"
        else:
            system.health = "Critical" if system.historical_status in ["Issue", "Removed"] else "Warning"

        system.save(update_fields=["health"])

    for system in systems:
        current_downtime = system.get_current_downtime()
        system.current_downtime = current_downtime
        system.is_currently_down = system.is_currently_down()

        downtime_metrics = system.get_downtime_metrics(30)
        system.downtime_metrics_data = downtime_metrics

    return render(
        request,
        "products/system_allocation.html",
        {
            "participants": combined_participants,
            "systems": systems,
            "stream": stream or get_default_stream_name(request),
            "selected_stream": stream or get_default_stream_name(request),
            "view_date": view_date,
            "view_date_str": view_date.strftime("%Y-%m-%d"),
            "can_manage_downtime": can_manage_system_allocation(request.user),
            "show_onboarding_tour": not OnboardingProgress.objects.filter(
                user=request.user, tour_key="system_allocation"
            ).exists(),
        },
    )


@login_required
@require_POST
def allocate_system(request, stream=None):  # noqa: C901, CCR001, E501
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    # pylint: disable=too-many-return-statements,too-complex,logging-too-many-args
    """Allocate system."""
    if request.method == "POST":
        logger.info("System allocation request received from user %s", request.user.username)
    system_type = request.POST.get("system_type")
    start_date = request.POST.get("start_date")
    end_date = request.POST.get("end_date")
    participant_id = request.POST.get("participant_id")

    # Parse datetime-local input robustly
    def parse_dt(dt_str):
        if not dt_str:
            return None
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return make_aware(datetime.strptime(dt_str, fmt))
            except ValueError:
                continue
        return None

    start_dt = parse_dt(start_date)
    end_dt = parse_dt(end_date)
    if not (system_type and start_dt and end_dt):
        return JsonResponse({"success": False, "error": "Missing or invalid data."}, status=400)
    user = request.user
    blocked_for_participant = None
    if request.user.is_superuser and participant_id:
        if participant_id.startswith("user_"):
            try:
                user_id = int(participant_id.split("_")[1])
                user = User.objects.get(id=user_id)
            except Exception:
                return JsonResponse({"success": False, "error": "User not found."}, status=404)
        elif participant_id.startswith("participant_"):
            try:
                part_id = int(participant_id.split("_")[1])
                participant = Participant.objects.get(id=part_id)
                blocked_for_participant = participant
                user = User.objects.filter(email=participant.email).first()
                if not user:
                    user = User.objects.filter(username=participant.name).first()
                if not user:
                    user = request.user  # fallback to admin
            except Participant.DoesNotExist:
                user = request.user
        else:
            # fallback: treat as participant id (legacy)
            try:
                participant = Participant.objects.get(id=participant_id)
                blocked_for_participant = participant
                user = request.user
            except Participant.DoesNotExist:
                user = request.user
    stream_obj = get_stream_or_404(stream, request=request)

    try:
        system = System.objects.get(name=system_type, stream=stream_obj)
    except System.DoesNotExist:
        return JsonResponse({"success": False, "error": "System not found."}, status=404)

    # Check for non-Active status during the booking period
    # We need to check each day in the range to see if there's a non-Active status

    def get_status_for_date(system, check_date):
        """Get the system status for a specific date based on status history."""
        day_start = make_aware(datetime.combine(check_date, datetime.min.time()))
        day_end = day_start + timedelta(days=1)

        status_record = (
            SystemStatusHistory.objects.filter(system=system, updated_at__gte=day_start, updated_at__lt=day_end)
            .order_by("-updated_at")
            .first()
        )

        if not status_record:
            status_record = (
                SystemStatusHistory.objects.filter(system=system, updated_at__lt=day_start)
                .order_by("-updated_at")
                .first()
            )

        if status_record:
            return status_record.status
        # No historical status found, default to Active
        return "Active"

    current_date = start_dt.date()
    end_date_check = end_dt.date()
    non_active_dates = []

    while current_date <= end_date_check:
        status = get_status_for_date(system, current_date)
        if status != "Active":
            non_active_dates.append(
                {"date": current_date.strftime("%Y-%m-%d"), "status": dict(System.STATUS_CHOICES).get(status, status)}
            )
        current_date += timedelta(days=1)

    if non_active_dates:
        if len(non_active_dates) == 1:
            error_msg = f"Cannot book: System is '{non_active_dates[0]['status']}' on {non_active_dates[0]['date']}"
        else:
            dates_info = ", ".join([f"{d['date']} ({d['status']})" for d in non_active_dates[:3]])
            if len(non_active_dates) > 3:
                dates_info += f" and {len(non_active_dates) - 3} more days"
            error_msg = f"Cannot book: System has non-Active status on: {dates_info}"
        return JsonResponse({"success": False, "error": error_msg}, status=409)

    # Check for overlap with transaction isolation to prevent double-booking race condition
    try:
        with transaction.atomic():
            overlap = (
                SystemAllocation.objects.select_for_update()
                .filter(system_type=system_type, end_date__gte=start_dt, start_date__lte=end_dt, stream=stream_obj)
                .exists()
            )
            if overlap:
                return JsonResponse({"success": False, "error": "System already blocked for this period."}, status=409)
            allocation = SystemAllocation.objects.create(
                system_type=system_type,
                user=user,
                start_date=start_dt,
                end_date=end_dt,
                blocked_for_participant=blocked_for_participant,
                stream=stream_obj,
            )
    except Exception:
        return JsonResponse({"success": False, "error": "Could not complete allocation. Please try again."}, status=500)
    AuditLog.log(
        "allocation",
        f"Allocated system {system.name} to {allocation.user.username}",
        user=request.user,
        request=request,
        obj=allocation,
        module="allocation",
        severity="info",
        stream=stream_obj,
    )
    if allocation.user != request.user:
        Notification.notify(
            allocation.user,
            f"System '{system.name}' has been allocated to you from "
            f"{start_dt.strftime('%b %d')} to {end_dt.strftime('%b %d, %Y')}.",
            "allocation",
        )
    return JsonResponse({"success": True, "allocation_id": allocation.id})


@login_required
@require_GET
def get_blocked_systems(request, stream=None):
    # pylint: disable=too-many-locals
    """Get blocked systems."""
    today = date.today()
    expired = SystemAllocation.objects.filter(end_date__lt=today)
    expired.delete()
    month = request.GET.get("month")
    year = request.GET.get("year")
    allocations = SystemAllocation.objects.filter(end_date__gte=today)
    if stream:
        if not stream or stream.strip() == "":
            stream = get_default_stream_name(request)

        stream_obj = get_stream_or_404(stream, request=request)

        allocations = allocations.filter(stream=stream_obj)
    if month and year:
        try:
            month = int(month)
            year = int(year)
            # Get all allocations that overlap any day in the selected month
            month_start = make_aware(datetime(year, month, 1))
            month_end = make_aware(datetime(year, month, monthrange(year, month)[1], 23, 59, 59))
            allocations = allocations.filter(start_date__lte=month_end, end_date__gte=month_start)
        except Exception:
            pass
    # Return all allocations (not just latest per system)
    data = []
    for alloc in allocations.order_by("system_type", "start_date"):
        blocked_for = None
        if alloc.blocked_for_participant:
            blocked_for = f"{alloc.blocked_for_participant.name} ({alloc.blocked_for_participant.email})"
        start_date_local = localtime(alloc.start_date)
        end_date_local = localtime(alloc.end_date)
        start_date_str = start_date_local.strftime("%Y-%m-%d %H:%M")
        end_date_str = end_date_local.strftime("%Y-%m-%d %H:%M")
        data.append(
            {
                "id": alloc.id,
                "system_type": alloc.system_type,
                "start_date": start_date_str,
                "end_date": end_date_str,
                "blocked_by": alloc.user.username,
                "blocked_for": blocked_for,
            }
        )
    return JsonResponse({"allocations": data})


@login_required
def release_system(request, stream=None):  # noqa: CCR001
    # pylint: disable=too-many-return-statements
    """Release system."""
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if request.method == "POST":
        system_type = request.POST.get("system_type")
        username = request.POST.get("username")
        allocation_id = request.POST.get("allocation_id")  # Get allocation ID

        allocation = None
        user = None

        stream_obj = get_stream_or_404(stream, request=request)

        if allocation_id and allocation_id.isdigit():
            allocation = SystemAllocation.objects.filter(id=int(allocation_id), stream=stream_obj).first()
        else:
            if is_ajax:
                return JsonResponse({"success": False, "error": "Invalid or missing allocation ID."}, status=400)
            messages.error(request, "Invalid or missing allocation ID.")
            return redirect("my_bookings", stream=stream)

        if allocation:
            if request.user.is_superuser and username:
                user = User.objects.filter(username=username).first()
                if user and user != request.user:
                    Notification.notify(
                        user, f"Your system allocation for {system_type} was released by admin.", "allocation"
                    )
            AuditLog.log(
                "release",
                f"Released system allocation: {allocation.system_type}",
                user=request.user,
                request=request,
                module="allocation",
                severity="info",
                stream=stream_obj,
            )
            allocation.delete()
            if is_ajax:
                return JsonResponse({"success": True})
            messages.success(request, f"Booking for {system_type} has been cancelled.")
            return redirect("my_bookings", stream=stream)
        if is_ajax:
            return JsonResponse({"success": False, "error": "No active allocation found for this user and system."})
        messages.error(request, "No active allocation found.")
        return redirect("my_bookings", stream=stream)
    return redirect("system_allocation_stream", stream=stream)


@login_required
@require_POST
def cancel_booking_day(request, stream=None):
    """Cancel a specific day from a multi-day booking by splitting the allocation."""
    stream_obj = get_stream_or_404(stream, request=request)
    allocation_id = request.POST.get("allocation_id")
    cancel_date_str = request.POST.get("cancel_date")  # YYYY-MM-DD

    if not allocation_id or not allocation_id.isdigit() or not cancel_date_str:
        messages.error(request, "Invalid request.")
        return redirect("my_bookings", stream=stream)

    allocation = SystemAllocation.objects.filter(id=int(allocation_id), stream=stream_obj).first()
    if not allocation:
        messages.error(request, "Booking not found.")
        return redirect("my_bookings", stream=stream)

    try:
        cancel_date = datetime.strptime(cancel_date_str, "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "Invalid date format.")
        return redirect("my_bookings", stream=stream)

    alloc_start_date = allocation.start_date.date()
    alloc_end_date = allocation.end_date.date()

    if cancel_date < alloc_start_date or cancel_date > alloc_end_date:
        messages.error(request, "Date is not within this booking range.")
        return redirect("my_bookings", stream=stream)

    start_time = allocation.start_date.time()
    end_time = allocation.end_date.time()
    tz_info = allocation.start_date.tzinfo

    # If single-day booking, just delete it
    if alloc_start_date == alloc_end_date:
        allocation.delete()
        messages.success(request, f"Booking for {cancel_date_str} has been cancelled.")
        return redirect("my_bookings", stream=stream)

    # Multi-day: split into before and after segments

    # Segment before the cancelled day
    if cancel_date > alloc_start_date:
        day_before = cancel_date - timedelta(days=1)
        SystemAllocation.objects.create(
            stream=allocation.stream,
            system_type=allocation.system_type,
            user=allocation.user,
            start_date=allocation.start_date,
            end_date=dt_class.combine(day_before, end_time).replace(tzinfo=tz_info),
            blocked_for_participant=allocation.blocked_for_participant,
        )

    # Segment after the cancelled day
    if cancel_date < alloc_end_date:
        day_after = cancel_date + timedelta(days=1)
        SystemAllocation.objects.create(
            stream=allocation.stream,
            system_type=allocation.system_type,
            user=allocation.user,
            start_date=dt_class.combine(day_after, start_time).replace(tzinfo=tz_info),
            end_date=allocation.end_date,
            blocked_for_participant=allocation.blocked_for_participant,
        )

    # Delete original allocation
    system_type = allocation.system_type
    AuditLog.log(
        "release",
        f"Cancelled day {cancel_date_str} from multi-day allocation: {system_type}",
        user=request.user,
        request=request,
        module="allocation",
        severity="info",
        stream=stream_obj,
    )
    allocation.delete()

    messages.success(request, f'Booking for {system_type} on {cancel_date.strftime("%b %d, %Y")} has been cancelled.')
    return redirect("my_bookings", stream=stream)


@login_required
@require_POST
def cancel_booking_days(request, stream=None):  # noqa: C901, CCR001
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-complex
    """Cancel multiple days from a multi-day booking at once."""
    stream_obj = get_stream_or_404(stream, request=request)
    allocation_id = request.POST.get("allocation_id")
    cancel_dates_str = request.POST.get("cancel_dates", "")  # comma-separated YYYY-MM-DD

    if not allocation_id or not allocation_id.isdigit() or not cancel_dates_str.strip():
        messages.error(request, "Invalid request.")
        return redirect("my_bookings", stream=stream)

    allocation = SystemAllocation.objects.filter(id=int(allocation_id), stream=stream_obj).first()
    if not allocation:
        messages.error(request, "Booking not found.")
        return redirect("my_bookings", stream=stream)

    # Parse cancel dates
    cancel_dates = []
    for date_str in cancel_dates_str.split(","):
        date_str = date_str.strip()
        if date_str:
            try:
                cancel_dates.append(datetime.strptime(date_str, "%Y-%m-%d").date())
            except ValueError:
                pass

    if not cancel_dates:
        messages.error(request, "No valid dates provided.")
        return redirect("my_bookings", stream=stream)

    cancel_dates.sort()
    cancel_set = set(cancel_dates)

    alloc_start = allocation.start_date.date()
    alloc_end = allocation.end_date.date()
    start_time = allocation.start_date.time()
    end_time = allocation.end_date.time()
    tz_info = allocation.start_date.tzinfo
    system_type = allocation.system_type

    # Build list of all days in the allocation
    all_days = []
    day = alloc_start
    while day <= alloc_end:
        all_days.append(day)
        day += timedelta(days=1)

    # Filter to only dates within range
    cancel_set = cancel_set & set(all_days)
    if not cancel_set:
        messages.error(request, "None of the selected dates are within this booking range.")
        return redirect("my_bookings", stream=stream)

    num_cancelled = len(cancel_set)

    # If cancelling ALL days, just delete
    if cancel_set >= set(all_days):
        allocation.delete()
        AuditLog.log(
            "release",
            f"Cancelled all {num_cancelled} days of allocation: {system_type}",
            user=request.user,
            request=request,
            module="allocation",
            severity="info",
            stream=stream_obj,
        )
        messages.success(request, f"All {num_cancelled} days of {system_type} booking have been cancelled.")
        return redirect("my_bookings", stream=stream)

    # Find remaining contiguous segments
    remaining = sorted([dy for dy in all_days if dy not in cancel_set])

    segments = []
    seg_start = remaining[0]
    seg_end = remaining[0]
    for rd in remaining[1:]:
        if rd == seg_end + timedelta(days=1):
            seg_end = rd
        else:
            segments.append((seg_start, seg_end))
            seg_start = rd
            seg_end = rd
    segments.append((seg_start, seg_end))

    # Create new allocations for each remaining segment
    for seg_s, seg_e in segments:
        SystemAllocation.objects.create(
            stream=allocation.stream,
            system_type=allocation.system_type,
            user=allocation.user,
            start_date=dt_class.combine(seg_s, start_time).replace(tzinfo=tz_info),
            end_date=dt_class.combine(seg_e, end_time).replace(tzinfo=tz_info),
            blocked_for_participant=allocation.blocked_for_participant,
        )

    # Delete original
    AuditLog.log(
        "release",
        f"Cancelled {num_cancelled} days from multi-day allocation: {system_type}",
        user=request.user,
        request=request,
        module="allocation",
        severity="info",
        stream=stream_obj,
    )
    allocation.delete()

    date_list = ", ".join(d.strftime("%b %d") for d in sorted(cancel_set))
    messages.success(request, f"{num_cancelled} day(s) cancelled from {system_type}: {date_list}")
    return redirect("my_bookings", stream=stream)
