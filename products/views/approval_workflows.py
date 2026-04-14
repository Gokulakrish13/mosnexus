"""Products app — Approval Workflow views."""

# pylint: disable=invalid-name,too-many-lines,wrong-import-position

import json
from datetime import timedelta

from ._helpers import (
    ContentType,
    CustomUser,
    HttpResponse,
    JsonResponse,
    Notification,
    Q,
    Workbook,
    get_bu_streams,
    get_column_letter,
    get_current_bu,
    get_object_or_404,
    is_admin,
    is_super_admin,
    login_required,
    messages,
    redirect,
    render,
    require_POST,
    timezone,
    transaction,
)
from ..models import (
    DISCOVERABLE_ENTITY_TYPES,
    DISCOVERABLE_EVENT_TYPES,
    ApprovalAutoTrigger,
    ApprovalComment,
    ApprovalEntityType,
    ApprovalEventType,
    ApprovalRequest,
    ApprovalStepAction,
    ApprovalStepTemplate,
    ApprovalWorkflowTemplate,
    BusinessUnit,
    Stream,
    ensure_system_types,
)

__all__ = [
    "approval_dashboard",
    "approval_templates_api",
    "approval_template_detail_api",
    "approval_request_create",
    "approval_request_detail",
    "approval_request_action",
    "approval_request_comment",
    "approval_my_pending",
    "approval_analytics_api",
    "approval_triggers_api",
    "approval_trigger_detail_api",
    "approval_entity_types_api",
    "approval_event_types_api",
]


@login_required
def approval_dashboard(request):
    """Main Approval Workflows dashboard."""
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")

    # Auto-seed system entity/event types for this BU (idempotent)
    ensure_system_types(bu)

    custom_profile, _ = CustomUser.objects.get_or_create(user=request.user)
    user_roles = list(custom_profile.user_roles.values_list("role", flat=True))

    # Requests submitted by me
    my_requests = ApprovalRequest.objects.filter(
        requested_by=request.user, business_unit=bu
    ).select_related("template")

    # Requests pending my action
    pending_my_action = ApprovalRequest.objects.filter(
        business_unit=bu,
        status__in=["pending", "in_review"],
    ).filter(
        Q(step_actions__action="pending", step_actions__acted_by=request.user)
        | Q(
            step_actions__action="pending",
            template__steps__approver_role__in=user_roles,
            template__steps__order=models.F("current_step"),
        )
    ).distinct().select_related("template")

    # Stats
    stats = {
        "total": ApprovalRequest.objects.filter(business_unit=bu).count(),
        "pending": ApprovalRequest.objects.filter(business_unit=bu, status="pending").count(),
        "in_review": ApprovalRequest.objects.filter(business_unit=bu, status="in_review").count(),
        "approved": ApprovalRequest.objects.filter(business_unit=bu, status="approved").count(),
        "rejected": ApprovalRequest.objects.filter(business_unit=bu, status="rejected").count(),
        "my_submitted": my_requests.count(),
        "my_pending": pending_my_action.count(),
    }

    # Templates for creating new requests
    templates = ApprovalWorkflowTemplate.objects.filter(
        business_unit=bu, is_active=True
    ).prefetch_related("steps")

    # All requests for admin view
    all_requests = ApprovalRequest.objects.filter(
        business_unit=bu
    ).select_related("template", "requested_by").order_by("-created_at")[:50]

    return render(request, "products/approval_dashboard.html", {
        "stats": stats,
        "templates": templates,
        "my_requests": my_requests[:20],
        "pending_my_action": pending_my_action[:20],
        "all_requests": all_requests,
        "is_admin": is_admin(request.user),
        "is_super_admin": is_super_admin(request.user),
    })


@login_required
def approval_templates_api(request):
    """CRUD API for approval workflow templates (admin only)."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    if request.method == "GET":
        templates = ApprovalWorkflowTemplate.objects.filter(
            business_unit=bu
        ).prefetch_related("steps")
        data = []
        for t in templates:
            steps = list(t.steps.order_by("order").values(
                "id", "order", "name", "approver_type", "approver_role", "is_mandatory"
            ))
            data.append({
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "entity_type": t.entity_type,
                "entity_type_display": t.get_entity_type_display(),
                "is_active": t.is_active,
                "require_all_steps": t.require_all_steps,
                "auto_approve_timeout_hours": t.auto_approve_timeout_hours,
                "step_count": len(steps),
                "steps": steps,
                "created_at": t.created_at.isoformat(),
            })
        return JsonResponse({
            "success": True,
            "templates": data,
            "entity_type_choices": [
                {"key": et.key, "label": et.label, "is_system": et.is_system}
                for et in ApprovalEntityType.objects.filter(
                    business_unit=bu, is_active=True
                ).order_by("label")
            ],
        })

    if request.method == "POST":
        if not is_admin(request.user):
            return JsonResponse({"success": False, "error": "Admin access required"}, status=403)
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

        name = body.get("name", "").strip()
        if not name:
            return JsonResponse({"success": False, "error": "Name is required"}, status=400)

        with transaction.atomic():
            tmpl = ApprovalWorkflowTemplate.objects.create(
                name=name,
                description=body.get("description", ""),
                entity_type=body.get("entity_type", "custom"),
                business_unit=bu,
                require_all_steps=body.get("require_all_steps", True),
                auto_approve_timeout_hours=body.get("auto_approve_timeout_hours") or None,
                created_by=request.user,
            )
            for i, step in enumerate(body.get("steps", []), start=1):
                ApprovalStepTemplate.objects.create(
                    template=tmpl,
                    order=i,
                    name=step.get("name", f"Step {i}"),
                    approver_type=step.get("approver_type", "role"),
                    approver_role=step.get("approver_role", ""),
                    is_mandatory=step.get("is_mandatory", True),
                )

        return JsonResponse({"success": True, "id": tmpl.id, "message": "Template created"})

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)


@login_required
def approval_template_detail_api(request, template_id):
    """Detail / update / delete a template."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    tmpl = get_object_or_404(ApprovalWorkflowTemplate, id=template_id, business_unit=bu)

    if request.method == "GET":
        steps = list(tmpl.steps.order_by("order").values(
            "id", "order", "name", "approver_type", "approver_role",
            "approver_user_id", "is_mandatory"
        ))
        return JsonResponse({
            "success": True,
            "template": {
                "id": tmpl.id,
                "name": tmpl.name,
                "description": tmpl.description,
                "entity_type": tmpl.entity_type,
                "is_active": tmpl.is_active,
                "require_all_steps": tmpl.require_all_steps,
                "auto_approve_timeout_hours": tmpl.auto_approve_timeout_hours,
                "steps": steps,
            },
        })

    if request.method in ("PUT", "PATCH"):
        if not is_admin(request.user):
            return JsonResponse({"success": False, "error": "Admin access required"}, status=403)
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

        with transaction.atomic():
            tmpl.name = body.get("name", tmpl.name)
            tmpl.description = body.get("description", tmpl.description)
            tmpl.entity_type = body.get("entity_type", tmpl.entity_type)
            tmpl.is_active = body.get("is_active", tmpl.is_active)
            tmpl.require_all_steps = body.get("require_all_steps", tmpl.require_all_steps)
            tmpl.auto_approve_timeout_hours = body.get("auto_approve_timeout_hours", tmpl.auto_approve_timeout_hours)
            tmpl.save()

            if "steps" in body:
                tmpl.steps.all().delete()
                for i, step in enumerate(body["steps"], start=1):
                    ApprovalStepTemplate.objects.create(
                        template=tmpl,
                        order=i,
                        name=step.get("name", f"Step {i}"),
                        approver_type=step.get("approver_type", "role"),
                        approver_role=step.get("approver_role", ""),
                        is_mandatory=step.get("is_mandatory", True),
                    )

        return JsonResponse({"success": True, "message": "Template updated"})

    if request.method == "DELETE":
        if not is_admin(request.user):
            return JsonResponse({"success": False, "error": "Admin access required"}, status=403)
        tmpl.delete()
        return JsonResponse({"success": True, "message": "Template deleted"})

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)


@login_required
def approval_request_create(request):
    """Create a new approval request."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    template_id = body.get("template_id")
    title = body.get("title", "").strip()
    if not title:
        return JsonResponse({"success": False, "error": "Title is required"}, status=400)
    if not template_id:
        return JsonResponse({"success": False, "error": "Template is required"}, status=400)

    tmpl = get_object_or_404(ApprovalWorkflowTemplate, id=template_id, business_unit=bu, is_active=True)
    steps = tmpl.steps.order_by("order")
    if not steps.exists():
        return JsonResponse({"success": False, "error": "Template has no steps"}, status=400)

    stream = None
    stream_name = body.get("stream")
    if stream_name:
        try:
            stream = Stream.objects.get(name=stream_name, business_unit=bu)
        except Stream.DoesNotExist:
            pass

    due_hours = tmpl.auto_approve_timeout_hours
    due_date = None
    if body.get("due_date"):
        from django.utils.dateparse import parse_datetime
        due_date = parse_datetime(body["due_date"])
    elif due_hours:
        due_date = timezone.now() + timedelta(hours=due_hours)

    with transaction.atomic():
        ar = ApprovalRequest.objects.create(
            template=tmpl,
            title=title,
            description=body.get("description", ""),
            priority=body.get("priority", "medium"),
            business_unit=bu,
            stream=stream,
            requested_by=request.user,
            current_step=1,
            total_steps=steps.count(),
            due_date=due_date,
        )

        # Link to entity if provided
        entity_type = body.get("entity_type")
        entity_id = body.get("entity_id")
        if entity_type and entity_id:
            try:
                ct = ContentType.objects.get(app_label="products", model=entity_type.lower())
                ar.content_type = ct
                ar.object_id = int(entity_id)
                ar.save(update_fields=["content_type", "object_id"])
            except (ContentType.DoesNotExist, ValueError):
                pass

        # Create step actions
        for step in steps:
            ApprovalStepAction.objects.create(
                request=ar,
                step_order=step.order,
                step_name=step.name,
                action="pending",
                acted_by=step.approver_user,
            )

        ar.status = "in_review"
        ar.save(update_fields=["status"])

    return JsonResponse({
        "success": True,
        "id": ar.id,
        "message": f"Approval request #{ar.id} created successfully",
    })


@login_required
def approval_request_detail(request, request_id):
    """Get full detail of an approval request."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    ar = get_object_or_404(ApprovalRequest, id=request_id, business_unit=bu)

    steps = list(ar.step_actions.order_by("step_order").values(
        "id", "step_order", "step_name", "action", "acted_by__username",
        "comments", "acted_at", "created_at"
    ))
    comments = list(ar.comments.order_by("created_at").values(
        "id", "author__username", "message", "created_at"
    ))

    data = {
        "id": ar.id,
        "title": ar.title,
        "description": ar.description,
        "status": ar.status,
        "status_display": ar.get_status_display(),
        "priority": ar.priority,
        "priority_display": ar.get_priority_display(),
        "template_name": ar.template.name if ar.template else "—",
        "entity_type": ar.template.get_entity_type_display() if ar.template else "—",
        "current_step": ar.current_step,
        "total_steps": ar.total_steps,
        "progress_percent": ar.progress_percent,
        "is_overdue": ar.is_overdue,
        "requested_by": ar.requested_by.username,
        "stream": ar.stream.name if ar.stream else "",
        "due_date": ar.due_date.isoformat() if ar.due_date else None,
        "completed_at": ar.completed_at.isoformat() if ar.completed_at else None,
        "created_at": ar.created_at.isoformat(),
        "is_enforced": ar.is_enforced,
        "enforcement_result": ar.enforcement_result,
        "intended_changes": ar.intended_changes,
        "steps": steps,
        "comments": comments,
    }
    return JsonResponse({"success": True, "request": data})


@login_required
@require_POST
def approval_request_action(request, request_id):
    """Approve / reject / delegate a step."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    ar = get_object_or_404(ApprovalRequest, id=request_id, business_unit=bu)

    if ar.status not in ("pending", "in_review"):
        return JsonResponse({"success": False, "error": "This request is no longer active"}, status=400)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    action = body.get("action")  # approved | rejected | delegated | skipped
    comments = body.get("comments", "")

    if action not in ("approved", "rejected", "delegated", "skipped"):
        return JsonResponse({"success": False, "error": "Invalid action"}, status=400)

    # Find the current pending step
    current_step_action = ar.step_actions.filter(
        step_order=ar.current_step, action="pending"
    ).first()

    if not current_step_action:
        return JsonResponse({"success": False, "error": "No pending step found"}, status=400)

    with transaction.atomic():
        current_step_action.action = action
        current_step_action.acted_by = request.user
        current_step_action.comments = comments
        current_step_action.acted_at = timezone.now()
        current_step_action.save()

        enforcement_msg = ""

        if action == "rejected":
            ar.status = "rejected"
            ar.completed_at = timezone.now()
            ar.save(update_fields=["status", "completed_at", "updated_at"])

            # ── Enforcement: notify requester the action will NOT happen ──
            if ar.is_enforced and ar.intended_changes:
                ar.enforcement_result = "cancelled"
                ar.save(update_fields=["enforcement_result"])
                enforcement_msg = " The requested action has been discarded."

        elif action == "approved":
            if ar.current_step >= ar.total_steps:
                ar.status = "approved"
                ar.completed_at = timezone.now()

                # ── Enforcement: auto-execute the blocked action ──
                if ar.is_enforced and ar.intended_changes:
                    from ..approval_triggers import execute_approved_action
                    success, exec_msg = execute_approved_action(ar)
                    if success:
                        enforcement_msg = f" Action executed: {exec_msg}"
                    else:
                        enforcement_msg = f" Action failed: {exec_msg}"
            else:
                ar.current_step += 1
            ar.save(update_fields=["status", "current_step", "completed_at", "updated_at"])
        elif action == "delegated":
            delegate_to = body.get("delegate_to_user_id")
            if delegate_to:
                current_step_action.action = "pending"
                current_step_action.acted_by_id = delegate_to
                current_step_action.comments = f"Delegated by {request.user.username}: {comments}"
                current_step_action.acted_at = None
                current_step_action.save()

        # Create notification for requester
        try:
            _base_msg = (
                f'Your approval request "{ar.title}" — Step {current_step_action.step_order} '
                f'has been {action} by {request.user.username}.'
            )
            Notification.objects.create(
                user=ar.requested_by,
                message=_base_msg + enforcement_msg,
            )
        except Exception:
            pass

    return JsonResponse({
        "success": True,
        "message": f"Step {action} successfully" + enforcement_msg,
        "new_status": ar.status,
        "enforcement_result": ar.enforcement_result if ar.is_enforced else None,
    })


@login_required
@require_POST
def approval_request_comment(request, request_id):
    """Add a comment to an approval request."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    ar = get_object_or_404(ApprovalRequest, id=request_id, business_unit=bu)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    msg = body.get("message", "").strip()
    if not msg:
        return JsonResponse({"success": False, "error": "Message is required"}, status=400)

    comment = ApprovalComment.objects.create(
        request=ar,
        author=request.user,
        message=msg,
    )

    return JsonResponse({
        "success": True,
        "comment": {
            "id": comment.id,
            "author": request.user.username,
            "message": comment.message,
            "created_at": comment.created_at.isoformat(),
        },
    })


@login_required
def approval_my_pending(request):
    """API: Get my pending approval actions."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    custom_profile, _ = CustomUser.objects.get_or_create(user=request.user)
    user_roles = list(custom_profile.user_roles.values_list("role", flat=True))

    pending = ApprovalRequest.objects.filter(
        business_unit=bu,
        status__in=["pending", "in_review"],
    ).select_related("template", "requested_by")

    results = []
    for ar in pending:
        current_action = ar.step_actions.filter(step_order=ar.current_step, action="pending").first()
        if not current_action:
            continue
        # Check if user can act on this step
        step_tmpl = ar.template.steps.filter(order=ar.current_step).first() if ar.template else None
        can_act = False
        if current_action.acted_by == request.user:
            can_act = True
        elif step_tmpl and step_tmpl.approver_type == "role" and step_tmpl.approver_role in user_roles:
            can_act = True
        elif is_super_admin(request.user):
            can_act = True

        if can_act:
            results.append({
                "id": ar.id,
                "title": ar.title,
                "priority": ar.priority,
                "status": ar.status,
                "template_name": ar.template.name if ar.template else "—",
                "current_step": ar.current_step,
                "total_steps": ar.total_steps,
                "step_name": current_action.step_name,
                "requested_by": ar.requested_by.username,
                "created_at": ar.created_at.isoformat(),
                "is_overdue": ar.is_overdue,
            })

    return JsonResponse({"success": True, "pending": results})


@login_required
def approval_analytics_api(request):
    """Analytics data for approval workflows."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    from django.db.models import Avg, Count

    qs = ApprovalRequest.objects.filter(business_unit=bu)

    by_status = dict(qs.values_list("status").annotate(c=Count("id")).values_list("status", "c"))
    by_priority = dict(qs.values_list("priority").annotate(c=Count("id")).values_list("priority", "c"))
    by_type = {}
    for ar in qs.select_related("template"):
        t = ar.template.get_entity_type_display() if ar.template else "Unknown"
        by_type[t] = by_type.get(t, 0) + 1

    # Average resolution time (completed requests)
    completed = qs.filter(status__in=["approved", "rejected"], completed_at__isnull=False)
    avg_hours = None
    if completed.exists():
        from django.db.models import ExpressionWrapper, DurationField
        durations = []
        for c in completed[:100]:
            if c.completed_at and c.created_at:
                durations.append((c.completed_at - c.created_at).total_seconds() / 3600)
        if durations:
            avg_hours = round(sum(durations) / len(durations), 1)

    return JsonResponse({
        "success": True,
        "analytics": {
            "by_status": by_status,
            "by_priority": by_priority,
            "by_type": by_type,
            "total": qs.count(),
            "avg_resolution_hours": avg_hours,
        },
    })


# Import models at module level for the pending query
from django.db import models  # noqa: E402


# ========================================================================
# TRIGGER RULES API
# ========================================================================

@login_required
def approval_triggers_api(request):
    """List / create auto-trigger rules."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    if request.method == "GET":
        triggers = ApprovalAutoTrigger.objects.filter(business_unit=bu).select_related(
            "template", "created_by"
        )
        data = []
        for t in triggers:
            data.append({
                "id": t.id,
                "name": t.name,
                "event_action": t.event_action,
                "event_display": t.get_event_action_display(),
                "template_id": t.template_id,
                "template_name": t.template.name if t.template else "",
                "priority": t.priority,
                "is_active": t.is_active,
                "created_by": t.created_by.username if t.created_by else "",
                "created_at": t.created_at.isoformat(),
            })
        # Dynamic event choices from DB, grouped by category
        event_types = ApprovalEventType.objects.filter(
            business_unit=bu, is_active=True
        ).order_by("category", "label")
        event_choices = [
            {"key": et.key, "label": et.label, "category": et.category, "is_system": et.is_system}
            for et in event_types
        ]
        # Also send legacy flat list for backward compat
        event_choices_flat = [[et.key, et.label] for et in event_types]

        return JsonResponse({
            "success": True,
            "triggers": data,
            "event_choices": event_choices_flat,
            "event_choices_grouped": event_choices,
            "templates": list(
                ApprovalWorkflowTemplate.objects.filter(
                    business_unit=bu, is_active=True
                ).values("id", "name", "entity_type")
            ),
        })

    if request.method == "POST":
        if not is_admin(request.user):
            return JsonResponse({"success": False, "error": "Admin access required"}, status=403)
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

        name = body.get("name", "").strip()
        event_action = body.get("event_action", "")
        template_id = body.get("template_id")
        if not name or not event_action or not template_id:
            return JsonResponse({"success": False, "error": "Name, event, and template are required"}, status=400)

        tmpl = get_object_or_404(ApprovalWorkflowTemplate, id=template_id, business_unit=bu, is_active=True)

        trigger, created = ApprovalAutoTrigger.objects.get_or_create(
            business_unit=bu,
            event_action=event_action,
            template=tmpl,
            defaults={
                "name": name,
                "priority": body.get("priority", "high"),
                "is_active": body.get("is_active", True),
                "created_by": request.user,
            },
        )
        if not created:
            return JsonResponse({"success": False, "error": "A trigger with this event + template already exists"}, status=400)

        return JsonResponse({"success": True, "id": trigger.id, "message": "Trigger rule created"})

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)


def _cancel_orphaned_requests(trigger):
    """Cancel all pending/in_review enforced requests created by a trigger.

    Called when a trigger is deleted or deactivated so that blocked actions
    are no longer stuck waiting for an approval that will never come.
    Returns the count of cancelled requests.
    """
    pending = ApprovalRequest.objects.filter(
        business_unit=trigger.business_unit,
        template=trigger.template,
        trigger_event=trigger.event_action,
        is_enforced=True,
        status__in=("pending", "in_review"),
    )
    count = pending.count()
    if count:
        pending.update(status="cancelled", enforcement_result="cancelled")
    return count


@login_required
def approval_trigger_detail_api(request, trigger_id):
    """Detail / toggle / delete a trigger rule."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    trigger = get_object_or_404(ApprovalAutoTrigger, id=trigger_id, business_unit=bu)

    if request.method == "GET":
        return JsonResponse({
            "success": True,
            "trigger": {
                "id": trigger.id,
                "name": trigger.name,
                "event_action": trigger.event_action,
                "event_display": trigger.get_event_action_display(),
                "template_id": trigger.template_id,
                "template_name": trigger.template.name if trigger.template else "",
                "priority": trigger.priority,
                "is_active": trigger.is_active,
            },
        })

    if request.method in ("PUT", "PATCH"):
        if not is_admin(request.user):
            return JsonResponse({"success": False, "error": "Admin access required"}, status=403)
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

        if "name" in body:
            trigger.name = body["name"]
        if "event_action" in body:
            trigger.event_action = body["event_action"]
        if "priority" in body:
            trigger.priority = body["priority"]
        if "is_active" in body:
            trigger.is_active = body["is_active"]
        if "template_id" in body:
            tmpl = get_object_or_404(ApprovalWorkflowTemplate, id=body["template_id"], business_unit=bu)
            trigger.template = tmpl
        trigger.save()

        # ── Auto-cancel pending enforced requests when trigger is deactivated ──
        if not trigger.is_active:
            _cancelled = _cancel_orphaned_requests(trigger)
            msg = "Trigger disabled"
            if _cancelled:
                msg += f" — {_cancelled} pending request(s) cancelled"
            return JsonResponse({"success": True, "message": msg})

        return JsonResponse({"success": True, "message": "Trigger updated"})

    if request.method == "DELETE":
        if not is_admin(request.user):
            return JsonResponse({"success": False, "error": "Admin access required"}, status=403)
        _cancelled = _cancel_orphaned_requests(trigger)
        trigger.delete()
        msg = "Trigger deleted"
        if _cancelled:
            msg += f" — {_cancelled} pending request(s) cancelled"
        return JsonResponse({"success": True, "message": msg})

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)


# ========================================================================
# ADMIN CRUD — ENTITY TYPES & EVENT TYPES
# ========================================================================

@login_required
def approval_entity_types_api(request):
    """List / create / delete custom entity types for the current BU."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    if request.method == "GET":
        types = ApprovalEntityType.objects.filter(business_unit=bu).order_by("label")
        existing_keys = set(types.values_list("key", flat=True))

        # Build list of discoverable options not yet added for this BU
        available = [
            {"key": k, "label": lbl, "description": desc}
            for k, lbl, desc in DISCOVERABLE_ENTITY_TYPES
            if k not in existing_keys
        ]

        return JsonResponse({
            "success": True,
            "entity_types": [
                {
                    "id": et.id, "key": et.key, "label": et.label,
                    "is_system": et.is_system, "is_active": et.is_active,
                }
                for et in types
            ],
            "available_entity_types": available,
        })

    if not is_admin(request.user):
        return JsonResponse({"success": False, "error": "Admin access required"}, status=403)

    if request.method == "POST":
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

        key = body.get("key", "").strip().lower().replace(" ", "_")
        label = body.get("label", "").strip()
        if not key or not label:
            return JsonResponse({"success": False, "error": "Key and label are required"}, status=400)
        if len(key) > 40:
            return JsonResponse({"success": False, "error": "Key must be ≤ 40 characters"}, status=400)

        obj, created = ApprovalEntityType.objects.get_or_create(
            business_unit=bu, key=key,
            defaults={"label": label, "is_system": False},
        )
        if not created:
            return JsonResponse({"success": False, "error": f"Entity type '{key}' already exists"}, status=400)
        return JsonResponse({"success": True, "id": obj.id, "message": f"Entity type '{label}' created"})

    if request.method == "DELETE":
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
        et_id = body.get("id")
        try:
            et = ApprovalEntityType.objects.get(id=et_id, business_unit=bu)
        except ApprovalEntityType.DoesNotExist:
            return JsonResponse({"success": False, "error": "Not found"}, status=404)
        if et.is_system:
            et.is_active = False
            et.save(update_fields=["is_active"])
            return JsonResponse({"success": True, "message": f"System type '{et.label}' deactivated"})
        et.delete()
        return JsonResponse({"success": True, "message": f"Entity type '{et.label}' deleted"})

    if request.method in ("PUT", "PATCH"):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
        et_id = body.get("id")
        try:
            et = ApprovalEntityType.objects.get(id=et_id, business_unit=bu)
        except ApprovalEntityType.DoesNotExist:
            return JsonResponse({"success": False, "error": "Not found"}, status=404)
        if "label" in body:
            et.label = body["label"]
        if "is_active" in body:
            et.is_active = body["is_active"]
        et.save()
        return JsonResponse({"success": True, "message": f"Entity type '{et.label}' updated"})

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)


@login_required
def approval_event_types_api(request):
    """List / create / delete custom event types for the current BU."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    if request.method == "GET":
        types = ApprovalEventType.objects.filter(business_unit=bu).order_by("category", "label")
        existing_keys = set(types.values_list("key", flat=True))

        # Build list of discoverable options not yet added for this BU
        available = [
            {
                "key": k, "label": lbl, "category": cat,
                "description": desc, "is_wired": wired,
            }
            for k, lbl, cat, desc, wired in DISCOVERABLE_EVENT_TYPES
            if k not in existing_keys
        ]

        return JsonResponse({
            "success": True,
            "event_types": [
                {
                    "id": et.id, "key": et.key, "label": et.label,
                    "category": et.category, "is_system": et.is_system,
                    "is_active": et.is_active,
                }
                for et in types
            ],
            "available_event_types": available,
        })

    if not is_admin(request.user):
        return JsonResponse({"success": False, "error": "Admin access required"}, status=403)

    if request.method == "POST":
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

        key = body.get("key", "").strip().lower().replace(" ", "_")
        label = body.get("label", "").strip()
        category = body.get("category", "").strip()
        if not key or not label:
            return JsonResponse({"success": False, "error": "Key and label are required"}, status=400)
        if len(key) > 40:
            return JsonResponse({"success": False, "error": "Key must be ≤ 40 characters"}, status=400)

        obj, created = ApprovalEventType.objects.get_or_create(
            business_unit=bu, key=key,
            defaults={"label": label, "category": category, "is_system": False},
        )
        if not created:
            return JsonResponse({"success": False, "error": f"Event type '{key}' already exists"}, status=400)
        return JsonResponse({"success": True, "id": obj.id, "message": f"Event type '{label}' created"})

    if request.method == "DELETE":
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
        et_id = body.get("id")
        try:
            et = ApprovalEventType.objects.get(id=et_id, business_unit=bu)
        except ApprovalEventType.DoesNotExist:
            return JsonResponse({"success": False, "error": "Not found"}, status=404)
        if et.is_system:
            et.is_active = False
            et.save(update_fields=["is_active"])
            return JsonResponse({"success": True, "message": f"System event '{et.label}' deactivated"})
        et.delete()
        return JsonResponse({"success": True, "message": f"Event type '{et.label}' deleted"})

    if request.method in ("PUT", "PATCH"):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
        et_id = body.get("id")
        try:
            et = ApprovalEventType.objects.get(id=et_id, business_unit=bu)
        except ApprovalEventType.DoesNotExist:
            return JsonResponse({"success": False, "error": "Not found"}, status=404)
        if "label" in body:
            et.label = body["label"]
        if "category" in body:
            et.category = body["category"]
        if "is_active" in body:
            et.is_active = body["is_active"]
        et.save()
        return JsonResponse({"success": True, "message": f"Event type '{et.label}' updated"})

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)
