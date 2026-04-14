"""Products app - Add, Delete, Update, and Reset System views."""

# pylint: disable=broad-exception-caught,no-else-return,unused-variable

from ._helpers import (
    AuditLog,
    JsonResponse,
    Participant,
    System,
    SystemMetrics,
    SystemStatusHistory,
    User,
    datetime,
    get_default_stream_name,
    get_stream_or_404,
    is_admin,
    logger,
    login_required,
    require_POST,
    timedelta,
    timezone,
    user_passes_test,
)
from ..approval_triggers import check_approval_required

__all__ = [
    "add_system",
    "delete_system",
    "update_system",
    "reset_system_utilization",
]


@login_required
@require_POST
def add_system(request, stream=None):
    """Add system."""
    try:
        name = request.POST.get("name", "").strip()
        if not name:
            logger.debug("System name missing in add_system")
            return JsonResponse({"success": False, "error": "System name required."}, status=400)

        if not stream or stream.strip() == "":
            stream = get_default_stream_name(request)

        stream_obj = get_stream_or_404(stream, request=request)

        if System.objects.filter(name=name, stream=stream_obj).exists():
            return JsonResponse({"success": False, "error": "System already exists."}, status=409)
        system = System.objects.create(name=name, stream=stream_obj)
        AuditLog.log(
            "create",
            f"Created new system: {system.name}",
            user=request.user,
            request=request,
            obj=system,
            module="systems",
            severity="info",
            stream=stream_obj,
        )
        return JsonResponse(
            {
                "success": True,
                "system_id": system.id,
                "name": system.name,
                "status": system.status,
                "description": system.description,
            }
        )
    except Exception:
        logger.exception("System operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)


@login_required
@user_passes_test(is_admin)
@require_POST
def delete_system(request, stream=None):
    """Delete system."""
    system_id = request.POST.get("id")
    if not system_id:
        return JsonResponse({"success": False, "error": "System ID required."}, status=400)

    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    stream_obj = get_stream_or_404(stream, request=request)

    try:
        system = System.objects.get(id=system_id, stream=stream_obj)
        AuditLog.log(
            "delete",
            f"Deleted system: {system.name}",
            user=request.user,
            request=request,
            obj=system,
            module="systems",
            severity="warning",
            stream=stream_obj,
        )
        system.delete()
        return JsonResponse({"success": True})
    except System.DoesNotExist:
        return JsonResponse({"success": False, "error": "System not found."}, status=404)


@login_required
@user_passes_test(is_admin)
@require_POST
def update_system(request, stream=None):  # noqa: C901, CCR001
    """Update system."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-statements
    system_id = request.POST.get("id")
    status = request.POST.get("status")
    description = request.POST.get("description", "").strip()
    participant_id = request.POST.get("participant_id")
    status_date = request.POST.get("status_date", "")  # Get the date when status changed
    assignee = None

    if not system_id or not status:
        return JsonResponse({"success": False, "error": "Missing system id or status."}, status=400)

    try:
        system_id_int = int(system_id)
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "error": "Invalid system id."}, status=400)

    stream_obj = get_stream_or_404(stream, request=request)

    try:
        system = System.objects.get(id=system_id_int, stream=stream_obj)
    except System.DoesNotExist:
        return JsonResponse({"success": False, "error": "System not found."}, status=404)

    if participant_id:
        if participant_id.startswith("user_"):
            try:
                user_id = int(participant_id.split("_")[1])
                user_obj = User.objects.get(id=user_id)
                assignee = f"{user_obj.username} ({user_obj.email})"
            except Exception:
                assignee = None
        elif participant_id.startswith("participant_"):
            try:
                part_id = int(participant_id.split("_")[1])
                participant = Participant.objects.get(id=part_id)
                assignee = f"{participant.name} ({participant.email})"
            except Exception:
                assignee = None
        else:
            # fallback: treat as participant id (legacy)
            try:
                participant = Participant.objects.get(id=participant_id)
                assignee = f"{participant.name} ({participant.email})"
            except Exception:
                assignee = None

    old_system_status = system.status

    # ── Pre-action enforcement: block system removal if approval required ──
    _approval_block = None
    if old_system_status != status and status == "Removed":
        _approval_block = check_approval_required(
            "system_removed",
            stream_obj.business_unit,
            request.user,
            entity_obj=system,
            stream=stream_obj,
            title=f"System '{system.name}' \u2192 Removed / Dismantled",
            description=f"System {system.name} status change from {old_system_status} to Removed by {request.user.username}",
            intended_changes={
                "action_type": "status_change",
                "model_label": "products.System",
                "pk": system.pk,
                "changes": {"status": "Removed"},
                "revert": {"status": old_system_status},
                "metadata": {"entity_name": system.name},
            },
        )

    system.status = old_system_status if _approval_block else status
    system.description = description
    system.save()

    if _approval_block:
        return JsonResponse({
            "success": False,
            "warning": f"Removing system '{system.name}' requires approval. Request #{_approval_block.id} submitted.",
            "approval_required": True,
            "approval_id": _approval_block.id,
        }, status=202)

    history_updated_at = None
    if status_date:
        try:
            # Parse the date string (YYYY-MM-DD format from HTML date input)
            history_date = datetime.strptime(status_date, "%Y-%m-%d")
            view_date = history_date.date()

            today = timezone.now().date()

            if view_date == today:
                # If updating today, always use current time for proper ordering
                history_updated_at = timezone.now()
            else:
                existing_records = SystemStatusHistory.objects.filter(
                    system=system, updated_at__date=view_date
                ).order_by("-updated_at")

                if existing_records.exists():
                    # Get the latest timestamp on that date and add 1 minute
                    latest_time = existing_records.first().updated_at
                    history_updated_at = latest_time + timedelta(minutes=1)
                else:
                    # No existing records on this date, use noon as the timestamp
                    history_updated_at = timezone.make_aware(
                        datetime.combine(view_date, datetime.min.time().replace(hour=12))
                    )
        except (ValueError, TypeError):
            history_updated_at = timezone.now()
    else:
        history_updated_at = timezone.now()

    _history_record = SystemStatusHistory.objects.create(  # noqa: F841
        system=system,
        status=status,
        description=description,
        assignee=assignee,
        updated_by=request.user.username,
        updated_at=history_updated_at,
    )

    AuditLog.log(
        "update",
        f"Updated system: {system.name}",
        user=request.user,
        request=request,
        obj=system,
        module="systems",
        severity="info",
        stream=stream_obj,
    )

    return JsonResponse({"success": True})


@login_required
@user_passes_test(is_admin)
@require_POST
def reset_system_utilization(request, stream=None):
    """Reset utilization percentage for one or all systems in a stream."""
    try:
        system_id = request.POST.get("system_id")
        reset_all = request.POST.get("reset_all") == "true"

        if not stream or stream.strip() == "":
            stream = get_default_stream_name(request)

        stream_obj = get_stream_or_404(stream, request=request)

        if reset_all:
            systems = System.objects.filter(stream=stream_obj)
            count = systems.update(utilization_percentage=0.0)

            for system in systems:
                metrics, _created = SystemMetrics.objects.get_or_create(system=system)
                metrics.usage_hours = 0.0
                metrics.total_allocations = 0
                metrics.last_allocation_date = None
                metrics.average_session_duration = None
                metrics.uptime_percentage = 100.0
                metrics.save()
            AuditLog.log(
                "update",
                f"Reset utilization for all {count} systems in {stream} stream",
                user=request.user,
                request=request,
                module="systems",
                severity="warning",
                stream=stream_obj,
            )
            return JsonResponse(
                {"success": True, "message": f"Reset utilization for {count} systems in {stream} stream."}
            )

        elif system_id:
            system = System.objects.get(id=system_id, stream=stream_obj)
            system.utilization_percentage = 0.0
            system.save(update_fields=["utilization_percentage"])

            metrics, created = SystemMetrics.objects.get_or_create(system=system)
            metrics.usage_hours = 0.0
            metrics.total_allocations = 0
            metrics.last_allocation_date = None
            metrics.average_session_duration = None
            metrics.uptime_percentage = 100.0
            metrics.save()

            AuditLog.log(
                "update",
                f'Reset utilization for system "{system.name}"',
                user=request.user,
                request=request,
                obj=system,
                module="systems",
                severity="warning",
                stream=stream_obj,
            )
            return JsonResponse(
                {"success": True, "message": f'Reset utilization for system "{system.name}" is successful.'}
            )

        else:
            return JsonResponse(
                {"success": False, "error": "Either system_id or reset_all parameter is required."}, status=400
            )

    except System.DoesNotExist:
        return JsonResponse({"success": False, "error": "System not found."}, status=404)
    except Exception:
        logger.exception("System operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)
