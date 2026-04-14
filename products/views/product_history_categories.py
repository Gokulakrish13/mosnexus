"""Products app - Product History, Categories, Bulk Operations, and CSV Export views."""

# pylint: disable=broad-exception-caught,consider-using-dict-items,invalid-name

from io import StringIO

from ._helpers import (
    AuditLog,
    Category,
    Count,
    HttpResponse,
    IntegrityError,
    JsonResponse,
    OnboardingProgress,
    Paginator,
    Product,
    Q,
    _fac_granted,
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
    re,
    redirect,
    render,
    render_to_string,
    require_POST,
)

__all__ = [
    "parse_history_details",
    "product_history_ajax",
    "category_list",
    "category_create",
    "category_edit",
    "category_delete",
    "category_bulk_delete",
    "category_export_csv",
]


def parse_history_details(details):
    """Parse the details string and return a list of changed fields with old and new values."""
    match = re.match(r"Edited from (.+) to (.+)", details)
    if not match:
        return []
    from_part, to_part = match.groups()

    def parse_part(part):
        fields = {}
        for item in part.split(","):
            if ":" in item:
                key, value = item.split(":", 1)
                fields[key.strip()] = value.strip()
        return fields

    from_fields = parse_part(from_part)
    to_fields = parse_part(to_part)
    changes = []
    for key in from_fields:
        old = from_fields[key]
        new = to_fields.get(key, "")
        if old != new:
            changes.append({"field": key, "old": old, "new": new})
    return changes


@login_required
def product_history_ajax(request, stream=None, pk=None):
    """Product history ajax."""
    stream_obj = get_stream_or_404(stream, request=request)

    product = get_object_or_404(Product, pk=pk, stream=stream_obj)
    history = product.history.order_by("-timestamp")[:30]  # Limit to 30 most recent entries
    for h in history:
        if h.action == "edited":
            h.changes = parse_history_details(h.details)
        else:
            h.changes = None
    html = render_to_string("products/history_snippet.html", {"history": history})
    return HttpResponse(html)


@login_required
def category_list(request, stream=None):
    """Category list."""
    q = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "-created_at")
    page_number = request.GET.get("page", 1)
    stream = stream or request.GET.get("stream") or get_default_stream_name(request)

    if not stream or stream.strip() == "":
        stream = "PIC"

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    stream_obj = get_stream_or_404(stream, request=request)

    categories_qs = Category.objects.filter(stream=stream_obj)

    if q:
        categories_qs = categories_qs.filter(Q(name__icontains=q) | Q(serial_number__icontains=q))

    categories_qs = categories_qs.annotate(product_count=Count("products"))

    if sort == "name":
        categories_qs = categories_qs.order_by("name")
    elif sort == "product_count":
        categories_qs = categories_qs.order_by("-product_count")
    else:
        categories_qs = categories_qs.order_by("-created_at")

    paginator = Paginator(categories_qs, 24)  # 24 cards per page
    page_obj = paginator.get_page(page_number)

    streams = list(get_bu_streams(request).values_list("name", flat=True).order_by("name"))

    # Onboarding tour check
    show_onboarding_tour = not OnboardingProgress.objects.filter(user=request.user, tour_key="category_list").exists()

    return render(
        request,
        "products/category_list.html",
        {
            "categories": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "streams": streams,
            "selected_stream": stream,
            "selected_sort": sort,
            "q": q,
            "show_onboarding_tour": show_onboarding_tour,
        },
    )


@login_required
def category_create(request, stream=None):  # noqa: C901, CCR001
    """Category create."""
    # pylint: disable=too-complex,too-many-return-statements
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    if not _fac_granted(request.user) and not request.user.is_superuser:
        return redirect("category_list_stream", stream=stream or get_default_stream_name(request))
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        serial_number = request.POST.get("serial_number", "").strip()
        if not name or not serial_number:
            return render(
                request,
                "products/category_form.html",
                {
                    "form_error": "Both Category Name and Serial Number are required.",
                    "category": {"name": name, "serial_number": serial_number},
                    "stream": stream,
                    "selected_stream": stream,
                },
            )
        try:
            stream_obj = get_stream_or_404(stream, request=request)
        except Exception:
            return render(
                request,
                "products/category_form.html",
                {
                    "form_error": "Invalid stream specified.",
                    "category": {"name": name, "serial_number": serial_number},
                    "stream": stream,
                    "selected_stream": stream,
                },
            )
        bu_streams = get_bu_streams(request)
        if (
            Category.objects.filter(name=name, stream__in=bu_streams).exists()
            or Category.objects.filter(serial_number=serial_number, stream__in=bu_streams).exists()
        ):
            return render(
                request,
                "products/category_form.html",
                {
                    "form_error": "Category with this name or serial number already exists in this Business Unit.",
                    "category": {"name": name, "serial_number": serial_number},
                    "stream": stream,
                    "selected_stream": stream,
                },
            )
        try:
            cat = Category.objects.create(
                name=name, serial_number=serial_number, created_by=request.user, stream=stream_obj
            )
            AuditLog.log(
                "create",
                f'Created category "{name}"',
                user=request.user,
                request=request,
                obj=cat,
                module="categories",
                severity="info",
                description=f'Created category "{name}" (SN: {serial_number}) in {stream}',
            )
            return redirect("category_list_stream", stream=stream or get_default_stream_name(request))
        except IntegrityError:
            return render(
                request,
                "products/category_form.html",
                {
                    "form_error": "Category with this name or serial number already exists in this Business Unit.",
                    "category": {"name": name, "serial_number": serial_number},
                    "stream": stream,
                    "selected_stream": stream,
                },
            )
    return render(request, "products/category_form.html", {"stream": stream, "selected_stream": stream})


@login_required
def category_edit(request, pk, stream=None):
    """Category edit."""
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    stream_obj = get_stream_or_404(stream, request=request)

    category = get_object_or_404(Category, pk=pk, stream=stream_obj)
    if request.method == "POST":
        name = request.POST.get("name")
        serial_number = request.POST.get("serial_number")
        bu_streams = get_bu_streams(request)
        if (
            Category.objects.filter(name=name, stream__in=bu_streams).exclude(pk=pk).exists()
            or Category.objects.filter(serial_number=serial_number, stream__in=bu_streams).exclude(pk=pk).exists()
        ):
            return render(
                request,
                "products/category_form.html",
                {
                    "form_error": "Category with this name or serial number already exists in this Business Unit.",
                    "category": category,
                    "edit": True,
                    "stream": stream,
                    "selected_stream": stream,
                },
            )
        category.name = name
        category.serial_number = serial_number
        try:
            category.save()
        except IntegrityError:
            return render(
                request,
                "products/category_form.html",
                {
                    "form_error": "A category with this name or serial number already exists in this Business Unit.",
                    "category": category,
                    "edit": True,
                    "stream": stream,
                    "selected_stream": stream,
                },
            )
        AuditLog.log(
            "update",
            f'Updated category "{name}"',
            user=request.user,
            request=request,
            obj=category,
            module="categories",
            severity="info",
            description=f'Updated category "{name}" in {stream}',
        )
        return redirect("category_list_stream", stream=stream or get_default_stream_name(request))
    return render(
        request,
        "products/category_form.html",
        {"category": category, "edit": True, "stream": stream, "selected_stream": stream},
    )


@login_required
def category_delete(request, pk, stream=None):
    """Category delete."""
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    stream_obj = get_stream_or_404(stream, request=request)

    try:
        category = Category.objects.get(pk=pk, stream=stream_obj)
    except Category.DoesNotExist:
        messages.warning(request, "Category already deleted.")
        return redirect("category_list_stream", stream=stream or get_default_stream_name(request))
    if request.method == "POST":
        cat_name = category.name
        category.delete()
        AuditLog.log(
            "delete",
            f'Deleted category "{cat_name}"',
            user=request.user,
            request=request,
            module="categories",
            severity="warning",
            description=f'Deleted category "{cat_name}" from {stream}',
        )
        messages.success(request, "Category deleted successfully")
        return redirect("category_list_stream", stream=stream or get_default_stream_name(request))
    return render(request, "products/category_confirm_delete.html", {"category": category, "stream": stream})


@login_required
def category_bulk_delete(request, stream=None):
    """Delete multiple categories sent as JSON list of ids in request body.

    Only superusers may perform this action.
    """
    if not _fac_granted(request.user) and not request.user.is_superuser:
        return JsonResponse({"success": False, "error": "Permission denied."}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        ids = payload.get("ids", [])
    except Exception:
        ids = request.POST.get("ids", "")
        ids = [int(x) for x in ids.split(",") if x]

    if not ids:
        return JsonResponse({"success": False, "error": "No IDs provided."}, status=400)

    stream_obj = get_stream_or_404(stream, request=request)

    categories = Category.objects.filter(id__in=ids, stream=stream_obj).annotate(product_count=Count("products"))

    deleted_count = categories.count()
    categories.delete()
    return JsonResponse({"success": True, "deleted": deleted_count})


@login_required
@require_POST
def category_export_csv(request, stream=None):
    """Export selected categories (ids) to a CSV. Accepts JSON body with ids list or form-encoded 'ids'."""
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        ids = payload.get("ids", [])
    except Exception:
        ids = request.POST.get("ids", "")
        ids = [int(x) for x in ids.split(",") if x]

    if not ids:
        return JsonResponse({"success": False, "error": "No IDs provided."}, status=400)

    stream_obj = get_stream_or_404(stream, request=request)

    categories = Category.objects.filter(id__in=ids, stream=stream_obj).annotate(product_count=Count("products"))

    csvfile = StringIO()
    writer = csv.writer(csvfile)
    writer.writerow(["ID", "Name", "Serial Number", "Product Count", "Created At"])
    for c in categories:
        writer.writerow(
            [
                c.id,
                c.name,
                c.serial_number,
                getattr(c, "product_count", 0),
                c.created_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(c, "created_at", None) else "",
            ]
        )

    resp = HttpResponse(csvfile.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="categories_{stream or "all"}.csv"'
    return resp
