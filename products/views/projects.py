"""Products app — Projects views."""

# pylint: disable=broad-exception-caught,import-error,invalid-name,logging-too-many-args,no-else-return
# pylint: disable=relative-beyond-top-level,too-many-lines

import json as _json
from datetime import datetime as _dt

from ..models import (
    ProjectAttachment,
    ProjectDependency,
    ProjectMilestone,
    ResourceAllocation,
    ResourceAllocationLock,
    ResourceAllocationYear,
    ResourceComponentType,
    ResourcePerson,
)
from ..approval_triggers import check_approval_required, fire_approval_trigger
from ._helpers import (
    AuditLog,
    JsonResponse,
    Notification,
    Project,
    Stream,
    User,
    check_password,
    date,
    datetime,
    get_bu_streams,
    is_admin,
    is_app_admin,
    is_super_admin,
    json,
    logger,
    login_required,
    messages,
    never_cache,
    redirect,
    render,
    require_POST,
    timezone,
    transaction,
)

__all__ = [
    "project_status",
    "delete_project",
    "project_milestone_api",
    "project_attachment_api",
    "project_dependency_api",
    "resource_allocation_api",
]


@login_required
@never_cache
def project_status(request):  # noqa: C901, CCR001
    """View to manage projects - list, create, edit, delete."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    # Get user's accessible streams scoped to current BU
    bu_streams = get_bu_streams(request)
    if bu_streams.exists():
        stream_obj = bu_streams.first()
    else:
        stream_obj = Stream.objects.filter(is_active=True).first()

    if not stream_obj:
        messages.error(request, "No active streams available.")
        return redirect("dashboard")

    # Import here to avoid circular imports

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create":
            # Create new project
            try:
                # Get selected stream from form or use default
                selected_stream_id = request.POST.get("stream")
                if selected_stream_id:
                    try:
                        project_stream = bu_streams.get(id=selected_stream_id)
                    except Stream.DoesNotExist:
                        project_stream = stream_obj  # fallback to default
                else:
                    project_stream = stream_obj  # use default if not specified

                # Parse dates safely
                start_date_str = request.POST.get("start_date", "").strip()
                initial_release_str = request.POST.get("initial_release_date", "").strip()
                final_release_str = request.POST.get("final_release_date", "").strip()

                if not start_date_str:
                    messages.error(request, "Start date is required.")
                    return redirect("project_status")

                try:
                    start_date_val = _dt.strptime(start_date_str, "%Y-%m-%d").date()
                except ValueError:
                    messages.error(request, "Invalid start date format.")
                    return redirect("project_status")

                initial_release_val = None
                if initial_release_str:
                    try:
                        initial_release_val = _dt.strptime(initial_release_str, "%Y-%m-%d").date()
                    except ValueError:
                        pass

                final_release_val = None
                if final_release_str:
                    try:
                        final_release_val = _dt.strptime(final_release_str, "%Y-%m-%d").date()
                    except ValueError:
                        pass

                project_name = request.POST.get("name", "").strip()
                if not project_name:
                    messages.error(request, "Project name is required.")
                    return redirect("project_status")

                project = Project.objects.create(
                    name=project_name,
                    description=request.POST.get("description", ""),
                    duration=request.POST.get("duration", ""),
                    start_date=start_date_val,
                    initial_release_date=initial_release_val,
                    final_release_date=final_release_val,
                    status=request.POST.get("status", "running"),
                    priority=request.POST.get("priority", "medium"),
                    progress_percentage=int(request.POST.get("progress_percentage", 0)),
                    stream=project_stream,
                    created_by=request.user,
                )

                # Calculate expected progress if running, otherwise set to 0
                if project.status == "running":
                    project.expected_progress = project.calculate_expected_progress()
                else:
                    project.expected_progress = 0
                project.save()

                # Handle team members if provided
                team_member_ids = request.POST.getlist("team_members")
                if team_member_ids:
                    project.team_members.set(team_member_ids)

                AuditLog.log(
                    action="create",
                    title=f"Created project: {project.name}",
                    user=request.user,
                    request=request,
                    obj=project,
                    module="projects",
                    severity="info",
                    stream=stream_obj,
                )
                messages.success(request, f'Project "{project.name}" created successfully!')
                team = project.team_members.exclude(id=request.user.id)
                if team.exists():
                    Notification.notify(team, f"You've been added to project '{project.name}'.", "project")
            except Exception:
                logger.exception("Failed to create project")
                messages.error(request, "Failed to create project")

        elif action == "update":
            # Update existing project
            try:
                project_id = request.POST.get("project_id")
                project = Project.objects.get(id=project_id, stream__in=bu_streams)
                project.name = request.POST.get("name")
                project.description = request.POST.get("description", "")
                project.duration = request.POST.get("duration", "")
                # Parse and assign start_date
                start_date_str = request.POST.get("start_date")
                if start_date_str:
                    try:
                        project.start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                    except Exception:
                        logger.warning("Could not parse start_date: %s", start_date_str)
                        project.start_date = None
                else:
                    project.start_date = None
                # Parse and assign initial_release_date
                initial_release_date_str = request.POST.get("initial_release_date")
                if initial_release_date_str:
                    try:
                        project.initial_release_date = datetime.strptime(initial_release_date_str, "%Y-%m-%d").date()
                    except Exception:
                        logger.warning("Could not parse initial_release_date: %s", initial_release_date_str)
                        project.initial_release_date = None
                else:
                    project.initial_release_date = None
                # Parse and assign final_release_date
                final_release_date_str = request.POST.get("final_release_date")
                if final_release_date_str:
                    try:
                        project.final_release_date = datetime.strptime(final_release_date_str, "%Y-%m-%d").date()
                    except Exception:
                        logger.warning("Could not parse final_release_date: %s", final_release_date_str)
                        project.final_release_date = None
                else:
                    project.final_release_date = None
                project.status = request.POST.get("status", "running")
                project.priority = request.POST.get("priority", "medium")
                project.progress_percentage = int(request.POST.get("progress_percentage", 0))

                # ── Pre-action enforcement for significant project status changes ──
                _proj_approval = None
                _old_proj_status = Project.objects.filter(pk=project.pk).values_list("status", flat=True).first()
                _STATUS_EVENTS = {
                    "cancelled": "project_cancelled",
                    "hold": "project_on_hold",
                    "completed": "project_completed",
                }
                if (
                    _old_proj_status
                    and _old_proj_status != project.status
                    and project.status in _STATUS_EVENTS
                ):
                    _proj_approval = check_approval_required(
                        _STATUS_EVENTS[project.status],
                        stream_obj.business_unit,
                        request.user,
                        entity_obj=project,
                        stream=stream_obj,
                        title=f"Project '{project.name}' \u2192 {project.get_status_display()}",
                        description=f"Project {project.name} status change from {_old_proj_status} to {project.status}",
                        intended_changes={
                            "action_type": "status_change",
                            "model_label": "products.Project",
                            "pk": project.pk,
                            "changes": {"status": project.status},
                            "revert": {"status": _old_proj_status},
                            "metadata": {"entity_name": project.name},
                        },
                    )
                    if _proj_approval:
                        project.status = _old_proj_status  # revert — keep old status until approved
                        messages.warning(request, f'\u23f3 Changing project "{project.name}" to {project.get_status_display()} requires approval. Request #{_proj_approval.id} submitted.')

                # Calculate expected progress if running, otherwise set to 0
                if project.status == "running":
                    project.expected_progress = project.calculate_expected_progress()
                else:
                    project.expected_progress = 0
                project.save()

                # Handle team members
                team_member_ids = request.POST.getlist("team_members")
                if team_member_ids:
                    project.team_members.set(team_member_ids)
                else:
                    project.team_members.clear()
                AuditLog.log(
                    action="update",
                    title=f"Updated project: {project.name}",
                    user=request.user,
                    request=request,
                    obj=project,
                    module="projects",
                    severity="info",
                    stream=stream_obj,
                )
                messages.success(request, f'Project "{project.name}" updated successfully!') if not _proj_approval else None
                team = project.team_members.exclude(id=request.user.id)
                if team.exists():
                    Notification.notify(team, f"Project '{project.name}' has been updated.", "project")
            except Project.DoesNotExist:
                messages.error(request, "Project not found.")
            except Exception:
                messages.error(request, "An error occurred. Please try again.")

        elif action == "update_status":
            # AJAX request to update just the project status (for drag and drop)
            try:
                project_id = request.POST.get("project_id")
                new_status = request.POST.get("status")

                if new_status not in ["running", "hold", "planned", "completed", "cancelled"]:
                    return JsonResponse({"success": False, "error": "Invalid status"})

                project = Project.objects.get(id=project_id, stream__in=bu_streams)
                old_status = project.status
                project.status = new_status

                # ── Pre-action enforcement for significant status changes ──
                _STATUS_EVENTS_DD = {
                    "cancelled": "project_cancelled",
                    "hold": "project_on_hold",
                    "completed": "project_completed",
                }
                if old_status != new_status and new_status in _STATUS_EVENTS_DD:
                    _proj_approval = check_approval_required(
                        _STATUS_EVENTS_DD[new_status],
                        stream_obj.business_unit,
                        request.user,
                        entity_obj=project,
                        stream=stream_obj,
                        title=f"Project '{project.name}' \u2192 {project.get_status_display()}",
                        description=f"Project {project.name} status change from {old_status} to {new_status}",
                        intended_changes={
                            "action_type": "status_change",
                            "model_label": "products.Project",
                            "pk": project.pk,
                            "changes": {"status": new_status},
                            "revert": {"status": old_status},
                            "metadata": {"entity_name": project.name},
                        },
                    )
                    if _proj_approval:
                        return JsonResponse({
                            "success": False,
                            "error": f"Changing project '{project.name}' to {project.get_status_display()} requires approval. Request #{_proj_approval.id} submitted.",
                            "approval_required": True,
                            "approval_id": _proj_approval.id,
                        }, status=202)

                # Calculate expected progress if running, otherwise set to 0
                if project.status == "running":
                    project.expected_progress = project.calculate_expected_progress()
                else:
                    project.expected_progress = 0
                project.save()

                AuditLog.log(
                    action="status_change",
                    title=f"Changed project status to {project.status}: {project.name}",
                    user=request.user,
                    request=request,
                    obj=project,
                    module="projects",
                    severity="info",
                    stream=stream_obj,
                )
                return JsonResponse(
                    {
                        "success": True,
                        "message": f"Project status is now {project.status}",
                        "project_id": project_id,
                        "new_status": project.status,
                    }
                )
            except Project.DoesNotExist:
                return JsonResponse({"success": False, "error": "Project not found"})
            except Exception:
                logger.exception("Operation failed")
                return JsonResponse({"success": False, "error": "An unexpected error occurred"})

        return redirect("project_status")

    # GET request - display project list scoped to current BU
    projects = (
        Project.objects.filter(stream__in=bu_streams)
        .select_related("created_by", "stream")
        .prefetch_related(
            "team_members",
            "milestones",
            "attachments",
            "dependencies_from__to_project",
            "dependencies_to__from_project",
        )
    )

    # Get all users for team member selection
    users = User.objects.filter(is_active=True).order_by("username")

    # Get all active streams for project assignment — scoped to current BU
    all_streams = bu_streams.order_by("name")

    # Prepare project data as JSON for Gantt chart and dependencies
    projects_json = _json.dumps(
        [
            {
                "id": p.id,
                "name": p.name,
                "status": p.status,
                "priority": p.priority,
                "start_date": p.start_date.isoformat() if p.start_date else None,
                "initial_release_date": p.initial_release_date.isoformat() if p.initial_release_date else None,
                "final_release_date": p.final_release_date.isoformat() if p.final_release_date else None,
                "progress": p.progress_percentage,
                "expected_progress": p.expected_progress,
                "milestones": [
                    {"id": m.id, "name": m.name, "due_date": m.due_date.isoformat(), "is_completed": m.is_completed}
                    for m in p.milestones.all()
                ],
                "dependencies": [
                    {
                        "id": d.id,
                        "to_project_id": d.to_project_id,
                        "to_project_name": d.to_project.name,
                        "type": d.dependency_type,
                    }
                    for d in p.dependencies_from.all()
                ],
                "team_member_ids": list(p.team_members.values_list("id", flat=True)),
            }
            for p in projects
        ]
    )

    context = {
        "selected_stream": stream_obj.name,
        "stream": stream_obj,
        "projects": projects,
        "projects_json": projects_json,
        "users": users,
        "all_streams": all_streams,
    }

    return render(request, "products/project_status.html", context)


@login_required
@require_POST
def delete_project(request):
    """Delete a project with password confirmation (admin only)."""
    # RBAC: Only admins can delete projects
    if not (is_admin(request.user) or is_super_admin(request.user) or is_app_admin(request.user)):
        return JsonResponse(
            {"success": False, "error": "Permission denied. Only administrators can delete projects."}, status=403
        )

    # Get user's accessible streams scoped to current BU
    bu_streams_qs = get_bu_streams(request)
    if bu_streams_qs.exists():
        stream_obj = bu_streams_qs.first()
    else:
        stream_obj = Stream.objects.filter(is_active=True).first()

    if not stream_obj:
        return JsonResponse({"success": False, "error": "No active streams available"}, status=400)

    try:
        data = json.loads(request.body)
        project_id = data.get("project_id")
        password = data.get("password")

        # Verify password
        if not check_password(password, request.user.password):
            return JsonResponse({"success": False, "error": "Invalid password"}, status=400)

        # Delete project
        project = Project.objects.get(id=project_id, stream__in=bu_streams_qs)
        project_name = project.name
        AuditLog.log(
            action="delete",
            title=f"Deleted project: {project.name}",
            user=request.user,
            request=request,
            obj=project,
            module="projects",
            severity="warning",
            stream=stream_obj,
        )
        project.delete()

        return JsonResponse({"success": True, "message": f'Project "{project_name}" deleted successfully'})

    except Project.DoesNotExist:
        return JsonResponse({"success": False, "error": "Project not found"}, status=404)
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)


# =============================================
# PROJECT MILESTONES, ATTACHMENTS, DEPENDENCIES
# =============================================


@login_required
def project_milestone_api(request):
    """CRUD API for project milestones."""
    bu_streams = get_bu_streams(request)

    if request.method == "POST":
        try:
            data = json.loads(request.body)
            action = data.get("action", "create")

            if action == "create":
                project = Project.objects.get(id=data["project_id"], stream__in=bu_streams)
                milestone = ProjectMilestone.objects.create(
                    project=project,
                    name=data["name"],
                    description=data.get("description", ""),
                    due_date=data["due_date"],
                )
                return JsonResponse({"success": True, "id": milestone.id, "message": "Milestone created"})

            elif action == "toggle":
                milestone = ProjectMilestone.objects.get(id=data["milestone_id"], project__stream__in=bu_streams)
                milestone.is_completed = not milestone.is_completed
                milestone.completed_at = timezone.now() if milestone.is_completed else None
                milestone.save()
                return JsonResponse({"success": True, "is_completed": milestone.is_completed})

            elif action == "delete":
                milestone = ProjectMilestone.objects.get(id=data["milestone_id"], project__stream__in=bu_streams)
                milestone.delete()
                return JsonResponse({"success": True, "message": "Milestone deleted"})

        except Exception:
            logger.exception("Milestone API error")
            return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=400)

    elif request.method == "GET":
        project_id = request.GET.get("project_id")
        milestones = ProjectMilestone.objects.filter(project_id=project_id, project__stream__in=bu_streams)
        data = [
            {
                "id": m.id,
                "name": m.name,
                "description": m.description,
                "due_date": m.due_date.isoformat(),
                "is_completed": m.is_completed,
            }
            for m in milestones
        ]
        return JsonResponse({"success": True, "milestones": data})

    return JsonResponse({"success": False, "error": "Invalid method"}, status=405)


@login_required
def project_attachment_api(request):
    """Upload/delete file attachments for projects."""
    bu_streams = get_bu_streams(request)

    if request.method == "POST":
        try:
            project_id = request.POST.get("project_id")
            project = Project.objects.get(id=project_id, stream__in=bu_streams)

            files = request.FILES.getlist("files")
            created = []
            for f in files:
                att = ProjectAttachment.objects.create(
                    project=project,
                    file=f,
                    original_filename=f.name,
                    uploaded_by=request.user,
                )
                created.append(
                    {
                        "id": att.id,
                        "name": att.original_filename,
                        "size": att.file_size_display,
                        "ext": att.file_extension,
                    }
                )
            return JsonResponse({"success": True, "attachments": created})
        except Exception:
            logger.exception("Attachment upload error")
            return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=400)

    elif request.method == "DELETE":
        try:
            data = json.loads(request.body)
            att = ProjectAttachment.objects.get(id=data["attachment_id"], project__stream__in=bu_streams)
            att.file.delete(save=False)
            att.delete()
            return JsonResponse({"success": True, "message": "Attachment deleted"})
        except Exception:
            logger.exception("Attachment delete error")
            return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=400)

    elif request.method == "GET":
        project_id = request.GET.get("project_id")
        atts = ProjectAttachment.objects.filter(project_id=project_id, project__stream__in=bu_streams).select_related(
            "uploaded_by"
        )
        data = [
            {
                "id": a.id,
                "name": a.original_filename,
                "size": a.file_size_display,
                "ext": a.file_extension,
                "url": a.file.url,
                "uploaded_by": a.uploaded_by.username if a.uploaded_by else "Unknown",
                "created_at": a.created_at.strftime("%b %d, %Y"),
            }
            for a in atts
        ]
        return JsonResponse({"success": True, "attachments": data})

    return JsonResponse({"success": False, "error": "Invalid method"}, status=405)


@login_required
def project_dependency_api(request):
    """CRUD API for project dependencies."""
    # pylint: disable=too-many-return-statements
    bu_streams = get_bu_streams(request)

    if request.method == "POST":
        try:
            data = json.loads(request.body)
            action = data.get("action", "create")

            if action == "create":
                from_project = Project.objects.get(id=data["from_project_id"], stream__in=bu_streams)
                to_project = Project.objects.get(id=data["to_project_id"], stream__in=bu_streams)
                if from_project.id == to_project.id:
                    return JsonResponse({"success": False, "error": "Cannot create dependency to self"}, status=400)
                dep, created = ProjectDependency.objects.get_or_create(
                    from_project=from_project,
                    to_project=to_project,
                    dependency_type=data.get("dependency_type", "relates_to"),
                    defaults={"created_by": request.user},
                )
                if not created:
                    return JsonResponse({"success": False, "error": "Dependency already exists"}, status=400)
                return JsonResponse({"success": True, "id": dep.id, "message": "Dependency created"})

            elif action == "delete":
                dep = ProjectDependency.objects.get(id=data["dependency_id"], from_project__stream__in=bu_streams)
                dep.delete()
                return JsonResponse({"success": True, "message": "Dependency deleted"})

        except Exception:
            logger.exception("Dependency API error")
            return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=400)

    elif request.method == "GET":
        project_id = request.GET.get("project_id")
        deps = ProjectDependency.objects.filter(
            from_project_id=project_id, from_project__stream__in=bu_streams
        ).select_related("to_project")
        data = [
            {
                "id": d.id,
                "to_project_id": d.to_project_id,
                "to_project_name": d.to_project.name,
                "dependency_type": d.dependency_type,
                "dependency_type_display": d.get_dependency_type_display(),
            }
            for d in deps
        ]
        return JsonResponse({"success": True, "dependencies": data})

    return JsonResponse({"success": False, "error": "Invalid method"}, status=405)


# =============================================
# RESOURCE ALLOCATION (FTE TRACKING) API
# =============================================


@login_required
def resource_allocation_api(request):  # noqa: C901, CCR001
    """GET  → return all persons + their monthly allocations for a given year.

    POST → bulk-upsert allocation cells
    """
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-statements
    bu_streams = get_bu_streams(request)
    if not bu_streams.exists():
        return JsonResponse({"success": False, "error": "No streams available"}, status=400)

    year = int(request.GET.get("year", date.today().year))

    if request.method == "GET":
        persons = (
            ResourcePerson.objects.filter(stream__in=bu_streams, is_active=True, show_in_allocation=True)
            .select_related("component")
            .order_by("name")
        )

        projects = Project.objects.filter(stream__in=bu_streams).order_by("name")

        allocations = ResourceAllocation.objects.filter(
            person__stream__in=bu_streams,
            year=year,
        ).select_related("person", "project")

        # Build lookup: (person_id, project_id, month) -> allocation
        alloc_map = {}
        for a in allocations:
            alloc_map[(a.person_id, a.project_id, a.month)] = float(a.allocation)

        # Component types
        components = ResourceComponentType.objects.filter(stream__in=bu_streams, is_active=True).order_by(
            "sort_order", "name"
        )

        # Find persons who have allocation records for this year
        person_ids_with_allocs = set(
            ResourceAllocation.objects.filter(person__stream__in=bu_streams, year=year)
            .order_by()
            .values_list("person_id", flat=True)
            .distinct()
        )

        persons_data = []
        for p in persons:
            # Only show persons who have allocation records for this year
            if p.id not in person_ids_with_allocs:
                continue

            # Get all allocation rows for this person in this year, grouped by project
            person_projects = (
                ResourceAllocation.objects.filter(person=p, year=year)
                .order_by()
                .values_list("project_id", flat=True)
                .distinct()
            )

            base = {
                "id": p.id,
                "component_id": p.component_id,
                "component_name": p.component.name if p.component else "",
                "fte_type": p.fte_type,
                "name": p.name,
                "emp_id": p.emp_id,
                "manager": p.manager,
                "location": p.location,
                "role": p.role,
            }

            if not person_projects:
                persons_data.append(
                    {
                        **base,
                        "project_id": None,
                        "project_name": "",
                        "months": {m: 0 for m in range(1, 13)},  # noqa: C420
                    }
                )
            else:
                for proj_id in person_projects:
                    proj = projects.filter(id=proj_id).first()
                    months = {}
                    for m in range(1, 13):
                        months[m] = alloc_map.get((p.id, proj_id, m), 0)
                    persons_data.append(
                        {
                            **base,
                            "project_id": proj_id,
                            "project_name": proj.name if proj else "",
                            "months": months,
                        }
                    )

        projects_list = [{"id": pr.id, "name": pr.name} for pr in projects]
        components_list = [{"id": c.id, "name": c.name} for c in components]

        # Configured years (deduplicated across streams)
        configured_years = sorted(
            set(
                ResourceAllocationYear.objects.filter(stream__in=bu_streams, is_active=True).values_list(
                    "year", flat=True
                )
            )
        )

        return JsonResponse(
            {
                "success": True,
                "year": year,
                "persons": persons_data,
                "projects": projects_list,
                "components": components_list,
                "configured_years": configured_years,
            }
        )

    # POST — bulk upsert allocations
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            entries = data.get("entries", [])
            save_year = data.get("year", year)

            # Get locked months to enforce server-side
            locked_months = set(
                ResourceAllocationLock.objects.filter(stream__in=bu_streams, year=save_year).values_list(
                    "month", flat=True
                )
            )

            with transaction.atomic():
                # Collect the set of (person_id, project_id) combos submitted
                submitted_combos = set()
                for entry in entries:
                    pid = entry.get("person_id")
                    prid = entry.get("project_id")
                    if pid and prid:
                        submitted_combos.add((int(pid), int(prid)))

                # Get all person IDs that were submitted
                submitted_person_ids = set(pid for pid, _ in submitted_combos)  # noqa: C401

                # For each submitted person, delete allocation records for
                # (person, project) combos that are NO LONGER in the grid
                for person_id in submitted_person_ids:
                    current_project_ids = [prid for pid, prid in submitted_combos if pid == person_id]
                    ResourceAllocation.objects.filter(
                        person_id=person_id,
                        year=save_year,
                    ).exclude(
                        project_id__in=current_project_ids,
                    ).delete()

                # Upsert allocation entries
                for entry in entries:
                    person_id = entry.get("person_id")
                    project_id = entry.get("project_id")
                    month = int(entry.get("month"))
                    value = entry.get("allocation", 0)

                    if not person_id or not project_id:
                        continue

                    # Skip locked months (server-side enforcement)
                    if month in locked_months:
                        continue

                    alloc_val = float(value) if value else 0

                    ResourceAllocation.objects.update_or_create(
                        person_id=person_id,
                        project_id=project_id,
                        year=save_year,
                        month=month,
                        defaults={
                            "allocation": alloc_val,
                            "created_by": request.user,
                        },
                    )

            return JsonResponse({"success": True, "message": "Allocations saved"})
        except Exception:
            logger.exception("Failed to save allocations")
            return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)

    return JsonResponse({"success": False, "error": "Invalid method"}, status=405)
