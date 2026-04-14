"""Products app - Notifications, System Status, Metrics, and Export views."""

# pylint: disable=invalid-name,too-many-lines,unused-argument,wrong-import-position

from ._helpers import (
    Avg,
    HttpResponse,
    JsonResponse,
    Notification,
    System,
    SystemAllocation,
    SystemMetrics,
    SystemStatusHistory,
    _parse_json_body,
    csv,
    datetime,
    get_default_stream_name,
    get_object_or_404,
    get_stream_or_404,
    login_required,
    require_GET,
    require_POST,
    timedelta,
    timezone,
)

__all__ = [
    "get_nc_details",
    "save_nc_details",
    "get_all_nc_details",
    "mark_notifications_read",
    "toggle_notification_read",
    "system_status_api",
    "system_metrics_api",
    "get_historical_system_status",
    "system_details_api",
    "system_metrics",
    "update_system_metrics",
    "export_systems_log",
]


@login_required
def get_nc_details(request, stream=None):
    """Get nc details."""
    system_id = request.GET.get("system_id")
    try:
        system = System.objects.get(pk=system_id)
        return JsonResponse({"details": system.nc_details or ""})
    except System.DoesNotExist:
        return JsonResponse({"details": ""})


@login_required
def save_nc_details(request, stream=None):
    """Save nc details."""
    if request.method == "POST":
        system_id = request.POST.get("system_id")
        details = request.POST.get("details", "")
        try:
            system = System.objects.get(pk=system_id)
            system.nc_details = details
            system.save()
            return JsonResponse({"success": True})
        except System.DoesNotExist:
            return JsonResponse({"success": False, "error": "System not found"})
    return JsonResponse({"success": False, "error": "Invalid request"})


from django.views.decorators.http import require_GET  # noqa: E402, F811


@login_required
@require_GET
def get_all_nc_details(request, stream=None):
    """Returns all systems' 12NC details for the given stream as JSON:.

    [{id, name, details}]
    """
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    stream_obj = get_stream_or_404(stream, request=request)

    systems = System.objects.filter(stream=stream_obj).order_by("name")
    data = []
    for sys in systems:
        data.append({"id": sys.id, "name": sys.name, "details": sys.nc_details or ""})
    return JsonResponse({"systems": data})


@login_required
def mark_notifications_read(request):
    """Mark notifications read."""
    if request.method == "POST":
        request.user.notifications.filter(is_read=False).update(is_read=True)
        return JsonResponse({"status": "ok"})
    return JsonResponse({"status": "error"}, status=400)


@login_required
@require_POST
def toggle_notification_read(request, pk):
    """Toggle a single notification between read/unread."""
    try:
        notif = Notification.objects.get(pk=pk, user=request.user)
        notif.is_read = not notif.is_read
        notif.save(update_fields=["is_read"])
        return JsonResponse({"status": "ok", "is_read": notif.is_read})
    except Notification.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Not found"}, status=404)


@login_required
@require_GET
def system_status_api(request, stream=None):
    """API endpoint to get current system status for real-time updates."""
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    stream_obj = get_stream_or_404(stream, request=request)

    systems = System.objects.filter(stream=stream_obj).order_by("name")
    system_data = []

    for system in systems:
        system_data.append(
            {
                "id": system.id,
                "name": system.name,
                "status": system.status,
                "health": system.health,
                "utilization": system.utilization_percentage,
                "last_updated": system.last_updated.isoformat() if system.last_updated else None,
            }
        )

    return JsonResponse({"success": True, "systems": system_data, "timestamp": timezone.now().isoformat()})


@login_required
@require_GET
def system_metrics_api(request, stream=None):
    """API endpoint to get system metrics data."""
    # pylint: disable=too-many-locals
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    stream_obj = get_stream_or_404(stream, request=request)

    systems = System.objects.filter(stream=stream_obj)

    total_systems = systems.count()
    active_systems = systems.filter(status="Active").count()
    blocked_systems = systems.exclude(status="Active").count()

    avg_utilization = systems.aggregate(avg_util=Avg("utilization_percentage"))["avg_util"] or 0

    most_active = systems.filter(utilization_percentage__gt=0).order_by("-utilization_percentage")[:5]

    most_active_data = [
        {
            "name": system.name,
            "usage_hours": round(system.utilization_percentage * 24 * 30 / 100, 1),  # Convert percentage to hours
        }
        for system in most_active
    ]

    now = timezone.now()
    usage_trends = []

    for i in range(7):
        date = now - timedelta(days=6 - i)
        day_name = date.strftime("%a")

        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        allocations_count = SystemAllocation.objects.filter(start_date__lt=day_end, end_date__gt=day_start).count()

        usage_trends.append({"label": day_name, "value": allocations_count})

    return JsonResponse(
        {
            "success": True,
            "total_systems": total_systems,
            "active_systems": active_systems,
            "blocked_systems": blocked_systems,
            "utilization": round(avg_utilization, 1),
            "most_active": most_active_data,
            "usage_trends": usage_trends,
        }
    )


@login_required
@require_GET
def get_historical_system_status(request, stream=None):  # noqa: CCR001
    """API endpoint to get historical system statuses for a specific date."""
    # pylint: disable=too-many-locals
    view_date_str = request.GET.get("view_date")
    if not view_date_str:
        return JsonResponse(
            {"success": False, "error": "view_date parameter required (format: YYYY-MM-DD)"}, status=400
        )

    try:
        view_date = datetime.strptime(view_date_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"success": False, "error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    try:
        stream_obj = get_stream_or_404(stream, request=request)
    except Http404:
        return JsonResponse({"success": False, "error": f'Stream "{stream}" not found'}, status=404)

    systems = System.objects.filter(stream=stream_obj).order_by("name")

    systems_data = []
    for system in systems:
        view_date_obj = view_date

        # Create date range for the entire day (24 hours)
        # Start: 00:00:00 of view_date
        # End: 00:00:00 of next day (exclusive)
        day_start = timezone.make_aware(datetime.combine(view_date_obj, datetime.min.time()))
        day_end = day_start + timedelta(days=1)

        # First, try to find the most recent status on the view_date itself
        historical_status = (
            SystemStatusHistory.objects.filter(system=system, updated_at__gte=day_start, updated_at__lt=day_end)
            .order_by("-updated_at")
            .first()
        )

        # If no status found on that exact day, look for the most recent status before that day
        if not historical_status:
            historical_status = (
                SystemStatusHistory.objects.filter(system=system, updated_at__lt=day_start)
                .order_by("-updated_at")
                .first()
            )

        if historical_status:
            status_value = historical_status.status
            status_display = historical_status.get_status_display()
            description = historical_status.description
            assignee = str(historical_status.assignee) if historical_status.assignee else ""
        else:
            # No historical status found before or on the view_date
            # This means on this date, the system should be considered Active (default state)
            status_value = "Active"
            status_display = "Active"
            description = ""
            assignee = ""

        systems_data.append(
            {
                "id": system.id,
                "name": system.name,
                "status": status_value,
                "status_display": status_display,
                "description": description,
                "assignee": assignee,
                "health": system.health,
                "utilization": system.utilization_percentage,
            }
        )

    return JsonResponse({"success": True, "view_date": view_date_str, "systems": systems_data})


@login_required
@require_GET
def system_details_api(request, stream=None, system_id=None):
    """API endpoint to get detailed information about a specific system."""
    try:
        try:
            stream_obj = get_stream_or_404(stream, request=request)
        except Http404:
            return JsonResponse({"success": False, "error": f'Stream "{stream}" not found'}, status=404)

        system = System.objects.get(id=system_id, stream=stream_obj)

        recent_allocations = SystemAllocation.objects.filter(system_type=system.name).order_by("-created_at")[:10]

        allocations_data = [
            {
                "user": allocation.user.username,
                "start_date": allocation.start_date.isoformat(),
                "end_date": allocation.end_date.isoformat(),
                "participant": allocation.blocked_for_participant.name if allocation.blocked_for_participant else None,
            }
            for allocation in recent_allocations
        ]

        status_history = SystemStatusHistory.objects.filter(system=system).order_by("-updated_at")[:10]

        history_data = [
            {
                "status": history.status,
                "description": history.description,
                "updated_by": history.updated_by,
                "updated_at": history.updated_at.isoformat(),
            }
            for history in status_history
        ]

        return JsonResponse(
            {
                "success": True,
                "system": {
                    "id": system.id,
                    "name": system.name,
                    "status": system.status,
                    "description": system.description,
                    "health": system.health,
                    "utilization": system.utilization_percentage,
                    "nc_details": system.nc_details,
                    "last_updated": system.last_updated.isoformat(),
                    "recent_allocations": allocations_data,
                    "status_history": history_data,
                },
            }
        )

    except System.DoesNotExist:
        return JsonResponse({"success": False, "error": "System not found"}, status=404)


@login_required
@require_GET
def system_metrics(request, system_id):
    """Get metrics for a specific system including downtime data."""
    system = get_object_or_404(System, id=system_id)
    try:
        metrics = SystemMetrics.objects.get(system=system)
    except SystemMetrics.DoesNotExist:
        metrics = SystemMetrics.objects.create(system=system)

    # Get downtime metrics (this calculates real availability)
    downtime_metrics = system.get_downtime_metrics(30)
    current_downtime = system.get_current_downtime()

    # Use calculated availability as uptime percentage instead of static value
    actual_uptime_percentage = (
        downtime_metrics.availability_percentage
        if hasattr(downtime_metrics, "availability_percentage")
        else metrics.uptime_percentage
    )

    # Update the metrics with calculated uptime
    if hasattr(downtime_metrics, "availability_percentage"):
        metrics.uptime_percentage = downtime_metrics.availability_percentage
        metrics.save()

    data = {
        "usage_hours": metrics.usage_hours,
        "total_allocations": metrics.total_allocations,
        "last_allocation_date": metrics.last_allocation_date.isoformat() if metrics.last_allocation_date else None,
        "average_session_duration": str(metrics.average_session_duration) if metrics.average_session_duration else None,
        "uptime_percentage": actual_uptime_percentage,  # Use calculated value
        "utilization_percentage": system.utilization_percentage,
        # Downtime metrics
        "downtime_metrics": {
            "availability_percentage": round(downtime_metrics.availability_percentage, 2),
            "total_downtime_hours": round(downtime_metrics.total_downtime_hours, 2),
            "total_incidents": downtime_metrics.total_incidents,
            "planned_downtime_hours": round(downtime_metrics.planned_downtime_hours, 2),
            "unplanned_downtime_hours": round(downtime_metrics.unplanned_downtime_hours, 2),
            "mean_time_to_repair_hours": (
                round(downtime_metrics.mean_time_to_repair_hours, 2)
                if downtime_metrics.mean_time_to_repair_hours
                else None
            ),
            "mean_time_between_failures_hours": (
                round(downtime_metrics.mean_time_between_failures_hours, 2)
                if downtime_metrics.mean_time_between_failures_hours
                else None
            ),
        },
        "current_downtime": {
            "is_down": system.is_currently_down(),
            "downtime_id": current_downtime.id if current_downtime else None,
            "title": current_downtime.title if current_downtime else None,
            "start_time": current_downtime.start_time.isoformat() if current_downtime else None,
            "duration_hours": round(current_downtime.duration_hours, 2) if current_downtime else 0,
            "impact_level": current_downtime.get_impact_level_display() if current_downtime else None,
        },
    }
    return JsonResponse(data)


@login_required
@require_POST
def update_system_metrics(request, system_id):
    """Update metrics for a specific system."""
    system = get_object_or_404(System, id=system_id)
    try:
        metrics = SystemMetrics.objects.get(system=system)
    except SystemMetrics.DoesNotExist:
        metrics = SystemMetrics.objects.create(system=system)

    data, err = _parse_json_body(request)
    if err:
        return err

    # Update the metrics
    if "usage_hours" in data:
        metrics.usage_hours = data["usage_hours"]
    if "total_allocations" in data:
        metrics.total_allocations = data["total_allocations"]
    if "uptime_percentage" in data:
        metrics.uptime_percentage = data["uptime_percentage"]

    metrics.save()

    # Update system utilization
    if "utilization_percentage" in data:
        system.utilization_percentage = data["utilization_percentage"]
        system.save()

    return JsonResponse({"status": "success"})


@login_required
def export_systems_log(request, stream=None):  # noqa: CCR001
    """Export a detailed log of all systems.

    Includes booking, utilization, status, and all possible details with timestamps.
    """
    # pylint: disable=too-many-locals
    if stream:
        if not stream or stream.strip() == "":
            stream = get_default_stream_name(request)

        stream_obj = get_stream_or_404(stream, request=request)
        systems = System.objects.filter(stream=stream_obj)
    else:
        systems = System.objects.all()
    response = HttpResponse(content_type="text/csv")
    filename = f"systems_detailed_log_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "System Name",
            "Status",
            "Utilization (%)",
            "Health",
            "Description",
            "Booking User",
            "Booking Start",
            "Booking End",
            "Last Status Change",
            "Last Utilization Update",
            "History Details",
        ]
    )
    for system in systems:
        allocation = (
            SystemAllocation.objects.filter(system_type=system.name, stream=system.stream).order_by("-end_date").first()
        )
        booking_user = allocation.user.username if allocation and allocation.user else ""
        booking_start = (
            allocation.start_date.strftime("%Y-%m-%d %H:%M:%S") if allocation and allocation.start_date else ""
        )
        booking_end = allocation.end_date.strftime("%Y-%m-%d %H:%M:%S") if allocation and allocation.end_date else ""
        booking_type = getattr(allocation, "blocked_for_participant", None)
        booking_type = booking_type.name if booking_type else ""
        last_status = SystemStatusHistory.objects.filter(system=system).order_by("-updated_at").first()
        last_status_change = (
            last_status.updated_at.strftime("%Y-%m-%d %H:%M:%S") if last_status and last_status.updated_at else ""
        )
        last_util_update = (
            last_status.updated_at.strftime("%Y-%m-%d %H:%M:%S") if last_status and last_status.updated_at else ""
        )
        history_details = []
        for h in SystemStatusHistory.objects.filter(system=system).order_by("-updated_at"):
            history_details.append(f"[{h.updated_at.strftime('%Y-%m-%d %H:%M:%S')}] {h.status}")
        row = [
            system.name or "",
            system.get_status_display() or "",
            getattr(system, "utilization_percentage", "") or "",
            getattr(system, "health", "") or "",
            getattr(system, "description", ""),
            booking_user,
            booking_start,
            booking_end,
            last_status_change,
            last_util_update,
            "\n".join(history_details),
        ]
        # Ensure row has exactly 10 columns
        while len(row) < 10:
            row.append("")
        writer.writerow(row)
    return response


from django.http import Http404  # noqa: E402
