"""Products app - Floor and Operating System Management views."""

from ._helpers import (
    AuditLog,
    BuildServer,
    Floor,
    IntegrityError,
    OperatingSystem,
    get_object_or_404,
    get_stream_or_404,
    login_required,
    messages,
    redirect,
    render,
)

__all__ = [
    "floor_list",
    "floor_create",
    "floor_edit",
    "floor_delete",
    "operating_system_list",
    "operating_system_create",
    "operating_system_edit",
    "operating_system_delete",
]


@login_required
def floor_list(request, stream=None):
    """List all floors with management options for specific stream."""
    stream_obj = get_stream_or_404(stream)
    floors = Floor.objects.filter(stream=stream_obj).order_by("name")

    context = {
        "floors": floors,
        "stream": stream,
        "stream_obj": stream_obj,
        "selected_stream": stream_obj,
    }
    return render(request, "products/floor_list.html", context)


@login_required
def floor_create(request, stream=None):
    """Create a new floor for specific stream."""
    stream_obj = get_stream_or_404(stream)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"

        if name:
            try:
                floor = Floor.objects.create(name=name, description=description, stream=stream_obj, is_active=is_active)
                AuditLog.log(
                    action="create",
                    title=f"Created floor: {floor.name}",
                    user=request.user,
                    request=request,
                    obj=floor,
                    module="systems",
                    severity="info",
                    stream=stream_obj,
                )
                messages.success(request, f'Floor "{name}" created successfully for {stream_obj.name} stream!')
                return redirect("floor_list", stream=stream)
            except IntegrityError:
                form_error = f'Floor "{name}" already exists in {stream_obj.name} stream!'
        else:
            form_error = "Floor name is required!"
    else:
        form_error = None

    context = {
        "is_edit": False,
        "title": "Add New Floor",
        "stream": stream,
        "stream_obj": stream_obj,
        "selected_stream": stream_obj,
        "form_error": form_error,
    }
    return render(request, "products/floor_form.html", context)


@login_required
def floor_edit(request, stream=None, floor_id=None):
    """Edit an existing floor within specific stream."""
    stream_obj = get_stream_or_404(stream)
    floor = get_object_or_404(Floor, id=floor_id, stream=stream_obj)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"

        if name:
            try:
                floor.name = name
                floor.description = description
                floor.is_active = is_active
                floor.save()
                AuditLog.log(
                    action="update",
                    title=f"Updated floor: {floor.name}",
                    user=request.user,
                    request=request,
                    obj=floor,
                    module="systems",
                    severity="info",
                    stream=stream_obj,
                )
                messages.success(request, f'Floor "{name}" updated successfully!')
                return redirect("floor_list", stream=stream)
            except IntegrityError:
                form_error = f'Floor "{name}" already exists in {stream_obj.name} stream!'
        else:
            form_error = "Floor name is required!"
    else:
        form_error = None

    context = {
        "floor": floor,
        "is_edit": True,
        "title": "Edit Floor",
        "stream": stream,
        "stream_obj": stream_obj,
        "selected_stream": stream_obj,
        "form_error": form_error,
    }
    return render(request, "products/floor_form.html", context)


@login_required
def floor_delete(request, stream=None, floor_id=None):
    """Delete a floor within specific stream."""
    stream_obj = get_stream_or_404(stream)
    floor = get_object_or_404(Floor, id=floor_id, stream=stream_obj)

    if request.method == "POST":
        servers_using_floor = BuildServer.objects.filter(floor=floor).count()

        if servers_using_floor > 0:
            messages.error(
                request,
                f'Cannot delete floor "{floor.name}" as it is being used by {servers_using_floor} build server(s)!',
            )
        else:
            floor_name = floor.name
            AuditLog.log(
                action="delete",
                title=f"Deleted floor: {floor.name}",
                user=request.user,
                request=request,
                obj=floor,
                module="systems",
                severity="warning",
                stream=stream_obj,
            )
            floor.delete()
            messages.success(request, f'Floor "{floor_name}" deleted successfully!')

        return redirect("floor_list", stream=stream)

    context = {
        "floor": floor,
        "servers_count": BuildServer.objects.filter(floor=floor).count(),
        "stream": stream,
        "stream_obj": stream_obj,
        "selected_stream": stream_obj,
    }
    return render(request, "products/floor_confirm_delete.html", context)


@login_required
def operating_system_list(request, stream=None):
    """List all operating systems with management options for specific stream."""
    stream_obj = get_stream_or_404(stream)
    operating_systems = OperatingSystem.objects.filter(stream=stream_obj).order_by("name", "version")

    context = {
        "operating_systems": operating_systems,
        "stream": stream,
        "stream_obj": stream_obj,
        "selected_stream": stream_obj,
    }
    return render(request, "products/operating_system_list.html", context)


@login_required
def operating_system_create(request, stream=None):
    """Create a new operating system for specific stream."""
    stream_obj = get_stream_or_404(stream)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        version = request.POST.get("version", "").strip() or None
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"

        if name:
            try:
                os_obj = OperatingSystem.objects.create(
                    name=name, version=version, description=description, stream=stream_obj, is_active=is_active
                )
                AuditLog.log(
                    action="create",
                    title=f"Created operating system: {os_obj}",
                    user=request.user,
                    request=request,
                    obj=os_obj,
                    module="systems",
                    severity="info",
                    stream=stream_obj,
                )
                messages.success(
                    request, f'Operating System "{os_obj}" created successfully for {stream_obj.name} stream!'
                )
                return redirect("operating_system_list", stream=stream)
            except IntegrityError:
                form_error = (
                    f'Operating System "{name}" with version "{version or "N/A"}" '
                    f"already exists in {stream_obj.name} stream!"
                )
        else:
            form_error = "Operating System name is required!"
    else:
        form_error = None

    context = {
        "is_edit": False,
        "title": "Add New Operating System",
        "stream": stream,
        "stream_obj": stream_obj,
        "selected_stream": stream_obj,
        "form_error": form_error,
    }
    return render(request, "products/operating_system_form.html", context)


@login_required
def operating_system_edit(request, stream=None, os_id=None):
    """Edit an existing operating system within specific stream."""
    stream_obj = get_stream_or_404(stream)
    os_obj = get_object_or_404(OperatingSystem, id=os_id, stream=stream_obj)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        version = request.POST.get("version", "").strip() or None
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"

        if name:
            try:
                os_obj.name = name
                os_obj.version = version
                os_obj.description = description
                os_obj.is_active = is_active
                os_obj.save()
                AuditLog.log(
                    action="update",
                    title=f"Updated operating system: {os_obj}",
                    user=request.user,
                    request=request,
                    obj=os_obj,
                    module="systems",
                    severity="info",
                    stream=stream_obj,
                )
                messages.success(request, f'Operating System "{os_obj}" updated successfully!')
                return redirect("operating_system_list", stream=stream)
            except IntegrityError:
                form_error = (
                    f'Operating System "{name}" with version "{version or "N/A"}" '
                    f"already exists in {stream_obj.name} stream!"
                )
        else:
            form_error = "Operating System name is required!"
    else:
        form_error = None

    context = {
        "os": os_obj,
        "is_edit": True,
        "title": "Edit Operating System",
        "stream": stream,
        "stream_obj": stream_obj,
        "selected_stream": stream_obj,
        "form_error": form_error,
    }
    return render(request, "products/operating_system_form.html", context)


@login_required
def operating_system_delete(request, stream=None, os_id=None):
    """Delete an operating system within specific stream."""
    stream_obj = get_stream_or_404(stream)
    os_obj = get_object_or_404(OperatingSystem, id=os_id, stream=stream_obj)

    if request.method == "POST":
        servers_using_os = BuildServer.objects.filter(operating_system=os_obj).count()

        if servers_using_os > 0:
            messages.error(
                request,
                f'Cannot delete Operating System "{os_obj}" as it is being used by {servers_using_os} build server(s)!',
            )
        else:
            os_name = str(os_obj)
            AuditLog.log(
                action="delete",
                title=f"Deleted operating system: {os_obj}",
                user=request.user,
                request=request,
                obj=os_obj,
                module="systems",
                severity="warning",
                stream=stream_obj,
            )
            os_obj.delete()
            messages.success(request, f'Operating System "{os_name}" deleted successfully!')

        return redirect("operating_system_list", stream=stream)

    context = {
        "os": os_obj,
        "servers_count": BuildServer.objects.filter(operating_system=os_obj).count(),
        "stream": stream,
        "stream_obj": stream_obj,
        "selected_stream": stream_obj,
    }
    return render(request, "products/operating_system_confirm_delete.html", context)


# =============================================================================
# UNIFIED BOOKING HUB & RECURRING RESERVATIONS VIEWS
# =============================================================================
