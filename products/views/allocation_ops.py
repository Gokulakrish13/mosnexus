"""Products app - System Extension, Option Change, Locations, and System CRUD views."""

# pylint: disable=broad-exception-caught

from ._helpers import (
    AuditLog,
    JsonResponse,
    Location,
    Notification,
    OnboardingProgress,
    Participant,
    SystemAllocation,
    User,
    _fac_granted,
    check_user_access,
    datetime,
    get_default_stream_name,
    get_object_or_404,
    get_stream_or_404,
    login_required,
    logout,
    make_aware,
    messages,
    redirect,
    render,
    require_POST,
    transaction,
)

__all__ = [
    "extend_system",
    "opt_change_system",
    "location_list",
    "location_create",
    "location_edit",
    "location_delete",
]


@login_required
@require_POST
def extend_system(request, stream=None):  # noqa: C901, CCR001
    # pylint: disable=too-many-return-statements,too-complex
    """Extend system."""
    system_type = request.POST.get("system_type")
    username = request.POST.get("username")
    new_end_date = request.POST.get("new_end_date")
    allocation_id = request.POST.get("allocation_id")

    def parse_dt(dt_str):
        if not dt_str:
            return None
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return make_aware(datetime.strptime(dt_str, fmt))
            except ValueError:
                continue
        return None

    new_end_dt = parse_dt(new_end_date)
    if not (system_type and username and new_end_dt and allocation_id):
        return JsonResponse({"success": False, "error": "Missing or invalid data."}, status=400)

    user = User.objects.filter(username=username).first()
    if not user:
        return JsonResponse({"success": False, "error": "User not found."}, status=404)
    if request.user != user and not request.user.is_superuser:
        return JsonResponse({"success": False, "error": "Permission denied."}, status=403)

    stream_obj = get_stream_or_404(stream, request=request)

    try:
        alloc_id_int = int(allocation_id)
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "error": "Invalid allocation ID."}, status=400)

    allocation = SystemAllocation.objects.filter(
        id=alloc_id_int, system_type=system_type, user=user, stream=stream_obj
    ).first()
    if not allocation:
        return JsonResponse({"success": False, "error": "No active allocation found."}, status=404)

    try:
        with transaction.atomic():
            overlap = (
                SystemAllocation.objects.select_for_update()
                .filter(
                    system_type=system_type,
                    start_date__lt=new_end_dt,
                    end_date__gt=allocation.end_date,
                    stream=stream_obj,
                )
                .exclude(id=allocation.id)
                .exists()
            )
            if overlap:
                return JsonResponse(
                    {"success": False, "error": "System already blocked for this extended period."}, status=409
                )

            allocation.end_date = new_end_dt
            allocation.save()
    except Exception:
        return JsonResponse({"success": False, "error": "Could not complete extension. Please try again."}, status=500)
    AuditLog.log(
        "update",
        f"Extended allocation for {allocation.system_type}",
        user=request.user,
        request=request,
        obj=allocation,
        module="allocation",
        severity="info",
        stream=stream_obj,
    )
    return JsonResponse({"success": True})


@login_required
@require_POST
def opt_change_system(request, stream=None):  # noqa: C901, CCR001
    # pylint: disable=too-many-locals,too-many-return-statements,too-many-branches,too-complex
    """Opt change system."""
    if not _fac_granted(request.user) and not request.user.is_superuser:
        return JsonResponse({"success": False, "error": "Permission denied."}, status=403)
    system_type = request.POST.get("system_type")
    old_username = request.POST.get("old_username")
    participant_id = request.POST.get("participant_id")
    new_start_date = request.POST.get("new_start_date")  # Split start date from frontend
    new_end_date = request.POST.get("new_end_date")

    def parse_dt(dt_str):
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return make_aware(datetime.strptime(dt_str, fmt))
            except Exception:
                continue
        return None

    new_start_dt = parse_dt(new_start_date) if new_start_date else None
    new_end_dt = parse_dt(new_end_date)
    if not (system_type and old_username and participant_id and new_end_dt):
        return JsonResponse({"success": False, "error": "Missing or invalid data."}, status=400)
    old_user = User.objects.filter(username=old_username).first()
    if not old_user:
        return JsonResponse({"success": False, "error": "Old user not found."}, status=404)
    stream_obj = get_stream_or_404(stream, request=request)
    allocation = (
        SystemAllocation.objects.filter(system_type=system_type, user=old_user, stream=stream_obj)
        .order_by("-end_date")
        .first()
    )
    if not allocation:
        return JsonResponse({"success": False, "error": "No active allocation found."}, status=404)
    # The new allocation must start after the original allocation ends, or at a specified new_start_dt
    orig_end = allocation.end_date
    split_start = new_start_dt if new_start_dt and new_start_dt > allocation.start_date else orig_end
    new_user = None
    participant = None
    if participant_id.startswith("user_"):
        try:
            user_id = int(participant_id.split("_")[1])
            new_user = User.objects.get(id=user_id)
        except Exception:
            return JsonResponse({"success": False, "error": "User not found."}, status=404)
    elif participant_id.startswith("participant_"):
        try:
            part_id = int(participant_id.split("_")[1])
            participant = Participant.objects.get(id=part_id)
            new_user = User.objects.filter(email=participant.email).first()
            if not new_user:
                new_user = User.objects.filter(username=participant.name).first()
            if not new_user:
                # Use admin as user, but set blocked_for_participant
                new_user = request.user
        except Participant.DoesNotExist:
            return JsonResponse({"success": False, "error": "Participant not found."}, status=404)
    else:
        return JsonResponse({"success": False, "error": "Invalid participant selection."}, status=400)
    overlap = SystemAllocation.objects.filter(
        system_type=system_type, start_date__lt=new_end_dt, end_date__gt=split_start, user=new_user, stream=stream_obj
    ).exists()
    if overlap:
        return JsonResponse(
            {"success": False, "error": "System already blocked for this period for the new user."}, status=409
        )
    new_alloc = SystemAllocation.objects.create(
        system_type=system_type,
        user=new_user,
        start_date=split_start,
        end_date=new_end_dt,
        blocked_for_participant=participant,
        stream=stream_obj,
    )
    if old_user != new_user:
        Notification.notify(
            old_user,
            f"Your system allocation for {system_type} was released and re-allocated to another user by admin.",
            "allocation",
        )
    # Only delete the original allocation if the new allocation exactly matches the original's start and end
    if split_start == allocation.start_date and new_end_dt == allocation.end_date:
        allocation.delete()
    AuditLog.log(
        "update",
        "Changed system allocation",
        user=request.user,
        request=request,
        module="allocation",
        severity="warning",
        stream=stream_obj,
    )
    return JsonResponse({"success": True, "new_allocation_id": new_alloc.id})


@login_required
def location_list(request, stream=None):
    """Location list."""
    if not stream or stream.strip() == "":
        stream = "PIC"

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    stream_obj = get_stream_or_404(stream, default="PIC")

    locations = Location.objects.filter(stream=stream_obj).order_by("-created_at")

    show_onboarding_tour = not OnboardingProgress.objects.filter(user=request.user, tour_key="location_list").exists()

    return render(
        request,
        "products/location_list.html",
        {
            "locations": locations,
            "stream": stream,
            "selected_stream": stream,
            "show_onboarding_tour": show_onboarding_tour,
        },
    )


@login_required
def location_create(request, stream=None):
    """Location create."""
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    if not _fac_granted(request.user) and not request.user.is_superuser:
        messages.error(request, "Only admins can add locations.")
        return redirect("location_list_stream", stream=stream or get_default_stream_name(request))
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        address = request.POST.get("address", "").strip()
        stream_obj = get_stream_or_404(stream, request=request)
        if name:
            location = Location.objects.create(name=name, address=address, stream=stream_obj)
            AuditLog.log(
                action="create",
                title=f"Created location: {name}",
                user=request.user,
                request=request,
                obj=location,
                module="systems",
                severity="info",
                stream=stream_obj,
            )
            messages.success(request, "Location added successfully.")
            return redirect("location_list_stream", stream=stream or get_default_stream_name(request))
        return render(
            request,
            "products/location_form.html",
            {"form_error": "Location name is required.", "stream": stream, "selected_stream": stream},
        )
    return render(request, "products/location_form.html", {"stream": stream, "selected_stream": stream})


@login_required
def location_edit(request, pk, stream=None):
    """Location edit."""
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    stream_obj = get_stream_or_404(stream, request=request)

    location = get_object_or_404(Location, pk=pk, stream=stream_obj)
    if not _fac_granted(request.user) and not request.user.is_superuser:
        messages.error(request, "Only admins can modify locations.")
        return redirect("location_list_stream", stream=stream)
    if request.method == "POST":
        location.name = request.POST.get("name", "").strip()
        location.address = request.POST.get("address", "").strip()
        location.save()
        AuditLog.log(
            action="update",
            title=f"Updated location: {location.name}",
            user=request.user,
            request=request,
            obj=location,
            module="systems",
            severity="info",
            stream=stream_obj,
        )
        messages.success(request, "Location updated successfully.")
        return redirect("location_list_stream", stream=stream)
    return render(
        request,
        "products/location_form.html",
        {"location": location, "edit": True, "stream": stream, "selected_stream": stream},
    )


@login_required
def location_delete(request, pk, stream=None):
    """Location delete."""
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    stream_obj = get_stream_or_404(stream, request=request)

    try:
        location = Location.objects.get(pk=pk, stream=stream_obj)
    except Location.DoesNotExist:
        messages.warning(request, "Location already deleted.")
        return redirect("location_list_stream", stream=stream)
    if not _fac_granted(request.user) and not request.user.is_superuser:
        messages.error(request, "Only admins can remove locations.")
        return redirect("location_list_stream", stream=stream)
    if request.method == "POST":
        AuditLog.log(
            action="delete",
            title=f"Deleted location: {location.name}",
            user=request.user,
            request=request,
            obj=location,
            module="systems",
            severity="warning",
            stream=stream_obj,
        )
        location.delete()
        messages.success(request, "Location removed successfully.")
        return redirect("location_list_stream", stream=stream)
    return render(
        request,
        "products/location_confirm_delete.html",
        {"location": location, "stream": stream, "selected_stream": stream},
    )
