"""Products app - Support Tickets and Live Support views."""

# pylint: disable=import-error,relative-beyond-top-level

from ..models import SupportTicketReply
from ._helpers import (
    JsonResponse,
    LiveSupportMessage,
    LiveSupportSession,
    Notification,
    SupportTicket,
    get_current_bu,
    get_default_stream_name,
    get_object_or_404,
    is_app_admin,
    json,
    login_required,
    redirect,
    render,
    timezone,
)

__all__ = [
    "support_ticket_list",
    "support_ticket_create",
    "support_ticket_detail",
    "live_support_start",
    "live_support_messages",
    "live_support_close",
    "live_support_admin_queue",
    "live_support_admin_page",
]


@login_required
def support_ticket_list(request):
    """List all tickets — users see their own; app_admins see everything in the BU."""
    bu = get_current_bu(request)
    is_admin = is_app_admin(request.user)

    if is_admin:
        base_qs = SupportTicket.objects.filter(business_unit=bu) if bu else SupportTicket.objects.all()
    else:
        base_qs = SupportTicket.objects.filter(created_by=request.user)
        if bu:
            base_qs = base_qs.filter(business_unit=bu)

    # Stats (unfiltered)
    stats = {
        "total": base_qs.count(),
        "open": base_qs.filter(status="open").count(),
        "in_progress": base_qs.filter(status="in_progress").count(),
        "resolved": base_qs.filter(status="resolved").count(),
        "closed": base_qs.filter(status="closed").count(),
    }

    # Filters
    tickets = base_qs
    status_filter = request.GET.get("status", "")
    category_filter = request.GET.get("category", "")
    if status_filter:
        tickets = tickets.filter(status=status_filter)
    if category_filter:
        tickets = tickets.filter(category=category_filter)

    tickets = tickets.select_related("created_by", "assigned_to", "business_unit").order_by("-created_at")

    stream = get_default_stream_name(request)
    context = {
        "tickets": tickets,
        "is_admin": is_admin,
        "status_filter": status_filter,
        "category_filter": category_filter,
        "stats": stats,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/support_tickets.html", context)


@login_required
def support_ticket_create(request):
    """Create a new support ticket (AJAX POST)."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    bu = get_current_bu(request)
    data = json.loads(request.body) if request.content_type == "application/json" else request.POST

    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    category = data.get("category", "bug")
    priority = data.get("priority", "medium")

    if not title or not description:
        return JsonResponse({"error": "Title and description are required"}, status=400)

    ticket = SupportTicket.objects.create(
        title=title,
        description=description,
        category=category,
        priority=priority,
        created_by=request.user,
        business_unit=bu,
    )
    Notification.notify_admins(
        bu,
        f"New {ticket.get_category_display()} ticket: '{title}' — Priority: {ticket.get_priority_display()}.",
        "support",
        exclude_user=request.user,
    )
    return JsonResponse(
        {
            "id": ticket.id,
            "title": ticket.title,
            "status": ticket.status,
            "created_at": ticket.created_at.strftime("%Y-%m-%d %H:%M"),
        }
    )


@login_required
def support_ticket_detail(request, ticket_id):  # noqa: C901, CCR001
    """View ticket detail & conversation, or post a reply."""
    # pylint: disable=too-complex,too-many-branches,too-many-return-statements
    bu = get_current_bu(request)
    is_admin = is_app_admin(request.user)

    ticket = get_object_or_404(SupportTicket, pk=ticket_id)
    # Access: owner or admin
    if ticket.created_by != request.user and not is_admin:
        return JsonResponse({"error": "Access denied"}, status=403)

    if request.method == "GET" and request.headers.get("Accept") == "application/json":
        # AJAX: return ticket + replies as JSON
        replies = ticket.replies.select_related("user").all()
        return JsonResponse(
            {
                "ticket": {
                    "id": ticket.id,
                    "title": ticket.title,
                    "description": ticket.description,
                    "category": ticket.category,
                    "category_display": ticket.get_category_display(),
                    "priority": ticket.priority,
                    "priority_display": ticket.get_priority_display(),
                    "status": ticket.status,
                    "status_display": ticket.get_status_display(),
                    "created_by": ticket.created_by.username,
                    "assigned_to": ticket.assigned_to.username if ticket.assigned_to else None,
                    "created_at": ticket.created_at.strftime("%Y-%m-%d %H:%M"),
                    "updated_at": ticket.updated_at.strftime("%Y-%m-%d %H:%M"),
                },
                "replies": [
                    {
                        "id": r.id,
                        "user": r.user.username,
                        "message": r.message,
                        "is_admin_reply": r.is_admin_reply,
                        "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
                    }
                    for r in replies
                ],
            }
        )

    if request.method == "POST":
        data = json.loads(request.body) if request.content_type == "application/json" else request.POST
        action = data.get("action", "reply")

        if action == "reply":
            message = (data.get("message") or "").strip()
            if not message:
                return JsonResponse({"error": "Message required"}, status=400)
            reply = SupportTicketReply.objects.create(
                ticket=ticket,
                user=request.user,
                message=message,
                is_admin_reply=is_admin,
            )
            if is_admin and ticket.created_by != request.user:
                Notification.notify(ticket.created_by, f"Admin replied to your ticket '{ticket.title}'.", "support")
            elif not is_admin:
                Notification.notify_admins(
                    bu,
                    f"New reply on ticket '{ticket.title}' from {request.user.username}.",
                    "support",
                    exclude_user=request.user,
                )
            return JsonResponse(
                {
                    "id": reply.id,
                    "user": reply.user.username,
                    "message": reply.message,
                    "is_admin_reply": reply.is_admin_reply,
                    "created_at": reply.created_at.strftime("%Y-%m-%d %H:%M"),
                }
            )

        if action == "update_status" and is_admin:
            new_status = data.get("status", "")
            if new_status in dict(SupportTicket.STATUS_CHOICES):
                ticket.status = new_status
                if new_status == "resolved":
                    ticket.resolved_at = timezone.now()
                ticket.save()
                # Auto-add a system reply
                SupportTicketReply.objects.create(
                    ticket=ticket,
                    user=request.user,
                    message=f"Status changed to {ticket.get_status_display()}",
                    is_admin_reply=True,
                )
                if ticket.created_by != request.user:
                    Notification.notify(
                        ticket.created_by,
                        f"Your ticket '{ticket.title}' status changed to {ticket.get_status_display()}.",
                        "support",
                    )
                return JsonResponse({"status": ticket.status, "status_display": ticket.get_status_display()})
            return JsonResponse({"error": "Invalid status"}, status=400)

        if action == "assign" and is_admin:
            assignee_id = data.get("assignee_id")
            if assignee_id:
                ticket.assigned_to_id = assignee_id
                ticket.save()
                return JsonResponse({"assigned_to": ticket.assigned_to.username})
            return JsonResponse({"error": "Assignee required"}, status=400)

    # Full page render
    replies = ticket.replies.select_related("user").all()
    stream = get_default_stream_name(request)
    context = {
        "ticket": ticket,
        "replies": replies,
        "is_admin": is_admin,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/support_ticket_detail.html", context)


# =============================================================================
# LIVE SUPPORT CHAT
# =============================================================================


@login_required
def live_support_start(request):
    """Start a new live support session (user-facing)."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    bu = get_current_bu(request)
    data = json.loads(request.body) if request.content_type == "application/json" else request.POST
    subject = (data.get("subject") or "").strip() or "General Support"

    # Reuse existing waiting session if any
    existing = LiveSupportSession.objects.filter(
        user=request.user, status__in=["waiting", "active"], business_unit=bu
    ).first()
    if existing:
        return JsonResponse({"session_id": existing.id, "status": existing.status})

    session = LiveSupportSession.objects.create(
        user=request.user,
        business_unit=bu,
        subject=subject,
    )
    Notification.notify_admins(
        bu,
        f"New live support request from {request.user.username}: '{subject}'.",
        "live_support",
        exclude_user=request.user,
    )
    return JsonResponse({"session_id": session.id, "status": "waiting"})


@login_required
def live_support_messages(request, session_id):  # noqa: CCR001
    """GET messages for a session, POST to send a message."""
    session = get_object_or_404(LiveSupportSession, pk=session_id)

    # Access check: user or admin
    is_admin = is_app_admin(request.user)
    if session.user != request.user and not is_admin:
        return JsonResponse({"error": "Access denied"}, status=403)

    if request.method == "GET":
        after_id = int(request.GET.get("after", 0))
        msgs = session.messages.filter(id__gt=after_id).select_related("user").order_by("created_at")[:100]
        return JsonResponse(
            {
                "session_id": session.id,
                "status": session.status,
                "admin": session.admin.username if session.admin else None,
                "messages": [
                    {
                        "id": m.id,
                        "user": m.user.username,
                        "user_id": m.user.id,
                        "message": m.message,
                        "created_at": m.created_at.strftime("%H:%M"),
                    }
                    for m in msgs
                ],
            }
        )

    if request.method == "POST":
        data = json.loads(request.body) if request.content_type == "application/json" else request.POST
        text = (data.get("message") or "").strip()
        if not text:
            return JsonResponse({"error": "Message required"}, status=400)

        # If admin is first to reply, assign session
        if is_admin and session.status == "waiting":
            session.admin = request.user
            session.status = "active"
            session.save()

        msg = LiveSupportMessage.objects.create(
            session=session,
            user=request.user,
            message=text,
        )
        return JsonResponse(
            {
                "id": msg.id,
                "user": msg.user.username,
                "user_id": msg.user.id,
                "message": msg.message,
                "created_at": msg.created_at.strftime("%H:%M"),
                "session_status": session.status,
            }
        )

    return JsonResponse({"error": "Method not allowed"}, status=405)


@login_required
def live_support_close(request, session_id):
    """Close a live support session."""
    session = get_object_or_404(LiveSupportSession, pk=session_id)
    is_admin = is_app_admin(request.user)
    if session.user != request.user and not is_admin:
        return JsonResponse({"error": "Access denied"}, status=403)
    session.status = "closed"
    session.closed_at = timezone.now()
    session.save()
    return JsonResponse({"closed": True})


@login_required
def live_support_admin_queue(request):
    """Admin view: list waiting & active support sessions."""
    if not is_app_admin(request.user):
        return JsonResponse({"error": "Admin access required"}, status=403)

    bu = get_current_bu(request)
    sessions = (
        LiveSupportSession.objects.filter(status__in=["waiting", "active"])
        .select_related("user", "admin", "business_unit")
        .order_by("created_at")
    )
    if bu:
        sessions = sessions.filter(business_unit=bu)

    return JsonResponse(
        {
            "sessions": [
                {
                    "id": s.id,
                    "user": s.user.username,
                    "subject": s.subject,
                    "status": s.status,
                    "admin": s.admin.username if s.admin else None,
                    "created_at": s.created_at.strftime("%Y-%m-%d %H:%M"),
                    "bu": str(s.business_unit) if s.business_unit else "",
                }
                for s in sessions
            ],
        }
    )


@login_required
def live_support_admin_page(request):
    """Admin page to view & respond to live support sessions."""
    if not is_app_admin(request.user):
        return redirect("dashboard")

    stream = get_default_stream_name(request)
    context = {
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/live_support_admin.html", context)
