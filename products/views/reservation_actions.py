"""Products app - Reservation Detail, Edit, Delete, Toggle Status, Confirm, Cancel views."""

# pylint: disable=broad-exception-caught

from datetime import datetime as dt_class

from ._helpers import (
    AuditLog,
    JsonResponse,
    Project,
    RecurringReservation,
    RecurringReservationInstance,
    ReservationWaitlist,
    System,
    SystemAllocation,
    User,
    date,
    get_object_or_404,
    get_stream_or_404,
    logger,
    login_required,
    messages,
    redirect,
    render,
    require_POST,
    timedelta,
    timezone,
)
from .recurring import check_reservation_conflict, create_allocation_from_instance, generate_recurring_instances

__all__ = [
    "recurring_reservation_detail",
    "recurring_reservation_edit",
    "recurring_reservation_delete",
    "recurring_reservation_toggle_status",
    "reservation_instance_confirm",
    "reservation_instance_cancel",
]


@login_required
def recurring_reservation_detail(request, stream=None, pk=None):
    """View details of a recurring reservation."""
    stream_obj = get_stream_or_404(stream)
    recurring = get_object_or_404(RecurringReservation, pk=pk, stream=stream_obj)

    instances = recurring.instances.order_by("-reservation_date")[:50]
    upcoming_instances = recurring.instances.filter(
        reservation_date__gte=date.today(), status__in=["scheduled", "confirmed"]
    ).order_by("reservation_date")[:10]

    conflict_instances = recurring.instances.filter(has_conflict=True, conflict_resolved=False)

    context = {
        "recurring": recurring,
        "instances": instances,
        "upcoming_instances": upcoming_instances,
        "conflict_instances": conflict_instances,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/recurring_reservation_detail.html", context)


@login_required
def recurring_reservation_edit(request, stream=None, pk=None):  # noqa: CCR001
    """Edit a recurring reservation."""
    stream_obj = get_stream_or_404(stream)
    recurring = get_object_or_404(RecurringReservation, pk=pk, stream=stream_obj)

    systems = System.objects.filter(stream=stream_obj, status="Active")
    projects = Project.objects.filter(stream=stream_obj)
    users = User.objects.filter(is_active=True)

    if request.method == "POST":
        try:
            recurring.title = request.POST.get("title", "").strip()
            recurring.description = request.POST.get("description", "").strip()
            recurring.system_id = request.POST.get("system")
            recurring.recurrence_type = request.POST.get("recurrence_type")
            recurring.days_of_week = ",".join(request.POST.getlist("days_of_week")) or None
            recurring.day_of_month = int(request.POST.get("day_of_month")) if request.POST.get("day_of_month") else None
            recurring.start_time = request.POST.get("start_time")
            recurring.end_time = request.POST.get("end_time")
            recurring.end_date = request.POST.get("end_date") or None
            recurring.max_occurrences = (
                int(request.POST.get("max_occurrences")) if request.POST.get("max_occurrences") else None
            )
            recurring.priority = request.POST.get("priority", "normal")
            recurring.status = request.POST.get("status", "active")
            recurring.reserved_for_id = request.POST.get("reserved_for") or None
            recurring.project_id = request.POST.get("project") or None
            recurring.allow_conflicts = request.POST.get("allow_conflicts") == "on"
            recurring.auto_resolve_conflicts = request.POST.get("auto_resolve_conflicts") == "on"
            recurring.notify_on_creation = request.POST.get("notify_on_creation") == "on"
            recurring.notify_on_conflict = request.POST.get("notify_on_conflict") == "on"
            recurring.reminder_hours_before = int(request.POST.get("reminder_hours_before", 24))
            recurring.notes = request.POST.get("notes", "").strip()
            recurring.save()

            AuditLog.log(
                "update",
                f"Updated recurring reservation: {recurring.title}",
                request=request,
                obj=recurring,
                module="reservations",
                severity="info",
                stream=stream_obj,
            )

            messages.success(request, f'Recurring reservation "{recurring.title}" updated successfully!')
            return redirect("recurring_reservation_detail", stream=stream, pk=pk)

        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    selected_days = recurring.days_of_week.split(",") if recurring.days_of_week else []

    context = {
        "recurring": recurring,
        "systems": systems,
        "projects": projects,
        "users": users,
        "stream": stream,
        "selected_stream": stream,
        "selected_days": selected_days,
        "recurrence_types": RecurringReservation.RECURRENCE_TYPES,
        "priority_choices": RecurringReservation.PRIORITY_CHOICES,
        "status_choices": RecurringReservation.STATUS_CHOICES,
        "is_edit": True,
        "form_error": form_error,
    }
    return render(request, "products/recurring_reservation_form.html", context)


@login_required
def recurring_reservation_delete(request, stream=None, pk=None):
    """Delete a recurring reservation."""
    stream_obj = get_stream_or_404(stream)
    recurring = get_object_or_404(RecurringReservation, pk=pk, stream=stream_obj)

    if request.method == "POST":
        delete_future_instances = request.POST.get("delete_future_instances") == "on"

        # Clean up linked SystemAllocations before deleting instances/reservation
        if delete_future_instances:
            target_instances = recurring.instances.filter(reservation_date__gte=date.today())
        else:
            target_instances = recurring.instances.all()

        allocation_ids = list(
            target_instances.exclude(system_allocation__isnull=True).values_list("system_allocation_id", flat=True)
        )
        if allocation_ids:
            SystemAllocation.objects.filter(id__in=allocation_ids).delete()

        if delete_future_instances:
            target_instances.delete()

        # When recurring.delete() cascades, remaining instances' allocations
        # also need cleanup (all instances, not just future)
        all_alloc_ids = list(
            recurring.instances.exclude(system_allocation__isnull=True).values_list("system_allocation_id", flat=True)
        )
        if all_alloc_ids:
            SystemAllocation.objects.filter(id__in=all_alloc_ids).delete()

        title = recurring.title
        AuditLog.log(
            "delete",
            f"Deleted recurring reservation: {recurring.title}",
            request=request,
            obj=recurring,
            module="reservations",
            severity="warning",
            stream=stream_obj,
        )
        recurring.delete()
        messages.success(request, f'Recurring reservation "{title}" deleted successfully!')
        return redirect("recurring_reservations_list", stream=stream)

    future_instances_count = recurring.instances.filter(reservation_date__gte=date.today()).count()

    context = {
        "recurring": recurring,
        "future_instances_count": future_instances_count,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/recurring_reservation_confirm_delete.html", context)


@login_required
@require_POST
def recurring_reservation_toggle_status(request, stream=None, pk=None):
    """Toggle the status of a recurring reservation (active/paused).

    Pause: Cancels all future scheduled/confirmed instances and deletes their allocations.
    The system is freed up for those dates.
    Resume: Regenerates instances for remaining dates and re-books available slots.
    """
    # pylint: disable=too-many-locals
    stream_obj = get_stream_or_404(stream)
    recurring = get_object_or_404(RecurringReservation, pk=pk, stream=stream_obj)
    today = date.today()

    if recurring.status == "active":
        # --- PAUSE: Cancel future instances & free up allocations ---
        recurring.status = "paused"

        future_instances = RecurringReservationInstance.objects.filter(
            recurring_reservation=recurring,
            reservation_date__gte=today,
            status__in=["scheduled", "confirmed", "conflict"],
        )

        # Collect allocation IDs to delete
        allocation_ids = list(
            future_instances.filter(system_allocation__isnull=False).values_list("system_allocation_id", flat=True)
        )

        # Cancel waitlist entries linked to these instances
        _cancelled_waitlist = ReservationWaitlist.objects.filter(  # noqa: F841
            system=recurring.system,
            user=recurring.reserved_for or recurring.created_by,
            desired_date__in=future_instances.values_list("reservation_date", flat=True),
            status="waiting",
        ).update(status="cancelled")

        cancelled_count = future_instances.count()

        # Mark all future instances as cancelled
        future_instances.update(
            status="cancelled",
            cancelled_by=request.user,
            cancelled_at=timezone.now(),
            cancellation_reason="Recurring reservation paused",
        )

        # Clear the allocation FK on instances before deleting allocations
        RecurringReservationInstance.objects.filter(
            recurring_reservation=recurring,
            system_allocation_id__in=allocation_ids,
        ).update(system_allocation=None)

        # Delete the allocations to free up the system
        freed_count = SystemAllocation.objects.filter(id__in=allocation_ids).delete()[0]

        recurring.save()

        message = (
            f'Recurring reservation "{recurring.title}" has been paused. '
            f"{cancelled_count} future instance(s) cancelled, {freed_count} allocation(s) freed."
        )

        AuditLog.log(
            "status_change",
            f"Paused reservation: {recurring.title}. Cancelled {cancelled_count} "
            f"future instances, freed {freed_count} allocations.",
            request=request,
            obj=recurring,
            module="reservations",
            severity="info",
            stream=stream_obj,
        )

    else:
        # --- RESUME: Reactivate and regenerate instances ---
        recurring.status = "active"

        # Delete the cancelled-by-pause instances so they can be regenerated fresh
        # (unique_together on recurring_reservation + reservation_date would block re-creation)
        pause_cancelled = RecurringReservationInstance.objects.filter(
            recurring_reservation=recurring,
            reservation_date__gte=today,
            status="cancelled",
            cancellation_reason="Recurring reservation paused",
        )
        deleted_old = pause_cancelled.count()
        # Also decrement occurrences_created for each deleted instance
        recurring.occurrences_created = max(0, (recurring.occurrences_created or 0) - deleted_old)
        pause_cancelled.delete()

        # Reset last_generated_date so generate_recurring_instances will regenerate from today
        start_date = recurring.start_date
        if isinstance(start_date, str):
            start_date = dt_class.strptime(start_date, "%Y-%m-%d").date()

        # Set last_generated_date to yesterday so generation starts from today
        recurring.last_generated_date = today - timedelta(days=1)
        if recurring.last_generated_date < start_date:
            recurring.last_generated_date = None

        recurring.save()

        # Regenerate instances for future dates
        try:
            new_count = generate_recurring_instances(recurring) or 0
        except Exception:
            logger.warning("Error regenerating instances on resume")
            new_count = 0

        message = (
            f'Recurring reservation "{recurring.title}" has been resumed. '
            f"{new_count} new instance(s) generated and booked."
        )

        AuditLog.log(
            "status_change",
            f"Resumed reservation: {recurring.title}. Regenerated {new_count} instances.",
            request=request,
            obj=recurring,
            module="reservations",
            severity="info",
            stream=stream_obj,
        )

    # Handle AJAX requests
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"success": True, "message": message, "new_status": recurring.status})

    # Regular form POST — redirect back with message
    messages.success(request, message)
    return redirect("recurring_reservation_detail", stream=stream, pk=pk)


@login_required
def reservation_instance_confirm(request, stream=None, pk=None):
    """Confirm a reservation instance and create the actual system allocation."""
    stream_obj = get_stream_or_404(stream)
    instance = get_object_or_404(RecurringReservationInstance, pk=pk, recurring_reservation__stream=stream_obj)

    if request.method == "POST":
        if instance.system_allocation:
            messages.warning(request, "This reservation is already confirmed with an allocation.")
        elif instance.status == "cancelled":
            messages.error(request, "Cannot confirm a cancelled reservation.")
        elif instance.status == "conflict":
            has_conflict, conflict_details = check_reservation_conflict(
                instance.recurring_reservation.system, instance.reservation_date, instance.start_time, instance.end_time
            )
            if has_conflict:
                messages.error(request, f"Cannot confirm: conflict still exists. {conflict_details}")
            else:
                _allocation = create_allocation_from_instance(instance)
                AuditLog.log(
                    "approve",
                    "Confirmed reservation instance",
                    request=request,
                    obj=instance,
                    module="reservations",
                    severity="info",
                    stream=stream_obj,
                )
                messages.success(
                    request,
                    f"Reservation confirmed! System allocated from {instance.start_time} to "
                    f"{instance.end_time} on {instance.reservation_date}.",
                )
        else:
            _allocation = create_allocation_from_instance(instance)  # noqa: F841
            AuditLog.log(
                "approve",
                "Confirmed reservation instance",
                request=request,
                obj=instance,
                module="reservations",
                severity="info",
                stream=stream_obj,
            )
            messages.success(
                request,
                f"Reservation confirmed! System allocated from {instance.start_time} to "
                f"{instance.end_time} on {instance.reservation_date}.",
            )

    return redirect("recurring_reservation_detail", stream=stream, pk=instance.recurring_reservation.pk)


@login_required
def reservation_instance_cancel(request, stream=None, pk=None):
    """Cancel a reservation instance and remove the system allocation if exists."""
    stream_obj = get_stream_or_404(stream)
    instance = get_object_or_404(RecurringReservationInstance, pk=pk, recurring_reservation__stream=stream_obj)

    if request.method == "POST":
        reason = request.POST.get("reason", "")

        if instance.system_allocation:
            instance.system_allocation.delete()
            instance.system_allocation = None

        instance.status = "cancelled"
        instance.cancelled_by = request.user
        instance.cancellation_reason = reason
        instance.cancelled_at = timezone.now()
        instance.save()

        AuditLog.log(
            "status_change",
            "Cancelled reservation instance",
            request=request,
            obj=instance,
            module="reservations",
            severity="info",
            stream=stream_obj,
        )

        messages.success(request, f"Reservation for {instance.reservation_date} has been cancelled.")

    return redirect("recurring_reservation_detail", stream=stream, pk=instance.recurring_reservation.pk)
