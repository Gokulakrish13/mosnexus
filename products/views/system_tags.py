"""Products app - System Tags, Allocation Tree, and Tag Management views."""

# pylint: disable=broad-exception-caught,undefined-variable

from ._helpers import (
    AuditLog,
    JsonResponse,
    Product,
    Project,
    SubLevel,
    SubLevelTool,
    System,
    SystemAllocation,
    SystemTag,
    SystemTagHistory,
    can_delete_products,
    can_edit_products,
    check_user_access,
    get_default_stream_name,
    get_stream_or_404,
    logger,
    login_required,
    logout,
    messages,
    redirect,
    render,
    require_GET,
    require_POST,
    timedelta,
    timezone,
)

__all__ = [
    "allocation_tree",
    "create_system_tag",
    "delete_system_tag",
    "manage_tag_items",
    "get_system_tag_history",
    "get_available_items",
]


@login_required
def allocation_tree(request, stream=None):
    """Display tree structure of systems with their tagged products and components."""
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    stream_obj = get_stream_or_404(stream, request=request)

    # Get all systems for this stream with their allocations
    systems = (
        System.objects.filter(stream=stream_obj)
        .prefetch_related("tags__products__category", "tags__sublevels", "tags__sublevel_tools", "tags__projects")
        .order_by("name")
    )

    # Get recent allocations for each system

    today = timezone.now()
    fifteen_days_ago = today - timedelta(days=15)

    systems_data = []
    for system in systems:
        # Get tags for this system
        tags = system.tags.all()

        recent_allocations = (
            SystemAllocation.objects.filter(system_type=system.name, stream=stream_obj, end_date__gte=fifteen_days_ago)
            .select_related("user", "blocked_for_participant")
            .order_by("-start_date")[:5]
        )

        systems_data.append({"system": system, "tags": tags, "recent_allocations": recent_allocations})

    context = {
        "systems_data": systems_data,
        "stream": stream,
        "selected_stream": stream,
    }

    return render(request, "products/allocation_tree.html", context)


@login_required
@require_POST
def create_system_tag(request, stream=None):  # noqa: CCR001
    """Create or update a system tag (only one tag allowed per system)."""
    # pylint: disable=too-many-return-statements
    if not can_edit_products(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    stream_obj = get_stream_or_404(stream, request=request)

    system_id = request.POST.get("system_id")
    tag_id = request.POST.get("tag_id", "").strip()  # For updates
    tag_name = request.POST.get("tag_name", "").strip()
    description = request.POST.get("description", "").strip()

    if not system_id or not tag_name:
        return JsonResponse({"success": False, "error": "System and tag name are required"}, status=400)

    try:
        system = System.objects.get(id=system_id, stream=stream_obj)

        # Check if we're updating an existing tag
        if tag_id:
            tag = SystemTag.objects.get(id=tag_id, system=system, stream=stream_obj)
            old_name = tag.tag_name
            tag.tag_name = tag_name
            tag.description = description
            tag.save()
            SystemTagHistory.objects.create(
                system_tag=tag,
                system_tag_name=tag_name,
                system_name=system.name,
                stream=stream_obj,
                action="updated",
                item_type="tag",
                description=(
                    f'Tag renamed from "{old_name}" to "{tag_name}"'
                    if old_name != tag_name
                    else "Tag description updated"
                ),
                modified_by=request.user,
            )
            message = f'Tag "{tag_name}" updated successfully'
        else:
            # Check if system already has a tag (only one allowed)
            existing_tag = SystemTag.objects.filter(system=system).first()
            if existing_tag:
                return JsonResponse(
                    {"success": False, "error": "This system already has a tag. Please edit the existing tag instead."},
                    status=400,
                )

            tag = SystemTag.objects.create(
                system=system, tag_name=tag_name, stream=stream_obj, description=description, created_by=request.user
            )
            SystemTagHistory.objects.create(
                system_tag=tag,
                system_tag_name=tag_name,
                system_name=system.name,
                stream=stream_obj,
                action="created",
                item_type="tag",
                description=f'Tag "{tag_name}" created for system "{system.name}"',
                modified_by=request.user,
            )
            message = f'Tag "{tag_name}" created successfully'

        AuditLog.log(
            "create",
            f'{"Updated" if tag_id else "Created"} system tag "{tag_name}" for system "{system.name}"',
            user=request.user,
            request=request,
            obj=tag,
            module="systems",
            severity="info",
            stream=stream_obj,
        )

        return JsonResponse({"success": True, "tag_id": tag.id, "message": message})
    except System.DoesNotExist:
        return JsonResponse({"success": False, "error": "System not found"}, status=404)
    except SystemTag.DoesNotExist:
        return JsonResponse({"success": False, "error": "Tag not found"}, status=404)
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)


@login_required
@require_POST
def delete_system_tag(request, stream=None, tag_id=None):
    """Delete a system tag."""
    if not can_delete_products(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    stream_obj = get_stream_or_404(stream, request=request)

    try:
        tag = SystemTag.objects.get(id=tag_id, stream=stream_obj)
        tag_name = tag.tag_name
        system_name = tag.system.name
        SystemTagHistory.objects.create(
            system_tag=None,  # Will be null after deletion
            system_tag_name=tag_name,
            system_name=system_name,
            stream=stream_obj,
            action="deleted",
            item_type="tag",
            description=f'Tag "{tag_name}" deleted from system "{system_name}"',
            modified_by=request.user,
        )
        AuditLog.log(
            "delete",
            f'Deleted system tag "{tag_name}" from system "{system_name}"',
            user=request.user,
            request=request,
            obj=tag,
            module="systems",
            severity="warning",
            stream=stream_obj,
        )
        tag.delete()

        return JsonResponse({"success": True, "message": f'Tag "{tag_name}" deleted successfully'})
    except SystemTag.DoesNotExist:
        return JsonResponse({"success": False, "error": "Tag not found"}, status=404)
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)


@login_required
@require_POST
def manage_tag_items(request, stream=None, tag_id=None):  # noqa: C901, CCR001
    """Add or remove items (products, sublevels, sublevel_tools) from a tag."""
    # pylint: disable=too-complex
    if not can_edit_products(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    stream_obj = get_stream_or_404(stream, request=request)

    try:
        tag = SystemTag.objects.get(id=tag_id, stream=stream_obj)

        action = request.POST.get("action")  # 'add' or 'remove'
        item_type = request.POST.get("item_type")  # 'product', 'sublevel', 'sublevel_tool', or 'project'
        item_id = request.POST.get("item_id")

        if action not in ["add", "remove"] or item_type not in ["product", "sublevel", "sublevel_tool", "project"]:
            return JsonResponse({"success": False, "error": "Invalid action or item type"}, status=400)

        if not item_id:
            return JsonResponse({"success": False, "error": "Item ID is required"}, status=400)

        # Get the appropriate model and relation
        if item_type == "product":
            item = Product.objects.get(id=item_id, stream=stream_obj)
            relation = tag.products
            item_name = item.name
        elif item_type == "sublevel":
            item = SubLevel.objects.get(id=item_id)
            relation = tag.sublevels
            item_name = item.name
        elif item_type == "sublevel_tool":
            item = SubLevelTool.objects.get(id=item_id)
            relation = tag.sublevel_tools
            item_name = item.name
        else:  # project
            # Get project regardless of stream since we now show all projects
            item = Project.objects.get(id=item_id)
            relation = tag.projects
            item_name = item.name

        # Perform action
        if action == "add":
            relation.add(item)
            message = f'{item_type.replace("_", " ").title()} added to tag'
            history_action = "item_added"
        else:
            relation.remove(item)
            message = f'{item_type.replace("_", " ").title()} removed from tag'
            history_action = "item_removed"
        SystemTagHistory.objects.create(
            system_tag=tag,
            system_tag_name=tag.tag_name,
            system_name=tag.system.name,
            stream=stream_obj,
            action=history_action,
            item_type=item_type,
            item_name=item_name,
            item_id=item.id,
            description=(
                f'{item_type.replace("_", " ").title()} "{item_name}" '
                f'{"added to" if action == "add" else "removed from"} tag "{tag.tag_name}"'
            ),
            modified_by=request.user,
        )

        AuditLog.log(
            "update",
            (
                f'{"Added" if action == "add" else "Removed"} {item_type.replace("_", " ")} '
                f'"{item_name}" {"to" if action == "add" else "from"} tag "{tag.tag_name}"'
            ),
            user=request.user,
            request=request,
            obj=tag,
            module="systems",
            severity="info",
            stream=stream_obj,
        )

        return JsonResponse({"success": True, "message": message, "item_count": tag.get_all_components_count()})

    except (
        SystemTag.DoesNotExist,
        Product.DoesNotExist,
        SubLevel.DoesNotExist,
        SubLevelTool.DoesNotExist,
        Project.DoesNotExist,
    ):
        return JsonResponse({"success": False, "error": "Tag or item not found"}, status=404)
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)


@login_required
@require_GET
def get_system_tag_history(request, stream=None, system_id=None):
    """Get modification history for a specific system's tags."""
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)
    stream_obj = get_stream_or_404(stream, request=request)

    try:

        # Get history for this specific system
        history = (
            SystemTagHistory.objects.filter(
                stream=stream_obj, system_name=System.objects.get(id=system_id, stream=stream_obj).name
            )
            .select_related("modified_by")
            .order_by("-modified_at")[:30]
        )

        history_data = []
        for entry in history:
            # Convert to local timezone
            local_time = timezone.localtime(entry.modified_at)
            history_data.append(
                {
                    "date": local_time.strftime("%d %b %Y"),
                    "time": local_time.strftime("%H:%M"),
                    "user": entry.modified_by.username if entry.modified_by else "Unknown",
                    "action": entry.action,
                    "tag_name": entry.system_tag_name,
                    "item_type": entry.item_type.replace("_", " ").title() if entry.item_type else "",
                    "item_name": entry.item_name or "",
                    "description": entry.description or "",
                }
            )

        return JsonResponse({"success": True, "history": history_data})
    except System.DoesNotExist:
        return JsonResponse({"success": False, "error": "System not found"}, status=404)
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)


@login_required
def get_available_items(request, stream=None):  # noqa: C901, CCR001
    """Get available products, sublevels, and sublevel_tools for tagging."""
    # pylint: disable=too-complex
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    stream_obj = get_stream_or_404(stream, request=request)

    tag_id = request.GET.get("tag_id")
    item_type = request.GET.get("item_type", "product")

    try:

        # Get already tagged items if tag_id is provided
        tagged_ids = []
        if tag_id:
            tag = SystemTag.objects.get(id=tag_id, stream=stream_obj)
            if item_type == "product":
                tagged_ids = list(tag.products.values_list("id", flat=True))
            elif item_type == "sublevel":
                tagged_ids = list(tag.sublevels.values_list("id", flat=True))
            elif item_type == "sublevel_tool":
                tagged_ids = list(tag.sublevel_tools.values_list("id", flat=True))
            elif item_type == "project":
                tagged_ids = list(tag.projects.values_list("id", flat=True))

        # Get available items
        if item_type == "product":
            items = (
                Product.objects.filter(stream=stream_obj)
                .select_related("category")
                .values("id", "name", "serial_number", "category__name")
            )
            items_list = [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "serial_number": item["serial_number"],
                    "category": item["category__name"],
                    "is_tagged": item["id"] in tagged_ids,
                }
                for item in items
            ]
        elif item_type == "sublevel":
            items = SubLevel.objects.all().values("id", "name", "stream", "in_stock", "in_use")
            items_list = [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "stream": item["stream"],
                    "in_stock": item["in_stock"],
                    "in_use": item["in_use"],
                    "is_tagged": item["id"] in tagged_ids,
                }
                for item in items
            ]
        elif item_type == "sublevel_tool":
            items = SubLevelTool.objects.all().values("id", "name", "stream", "in_stock", "in_use")
            items_list = [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "stream": item["stream"],
                    "in_stock": item["in_stock"],
                    "in_use": item["in_use"],
                    "is_tagged": item["id"] in tagged_ids,
                }
                for item in items
            ]
        else:  # project
            items = Project.objects.all().values("id", "name", "status", "priority", "progress_percentage")
            items_list = [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "status": item["status"],
                    "priority": item["priority"],
                    "progress_percentage": item["progress_percentage"],
                    "is_tagged": item["id"] in tagged_ids,
                }
                for item in items
            ]

        return JsonResponse({"success": True, "items": items_list})

    except SystemTag.DoesNotExist:
        return JsonResponse({"success": False, "error": "Tag not found"}, status=404)
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)


# Project Status Management Views
