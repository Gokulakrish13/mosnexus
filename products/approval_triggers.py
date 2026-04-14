"""Approval Workflows — automatic trigger utilities.

Three public functions:

* ``fire_approval_trigger(event, ...)``
      Post-hoc, **non-enforced** review request (used for creates/info events).
      The action has already been committed; the approval is for audit/review.

* ``check_approval_required(event, ...)``
      **Pre-action enforcement.**  Call this *before* committing a destructive
      or high-impact action (status change, delete).  If an active trigger
      matches, the action is **blocked** — an enforced ``ApprovalRequest`` is
      created with ``intended_changes`` describing what should happen on
      approval.  Returns the request (truthy) or ``None`` (falsy = proceed).

* ``execute_approved_action(approval_request)``
      Called when an enforced request reaches the **approved** state.  Reads
      ``intended_changes`` and applies the stored mutation (status change,
      delete, bulk ops) to the database.
"""

import logging
from datetime import timedelta

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────
#  Internal helper — shared request-creation logic
# ───────────────────────────────────────────────────────────────

def _create_approval_requests(
    event_action,
    business_unit,
    user,
    *,
    entity_obj=None,
    stream=None,
    title="",
    description="",
    is_enforced=False,
    intended_changes=None,
):
    """Low-level helper that finds matching trigger rules and creates requests."""
    from .models import (
        ApprovalAutoTrigger,
        ApprovalRequest,
        ApprovalStepAction,
    )

    triggers = ApprovalAutoTrigger.objects.filter(
        business_unit=business_unit,
        event_action=event_action,
        is_active=True,
        template__is_active=True,
    ).select_related("template")

    if not triggers.exists():
        return []

    # ── Deduplication: if an enforced request for the same entity + event
    #    is already pending / in_review, return it instead of creating a new one.
    if is_enforced and entity_obj is not None:
        from django.contrib.contenttypes.models import ContentType as _CT
        _ct = _CT.objects.get_for_model(entity_obj)
        existing = ApprovalRequest.objects.filter(
            content_type=_ct,
            object_id=entity_obj.pk,
            trigger_event=event_action,
            is_enforced=True,
            status__in=("pending", "in_review"),
        ).order_by("-created_at").first()
        if existing:
            logger.info(
                "Reusing existing enforced request #%d for event '%s' on %s #%d",
                existing.id, event_action, entity_obj.__class__.__name__, entity_obj.pk,
            )
            return [existing]

    # Try to auto-detect stream from entity
    if stream is None and entity_obj is not None:
        stream = getattr(entity_obj, "stream", None)
        if stream is None and hasattr(entity_obj, "product"):
            stream = getattr(entity_obj.product, "stream", None)

    created_requests = []

    for trigger in triggers:
        tmpl = trigger.template
        steps = tmpl.steps.order_by("order")
        if not steps.exists():
            logger.warning(
                "Auto-trigger '%s' skipped — template '%s' has no steps.",
                trigger.name, tmpl.name,
            )
            continue

        req_title = title or f"[Auto] {trigger.name}"

        due_date = None
        if tmpl.auto_approve_timeout_hours:
            due_date = timezone.now() + timedelta(hours=tmpl.auto_approve_timeout_hours)

        ar = ApprovalRequest.objects.create(
            template=tmpl,
            title=req_title,
            description=description or f"Automatically triggered by event: {trigger.get_event_action_display()}",
            priority=trigger.priority,
            business_unit=business_unit,
            stream=stream,
            requested_by=user,
            current_step=1,
            total_steps=steps.count(),
            due_date=due_date,
            is_enforced=is_enforced,
            trigger_event=event_action,
            intended_changes=intended_changes,
        )

        # Link entity via GenericForeignKey
        if entity_obj is not None:
            try:
                ct = ContentType.objects.get_for_model(entity_obj)
                ar.content_type = ct
                ar.object_id = entity_obj.pk
                ar.save(update_fields=["content_type", "object_id"])
            except Exception:
                logger.exception("Failed to link entity to approval request %s", ar.id)

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

        created_requests.append(ar)
        logger.info(
            "Auto-created %sapproval request #%d (%s) for event '%s' by user %s",
            "ENFORCED " if is_enforced else "",
            ar.id, req_title, event_action, user,
        )

    return created_requests


# ───────────────────────────────────────────────────────────────
#  Public API
# ───────────────────────────────────────────────────────────────

def fire_approval_trigger(
    event_action: str,
    business_unit,
    user,
    *,
    entity_obj=None,
    stream=None,
    title: str = "",
    description: str = "",
):
    """Non-enforced (review-only) approval trigger — fires AFTER the action.

    Used for events where the action has already been committed (creates,
    informational events) and the approval is purely for audit / review.

    Returns list[ApprovalRequest].
    """
    return _create_approval_requests(
        event_action, business_unit, user,
        entity_obj=entity_obj, stream=stream,
        title=title, description=description,
        is_enforced=False, intended_changes=None,
    )


def check_approval_required(
    event_action: str,
    business_unit,
    user,
    *,
    entity_obj=None,
    stream=None,
    title: str = "",
    description: str = "",
    intended_changes: dict | None = None,
):
    """Pre-action enforcement check — call BEFORE committing the action.

    If an active trigger rule exists for *event_action* in *business_unit*,
    an **enforced** ``ApprovalRequest`` is created (with the supplied
    ``intended_changes``).  The view should then **skip** the action and show
    a "pending approval" message.

    Returns
    -------
    ApprovalRequest | None
        The first enforced request (truthy → block the action).
        ``None`` if no trigger matches (falsy → proceed normally).
    """
    requests = _create_approval_requests(
        event_action, business_unit, user,
        entity_obj=entity_obj, stream=stream,
        title=title, description=description,
        is_enforced=True, intended_changes=intended_changes,
    )
    return requests[0] if requests else None


def execute_approved_action(approval_request):
    """Execute the intended_changes stored on an approved enforced request.

    Called automatically when the final approval step is reached.

    Returns
    -------
    tuple[bool, str]
        ``(True, message)`` on success, ``(False, error)`` on failure.
    """
    ar = approval_request
    changes = ar.intended_changes

    if not changes or not ar.is_enforced:
        ar.enforcement_result = "not_applicable"
        ar.save(update_fields=["enforcement_result"])
        return True, "No enforcement action needed."

    action_type = changes.get("action_type", "")
    model_label = changes.get("model_label", "")

    try:
        app_label, model_name = model_label.split(".")
        Model = apps.get_model(app_label, model_name)
    except Exception as exc:
        msg = f"Cannot resolve model '{model_label}': {exc}"
        logger.error(msg)
        ar.enforcement_result = "failed"
        ar.save(update_fields=["enforcement_result"])
        return False, msg

    try:
        if action_type == "status_change":
            pk = changes["pk"]
            obj = Model.objects.filter(pk=pk).first()
            if not obj:
                msg = f"{model_name} #{pk} no longer exists — cannot apply status change."
                ar.enforcement_result = "failed"
                ar.save(update_fields=["enforcement_result"])
                return False, msg
            for field, value in changes.get("changes", {}).items():
                setattr(obj, field, value)
            obj.save()
            ar.enforcement_result = "executed"
            ar.save(update_fields=["enforcement_result"])
            return True, f"{model_name} #{pk} updated successfully."

        elif action_type == "delete":
            pk = changes["pk"]
            obj = Model.objects.filter(pk=pk).first()
            if not obj:
                msg = f"{model_name} #{pk} no longer exists — already deleted."
                ar.enforcement_result = "executed"
                ar.save(update_fields=["enforcement_result"])
                return True, msg
            entity_repr = str(obj)
            obj.delete()
            ar.enforcement_result = "executed"
            ar.save(update_fields=["enforcement_result"])
            return True, f"{model_name} '{entity_repr}' deleted successfully."

        elif action_type == "bulk_delete":
            pks = changes.get("pks", [])
            deleted_count, _ = Model.objects.filter(pk__in=pks).delete()
            ar.enforcement_result = "executed"
            ar.save(update_fields=["enforcement_result"])
            return True, f"{deleted_count} {model_name}(s) deleted."

        elif action_type == "bulk_status_change":
            pks = changes.get("pks", [])
            field_changes = changes.get("changes", {})
            updated = Model.objects.filter(pk__in=pks).update(**field_changes)
            ar.enforcement_result = "executed"
            ar.save(update_fields=["enforcement_result"])
            return True, f"{updated} {model_name}(s) status updated."

        else:
            msg = f"Unknown action_type: {action_type}"
            ar.enforcement_result = "failed"
            ar.save(update_fields=["enforcement_result"])
            return False, msg

    except Exception as exc:
        msg = f"Enforcement execution failed: {exc}"
        logger.exception(msg)
        ar.enforcement_result = "failed"
        ar.save(update_fields=["enforcement_result"])
        return False, msg
