"""Products app - System Downtime, Tickets, Build Servers, Floor and OS Management views."""

# pylint: disable=too-many-lines,broad-exception-caught,inconsistent-return-statements
# pylint: disable=import-error,relative-beyond-top-level

from ..models import SystemTicket, SystemTicketComment
from ..approval_triggers import fire_approval_trigger, check_approval_required
from ._helpers import (
    AuditLog,
    JsonResponse,
    Notification,
    Q,
    System,
    SystemDowntime,
    User,
    can_manage_system_allocation,
    can_view_analytics,
    datetime,
    get_current_bu,
    get_object_or_404,
    get_stream_or_404,
    json,
    logger,
    login_required,
    require_GET,
    require_http_methods,
    require_POST,
    timedelta,
    timezone,
)

__all__ = [
    "system_downtime_events",
    "system_downtime_event_detail",
    "system_downtime_metrics",
    "resolve_downtime",
    "system_tickets_api",
    "system_ticket_action",
]


@login_required
@require_http_methods(["GET", "POST"])
def system_downtime_events(  # noqa: C901, CCR001
    request,
    stream=None,
    system_id=None,
):
    """Handle downtime events - GET to retrieve, POST to create."""
    # pylint: disable=too-many-locals,too-many-return-statements,too-many-branches
    # pylint: disable=too-many-statements,inconsistent-return-statements,too-complex
    stream_obj = get_stream_or_404(stream, request=request)

    if not can_manage_system_allocation(request.user):
        return JsonResponse({"error": "Permission denied"}, status=403)

    if request.method == "GET":
        if system_id:
            system = get_object_or_404(System, id=system_id, stream=stream_obj)
            downtimes = SystemDowntime.objects.filter(system=system)
        else:
            downtimes = SystemDowntime.objects.filter(stream=stream_obj)

        status_filter = request.GET.get("status")
        if status_filter:
            downtimes = downtimes.filter(status=status_filter)

        try:
            limit = int(request.GET.get("limit", 50))
        except (ValueError, TypeError):
            limit = 50
        downtimes = downtimes.order_by("-start_time")[:limit]

        downtime_data = []
        for downtime in downtimes:
            downtime_data.append(
                {
                    "id": downtime.id,
                    "system_id": downtime.system.id,
                    "system_name": downtime.system.name,
                    "title": downtime.title,
                    "description": downtime.description,
                    "downtime_type": downtime.downtime_type,
                    "downtime_type_display": downtime.get_downtime_type_display(),
                    "impact_level": downtime.impact_level,
                    "impact_level_display": downtime.get_impact_level_display(),
                    "status": downtime.status,
                    "status_display": downtime.get_status_display(),
                    "start_time": downtime.start_time.isoformat(),
                    "end_time": downtime.end_time.isoformat() if downtime.end_time else None,
                    "duration_hours": round(downtime.duration_hours, 2),
                    "is_ongoing": downtime.is_ongoing,
                    "reported_by": downtime.reported_by.username if downtime.reported_by else None,
                    "assigned_to": downtime.assigned_to.username if downtime.assigned_to else None,
                    "resolved_by": downtime.resolved_by.username if downtime.resolved_by else None,
                    "root_cause": downtime.root_cause,
                    "resolution_steps": downtime.resolution_steps,
                    "external_ticket_id": downtime.external_ticket_id,
                    "created_at": downtime.created_at.isoformat(),
                    "updated_at": downtime.updated_at.isoformat(),
                }
            )

        return JsonResponse({"downtimes": downtime_data})

    if request.method == "POST":
        try:
            data = json.loads(request.body)

            system_id = data.get("system_id")
            if not system_id:
                return JsonResponse({"error": "system_id is required"}, status=400)

            system = get_object_or_404(System, id=system_id, stream=stream_obj)

            start_time_str = data.get("start_time")
            if not start_time_str:
                start_time = timezone.now()
            else:
                try:
                    start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                    if timezone.is_naive(start_time):
                        start_time = timezone.make_aware(start_time)
                except ValueError:
                    return JsonResponse({"error": "Invalid start_time format"}, status=400)

            end_time = None
            if data.get("end_time"):
                try:
                    end_time = datetime.fromisoformat(data["end_time"].replace("Z", "+00:00"))
                    if timezone.is_naive(end_time):
                        end_time = timezone.make_aware(end_time)
                except ValueError:
                    return JsonResponse({"error": "Invalid end_time format"}, status=400)

            downtime = SystemDowntime.objects.create(
                system=system,
                stream=stream_obj,
                title=data.get("title", "System Downtime"),
                description=data.get("description", ""),
                downtime_type=data.get("downtime_type", "other"),
                impact_level=data.get("impact_level", "medium"),
                status=data.get("status", "ongoing"),
                start_time=start_time,
                end_time=end_time,
                root_cause=data.get("root_cause", ""),
                resolution_steps=data.get("resolution_steps", ""),
                external_ticket_id=data.get("external_ticket_id", ""),
                reported_by=request.user,
            )

            assigned_to_id = data.get("assigned_to_id")
            if assigned_to_id:
                try:
                    assigned_user = User.objects.get(id=assigned_to_id)
                    downtime.assigned_to = assigned_user
                    downtime.save()
                except User.DoesNotExist:
                    pass

            AuditLog.log(
                action="create",
                title=f"Created downtime event: {downtime.title} for {system.name}",
                user=request.user,
                request=request,
                obj=downtime,
                module="downtime",
                severity="warning",
                stream=stream_obj,
            )
            bu = get_current_bu(request)
            Notification.notify_admins(
                bu, f"Downtime reported for '{system.name}': {downtime.title}.", "downtime", exclude_user=request.user
            )
            if hasattr(downtime, "assigned_to") and downtime.assigned_to and downtime.assigned_to != request.user:
                Notification.notify(
                    downtime.assigned_to,
                    f"Downtime event '{downtime.title}' for system '{system.name}' has been assigned to you.",
                    "downtime",
                )

            # ── Auto-trigger approval for system downtime ──
            fire_approval_trigger(
                "system_downtime_created",
                bu,
                request.user,
                entity_obj=downtime,
                stream=stream_obj,
                title=f"System downtime: {system.name} — {downtime.title}",
                description=f"Downtime event '{downtime.title}' reported for system '{system.name}' | Impact: {downtime.impact_level} | Type: {downtime.downtime_type}",
            )

            return JsonResponse(
                {"success": True, "downtime_id": downtime.id, "message": "Downtime event created successfully"}
            )

        except Exception:
            logger.exception("Operation failed")
            return JsonResponse({"error": "An unexpected error occurred"}, status=500)


@login_required
@require_http_methods(["PUT", "DELETE"])
def system_downtime_event_detail(  # noqa: C901, CCR001
    request,
    stream=None,
    downtime_id=None,
):
    """Handle individual downtime events - PUT to update, DELETE to remove."""
    # pylint: disable=too-many-return-statements,too-many-branches,too-complex
    # pylint: disable=too-many-statements,too-many-nested-blocks,inconsistent-return-statements
    stream_obj = get_stream_or_404(stream, request=request)

    if not can_manage_system_allocation(request.user):
        return JsonResponse({"error": "Permission denied"}, status=403)

    downtime = get_object_or_404(SystemDowntime, id=downtime_id, stream=stream_obj)

    if request.method == "PUT":
        try:
            data = json.loads(request.body)

            if "title" in data:
                downtime.title = data["title"]
            if "description" in data:
                downtime.description = data["description"]
            if "downtime_type" in data:
                downtime.downtime_type = data["downtime_type"]
            if "impact_level" in data:
                downtime.impact_level = data["impact_level"]
            if "status" in data:
                _old_downtime_status = downtime.status
                downtime.status = data["status"]
            if "root_cause" in data:
                downtime.root_cause = data["root_cause"]
            if "resolution_steps" in data:
                downtime.resolution_steps = data["resolution_steps"]
            if "external_ticket_id" in data:
                downtime.external_ticket_id = data["external_ticket_id"]

            if "end_time" in data:
                if data["end_time"]:
                    try:
                        end_time = datetime.fromisoformat(data["end_time"].replace("Z", "+00:00"))
                        if timezone.is_naive(end_time):
                            end_time = timezone.make_aware(end_time)
                        downtime.end_time = end_time
                    except ValueError:
                        return JsonResponse({"error": "Invalid end_time format"}, status=400)
                else:
                    downtime.end_time = None

            if data.get("resolve") and not downtime.end_time:
                downtime.resolve(resolved_by_user=request.user, resolution_notes=data.get("resolution_notes"))

            if "assigned_to_id" in data:
                if data["assigned_to_id"]:
                    try:
                        assigned_user = User.objects.get(id=data["assigned_to_id"])
                        downtime.assigned_to = assigned_user
                    except User.DoesNotExist:
                        return JsonResponse({"error": "Assigned user not found"}, status=400)
                else:
                    downtime.assigned_to = None

            downtime.save()

            # ── Fire audit trigger for escalation ──
            if "status" in data and data["status"] == "escalated" and _old_downtime_status != "escalated":
                fire_approval_trigger(
                    "system_downtime_escalated",
                    stream_obj.business_unit,
                    request.user,
                    entity_obj=downtime,
                    stream=stream_obj,
                    title=f"Downtime '{downtime.title}' escalated",
                    description=f"System downtime event '{downtime.title}' escalated from {_old_downtime_status} to escalated",
                )

            return JsonResponse({"success": True, "message": "Downtime event updated successfully"})

        except Exception:
            logger.exception("Operation failed")
            return JsonResponse({"error": "An unexpected error occurred"}, status=500)

    if request.method == "DELETE":
        try:
            downtime.delete()
            return JsonResponse({"success": True, "message": "Downtime event deleted successfully"})

        except Exception:
            logger.exception("Operation failed")
            return JsonResponse({"error": "An unexpected error occurred"}, status=500)


@login_required
@require_GET
def system_downtime_metrics(  # pylint: disable=too-many-locals
    request,
    stream=None,
    system_id=None,
):  # noqa: CCR001
    """Get downtime metrics for a system or all systems in a stream."""
    stream_obj = get_stream_or_404(stream, request=request)

    if not can_view_analytics(request.user):
        return JsonResponse({"error": "Permission denied"}, status=403)

    try:
        days = int(request.GET.get("days", 30))
    except (ValueError, TypeError):
        days = 30
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)

    if system_id:
        system = get_object_or_404(System, id=system_id, stream=stream_obj)
        metrics = system.get_downtime_metrics(days)

        recent_events = SystemDowntime.objects.filter(system=system, start_time__gte=start_date).order_by(
            "-start_time"
        )[:10]

        events_data = []
        for event in recent_events:
            events_data.append(
                {
                    "id": event.id,
                    "title": event.title,
                    "downtime_type": event.get_downtime_type_display(),
                    "impact_level": event.get_impact_level_display(),
                    "status": event.get_status_display(),
                    "start_time": event.start_time.isoformat(),
                    "duration_hours": round(event.duration_hours, 2),
                    "is_ongoing": event.is_ongoing,
                }
            )

        return JsonResponse(
            {
                "system_id": system.id,
                "system_name": system.name,
                "period_days": days,
                "metrics": {
                    "availability_percentage": round(metrics.availability_percentage, 2),
                    "total_downtime_hours": round(metrics.total_downtime_hours, 2),
                    "total_incidents": metrics.total_incidents,
                    "planned_downtime_hours": round(metrics.planned_downtime_hours, 2),
                    "unplanned_downtime_hours": round(metrics.unplanned_downtime_hours, 2),
                    "mean_time_to_repair_hours": (
                        round(metrics.mean_time_to_repair_hours, 2) if metrics.mean_time_to_repair_hours else None
                    ),
                    "mean_time_between_failures_hours": (
                        round(metrics.mean_time_between_failures_hours, 2)
                        if metrics.mean_time_between_failures_hours
                        else None
                    ),
                    "most_common_downtime_type": metrics.most_common_downtime_type,
                    "most_common_impact_level": metrics.most_common_impact_level,
                },
                "recent_events": events_data,
            }
        )

    systems = System.objects.filter(stream=stream_obj)
    systems_metrics = []

    for system in systems:
        metrics = system.get_downtime_metrics(days)
        systems_metrics.append(
            {
                "system_id": system.id,
                "system_name": system.name,
                "availability_percentage": round(metrics.availability_percentage, 2),
                "total_downtime_hours": round(metrics.total_downtime_hours, 2),
                "total_incidents": metrics.total_incidents,
                "is_currently_down": system.is_currently_down(),
                "current_status": system.status,
            }
        )

    total_systems = len(systems_metrics)
    total_incidents = sum(s["total_incidents"] for s in systems_metrics)
    avg_availability = (
        sum(s["availability_percentage"] for s in systems_metrics) / total_systems if total_systems > 0 else 100
    )
    systems_down = sum(1 for s in systems_metrics if s["is_currently_down"])

    return JsonResponse(
        {
            "stream": stream,
            "period_days": days,
            "summary": {
                "total_systems": total_systems,
                "systems_currently_down": systems_down,
                "average_availability": round(avg_availability, 2),
                "total_incidents": total_incidents,
            },
            "systems": systems_metrics,
        }
    )


@login_required
@require_POST
def resolve_downtime(request, stream=None, downtime_id=None):
    """Resolve a specific downtime event."""
    stream_obj = get_stream_or_404(stream, request=request)

    if not can_manage_system_allocation(request.user):
        return JsonResponse({"error": "Permission denied"}, status=403)

    downtime = get_object_or_404(SystemDowntime, id=downtime_id, stream=stream_obj)

    try:
        data = json.loads(request.body)
        resolution_notes = data.get("resolution_notes", "")

        downtime.resolve(resolved_by_user=request.user, resolution_notes=resolution_notes)

        AuditLog.log(
            action="update",
            title=f"Resolved downtime event: {downtime.title}",
            user=request.user,
            request=request,
            obj=downtime,
            module="downtime",
            severity="info",
            stream=stream_obj,
        )
        return JsonResponse(
            {
                "success": True,
                "message": "Downtime resolved successfully",
                "end_time": downtime.end_time.isoformat(),
                "duration_hours": round(downtime.duration_hours, 2),
            }
        )

    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"error": "An unexpected error occurred"}, status=500)


# =========================================================================
# SERVER-SIDE TICKET TRACKING API
# =========================================================================


@login_required
def system_tickets_api(  # noqa: C901, CCR001
    request,
    stream=None,
):
    """List / create system tickets (GET = list, POST = create)."""
    # pylint: disable=too-many-locals,too-complex
    stream_obj = get_stream_or_404(stream, request=request)

    if request.method == "GET":
        qs = SystemTicket.objects.filter(stream=stream_obj).select_related("system", "created_by")
        status_f = request.GET.get("status")
        impact_f = request.GET.get("impact")
        search = request.GET.get("q", "").strip()
        if status_f:
            qs = qs.filter(status=status_f)
        if impact_f:
            qs = qs.filter(impact=impact_f)
        if search:
            qs = qs.filter(
                Q(ticket_id__icontains=search) | Q(title__icontains=search) | Q(description__icontains=search)
            )
        tickets = []
        for tkt in qs[:200]:
            tickets.append(
                {
                    "id": tkt.id,
                    "ticket_id": tkt.ticket_id,
                    "system_id": tkt.system_id,
                    "system_name": tkt.system.name,
                    "title": tkt.title,
                    "description": tkt.description,
                    "status": tkt.status,
                    "impact": tkt.impact,
                    "downtime_type": tkt.downtime_type,
                    "created_by": tkt.created_by.username if tkt.created_by else "",
                    "resolution": tkt.resolution or "",
                    "resolved_at": tkt.resolved_at.isoformat() if tkt.resolved_at else None,
                    "sla_due": tkt.sla_due.isoformat() if tkt.sla_due else None,
                    "is_sla_breached": tkt.is_sla_breached,
                    "created_at": tkt.created_at.isoformat(),
                    "updated_at": tkt.updated_at.isoformat(),
                    "comments": [
                        {
                            "id": c.id,
                            "text": c.text,
                            "author": c.author.username if c.author else "system",
                            "type": c.comment_type,
                            "created_at": c.created_at.isoformat(),
                        }
                        for c in tkt.comments.all()
                    ],
                }
            )
        # Analytics
        all_qs = SystemTicket.objects.filter(stream=stream_obj)
        open_count = all_qs.filter(status__in=["open", "in_progress"]).count()
        closed_count = all_qs.filter(status="closed").count()
        breached = sum(1 for t in all_qs.filter(status__in=["open", "in_progress"]) if t.is_sla_breached)
        critical_count = all_qs.filter(impact="critical", status__in=["open", "in_progress"]).count()
        resolved_tickets = all_qs.filter(status__in=["resolved", "closed"], resolved_at__isnull=False)
        avg_hours = 0
        if resolved_tickets.exists():
            total_h = sum(
                (t.resolved_at - t.created_at).total_seconds() / 3600 for t in resolved_tickets if t.resolved_at
            )
            avg_hours = round(total_h / resolved_tickets.count(), 1)
        return JsonResponse(
            {
                "success": True,
                "tickets": tickets,
                "analytics": {
                    "open": open_count,
                    "closed": closed_count,
                    "breached": breached,
                    "critical": critical_count,
                    "avg_resolution_hours": avg_hours,
                },
            }
        )

    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
        system_id = data.get("system_id")
        if not system_id:
            return JsonResponse({"success": False, "error": "system_id required"}, status=400)
        system = get_object_or_404(System, id=system_id, stream=stream_obj)
        ticket = SystemTicket.objects.create(
            ticket_id=data.get("ticket_id", ""),
            system=system,
            stream=stream_obj,
            title=data.get("title", "Untitled"),
            description=data.get("description", ""),
            impact=data.get("impact", "medium"),
            downtime_type=data.get("downtime_type", "other"),
            start_time=data.get("start_time"),
            created_by=request.user,
        )
        if not ticket.ticket_id:
            ticket.ticket_id = f"TKT-{ticket.pk:06d}"
            ticket.save(update_fields=["ticket_id"])
        SystemTicketComment.objects.create(
            ticket=ticket, author=request.user, text="Ticket created", comment_type="system"
        )
        return JsonResponse({"success": True, "ticket_id": ticket.ticket_id, "id": ticket.id})

    return JsonResponse({"error": "Method not allowed"}, status=405)


@login_required
@require_POST
def system_ticket_action(request, stream=None, ticket_id=None):
    """Resolve / close / reopen a ticket."""
    stream_obj = get_stream_or_404(stream, request=request)
    ticket = get_object_or_404(SystemTicket, id=ticket_id, stream=stream_obj)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = {}
    action = data.get("action", "")
    notes = data.get("notes", "")
    if action == "resolve":
        ticket.status = "resolved"
        ticket.resolution = notes or "Resolved"
        ticket.resolved_at = timezone.now()
        ticket.save()
        SystemTicketComment.objects.create(
            ticket=ticket, author=request.user, text=f"Ticket resolved: {notes}", comment_type="system"
        )
    elif action == "close":
        if ticket.status != "resolved":
            ticket.resolution = notes or "Closed"
            ticket.resolved_at = timezone.now()
        ticket.status = "closed"
        ticket.save()
        SystemTicketComment.objects.create(
            ticket=ticket, author=request.user, text=f"Ticket closed: {notes}", comment_type="system"
        )
    elif action == "reopen":
        ticket.status = "open"
        ticket.resolution = None
        ticket.resolved_at = None
        ticket.save()
        SystemTicketComment.objects.create(
            ticket=ticket, author=request.user, text=f"Ticket reopened: {notes}", comment_type="system"
        )
    elif action == "comment":
        SystemTicketComment.objects.create(ticket=ticket, author=request.user, text=notes, comment_type="user")
        ticket.save(update_fields=["updated_at"])
    else:
        return JsonResponse({"success": False, "error": "Unknown action"}, status=400)
    return JsonResponse({"success": True, "status": ticket.status})
