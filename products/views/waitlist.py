"""Products app - Waitlist, Utilization Dashboard, and Conflict Resolution views."""

# pylint: disable=broad-exception-caught,too-many-lines

from django.db.models.functions import TruncDate

from ._helpers import (
    AuditLog,
    Count,
    JsonResponse,
    Notification,
    Project,
    ReservationConflict,
    ReservationWaitlist,
    System,
    SystemAllocation,
    can_manage_system_allocation,
    check_user_access,
    date,
    datetime,
    get_current_bu,
    get_object_or_404,
    get_stream_or_404,
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
from .recurring import check_reservation_conflict

__all__ = [
    "waitlist_dashboard",
    "waitlist_join",
    "waitlist_entry_detail",
    "find_alternative_slots",
    "waitlist_cancel",
    "waitlist_fulfill",
    "utilization_dashboard",
    "conflicts_list",
    "conflict_resolve",
]


@login_required
def waitlist_dashboard(request, stream=None):
    """Dashboard for managing reservation waitlists."""
    stream_obj = get_stream_or_404(stream)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        messages.error(request, error_message)
        return redirect("dashboard")

    status_filter = request.GET.get("status", "waiting")
    system_filter = request.GET.get("system", "")
    priority_filter = request.GET.get("priority", "")

    waitlist_entries = ReservationWaitlist.objects.filter(stream=stream_obj)

    if status_filter:
        waitlist_entries = waitlist_entries.filter(status=status_filter)

    if system_filter:
        waitlist_entries = waitlist_entries.filter(system_id=system_filter)

    if priority_filter:
        waitlist_entries = waitlist_entries.filter(priority=priority_filter)

    for entry in waitlist_entries:
        if entry.status == "waiting":
            if entry.is_slot_passed():
                # Slot time has passed without rescheduling → Not Allocated
                entry.status = "not_allocated"
                entry.save(update_fields=["status", "updated_at"])
            elif entry.is_expired():
                entry.status = "expired"
                entry.save()

    stats = {
        "total_waiting": waitlist_entries.filter(status="waiting").count(),
        "total_fulfilled": ReservationWaitlist.objects.filter(stream=stream_obj, status="fulfilled").count(),
        "total_expired": ReservationWaitlist.objects.filter(stream=stream_obj, status="expired").count(),
        "total_not_allocated": ReservationWaitlist.objects.filter(stream=stream_obj, status="not_allocated").count(),
        "avg_wait_time": "N/A",
    }

    systems = System.objects.filter(stream=stream_obj)

    context = {
        "waitlist_entries": waitlist_entries.select_related("system", "user", "project"),
        "systems": systems,
        "stats": stats,
        "stream": stream,
        "selected_stream": stream,
        "status_filter": status_filter,
        "system_filter": system_filter,
        "priority_filter": priority_filter,
        "status_choices": ReservationWaitlist.STATUS_CHOICES,
        "priority_choices": ReservationWaitlist.PRIORITY_CHOICES,
    }
    return render(request, "products/waitlist_dashboard.html", context)


@login_required
def waitlist_join(request, stream=None):
    """Join the waitlist for a system reservation."""
    # pylint: disable=too-many-locals
    stream_obj = get_stream_or_404(stream)

    systems = System.objects.filter(stream=stream_obj, status="Active")
    projects = Project.objects.filter(stream=stream_obj, status="running")

    if request.method == "POST":
        try:
            system_id = request.POST.get("system")
            desired_date = request.POST.get("desired_date")
            desired_start_time = request.POST.get("desired_start_time")
            desired_end_time = request.POST.get("desired_end_time")
            is_flexible_date = request.POST.get("is_flexible_date") == "on"
            is_flexible_time = request.POST.get("is_flexible_time") == "on"
            flexibility_days = int(request.POST.get("flexibility_days", 3))
            priority = request.POST.get("priority", "normal")
            project_id = request.POST.get("project") or None
            reason = request.POST.get("reason", "").strip()
            notify_via_email = request.POST.get("notify_via_email") == "on"
            notes = request.POST.get("notes", "").strip()

            system = get_object_or_404(System, id=system_id, stream=stream_obj)

            max_position = (
                ReservationWaitlist.objects.filter(
                    system=system, desired_date=desired_date, status="waiting"
                ).aggregate(models.Max("queue_position"))["queue_position__max"]
                or 0
            )

            expiry = datetime.strptime(desired_date, "%Y-%m-%d") + timedelta(days=7)

            waitlist_entry = ReservationWaitlist.objects.create(
                system=system,
                stream=stream_obj,
                user=request.user,
                desired_date=desired_date,
                desired_start_time=desired_start_time,
                desired_end_time=desired_end_time,
                is_flexible_date=is_flexible_date,
                is_flexible_time=is_flexible_time,
                flexibility_days=flexibility_days,
                priority=priority,
                project_id=project_id,
                reason=reason,
                queue_position=max_position + 1,
                notify_via_email=notify_via_email,
                expires_at=timezone.make_aware(expiry) if expiry else None,
                notes=notes,
            )

            AuditLog.log(
                "create",
                "Joined waitlist for system",
                request=request,
                obj=waitlist_entry,
                module="waitlist",
                severity="info",
                stream=stream_obj,
            )

            messages.success(
                request,
                f"You have been added to the waitlist for {system.name}. Your position is #{waitlist_entry.queue_position}.",  # noqa: E501
            )
            bu = get_current_bu(request)
            Notification.notify_admins(
                bu,
                f"{request.user.username} joined waitlist for '{system.name}' (position #{waitlist_entry.queue_position}).",  # noqa: E501
                "waitlist",
                exclude_user=request.user,
            )
            return redirect("waitlist_dashboard", stream=stream)

        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "systems": systems,
        "projects": projects,
        "stream": stream,
        "selected_stream": stream,
        "priority_choices": ReservationWaitlist.PRIORITY_CHOICES,
        "form_error": form_error,
    }
    return render(request, "products/waitlist_join_form.html", context)


@login_required
def waitlist_entry_detail(request, stream=None, pk=None):
    """View waitlist entry details."""
    stream_obj = get_stream_or_404(stream)
    entry = get_object_or_404(ReservationWaitlist, pk=pk, stream=stream_obj)

    alternatives = find_alternative_slots(entry) if entry.status == "waiting" else []

    context = {
        "entry": entry,
        "alternatives": alternatives,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/waitlist_entry_detail.html", context)


def find_alternative_slots(waitlist_entry, num_suggestions=5):
    """Find alternative available slots for a waitlist entry."""
    alternatives = []
    system = waitlist_entry.system
    desired_date = waitlist_entry.desired_date
    flexibility_days = waitlist_entry.flexibility_days if waitlist_entry.is_flexible_date else 0

    for day_offset in range(-flexibility_days, flexibility_days + 1):
        check_date = desired_date + timedelta(days=day_offset)
        if check_date < date.today():
            continue

        has_conflict, _ = check_reservation_conflict(
            system, check_date, waitlist_entry.desired_start_time, waitlist_entry.desired_end_time
        )

        if not has_conflict:
            alternatives.append(
                {
                    "date": check_date,
                    "start_time": waitlist_entry.desired_start_time,
                    "end_time": waitlist_entry.desired_end_time,
                    "type": "exact_time" if day_offset == 0 else "alternative_date",
                }
            )

        if len(alternatives) >= num_suggestions:
            break

    return alternatives


@login_required
@require_POST
def waitlist_cancel(request, stream=None, pk=None):
    """Cancel a waitlist entry."""
    stream_obj = get_stream_or_404(stream)
    entry = get_object_or_404(ReservationWaitlist, pk=pk, stream=stream_obj, user=request.user)

    if entry.status == "waiting":
        entry.status = "declined"
        entry.save()
        AuditLog.log(
            "status_change",
            "Cancelled waitlist entry",
            request=request,
            obj=entry,
            module="waitlist",
            severity="info",
            stream=stream_obj,
        )
        messages.success(request, "Your waitlist entry has been cancelled.")
    else:
        messages.error(request, "This waitlist entry cannot be cancelled.")

    return redirect("waitlist_dashboard", stream=stream)


@login_required
@require_POST
def waitlist_fulfill(request, stream=None, pk=None):
    """Fulfill a waitlist entry (admin action)."""
    stream_obj = get_stream_or_404(stream)
    entry = get_object_or_404(ReservationWaitlist, pk=pk, stream=stream_obj)

    if not can_manage_system_allocation(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    try:
        start_dt = timezone.make_aware(datetime.combine(entry.desired_date, entry.desired_start_time))
        end_dt = timezone.make_aware(datetime.combine(entry.desired_date, entry.desired_end_time))

        allocation = SystemAllocation.objects.create(
            system_type=entry.system.name,
            stream=stream_obj,
            user=entry.user,
            start_date=start_dt,
            end_date=end_dt,
        )

        entry.status = "fulfilled"
        entry.fulfilled_allocation = allocation
        entry.fulfilled_at = timezone.now()
        entry.save()

        AuditLog.log(
            "approve",
            "Fulfilled waitlist entry",
            request=request,
            obj=entry,
            module="waitlist",
            severity="info",
            stream=stream_obj,
        )
        if entry.user != request.user:
            Notification.notify(
                entry.user,
                f"Your waitlist request for '{entry.system.name}' has been fulfilled! A system has been allocated.",
                "waitlist",
            )
        return JsonResponse({"success": True, "message": "Waitlist entry fulfilled successfully!"})

    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@login_required
def utilization_dashboard(request, stream=None):  # noqa: C901, CCR001
    """Dashboard showing system utilization analytics and optimization insights."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-statements
    stream_obj = get_stream_or_404(stream)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        messages.error(request, error_message)
        return redirect("dashboard")

    today = date.today()
    last_30_days = today - timedelta(days=30)
    _last_7_days = today - timedelta(days=7)  # noqa: F841

    systems = System.objects.filter(stream=stream_obj)

    total_allocations = SystemAllocation.objects.filter(stream=stream_obj, start_date__gte=last_30_days).count()

    allocations_by_system = (
        SystemAllocation.objects.filter(stream=stream_obj, start_date__gte=last_30_days)
        .values("system_type")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    daily_trend = (
        SystemAllocation.objects.filter(stream=stream_obj, start_date__gte=last_30_days)
        .annotate(day=TruncDate("start_date"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )

    system_utilization = []
    for system in systems:
        system_allocations = SystemAllocation.objects.filter(
            stream=stream_obj, system_type=system.name, start_date__gte=last_30_days
        ).count()

        # Calculate utilization percentage (assuming 8 hours per day, 30 days)
        max_possible = 30 * 8
        utilization_pct = (system_allocations / max_possible * 100) if max_possible > 0 else 0

        system_utilization.append(
            {
                "system": system,
                "allocations": system_allocations,
                "utilization_pct": min(utilization_pct, 100),
            }
        )

    system_utilization.sort(key=lambda x: x["utilization_pct"], reverse=True)

    upcoming_reservations = (
        SystemAllocation.objects.filter(
            stream=stream_obj, start_date__gte=today, start_date__lte=today + timedelta(days=7)
        )
        .select_related("user")
        .order_by("start_date")[:20]
    )

    waitlist_count = ReservationWaitlist.objects.filter(stream=stream_obj, status="waiting").count()

    peak_hours = list(range(9, 18))

    total_systems = systems.count()
    avg_utilization = sum(s["utilization_pct"] for s in system_utilization) / total_systems if total_systems > 0 else 0

    total_hours = 0
    for alloc in SystemAllocation.objects.filter(stream=stream_obj, start_date__gte=last_30_days):
        if alloc.end_date and alloc.start_date:
            duration = (alloc.end_date - alloc.start_date).total_seconds() / 3600
            total_hours += duration
    avg_hours = total_hours / total_allocations if total_allocations > 0 else 0

    metrics = {
        "overall_utilization": round(avg_utilization, 1),
        "utilization_trend": round(avg_utilization - 50, 1),
        "total_systems": total_systems,
        "total_reservations": total_allocations,
        "avg_reservation_hours": round(avg_hours, 1),
    }

    recommendations = []

    for su in system_utilization:
        if su["utilization_pct"] < 20:
            recommendations.append(
                {
                    "priority": "medium",
                    "icon": "fa-chart-line",
                    "title": f"Low utilization on {su['system'].name}",
                    "description": (
                        f"This system has only {su['utilization_pct']:.0f}% utilization. "
                        "Consider consolidating workloads or promoting its availability."
                    ),
                    "action_url": "#",
                    "action_text": "View Details",
                }
            )

    if waitlist_count > 0:
        recommendations.append(
            {
                "priority": "high",
                "icon": "fa-users",
                "title": f"{waitlist_count} users waiting for systems",
                "description": (
                    "There are users on the waitlist. Consider reviewing "
                    "high-utilization systems or extending operating hours."
                ),
                "action_url": f"/stream/{stream}/waitlist/",
                "action_text": "View Waitlist",
            }
        )

    for su in system_utilization:
        if su["utilization_pct"] > 80:
            recommendations.append(
                {
                    "priority": "high",
                    "icon": "fa-exclamation-triangle",
                    "title": f"High demand for {su['system'].name}",
                    "description": (
                        f"This system has {su['utilization_pct']:.0f}% utilization. "
                        "Consider adding more capacity or scheduling maintenance during off-peak hours."
                    ),
                    "action_url": "#",
                    "action_text": "View Schedule",
                }
            )

    if not recommendations:
        recommendations.append(
            {
                "priority": "low",
                "icon": "fa-check-circle",
                "title": "All systems operating normally",
                "description": "Utilization is balanced across all systems. No immediate action required.",
                "action_url": "#",
                "action_text": "View Report",
            }
        )

    trend_labels = []
    trend_data = []
    for day_data in daily_trend:
        trend_labels.append(day_data["day"].strftime("%b %d"))
        daily_util = min((day_data["count"] / max(total_systems, 1)) * 100, 100)
        trend_data.append(round(daily_util, 1))

    if not trend_labels:
        for i in range(7):
            day = today - timedelta(days=6 - i)
            trend_labels.append(day.strftime("%b %d"))
            trend_data.append(0)

    available_count = systems.filter(status="available").count() if hasattr(systems.first(), "status") else 0
    reserved_count = (
        SystemAllocation.objects.filter(stream=stream_obj, start_date__lte=today, end_date__gte=today)
        .values("system_type")
        .distinct()
        .count()
    )
    maintenance_count = total_systems - available_count - reserved_count
    maintenance_count = max(maintenance_count, 0)
    status_data = [max(available_count, total_systems - reserved_count), reserved_count, maintenance_count]

    systems_data = []
    for su in system_utilization:
        system = su["system"]
        last_alloc = (
            SystemAllocation.objects.filter(stream=stream_obj, system_type=system.name).order_by("-start_date").first()
        )

        systems_data.append(
            {
                "name": system.name,
                "ip_address": getattr(system, "ip_address", None),
                "project_name": getattr(system, "project_name", None)
                or (last_alloc.project_name if last_alloc and hasattr(last_alloc, "project_name") else None),
                "status": getattr(system, "status", "available"),
                "utilization": round(su["utilization_pct"], 0),
                "reservation_count": su["allocations"],
                "hours_used": round(su["allocations"] * 2, 1),  # Estimate hours
                "last_activity": last_alloc.start_date if last_alloc else None,
            }
        )

    start_date = request.GET.get("start_date", last_30_days)
    end_date = request.GET.get("end_date", today)

    context = {
        "stream": stream,
        "selected_stream": stream,
        "systems": systems,
        "total_allocations": total_allocations,
        "allocations_by_system": list(allocations_by_system),
        "daily_trend": list(daily_trend),
        "system_utilization": system_utilization,
        "upcoming_reservations": upcoming_reservations,
        "waitlist_count": waitlist_count,
        "peak_hours": peak_hours,
        "last_30_days": last_30_days,
        "today": today,
        "metrics": metrics,
        "recommendations": recommendations,
        "trend_labels": trend_labels,
        "trend_data": trend_data,
        "status_data": status_data,
        "systems_data": systems_data,
        "start_date": start_date,
        "end_date": end_date,
    }
    return render(request, "products/utilization_dashboard.html", context)


@login_required
def conflicts_list(request, stream=None):
    """List all reservation conflicts."""
    stream_obj = get_stream_or_404(stream)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        messages.error(request, error_message)
        return redirect("dashboard")

    status_filter = request.GET.get("status", "pending")

    conflicts = ReservationConflict.objects.filter(stream=stream_obj)

    if status_filter:
        conflicts = conflicts.filter(resolution_status=status_filter)

    context = {
        "conflicts": conflicts.select_related("system", "primary_allocation", "conflicting_allocation"),
        "stream": stream,
        "selected_stream": stream,
        "status_filter": status_filter,
        "resolution_statuses": ReservationConflict.RESOLUTION_STATUS,
    }
    return render(request, "products/conflicts_list.html", context)


@login_required
@require_POST
def conflict_resolve(request, stream=None, pk=None):
    """Resolve a conflict."""
    stream_obj = get_stream_or_404(stream)
    conflict = get_object_or_404(ReservationConflict, pk=pk, stream=stream_obj)

    if not can_manage_system_allocation(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    resolution_notes = request.POST.get("resolution_notes", "")

    conflict.resolution_status = "resolved"
    conflict.resolution_notes = resolution_notes
    conflict.resolved_by = request.user
    conflict.resolved_at = timezone.now()
    conflict.save()

    return JsonResponse({"success": True, "message": "Conflict resolved successfully!"})


# =============================================================================
# CALIBRATION & COMPLIANCE TRACKING VIEWS
# =============================================================================
