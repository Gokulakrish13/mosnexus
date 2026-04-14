"""Products app - Holistic Dashboard, System Downtime, Build Servers, Floor and OS views."""

# pylint: disable=broad-exception-caught

import json as _json

from ._helpers import (
    AuditLog,
    HolisticSystem,
    HolisticSystemHistory,
    HolisticWeeklyData,
    IntegrityError,
    Project,
    Q,
    check_user_access,
    date,
    get_bu_streams,
    get_default_stream_name,
    get_object_or_404,
    get_stream_or_404,
    login_required,
    logout,
    messages,
    redirect,
    render,
    timedelta,
)

__all__ = [
    "holistic_dashboard",
    "holistic_system_create",
    "holistic_system_edit",
    "holistic_system_delete",
    "holistic_system_detail",
]


@login_required
def holistic_dashboard(request, stream=None):  # noqa: C901, CCR001
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-complex
    """Main view for the advanced holistic dashboard."""
    # Handle stream — default to first BU stream
    bu_streams = get_bu_streams(request)
    if stream:
        stream_obj = get_stream_or_404(stream)
        # Validate the stream belongs to the current BU
        if bu_streams.exists() and not bu_streams.filter(pk=stream_obj.pk).exists():
            stream_obj = bu_streams.first()
            stream = stream_obj.name if stream_obj else "HIC"
    else:
        stream_name = request.GET.get("stream", "")
        if stream_name:
            stream_obj = get_stream_or_404(stream_name)
            if bu_streams.exists() and not bu_streams.filter(pk=stream_obj.pk).exists():
                stream_obj = bu_streams.first()
        else:
            stream_obj = bu_streams.first() if bu_streams.exists() else get_stream_or_404("HIC")
        stream = stream_obj.name if stream_obj else "HIC"

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    # Get filter parameters
    status_filter = request.GET.get("status", "")
    search_query = request.GET.get("q", "").strip()
    week_filter = request.GET.get("week", "")

    # Base queryset
    systems = HolisticSystem.objects.filter(stream=stream_obj).select_related("created_by", "updated_by")

    # Apply filters
    if status_filter:
        systems = systems.filter(system_availability=status_filter)

    if search_query:
        systems = systems.filter(
            Q(sr_no__icontains=search_query)
            | Q(system_owner__icontains=search_query)
            | Q(stmi_number__icontains=search_query)
            | Q(test_engineer__icontains=search_query)
            | Q(location_info__icontains=search_query)
        )

    # Get current week
    current_week = date.today().isocalendar()[1]
    current_year = date.today().year

    # Get all unique weeks for dropdown
    all_weeks = HolisticWeeklyData.objects.values("week_number", "year").distinct().order_by("-year", "-week_number")

    # Prepare week data and project IDs for each system
    for system in systems:
        if week_filter:
            try:
                # Expecting format W47-2025
                if "-" in week_filter:
                    week_part, year_part = week_filter.split("-")
                    week_num = int(week_part.replace("W", ""))
                    year_num = int(year_part)
                else:
                    week_num = int(week_filter.replace("W", ""))
                    year_num = current_year
                system.current_week_data = system.weekly_data.filter(week_number=week_num, year=year_num).first()
            except Exception:
                system.current_week_data = system.get_current_week_data()
        else:
            system.current_week_data = system.get_current_week_data()

        # If the week is in the past, set utilization_percentage to 100 for display
        if system.current_week_data:
            week_is_past = (system.current_week_data.year < current_year) or (
                system.current_week_data.year == current_year and system.current_week_data.week_number < current_week
            )
            if week_is_past:
                system.current_week_data.utilization_percentage = 100

        # Precompute current project ID for template (if any)
        current_project_id = None
        if system.current_week_data and system.current_week_data.project:
            current_project_id = system.current_week_data.project.id
        system.current_project_id_json = _json.dumps(current_project_id)

        # Get project timeline for this system
        system.project_timeline = system.get_project_timeline()

        # Serialize allocation period info
        system.allocation_period_json = _json.dumps(system.get_allocation_status_display_text())

    # Calculate statistics
    total_systems = systems.count()
    available_count = systems.filter(system_availability="available").count()
    allocated_count = systems.filter(system_availability="allocated").count()
    maintenance_count = systems.filter(system_availability="maintenance").count()
    offline_count = systems.filter(system_availability="offline").count()
    reserved_count = systems.filter(system_availability="reserved").count()

    # Get recent weeks for display (last 8 weeks)
    recent_weeks = []
    for i in range(8):
        week_date = date.today() - timedelta(weeks=i)
        week_num = week_date.isocalendar()[1]
        week_year = week_date.year
        recent_weeks.append(
            {"week": week_num, "year": week_year, "label": f"W{week_num}", "value": f"W{week_num}-{week_year}"}
        )

    bu_streams = get_bu_streams(request)
    projects = Project.objects.filter(stream__in=bu_streams).order_by("name")
    context = {
        "systems": systems,
        "stream": stream,
        "selected_stream": stream,
        "status_filter": status_filter,
        "search_query": search_query,
        "week_filter": week_filter,
        "all_weeks": all_weeks,
        "recent_weeks": recent_weeks,
        "current_week": current_week,
        "current_year": current_year,
        "total_systems": total_systems,
        "available_count": available_count,
        "allocated_count": allocated_count,
        "maintenance_count": maintenance_count,
        "offline_count": offline_count,
        "reserved_count": reserved_count,
        "status_choices": HolisticSystem.STATUS_CHOICES,
        "projects": projects,
    }

    return render(request, "products/holistic_dashboard.html", context)


@login_required
def holistic_system_create(request, stream=None):
    """Create a new holistic system."""
    stream = stream or get_default_stream_name(request)
    stream_obj = get_stream_or_404(stream)

    if request.method == "POST":
        try:
            # Create system
            allocation_start = request.POST.get("allocation_start_date") or None
            allocation_end = request.POST.get("allocation_end_date") or None
            allocation_project_id = request.POST.get("allocation_project") or None

            system = HolisticSystem.objects.create(
                sr_no=request.POST.get("sr_no"),
                system_availability=request.POST.get("system_availability", "available"),
                allocation_to_sl_no=request.POST.get("allocation_to_sl_no"),
                location_info=request.POST.get("location_info"),
                stmi_number=request.POST.get("stmi_number"),
                system_owner=request.POST.get("system_owner"),
                ecr_number=request.POST.get("ecr_number"),
                test_engineer=request.POST.get("test_engineer"),
                description=request.POST.get("description"),
                notes=request.POST.get("notes"),
                priority=request.POST.get("priority", "medium"),
                allocation_start_date=allocation_start,
                allocation_end_date=allocation_end,
                allocation_project_id=allocation_project_id,
                stream=stream_obj,
                created_by=request.user,
                updated_by=request.user,
            )

            # Create history entry
            HolisticSystemHistory.objects.create(
                holistic_system=system, action="created", user=request.user, details=f"System {system.sr_no} created"
            )

            AuditLog.log(
                action="create",
                title=f"Created holistic system: {system.sr_no}",
                user=request.user,
                request=request,
                obj=system,
                module="holistic",
                severity="info",
                stream=stream_obj,
            )
            return redirect("holistic_dashboard")

        except IntegrityError:
            form_error = "A system with this Serial Number already exists."
        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    bu_streams = get_bu_streams(request)
    projects = Project.objects.filter(stream__in=bu_streams).order_by("name")

    context = {
        "stream": stream,
        "selected_stream": stream,
        "status_choices": HolisticSystem.STATUS_CHOICES,
        "edit": False,
        "form_error": form_error,
        "projects": projects,
    }

    return render(request, "products/holistic_system_form.html", context)


@login_required
def holistic_system_edit(request, pk, stream=None):  # noqa: CCR001
    """Edit an existing holistic system."""
    stream = stream or get_default_stream_name(request)
    stream_obj = get_stream_or_404(stream)

    system = get_object_or_404(HolisticSystem, pk=pk, stream=stream_obj)

    if request.method == "POST":
        try:
            changes = []
            old_values = {
                "sr_no": system.sr_no,
                "system_availability": system.system_availability,
                "allocation_to_sl_no": system.allocation_to_sl_no,
                "location_info": system.location_info,
                "stmi_number": system.stmi_number,
                "system_owner": system.system_owner,
                "ecr_number": system.ecr_number,
                "test_engineer": system.test_engineer,
                "description": system.description,
                "notes": system.notes,
                "priority": system.priority,
            }

            system.sr_no = request.POST.get("sr_no")
            system.system_availability = request.POST.get("system_availability")
            system.allocation_to_sl_no = request.POST.get("allocation_to_sl_no")
            system.location_info = request.POST.get("location_info")
            system.stmi_number = request.POST.get("stmi_number")
            system.system_owner = request.POST.get("system_owner")
            system.ecr_number = request.POST.get("ecr_number")
            system.test_engineer = request.POST.get("test_engineer")
            system.description = request.POST.get("description")
            system.notes = request.POST.get("notes")
            system.priority = request.POST.get("priority", "medium")
            system.allocation_start_date = request.POST.get("allocation_start_date") or None
            system.allocation_end_date = request.POST.get("allocation_end_date") or None
            system.allocation_project_id = request.POST.get("allocation_project") or None
            system.updated_by = request.user

            for field, old_value in old_values.items():
                new_value = getattr(system, field)
                if old_value != new_value:
                    changes.append(f"{field}: '{old_value}' → '{new_value}'")

            system.save()

            if changes:
                HolisticSystemHistory.objects.create(
                    holistic_system=system, action="edited", user=request.user, details="; ".join(changes)
                )

            AuditLog.log(
                action="update",
                title=f"Updated holistic system: {system.sr_no}",
                user=request.user,
                request=request,
                obj=system,
                module="holistic",
                severity="info",
                stream=stream_obj,
            )
            messages.success(request, f"System {system.sr_no} updated successfully!")
            return redirect("holistic_dashboard")

        except IntegrityError:
            form_error = "A system with this Serial Number already exists."
        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    bu_streams = get_bu_streams(request)
    projects = Project.objects.filter(stream__in=bu_streams).order_by("name")

    context = {
        "system": system,
        "stream": stream,
        "selected_stream": stream,
        "status_choices": HolisticSystem.STATUS_CHOICES,
        "edit": True,
        "form_error": form_error,
        "projects": projects,
    }

    return render(request, "products/holistic_system_form.html", context)


@login_required
def holistic_system_delete(request, pk, stream=None):
    """Delete a holistic system."""
    stream = stream or get_default_stream_name(request)
    stream_obj = get_stream_or_404(stream)

    system = get_object_or_404(HolisticSystem, pk=pk, stream=stream_obj)

    if request.method == "POST":
        sr_no = system.sr_no
        AuditLog.log(
            action="delete",
            title=f"Deleted holistic system: {system.sr_no}",
            user=request.user,
            request=request,
            obj=system,
            module="holistic",
            severity="warning",
            stream=stream_obj,
        )
        system.delete()
        messages.success(request, f"System {sr_no} deleted successfully!")
        return redirect("holistic_dashboard")

    context = {
        "system": system,
        "stream": stream,
        "selected_stream": stream,
    }

    return render(request, "products/holistic_system_confirm_delete.html", context)


@login_required
def holistic_system_detail(request, pk, stream=None):
    """View detailed information about a holistic system."""
    stream = stream or get_default_stream_name(request)
    stream_obj = get_stream_or_404(stream)

    system = get_object_or_404(HolisticSystem, pk=pk, stream=stream_obj)

    weekly_data = system.weekly_data.all().order_by("-year", "-week_number")[:20]

    history = system.history.all().order_by("-timestamp")[:50]

    context = {
        "system": system,
        "weekly_data": weekly_data,
        "history": history,
        "stream": stream,
        "selected_stream": stream,
    }

    return render(request, "products/holistic_system_detail.html", context)
