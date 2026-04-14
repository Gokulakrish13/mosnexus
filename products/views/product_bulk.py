"""Products app - Product Edit, Bulk Delete/Status/Export, and Product Delete views."""

# pylint: disable=broad-exception-caught,invalid-name

from ._helpers import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_SIZE,
    AuditLog,
    Category,
    HttpResponse,
    IntegrityError,
    JsonResponse,
    Location,
    Product,
    ProductHistory,
    ProductImage,
    Stream,
    can_delete_products,
    can_edit_products,
    check_user_access,
    csv,
    get_bu_streams,
    get_default_stream_name,
    get_object_or_404,
    get_stream_or_404,
    json,
    login_required,
    logout,
    messages,
    redirect,
    render,
    require_POST,
    reverse,
    validate_uploaded_file,
)
from ..approval_triggers import check_approval_required, fire_approval_trigger

__all__ = [
    "product_edit",
    "product_bulk_delete",
    "product_bulk_status",
    "product_bulk_export",
    "product_delete",
]


@login_required
def product_edit(request, pk, stream=None):  # noqa: C901, CCR001
    """Product edit."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-statements
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    stream_obj = get_stream_or_404(stream, request=request)

    product = get_object_or_404(Product, pk=pk, stream=stream_obj)
    categories = Category.objects.filter(stream=product.stream).order_by("name")
    locations = Location.objects.filter(stream=product.stream).order_by("name")
    all_streams = get_bu_streams(request).order_by("name")
    if request.method == "POST":
        save_as_draft = request.POST.get("save_as_draft") == "1"
        old_name = product.name
        old_serial = product.serial_number
        old_description = product.description
        old_category = product.category
        old_status = getattr(product, "status", "Active")
        old_handover_team_type = getattr(product, "handover_team_type", "")
        old_handover_external_team = getattr(product, "handover_external_team", "")
        old_handover_owner = getattr(product, "handover_owner", "")
        old_handover_stream = getattr(product, "handover_stream", None)
        old_location = product.location
        old_issue_description = getattr(product, "issue_description", "")
        old_twelve_nc = getattr(product, "twelve_nc", "")
        old_device_serial_number = getattr(product, "device_serial_number", "")

        issue_description = request.POST.get("issue_description", "")
        twelve_nc = request.POST.get("twelve_nc", "")
        device_serial_number = request.POST.get("device_serial_number", "")

        product.name = request.POST.get("name")
        product.serial_number = request.POST.get("serial_number")
        product.description = request.POST.get("description")
        product.issue_description = issue_description
        product.twelve_nc = twelve_nc
        product.device_serial_number = device_serial_number
        category_id = request.POST.get("category")
        try:
            product.category = Category.objects.get(pk=category_id, stream=product.stream) if category_id else None
        except Exception:
            product.category = None

        _requested_status = request.POST.get("status", "Active")

        # ── Pre-action enforcement: block major status changes that need approval ──
        _approval_block = None
        if old_status != _requested_status and _requested_status in ("Scraped", "Hand-Overed"):
            _event = "product_scrapped" if _requested_status == "Scraped" else "product_handovered"
            _approval_block = check_approval_required(
                _event,
                stream_obj.business_unit,
                request.user,
                entity_obj=product,
                stream=stream_obj,
                title=f"Product '{product.name}' status \u2192 {_requested_status}",
                description=(
                    f"Product {product.name} (SN: {product.serial_number}) status change "
                    f"from {old_status} to {_requested_status} by {request.user.username}"
                ),
                intended_changes={
                    "action_type": "status_change",
                    "model_label": "products.Product",
                    "pk": product.pk,
                    "changes": {"status": _requested_status},
                    "revert": {"status": old_status},
                    "metadata": {"entity_name": product.name, "stream_name": stream},
                },
            )
        elif old_status != _requested_status and _requested_status == "Not Active":
            _approval_block = check_approval_required(
                "product_status_inactive",
                stream_obj.business_unit,
                request.user,
                entity_obj=product,
                stream=stream_obj,
                title=f"Product '{product.name}' status \u2192 Not Active",
                description=(
                    f"Product {product.name} (SN: {product.serial_number}) deactivation "
                    f"from {old_status} to Not Active by {request.user.username}"
                ),
                intended_changes={
                    "action_type": "status_change",
                    "model_label": "products.Product",
                    "pk": product.pk,
                    "changes": {"status": "Not Active"},
                    "revert": {"status": old_status},
                    "metadata": {"entity_name": product.name, "stream_name": stream},
                },
            )

        # If approval is blocking the status change, keep old status; otherwise apply
        product.status = old_status if _approval_block else _requested_status
        product.handover_team_type = (
            request.POST.get("handover_team_type", "") if product.status == "Hand-Overed" else ""
        )
        handover_stream_id = request.POST.get("handover_stream", "")
        product.handover_stream = (
            Stream.objects.filter(id=handover_stream_id, is_active=True).first()
            if product.status == "Hand-Overed"
            and request.POST.get("handover_team_type", "") == "Internal"
            and handover_stream_id
            else None
        )
        product.handover_external_team = (
            request.POST.get("handover_external_team", "")
            if product.status == "Hand-Overed" and request.POST.get("handover_team_type", "") == "External"
            else ""
        )
        product.handover_owner = request.POST.get("handover_owner", "") if product.status == "Hand-Overed" else ""
        location_id = request.POST.get("location")
        product.location = (
            Location.objects.filter(id=location_id, stream=product.stream).first() if location_id else None
        )
        product.updated_by = request.user

        changes = []
        if old_name != product.name:
            changes.append(f"Name: '{old_name}' → '{product.name}'")
        if old_serial != product.serial_number:
            changes.append(f"Serial NO: '{old_serial}' → '{product.serial_number}'")
        if old_description != product.description:
            changes.append(f"Desc: '{old_description}' → '{product.description}'")
        if old_issue_description != issue_description:
            changes.append(f"Issue Desc: '{old_issue_description}' → '{issue_description}'")
        if old_twelve_nc != product.twelve_nc:
            changes.append(f"12NC: '{old_twelve_nc}' → '{product.twelve_nc}'")
        if old_device_serial_number != product.device_serial_number:
            changes.append(f"Serial Number: '{old_device_serial_number}' → '{product.device_serial_number}'")
        if old_category != product.category:
            changes.append(f"Category: '{old_category}' → '{product.category}'")
        if old_status != product.status:
            changes.append(f"Status: '{old_status}' → '{product.status}'")
        if old_handover_team_type != product.handover_team_type:
            changes.append(f"Handover_team_type: '{old_handover_team_type}' → '{product.handover_team_type}'")
        if old_handover_external_team != product.handover_external_team:
            changes.append(
                f"Handover_external_team: '{old_handover_external_team}' → '{product.handover_external_team}'"
            )
        if old_handover_owner != product.handover_owner:
            changes.append(f"Handover_owner: '{old_handover_owner}' → '{product.handover_owner}'")
        old_hs_name = old_handover_stream.name if old_handover_stream else "None"
        new_hs_name = product.handover_stream.name if product.handover_stream else "None"
        if old_hs_name != new_hs_name:
            changes.append(f"Handover_stream: '{old_hs_name}' → '{new_hs_name}'")
        if (old_location.name if old_location else None) != (product.location.name if product.location else None):
            changes.append(
                f"Location: '{old_location.name if old_location else 'None'}'"
                f" → '{product.location.name if product.location else 'None'}'"
            )

        old_is_draft = product.is_draft
        product.is_draft = save_as_draft
        if old_is_draft and not save_as_draft:
            changes.append("Draft → Published")
        elif not old_is_draft and save_as_draft:
            changes.append("Published → Draft")

        try:
            product.save()
        except IntegrityError:
            return render(
                request,
                "products/product_edit.html",
                {
                    "form_error": f"A product with serial number '{product.serial_number}' already exists in this Business Unit.",  # noqa: E501
                    "product": product,
                    "edit": True,
                    "categories": Category.objects.filter(stream=product.stream).order_by("name"),
                    "selected_category": product.category,
                    "locations": Location.objects.filter(stream=product.stream).order_by("name"),
                    "all_streams": get_bu_streams(request).order_by("name"),
                    "stream": stream,
                    "selected_stream": stream,
                },
            )

        delete_image_ids = request.POST.getlist("delete_images")
        if delete_image_ids:
            deleted_images = ProductImage.objects.filter(id__in=delete_image_ids, product=product)
            deleted_count = deleted_images.count()
            for di in deleted_images:
                if di.image:
                    di.image.delete(save=False)
                di.delete()
            if deleted_count:
                changes.append(f"Removed {deleted_count} image(s)")

        # Upload images (same validation as product_create)
        images = request.FILES.getlist("images")
        for img in images:
            is_valid, error_msg = validate_uploaded_file(
                img, ALLOWED_IMAGE_TYPES, ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_SIZE
            )
            if is_valid:
                ProductImage.objects.create(product=product, image=img)
            else:
                messages.warning(request, f'Skipped "{img.name}": {error_msg}')
        if images:
            changes.append(f"Added {len(images)} new image(s)")

        if changes:
            ProductHistory.objects.create(
                product=product, action="edited", user=request.user, details="; ".join(changes)
            )

        # ── If status change was blocked by approval, notify user ──
        if _approval_block:
            messages.warning(
                request,
                f'\u23f3 Status change to "{_requested_status}" requires approval. '
                f'Request #{_approval_block.id} has been submitted for review.',
            )

        draft_label = " (Draft)" if save_as_draft else ""
        AuditLog.log(
            "update",
            f'Updated product "{product.name}"{draft_label}',
            user=request.user,
            request=request,
            obj=product,
            module="products",
            severity="info",
            description=f'Updated product "{product.name}" (SN: {product.serial_number}) in {stream}{draft_label}',
        )
        if save_as_draft and not _approval_block:
            messages.success(request, f'Product "{product.name}" saved as draft successfully.')
        url = reverse("product_list_stream", kwargs={"stream": stream or get_default_stream_name(request)})
        if product.category:
            url += f"?category={product.category.pk}"
        return redirect(url)
    return render(
        request,
        "products/product_edit.html",
        {
            "product": product,
            "edit": True,
            "categories": categories,
            "selected_category": product.category,
            "next_serial": product.serial_number,
            "locations": locations,
            "all_streams": all_streams,
            "stream": product.stream,
            "selected_stream": product.stream.name if hasattr(product.stream, "name") else product.stream,
        },
    )


# ─── Bulk Product Actions ───


@login_required
@require_POST
def product_bulk_delete(request, stream=None):
    """Delete multiple products. Requires delete permission."""
    if not can_delete_products(request.user):
        return JsonResponse({"success": False, "error": "Permission denied. Admin privileges required."}, status=403)

    stream_obj = get_stream_or_404(stream, request=request)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        ids = payload.get("ids", [])
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid request."}, status=400)

    if not ids:
        return JsonResponse({"success": False, "error": "No product IDs provided."}, status=400)

    products = Product.objects.filter(id__in=ids, stream=stream_obj)
    count = products.count()

    if count == 0:
        return JsonResponse({"success": False, "error": "No matching products found."}, status=404)

    # ── Pre-action enforcement: block bulk delete if approval required ──
    _approval = check_approval_required(
        "product_bulk_delete",
        stream_obj.business_unit,
        request.user,
        stream=stream_obj,
        title=f"Bulk delete: {count} product(s)",
        description=f"{count} product(s) bulk-delete requested in stream {stream} by {request.user.username}",
        intended_changes={
            "action_type": "bulk_delete",
            "model_label": "products.Product",
            "pks": ids,
            "metadata": {"count": count, "stream_name": stream},
        },
    )
    if _approval:
        return JsonResponse({
            "success": False,
            "error": f"Bulk delete requires approval. Request #{_approval.id} submitted.",
            "approval_required": True,
            "approval_id": _approval.id,
        }, status=202)

    for p in products:
        AuditLog.log(
            "delete",
            f'Bulk deleted product "{p.name}"',
            user=request.user,
            request=request,
            module="products",
            severity="warning",
            description=f'Bulk deleted product "{p.name}" (SN: {p.serial_number}) from {stream}',
        )

    products.delete()

    return JsonResponse({"success": True, "deleted": count})


@login_required
@require_POST
def product_bulk_status(request, stream=None):
    """Change status of multiple products. Requires edit permission."""
    if not can_edit_products(request.user):
        return JsonResponse({"success": False, "error": "Permission denied. Edit privileges required."}, status=403)

    stream_obj = get_stream_or_404(stream, request=request)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        ids = payload.get("ids", [])
        new_status = payload.get("status", "")
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid request."}, status=400)

    valid_statuses = ["Active", "Not Active", "Scraped", "Hand-Overed"]
    if new_status not in valid_statuses:
        return JsonResponse(
            {"success": False, "error": f'Invalid status. Must be one of: {", ".join(valid_statuses)}'}, status=400
        )

    if not ids:
        return JsonResponse({"success": False, "error": "No product IDs provided."}, status=400)

    products = Product.objects.filter(id__in=ids, stream=stream_obj)
    count = products.count()

    if count == 0:
        return JsonResponse({"success": False, "error": "No matching products found."}, status=404)

    # ── Pre-action enforcement: block major bulk status changes if approval required ──
    if new_status in ("Scraped", "Hand-Overed", "Not Active"):
        _event = "product_bulk_status" if new_status in ("Scraped", "Hand-Overed") else "product_status_inactive"
        _approval = check_approval_required(
            _event,
            stream_obj.business_unit,
            request.user,
            stream=stream_obj,
            title=f"Bulk status change → {new_status} ({count} products)",
            description=f"{count} product(s) status change to {new_status} in stream {stream} by {request.user.username}",
            intended_changes={
                "action_type": "bulk_status_change",
                "model_label": "products.Product",
                "pks": ids,
                "changes": {"status": new_status},
                "metadata": {"count": count, "stream_name": stream},
            },
        )
        if _approval:
            return JsonResponse({
                "success": False,
                "error": f"Bulk status change to '{new_status}' requires approval. Request #{_approval.id} submitted.",
                "approval_required": True,
                "approval_id": _approval.id,
            }, status=202)

    for p in products:
        old_status = p.status
        if old_status != new_status:
            ProductHistory.objects.create(
                product=p,
                action="edited",
                user=request.user,
                details=f"Bulk status change from status: {old_status} to status: {new_status}",
            )
            AuditLog.log(
                "edit",
                f'Bulk status change for "{p.name}"',
                user=request.user,
                request=request,
                module="products",
                severity="info",
                description=f'Changed status of "{p.name}" (SN: {p.serial_number}) from {old_status} to {new_status}',
            )

    products.update(status=new_status, updated_by=request.user)

    return JsonResponse({"success": True, "updated": count, "status": new_status})


@login_required
@require_POST
def product_bulk_export(request, stream=None):  # noqa: CCR001
    """Export selected products to CSV."""
    stream_obj = get_stream_or_404(stream, request=request)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        ids = payload.get("ids", [])
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid request."}, status=400)

    if not ids:
        return JsonResponse({"success": False, "error": "No product IDs provided."}, status=400)

    products = Product.objects.filter(id__in=ids, stream=stream_obj).select_related("category", "location")

    if not products.exists():
        return JsonResponse({"success": False, "error": "No matching products found."}, status=404)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="products_export_{stream}.csv"'

    writer = csv.writer(response)
    writer.writerow(
        ["Name", "Serial Number", "12NC", "Category", "Status", "Location", "Description", "Created At", "Created By"]
    )

    for p in products:
        writer.writerow(
            [
                p.name,
                p.serial_number,
                p.twelve_nc or "",
                str(p.category) if p.category else "",
                p.status,
                p.location.name if p.location else "",
                p.description or "",
                p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "",
                str(p.created_by) if p.created_by else "",
            ]
        )

    AuditLog.log(
        "export",
        f"Bulk exported {products.count()} products to CSV",
        user=request.user,
        request=request,
        module="products",
        severity="info",
        stream=stream_obj,
    )
    return response


@login_required
def product_delete(request, pk, stream=None):
    """Product delete."""
    stream_obj = get_stream_or_404(stream, request=request)

    if not can_delete_products(request.user):
        messages.error(request, "Access denied. You need admin privileges to delete products.")
        return redirect("product_list_stream", stream=stream or get_default_stream_name(request))

    try:
        product = Product.objects.get(pk=pk, stream=stream_obj)
    except Product.DoesNotExist:
        messages.warning(request, "Product already deleted.")
        url = reverse("product_list_stream", kwargs={"stream": stream or get_default_stream_name(request)})
        query_params = request.GET.urlencode()
        if query_params:
            url += "?" + query_params
        return redirect(url)
    if request.method == "POST":
        prod_name, prod_sn = product.name, product.serial_number
        _bu = stream_obj.business_unit

        # ── Pre-action enforcement: block delete if approval required ──
        _approval = check_approval_required(
            "product_deleted",
            _bu,
            request.user,
            entity_obj=product,
            stream=stream_obj,
            title=f"Product '{prod_name}' deletion",
            description=f"Product {prod_name} (SN: {prod_sn}) delete requested in {stream} by {request.user.username}",
            intended_changes={
                "action_type": "delete",
                "model_label": "products.Product",
                "pk": product.pk,
                "metadata": {"entity_name": prod_name, "serial_number": prod_sn, "stream_name": stream},
            },
        )
        if _approval:
            messages.warning(
                request,
                f'\u23f3 Deleting "{prod_name}" requires approval. Request #{_approval.id} submitted.',
            )
            url = reverse("product_list_stream", kwargs={"stream": stream or get_default_stream_name(request)})
            query_params = request.POST.get("query_params", "")
            if query_params:
                url += "?" + query_params
            return redirect(url)

        product.delete()
        AuditLog.log(
            "delete",
            f'Deleted product "{prod_name}"',
            user=request.user,
            request=request,
            module="products",
            severity="warning",
            description=f'Deleted product "{prod_name}" (SN: {prod_sn}) from {stream}',
        )
        messages.success(request, "Product deleted successfully")
        url = reverse("product_list_stream", kwargs={"stream": stream or get_default_stream_name(request)})
        query_params = request.POST.get("query_params", "")
        if query_params:
            url += "?" + query_params
        return redirect(url)
    query_params = request.GET.urlencode()
    return render(
        request,
        "products/product_confirm_delete.html",
        {"product": product, "stream": stream, "query_params": query_params},
    )
