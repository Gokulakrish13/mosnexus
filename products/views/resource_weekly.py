"""Products app - Resource Weekly Allocations, Person API, Cell Notes, Lock, Compare views."""

# pylint: disable=broad-exception-caught,import-error,invalid-name,logging-too-many-args,no-else-return
# pylint: disable=relative-beyond-top-level,too-many-lines

from collections import defaultdict

from ..models import (
    ResourceAllocation,
    ResourceAllocationLock,
    ResourceAllocationYear,
    ResourceCellNote,
    ResourceComponentType,
    ResourcePerson,
)
from ._helpers import (
    AuditLog,
    JsonResponse,
    Project,
    date,
    get_bu_streams,
    json,
    logger,
    login_required,
    timedelta,
    transaction,
)

__all__ = [
    "resource_weekly_allocation_api",
    "resource_person_api",
    "resource_cell_note_api",
    "resource_allocation_lock_api",
    "resource_allocation_compare_api",
]


@login_required
def resource_weekly_allocation_api(request):  # noqa: C901, CCR001
    """Weekly view is derived from monthly ResourceAllocation data.

    GET  → split monthly values evenly across weeks in each month
    POST → aggregate weekly cell values back to monthly totals, save to ResourceAllocation
    """
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-statements
    bu_streams = get_bu_streams(request)
    if not bu_streams.exists():
        return JsonResponse({"success": False, "error": "No streams available"}, status=400)

    year = int(request.GET.get("year", date.today().year))

    # Determine week range based on optional filters
    quarter = request.GET.get("quarter")
    month_filter = request.GET.get("month")

    # Build ISO week info for this year
    week_info = []
    seen_weeks = set()
    d = date(year, 1, 1)
    while d.year <= year:
        iso_year, iso_week, _ = d.isocalendar()
        if iso_year == year and iso_week not in seen_weeks:
            seen_weeks.add(iso_week)
            week_start = d - timedelta(days=d.weekday())
            week_end = week_start + timedelta(days=6)
            m = week_start.month if week_start.year == year else week_end.month
            q = (m - 1) // 3 + 1
            week_info.append(
                {
                    "week": iso_week,
                    "start": week_start.strftime("%b %d"),
                    "end": week_end.strftime("%b %d"),
                    "month": m,
                    "quarter": q,
                    "label": f"W{iso_week}",
                }
            )
        d += timedelta(days=1)
        if d.year > year and d.month > 1:
            break

    week_info.sort(key=lambda w: w["week"])  # type: ignore[arg-type, return-value]

    # Build month → list of week numbers mapping
    month_to_weeks = defaultdict(list)
    week_to_month = {}
    for w in week_info:
        month_to_weeks[w["month"]].append(w["week"])
        week_to_month[w["week"]] = w["month"]

    # Filter by quarter or month
    if quarter:
        q = int(quarter)
        week_info = [w for w in week_info if w["quarter"] == q]
    elif month_filter:
        mf = int(month_filter)
        week_info = [w for w in week_info if w["month"] == mf]

    week_numbers = [w["week"] for w in week_info]

    if request.method == "GET":
        persons = (
            ResourcePerson.objects.filter(stream__in=bu_streams, is_active=True, show_in_allocation=True)
            .select_related("component")
            .order_by("name")
        )

        projects = Project.objects.filter(stream__in=bu_streams).order_by("name")

        # Read MONTHLY allocations as the source of truth
        allocations = ResourceAllocation.objects.filter(person__stream__in=bu_streams, year=year).select_related(
            "person", "project"
        )

        alloc_map = {}  # (person_id, project_id, month) -> float
        for a in allocations:
            alloc_map[(a.person_id, a.project_id, a.month)] = float(a.allocation)

        person_ids_with_allocs = set(
            ResourceAllocation.objects.filter(person__stream__in=bu_streams, year=year)
            .order_by()
            .values_list("person_id", flat=True)
            .distinct()
        )

        components = ResourceComponentType.objects.filter(stream__in=bu_streams, is_active=True).order_by(
            "sort_order", "name"
        )

        persons_data = []
        for p in persons:
            if p.id not in person_ids_with_allocs:
                continue

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
                weeks = {w: 0 for w in week_numbers}  # noqa: C420
                persons_data.append({**base, "project_id": None, "project_name": "", "weeks": weeks})
            else:
                for proj_id in person_projects:
                    proj = projects.filter(id=proj_id).first()
                    weeks = {}
                    for wn in week_numbers:
                        m = week_to_month[wn]  # type: ignore[assignment]
                        monthly_val = alloc_map.get((p.id, proj_id, m), 0)
                        num_weeks_in_month = len(month_to_weeks[m])
                        weeks[wn] = (
                            round(monthly_val / num_weeks_in_month, 4)  # type: ignore[assignment]
                            if num_weeks_in_month
                            else 0
                        )
                    persons_data.append(
                        {
                            **base,
                            "project_id": proj_id,
                            "project_name": proj.name if proj else "",
                            "weeks": weeks,
                        }
                    )

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
                "week_info": week_info,
                "month_to_weeks": {str(m): wks for m, wks in month_to_weeks.items()},
                "persons": persons_data,
                "projects": [{"id": pr.id, "name": pr.name} for pr in projects],
                "components": [{"id": c.id, "name": c.name} for c in components],
                "configured_years": configured_years,
            }
        )

    # POST — aggregate weekly values back to monthly, save to ResourceAllocation
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            entries = data.get("entries", [])
            save_year = data.get("year", year)

            # Aggregate by (person_id, project_id, month)
            monthly_totals: dict[tuple, float] = defaultdict(float)  # (pid, prid, month) -> sum
            submitted_combos = set()

            for entry in entries:
                pid = entry.get("person_id")
                prid = entry.get("project_id")
                wk = int(entry.get("week", 0))
                val = float(entry.get("allocation", 0) or 0)
                if not pid or not prid or not wk:
                    continue
                pid, prid = int(pid), int(prid)
                submitted_combos.add((pid, prid))
                m = week_to_month.get(wk)  # type: ignore[assignment]
                if m:
                    monthly_totals[(pid, prid, m)] += val

            with transaction.atomic():
                submitted_person_ids = set(pid for pid, _ in submitted_combos)  # noqa: C401

                # Clean up removed project combos
                for person_id in submitted_person_ids:
                    current_project_ids = [prid for pid, prid in submitted_combos if pid == person_id]
                    ResourceAllocation.objects.filter(
                        person_id=person_id,
                        year=save_year,
                    ).exclude(
                        project_id__in=current_project_ids,
                    ).delete()

                # Upsert monthly values
                for (pid, prid, m), total in monthly_totals.items():
                    ResourceAllocation.objects.update_or_create(
                        person_id=pid,
                        project_id=prid,
                        year=save_year,
                        month=m,
                        defaults={
                            "allocation": round(total, 2),
                            "created_by": request.user,
                        },
                    )

            return JsonResponse({"success": True, "message": "Allocations saved (synced to monthly)"})
        except Exception:
            logger.exception("Failed to save weekly allocations")
            return JsonResponse({"success": False, "error": "Failed to save weekly allocations"}, status=500)

    return JsonResponse({"success": False, "error": "Invalid method"}, status=405)


@login_required
def resource_person_api(request):  # noqa: C901, CCR001
    """GET  → list all active resource persons (for dropdown/search).

    POST → create or update a resource person
    DELETE → deactivate a resource person
    """
    # pylint: disable=too-complex,too-many-branches,too-many-return-statements,too-many-statements
    bu_streams = get_bu_streams(request)
    if not bu_streams.exists():
        return JsonResponse({"success": False, "error": "No streams available"}, status=400)

    if request.method == "GET":
        persons = (
            ResourcePerson.objects.filter(stream__in=bu_streams, is_active=True)
            .select_related("component")
            .order_by("name")
        )
        data = []
        for p in persons:
            data.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "emp_id": p.emp_id,
                    "fte_type": p.fte_type,
                    "role": p.role,
                    "manager": p.manager,
                    "location": p.location,
                    "component_id": p.component_id,
                    "component_name": p.component.name if p.component else "",
                }
            )
        return JsonResponse({"success": True, "persons": data})

    stream_obj = bu_streams.first()

    if request.method == "POST":
        try:
            data = json.loads(request.body)
            person_id = data.get("id")

            if person_id:
                # Update
                person = ResourcePerson.objects.get(id=person_id, stream__in=bu_streams)
                person.fte_type = data.get("fte_type", person.fte_type)
                person.name = data.get("name", person.name)
                person.emp_id = data.get("emp_id", person.emp_id)
                person.manager = data.get("manager", person.manager)
                person.location = data.get("location", person.location)
                person.role = data.get("role", person.role)
                comp_id = data.get("component_id")
                person.component_id = int(comp_id) if comp_id else None
                person.save()
                AuditLog.log(
                    action="update",
                    title=f"Updated resource person: {person.name}",
                    user=request.user,
                    request=request,
                    obj=person,
                    module="projects",
                    severity="info",
                    stream=stream_obj,
                )
                return JsonResponse({"success": True, "id": person.id, "message": "Person updated"})
            else:
                # Create
                comp_id = data.get("component_id")
                person = ResourcePerson.objects.create(
                    stream=stream_obj,
                    component_id=int(comp_id) if comp_id else None,
                    fte_type=data.get("fte_type", "FTE"),
                    name=data.get("name", ""),
                    emp_id=data.get("emp_id", ""),
                    manager=data.get("manager", ""),
                    location=data.get("location", ""),
                    role=data.get("role", ""),
                    created_by=request.user,
                )
                AuditLog.log(
                    action="create",
                    title=f"Created resource person: {person.name}",
                    user=request.user,
                    request=request,
                    obj=person,
                    module="projects",
                    severity="info",
                    stream=stream_obj,
                )
                return JsonResponse({"success": True, "id": person.id, "message": "Person created"})
        except ResourcePerson.DoesNotExist:
            return JsonResponse({"success": False, "error": "Person not found"}, status=404)
        except Exception:
            logger.exception("resource_person_api error")
            return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)

    if request.method == "DELETE":
        try:
            data = json.loads(request.body)
            person_id = data.get("id")
            deactivate = data.get("deactivate", False)  # True = config page delete, False = allocation page remove
            person = ResourcePerson.objects.get(id=person_id, stream__in=bu_streams)
            person_name = person.name
            if deactivate:
                person.is_active = False
                person.show_in_allocation = False
                person.save()
                action_label = "Deactivated"
            else:
                # Year-specific removal: only delete allocations for the given year
                remove_year = data.get("year")
                if remove_year:
                    deleted_count, _ = ResourceAllocation.objects.filter(person=person, year=int(remove_year)).delete()
                    action_label = f"Removed from {remove_year} allocation ({deleted_count} records)"
                else:
                    # Fallback: hide from all years
                    person.show_in_allocation = False
                    person.save()
                    action_label = "Removed from allocation"
            AuditLog.log(
                action="delete",
                title=f"{action_label} resource person: {person_name}",
                user=request.user,
                request=request,
                obj=person,
                module="projects",
                severity="warning",
                stream=stream_obj,
            )
            return JsonResponse({"success": True, "message": f"{person_name} {action_label.lower()}"})
        except ResourcePerson.DoesNotExist:
            return JsonResponse({"success": False, "error": "Person not found"}, status=404)
        except Exception as exc:
            logger.exception("resource_person_api delete error: %s", exc)
            return JsonResponse({"success": False, "error": str(exc)}, status=500)

    return JsonResponse({"success": False, "error": "Invalid method"}, status=405)


# ── Cell Notes API ────────────────────────────────────────────────────────────


@login_required
def resource_cell_note_api(request):  # noqa: C901, CCR001
    """GET → notes for a year, POST → save note, DELETE → remove note."""
    # pylint: disable=too-complex,too-many-return-statements
    bu_streams = get_bu_streams(request)
    if not bu_streams.exists():
        return JsonResponse({"success": False, "error": "No streams"}, status=400)

    if request.method == "GET":
        year = int(request.GET.get("year", date.today().year))
        notes = ResourceCellNote.objects.filter(person__stream__in=bu_streams, year=year).select_related("created_by")
        data = {}
        for n in notes:
            key = f"{n.person_id}-{n.project_id}-{n.month}"
            data[key] = {
                "id": n.id,
                "note": n.note,
                "created_by": n.created_by.get_full_name() if n.created_by else "",
                "updated_at": n.updated_at.strftime("%Y-%m-%d %H:%M"),
            }
        return JsonResponse({"success": True, "notes": data})

    if request.method == "POST":
        try:
            d = json.loads(request.body)
            person_id, project_id = int(d["person_id"]), int(d["project_id"])
            year, month = int(d["year"]), int(d["month"])
            note_text = d.get("note", "").strip()
            if not note_text:
                ResourceCellNote.objects.filter(
                    person_id=person_id, project_id=project_id, year=year, month=month
                ).delete()
                return JsonResponse({"success": True, "message": "Note removed"})
            obj, _ = ResourceCellNote.objects.update_or_create(
                person_id=person_id,
                project_id=project_id,
                year=year,
                month=month,
                defaults={"note": note_text, "created_by": request.user},
            )
            return JsonResponse({"success": True, "message": "Note saved", "id": obj.id})
        except Exception as exc:
            logger.exception("cell_note_api error: %s", exc)
            return JsonResponse({"success": False, "error": str(exc)}, status=500)

    if request.method == "DELETE":
        try:
            d = json.loads(request.body)
            ResourceCellNote.objects.filter(id=int(d["id"]), person__stream__in=bu_streams).delete()
            return JsonResponse({"success": True, "message": "Note deleted"})
        except Exception as exc:
            return JsonResponse({"success": False, "error": str(exc)}, status=500)

    return JsonResponse({"success": False, "error": "Invalid method"}, status=405)


# ── Allocation Lock API ───────────────────────────────────────────────────────


@login_required
def resource_allocation_lock_api(request):  # noqa: C901, CCR001
    """GET → locked months for a year, POST → lock, DELETE → unlock."""
    # pylint: disable=too-complex,too-many-return-statements
    bu_streams = get_bu_streams(request)
    if not bu_streams.exists():
        return JsonResponse({"success": False, "error": "No streams"}, status=400)
    stream_obj = bu_streams.first()

    if request.method == "GET":
        year = int(request.GET.get("year", date.today().year))
        locks = ResourceAllocationLock.objects.filter(stream__in=bu_streams, year=year).select_related("locked_by")
        data = {}
        for lk in locks:
            data[str(lk.month)] = {
                "id": lk.id,
                "locked_by": lk.locked_by.get_full_name() if lk.locked_by else "",
                "locked_at": lk.locked_at.strftime("%Y-%m-%d %H:%M"),
                "reason": lk.reason,
            }
        return JsonResponse({"success": True, "locks": data})

    quarter_months = {1: [1, 2, 3], 2: [4, 5, 6], 3: [7, 8, 9], 4: [10, 11, 12]}

    if request.method == "POST":
        try:
            d = json.loads(request.body)
            year = int(d["year"])
            reason = d.get("reason", "")
            quarter = d.get("quarter")
            months = quarter_months[int(quarter)] if quarter else [int(d["month"])]
            for m in months:
                ResourceAllocationLock.objects.update_or_create(
                    stream=stream_obj, year=year, month=m, defaults={"locked_by": request.user, "reason": reason}
                )
            label = f"Q{quarter}" if quarter else f"Month {months[0]}"
            return JsonResponse({"success": True, "message": f"{label} locked"})
        except Exception:
            return JsonResponse({"success": False, "error": "An error occurred"}, status=500)

    if request.method == "DELETE":
        try:
            d = json.loads(request.body)
            year = int(d["year"])
            quarter = d.get("quarter")
            months = quarter_months[int(quarter)] if quarter else [int(d["month"])]
            ResourceAllocationLock.objects.filter(stream__in=bu_streams, year=year, month__in=months).delete()
            label = f"Q{quarter}" if quarter else f"Month {months[0]}"
            return JsonResponse({"success": True, "message": f"{label} unlocked"})
        except Exception:
            return JsonResponse({"success": False, "error": "An error occurred"}, status=500)

    return JsonResponse({"success": False, "error": "Invalid method"}, status=405)


# ── Compare Years API ─────────────────────────────────────────────────────────


@login_required
def resource_allocation_compare_api(request):  # noqa: CCR001
    """GET → allocation data for two years side-by-side."""
    bu_streams = get_bu_streams(request)
    if not bu_streams.exists():
        return JsonResponse({"success": False, "error": "No streams"}, status=400)

    year_a = int(request.GET.get("year_a", date.today().year))
    year_b = int(request.GET.get("year_b", date.today().year + 1))

    persons = (
        ResourcePerson.objects.filter(stream__in=bu_streams, is_active=True)
        .select_related("component")
        .order_by("name")
    )

    projects = Project.objects.filter(stream__in=bu_streams)
    proj_map = {p.id: p.name for p in projects}

    def build_year_data(yr):
        allocs = ResourceAllocation.objects.filter(person__stream__in=bu_streams, year=yr)
        alloc_map = {}
        for a in allocs:
            alloc_map[(a.person_id, a.project_id, a.month)] = float(a.allocation)
        pid_set = set(allocs.order_by().values_list("person_id", flat=True).distinct())
        rows = []
        for p in persons:
            if p.id not in pid_set:
                continue
            for pid in allocs.filter(person=p).order_by().values_list("project_id", flat=True).distinct():
                months = {m: alloc_map.get((p.id, pid, m), 0) for m in range(1, 13)}
                rows.append(
                    {
                        "person_id": p.id,
                        "name": p.name,
                        "component": p.component.name if p.component else "",
                        "fte_type": p.fte_type,
                        "project": proj_map.get(pid, ""),
                        "months": months,
                        "total": round(sum(months.values()), 2),
                    }
                )
        return rows

    return JsonResponse(
        {
            "success": True,
            "year_a": year_a,
            "data_a": build_year_data(year_a),
            "year_b": year_b,
            "data_b": build_year_data(year_b),
        }
    )


# ── Excel Import API ─────────────────────────────────────────────────────────
