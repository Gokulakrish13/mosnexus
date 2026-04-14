"""Products app - User Booking History, Booking Conflicts, Gantt Data, Downtime Dashboard views."""

from django.utils.dateparse import parse_datetime

from ._helpers import (
    JsonResponse,
    System,
    SystemAllocation,
    SystemDowntime,
    User,
    can_manage_system_allocation,
    can_view_analytics,
    get_default_stream_name,
    get_object_or_404,
    get_stream_or_404,
    localtime,
    login_required,
    make_aware,
    messages,
    redirect,
    render,
    require_GET,
    timedelta,
    timezone,
)

__all__ = [
    "user_booking_history_api",
    "booking_conflicts_api",
    "gantt_data_api",
    "downtime_dashboard",
]


@login_required
@require_GET
def user_booking_history_api(request, stream=None):
    """Return the current user's booking history for the stream."""
    stream_obj = get_stream_or_404(stream, request=request)
    now = timezone.now()
    allocations = SystemAllocation.objects.filter(stream=stream_obj, user=request.user).order_by("-start_date")[:100]
    data = []
    for alloc in allocations:
        start_l = localtime(alloc.start_date)
        end_l = localtime(alloc.end_date)
        data.append(
            {
                "id": alloc.id,
                "system_type": alloc.system_type,
                "start_date": start_l.strftime("%Y-%m-%d %H:%M"),
                "end_date": end_l.strftime("%Y-%m-%d %H:%M"),
                "is_active": alloc.end_date >= now,
                "blocked_for": f"{alloc.blocked_for_participant.name}" if alloc.blocked_for_participant else None,
            }
        )
    active = sum(1 for d in data if d["is_active"])
    past = len(data) - active
    return JsonResponse({"success": True, "bookings": data, "active_count": active, "past_count": past})


@login_required
@require_GET
def booking_conflicts_api(request, stream=None):
    """Check booking conflicts for a system in a date range."""
    stream_obj = get_stream_or_404(stream, request=request)
    system_id = request.GET.get("system_id")
    start = request.GET.get("start_date")
    end = request.GET.get("end_date")
    if not all([system_id, start, end]):
        return JsonResponse({"success": False, "error": "Missing parameters"}, status=400)
    system = get_object_or_404(System, id=system_id, stream=stream_obj)
    start_dt = parse_datetime(start) or parse_datetime(start + "T00:00")
    end_dt = parse_datetime(end) or parse_datetime(end + "T23:59")
    if not start_dt or not end_dt:
        return JsonResponse({"success": False, "error": "Invalid dates"}, status=400)
    if timezone.is_naive(start_dt):
        start_dt = make_aware(start_dt)
    if timezone.is_naive(end_dt):
        end_dt = make_aware(end_dt)
    conflicts = SystemAllocation.objects.filter(
        system_type=system.name, stream=stream_obj, start_date__lt=end_dt, end_date__gt=start_dt
    ).order_by("start_date")
    data = []
    for conflict in conflicts:
        sl = localtime(conflict.start_date)
        el = localtime(conflict.end_date)
        data.append(
            {
                "id": conflict.id,
                "start": sl.strftime("%Y-%m-%dT%H:%M"),
                "end": el.strftime("%Y-%m-%dT%H:%M"),
                "user": conflict.user.username if conflict.user else "Unknown",
            }
        )
    return JsonResponse({"success": True, "system_name": system.name, "conflicts": data})


@login_required
@require_GET
def gantt_data_api(request, stream=None):
    """Return allocation data formatted for Gantt / timeline view."""
    stream_obj = get_stream_or_404(stream, request=request)
    days = int(request.GET.get("days", 14))
    now = timezone.now()
    start_range = now - timedelta(days=3)
    end_range = now + timedelta(days=days)
    systems = System.objects.filter(stream=stream_obj).order_by("name")
    allocations = SystemAllocation.objects.filter(
        stream=stream_obj, start_date__lte=end_range, end_date__gte=start_range
    ).order_by("start_date")
    alloc_map: dict[str, list] = {}
    for alloc in allocations:
        alloc_map.setdefault(alloc.system_type, []).append(
            {
                "id": alloc.id,
                "start": localtime(alloc.start_date).isoformat(),
                "end": localtime(alloc.end_date).isoformat(),
                "user": alloc.user.username if alloc.user else "Unknown",
                "is_current": alloc.start_date <= now <= alloc.end_date,
            }
        )
    rows = []
    for sys_obj in systems:
        rows.append(
            {
                "system_id": sys_obj.id,
                "name": sys_obj.name,
                "status": sys_obj.status,
                "health": sys_obj.health,
                "allocations": alloc_map.get(sys_obj.name, []),
            }
        )
    return JsonResponse(
        {
            "success": True,
            "systems": rows,
            "range_start": localtime(start_range).isoformat(),
            "range_end": localtime(end_range).isoformat(),
        }
    )


@login_required
@require_GET
def downtime_dashboard(request, stream=None):
    """Render the downtime dashboard with current status and metrics."""
    stream_obj = get_stream_or_404(stream, request=request)

    if not can_view_analytics(request.user):
        messages.error(request, "Access denied. You need appropriate privileges to view downtime dashboard.")
        return redirect("dashboard")

    systems = System.objects.filter(stream=stream_obj).order_by("name")

    ongoing_downtimes = SystemDowntime.objects.filter(stream=stream_obj, status="ongoing").order_by("-start_time")

    recent_downtimes = SystemDowntime.objects.filter(stream=stream_obj, status="resolved").order_by("-end_time")[:20]

    users = User.objects.filter(is_active=True).order_by("username")

    context = {
        "stream": stream or get_default_stream_name(request),
        "selected_stream": stream or get_default_stream_name(request),
        "systems": systems,
        "ongoing_downtimes": ongoing_downtimes,
        "recent_downtimes": recent_downtimes,
        "users": users,
        "downtime_types": SystemDowntime.DOWNTIME_TYPES,
        "impact_levels": SystemDowntime.IMPACT_LEVELS,
        "status_choices": SystemDowntime.STATUS_CHOICES,
        "can_manage": can_manage_system_allocation(request.user),
    }

    return render(request, "products/downtime_dashboard.html", context)


# ================================
# BUILD SERVERS VIEWS
# ================================
