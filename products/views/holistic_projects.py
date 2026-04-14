"""Products app - Holistic Project Assignments, Systems List, and Graph Data views."""

# pylint: disable=broad-exception-caught

from io import StringIO

from ._helpers import (
    HolisticSystem,
    HolisticSystemHistory,
    HolisticWeeklyData,
    HttpResponse,
    JsonResponse,
    Project,
    csv,
    date,
    json,
    logger,
    login_required,
)

__all__ = [
    "holistic_assign_project_to_week",
    "holistic_get_week_data",
    "holistic_get_project_assignments",
    "holistic_all_systems_list",
    "holistic_graph_data",
    "holistic_export_graph_data",
]


@login_required
def holistic_assign_project_to_week(request):
    """Holistic assign project to week."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"})
    try:
        data = json.loads(request.body.decode("utf-8"))
        system_id = data.get("system_id")
        project_id = data.get("project_id")
        week_number = data.get("week_number")
        year = data.get("year", date.today().year)

        # Allocation period fields (optional)
        allocation_start = data.get("allocation_start_date")
        allocation_end = data.get("allocation_end_date")

        system = HolisticSystem.objects.get(id=system_id)
        project = Project.objects.get(id=project_id) if project_id else None

        weekly_data, _created = HolisticWeeklyData.objects.get_or_create(
            holistic_system=system, week_number=week_number, year=year, defaults={"updated_by": request.user}
        )

        weekly_data.project = project
        weekly_data.updated_by = request.user
        weekly_data.save()

        # Update allocation period on the system if provided
        if allocation_start or allocation_end:
            if allocation_start:
                system.allocation_start_date = allocation_start
            if allocation_end:
                system.allocation_end_date = allocation_end
            system.allocation_project = project
            system.updated_by = request.user
            system.save()

        action = (
            f"Assigned project '{project.name}' to week W{week_number} {year}"
            if project
            else f"Removed project from week W{week_number} {year}"
        )
        HolisticSystemHistory.objects.create(
            holistic_system=system, action="project_assigned", user=request.user, details=action
        )

        return JsonResponse({"success": True, "message": f"Project assignment updated for week W{week_number}"})
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@login_required
def holistic_get_week_data(request):
    """Holistic get week data."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"})
    try:
        data = json.loads(request.body.decode("utf-8"))
        system_id = data.get("system_id")
        week_number = data.get("week_number")
        year = data.get("year")

        system = HolisticSystem.objects.get(id=system_id)

        try:
            weekly_data = HolisticWeeklyData.objects.get(holistic_system=system, week_number=week_number, year=year)

            week_data = {
                "week_number": weekly_data.week_number,
                "year": weekly_data.year,
                "allocation_status": weekly_data.allocation_status or "",
                "utilization_percentage": (
                    float(weekly_data.utilization_percentage) if weekly_data.utilization_percentage else 0
                ),
                "assigned_to": weekly_data.assigned_to or "",
                "hours_used": float(weekly_data.hours_used) if weekly_data.hours_used else 0,
                "availability_hours": float(weekly_data.availability_hours) if weekly_data.availability_hours else 40,
                "task_description": weekly_data.task_description or "",
                "notes": weekly_data.notes or "",
                "project_id": weekly_data.project_id,
            }

            return JsonResponse({"success": True, "week_data": week_data})

        except HolisticWeeklyData.DoesNotExist:
            week_data = {
                "week_number": week_number,
                "year": year,
                "allocation_status": "",
                "utilization_percentage": 0,
                "assigned_to": "",
                "hours_used": 0,
                "availability_hours": 40,
                "task_description": "",
                "notes": "",
            }

            return JsonResponse({"success": False, "week_data": week_data})

    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@login_required
def holistic_get_project_assignments(request):  # noqa: CCR001
    """Holistic get project assignments."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"})
    try:
        data = json.loads(request.body.decode("utf-8"))
        system_id = data.get("system_id")

        system = HolisticSystem.objects.get(id=system_id)
        weekly_data = system.weekly_data.select_related("project").order_by("year", "week_number")

        assignments = []
        for week in weekly_data:
            assignments.append(
                {
                    "week_number": week.week_number,
                    "year": week.year,
                    "project_id": week.project.id if week.project else None,
                    "project_name": week.project.name if week.project else None,
                    "allocation_status": week.allocation_status or "",
                    "utilization": float(week.utilization_percentage) if week.utilization_percentage else 0,
                    "assigned_to": week.assigned_to or "",
                }
            )

        # Include allocation period info
        allocation_period = None
        if system.allocation_start_date and system.allocation_end_date:
            remaining = (system.allocation_end_date - date.today()).days
            allocation_period = {
                "start": system.allocation_start_date.isoformat(),
                "end": system.allocation_end_date.isoformat(),
                "project": system.allocation_project.name if system.allocation_project else None,
                "project_id": system.allocation_project.id if system.allocation_project else None,
                "remaining_days": remaining,
                "is_active": system.allocation_start_date <= date.today() <= system.allocation_end_date,
            }

        return JsonResponse({"success": True, "assignments": assignments, "allocation_period": allocation_period})
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@login_required
def holistic_all_systems_list(request):
    """Fetch list of all systems for selection."""
    try:
        systems = HolisticSystem.objects.all().select_related("created_by").order_by("sr_no")

        systems_data = []
        for system in systems:
            weekly_data = system.weekly_data.all()
            utilizations = [
                float(w.utilization_percentage) for w in weekly_data if w.utilization_percentage is not None
            ]
            avg_utilization = sum(utilizations) / len(utilizations) if utilizations else 0
            systems_data.append(
                {
                    "id": system.id,
                    "sr_no": system.sr_no,
                    "status": system.get_system_availability_display(),
                    "owner": system.system_owner or "-",
                    "location": system.location_info or "-",
                    "stmi": system.stmi_number or "-",
                    "priority": (
                        system.get_priority_display()
                        if hasattr(system, "get_priority_display")
                        else system.priority or "-"
                    ),
                    "avg_utilization": round(avg_utilization, 2),
                }
            )

        return JsonResponse({"success": True, "systems": systems_data})

    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)


@login_required
def holistic_graph_data(request, system_id):  # noqa: CCR001
    """Fetch allocation data for graph visualization."""
    try:
        system = HolisticSystem.objects.get(id=system_id)

        weekly_data = HolisticWeeklyData.objects.filter(holistic_system=system).order_by("year", "week_number")

        weekly_data_list = []
        utilization_values = []

        for week in weekly_data:
            project_name = week.project.name if week.project else "Unassigned"

            utilization = float(week.utilization_percentage) if week.utilization_percentage else 0
            utilization_values.append(utilization)

            weekly_data_list.append(
                {
                    "week": week.week_number,
                    "year": week.year,
                    "status": week.allocation_status or system.get_system_availability_display(),
                    "project_name": project_name,
                    "utilization": utilization,
                    "hours_used": float(week.hours_used) if week.hours_used else 0,
                    "assigned_to": week.assigned_to or "-",
                }
            )

        project_distribution = []
        project_weeks: dict[str, int] = {}

        for week in weekly_data_list:
            project_name = week["project_name"]
            if project_name in project_weeks:
                project_weeks[project_name] += 1
            else:
                project_weeks[project_name] = 1

        for project_name, weeks_count in project_weeks.items():
            project_distribution.append({"project_name": project_name, "weeks_count": weeks_count})

        avg_utilization = sum(utilization_values) / len(utilization_values) if utilization_values else 0
        max_utilization = max(utilization_values) if utilization_values else 0

        response_data = {
            "success": True,
            "system": {
                "id": system.id,
                "name": system.sr_no,
                "status": system.get_system_availability_display(),
                "owner": system.system_owner,
                "location": system.location_info,
            },
            "weekly_data": weekly_data_list,
            "project_distribution": project_distribution,
            "statistics": {
                "total_weeks": len(weekly_data_list),
                "avg_utilization": avg_utilization,
                "max_utilization": max_utilization,
                "unique_projects": len(project_weeks),
            },
        }

        return JsonResponse(response_data)

    except HolisticSystem.DoesNotExist:
        return JsonResponse({"success": False, "error": "System not found"}, status=404)
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)


@login_required
def holistic_export_graph_data(request, system_id):
    """Export system allocation data as CSV."""
    try:
        system = HolisticSystem.objects.get(id=system_id)
        weekly_data = HolisticWeeklyData.objects.filter(holistic_system=system).order_by("year", "week_number")

        output = StringIO()
        writer = csv.writer(output)

        writer.writerow(
            [
                "System Name",
                "Week",
                "Year",
                "Status",
                "Allocation Status",
                "Utilization %",
                "Hours Used",
                "Available Hours",
                "Assigned To",
                "Task Description",
                "Notes",
            ]
        )

        for week in weekly_data:
            writer.writerow(
                [
                    system.sr_no,
                    f"W{week.week_number}",
                    week.year,
                    system.get_system_availability_display(),
                    week.allocation_status or "-",
                    float(week.utilization_percentage) or 0,
                    float(week.hours_used) or 0,
                    float(week.availability_hours) or 40,
                    week.assigned_to or "-",
                    week.task_description or "-",
                    week.notes or "-",
                ]
            )

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="system_{system.sr_no}_allocation.csv"'
        return response

    except HolisticSystem.DoesNotExist:
        return JsonResponse({"error": "System not found"}, status=404)
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"error": "An unexpected error occurred"}, status=500)


# ================================
# DOWNTIME TRACKING VIEWS
# ================================
