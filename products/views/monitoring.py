"""Products app - Stream History, System Metrics, and Personal Trackboard views."""

# pylint: disable=broad-exception-caught,consider-using-generator,no-else-return

from ._helpers import (
    Count,
    JsonResponse,
    PersonalTask,
    StreamDeletionHistory,
    System,
    SystemAllocation,
    SystemStatusHistory,
    get_object_or_404,
    get_stream_or_404,
    json,
    logger,
    login_required,
    render,
    require_GET,
    timedelta,
    timezone,
)

__all__ = [
    "stream_deletion_history",
    "system_status_history",
    "get_system_metrics",
    "personal_trackboard",
]


@login_required
def stream_deletion_history(request):
    """Stream deletion history."""
    history = StreamDeletionHistory.objects.select_related("deleted_by").order_by("-deleted_at")[:100]
    return render(request, "products/stream_deletion_history.html", {"history": history})


@login_required
def system_status_history(request, stream, system_id):
    """System status history."""
    # Resolve stream name to Stream object (404 if not found). Default to 'HIC' when missing.
    stream_obj = get_stream_or_404(stream, request=request)

    system = get_object_or_404(System, id=system_id, stream=stream_obj)
    history = SystemStatusHistory.objects.filter(system=system).order_by("-updated_at")
    return render(
        request,
        "products/system_status_history.html",
        {
            "system": system,
            "history": history,
            "stream": stream,
            "selected_stream": stream,
        },
    )


@login_required
@require_GET
def get_system_metrics(request, stream=None):
    """Get system metrics."""
    # pylint: disable=too-many-locals
    try:
        stream_obj = get_stream_or_404(stream, request=request)

        total_systems = System.objects.filter(stream=stream_obj).count()
        active_systems = System.objects.filter(stream=stream_obj, status="Active").count()
        blocked_systems = SystemAllocation.objects.filter(stream=stream_obj, end_date__gt=timezone.now()).count()

        systems = System.objects.filter(stream=stream_obj)
        total_utilization = sum([s.utilization_percentage for s in systems if hasattr(s, "utilization_percentage")])
        avg_utilization = round(total_utilization / total_systems if total_systems > 0 else 0)

        end_date = timezone.now()
        start_date = end_date - timedelta(days=7)
        daily_usage = (
            SystemAllocation.objects.filter(stream=stream_obj, start_date__gte=start_date, end_date__lte=end_date)
            .values("start_date__date")
            .annotate(count=Count("id"))
        )

        usage_trends = []
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.date().strftime("%Y-%m-%d")
            count = 0
            for usage in daily_usage:
                if usage["start_date__date"].strftime("%Y-%m-%d") == date_str:
                    count = usage["count"]
                    break
            usage_trends.append({"date": date_str, "value": count})
            current_date += timedelta(days=1)

        most_active = System.objects.filter(stream=stream_obj).order_by("-utilization_percentage")[:5]
        most_active_data = [
            {
                "name": system.name,
                "usage_hours": round(system.utilization_percentage * 24 / 100, 1),  # Convert percentage to hours
            }
            for system in most_active
        ]

        return JsonResponse(
            {
                "success": True,
                "total_systems": total_systems,
                "active_systems": active_systems,
                "blocked_systems": blocked_systems,
                "utilization": avg_utilization,
                "usage_trends": usage_trends,
                "most_active": most_active_data,
            }
        )
    except Exception:
        logger.exception("Metrics API failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@login_required
def personal_trackboard(request):  # noqa: C901, CCR001
    """Personal trackboard."""
    # pylint: disable=too-complex,too-many-return-statements
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            title = request.POST.get("title", "").strip()
            if title:
                PersonalTask.objects.create(user=request.user, title=title)
                return JsonResponse({"success": True})
            return JsonResponse({"success": False, "error": "Title required"})
        elif action == "update":
            task_id = request.POST.get("task_id")
            status = request.POST.get("status")
            try:
                task = PersonalTask.objects.get(id=task_id, user=request.user)
                if status in dict(PersonalTask.STATUS_CHOICES):
                    task.status = status
                    task.save()
                    return JsonResponse({"success": True})
            except PersonalTask.DoesNotExist:
                pass
            return JsonResponse({"success": False, "error": "Task not found"})
        elif action == "delete":
            task_id = request.POST.get("task_id")
            try:
                task = PersonalTask.objects.get(id=task_id, user=request.user)
                task.delete()
                return JsonResponse({"success": True})
            except PersonalTask.DoesNotExist:
                return JsonResponse({"success": False, "error": "Task not found"})
    # GET: Render the page with user's tasks
    tasks = PersonalTask.objects.filter(user=request.user).order_by("created_at")

    user_context = {
        "username": request.user.username,
        "first_name": request.user.first_name,
        "last_name": request.user.last_name,
        "full_name": request.user.get_full_name() or request.user.username,
        "initials": (request.user.first_name[:1] if request.user.first_name else request.user.username[:1]).upper()
        + (request.user.last_name[:1] if request.user.last_name else "").upper(),
        "is_admin": request.user.is_superuser,
    }

    # Try to get custom user profile for role information
    try:
        custom_profile = request.user.custom_profile
        user_context["role"] = custom_profile.get_roles_display() if custom_profile.user_roles.exists() else ""
    except Exception:
        user_context["role"] = ""

    tasks_data = [
        {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        }
        for task in tasks
    ]

    context = {
        "tasks": tasks,
        "user_context": user_context,
        "tasks_json": json.dumps(tasks_data),
    }

    return render(request, "products/personal_trackboard.html", context)
