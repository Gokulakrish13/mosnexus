"""Products app — Products views."""

# pylint: disable=broad-exception-caught,else-if-used,invalid-name,no-else-return

from ._helpers import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_SIZE,
    AssetLifecycleRecord,
    AssetLifecycleStage,
    AuditLog,
    BytesIO,
    Category,
    IntegrityError,
    JsonResponse,
    Location,
    OnboardingProgress,
    Product,
    ProductHistory,
    ProductImage,
    Q,
    Stream,
    User,
    base64,
    check_user_access,
    get_bu_streams,
    get_current_bu,
    get_default_stream_name,
    get_object_or_404,
    get_stream_or_404,
    login_not_required,
    login_required,
    logout,
    messages,
    qrcode,
    redirect,
    render,
    reverse,
    validate_uploaded_file,
)
from .lifecycle_inventory import _ensure_lifecycle_stages_exist

__all__ = [
    "product_list",
    "product_create",
    "product_detail",
    "check_availability",
]


@login_required
def product_list(request, stream=None):  # noqa: CCR001
    """Product list."""
    # pylint: disable=too-many-locals
    category_id = request.GET.get("category")
    q = request.GET.get("q", "").strip()
    stream = stream or request.GET.get("stream") or get_default_stream_name(request)
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    location_id = request.GET.get("location")

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    stream_obj = get_stream_or_404(stream)

    if category_id:
        products = Product.objects.filter(category_id=category_id, stream=stream_obj)
    else:
        products = Product.objects.filter(stream=stream_obj)
    if q:
        products = products.filter(
            Q(name__icontains=q)
            | Q(serial_number__icontains=q)
            | Q(description__icontains=q)
            | Q(twelve_nc__icontains=q)
            | Q(location__name__icontains=q)
            | Q(category__serial_number__icontains=q)
        )
    # Date range filtering using created_at date (works directly with YYYY-MM-DD strings from the form)
    if start_date and end_date:
        products = products.filter(created_at__date__range=(start_date, end_date))
    else:
        if start_date:
            products = products.filter(created_at__date__gte=start_date)
        if end_date:
            products = products.filter(created_at__date__lte=end_date)
    if location_id:
        products = products.filter(location_id=location_id).exclude(location=None)
    products = (
        products.prefetch_related("system_tags__system")
        .select_related("lifecycle", "lifecycle__current_stage")
        .order_by("location__name", "-created_at")
    )
    locations = Location.objects.filter(stream=stream_obj).order_by("name")
    categories = Category.objects.filter(stream=stream_obj).order_by("name")

    total_count = products.count()
    status_counts = {
        "Active": products.filter(status="Active").count(),
        "Not Active": products.filter(status="Not Active").count(),
        "Scraped": products.filter(status="Scraped").count(),
        "Hand-Overed": products.filter(status="Hand-Overed").count(),
        "Issue": products.filter(status="Issue").count(),
    }

    # Onboarding tour check
    show_onboarding_tour = not OnboardingProgress.objects.filter(user=request.user, tour_key="product_list").exists()

    return render(
        request,
        "products/product_list.html",
        {
            "products": products,
            "selected_stream": stream,
            "category_id": category_id,
            "product_list_url": (
                f"/stream/{stream}/products/?category={category_id}" if category_id else f"/stream/{stream}/products/"
            ),
            "locations": locations,
            "categories": categories,
            "total_count": total_count,
            "status_counts": status_counts,
            "show_onboarding_tour": show_onboarding_tour,
        },
    )


@login_required
def product_create(request, stream=None):  # noqa: C901, CCR001
    """Product create."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    category_id = request.GET.get("category")
    stream_obj = get_stream_or_404(stream, request=request)
    categories = Category.objects.filter(stream=stream_obj).order_by("name")
    locations = Location.objects.filter(stream=stream_obj).order_by("name")
    all_streams = get_bu_streams(request).order_by("name")
    selected_category = None
    next_serial = ""
    if category_id:
        try:
            selected_category = Category.objects.get(id=category_id, stream=stream_obj)
            last_product = (
                Product.objects.filter(category_id=category_id, stream=stream_obj).order_by("-serial_number").first()
            )
            if last_product and last_product.serial_number.isdigit():
                next_serial = str(int(last_product.serial_number) + 1)
            else:
                if selected_category.serial_number.isdigit():
                    next_serial = str(int(selected_category.serial_number) + 1)
        except Category.DoesNotExist:
            selected_category = None
    if request.method == "POST":
        save_as_draft = request.POST.get("save_as_draft") == "1"
        name = request.POST.get("name", "")
        serial_number = request.POST.get("serial_number", "")
        description = request.POST.get("description", "")
        issue_description = request.POST.get("issue_description", "")
        twelve_nc = request.POST.get("twelve_nc", "")
        device_serial_number = request.POST.get("device_serial_number", "")
        category_id = request.POST.get("category", "")
        status = request.POST.get("status", "Active")
        handover_team_type = request.POST.get("handover_team_type", "")
        handover_external_team = request.POST.get("handover_external_team", "")
        handover_owner = request.POST.get("handover_owner", "")
        handover_stream_id = request.POST.get("handover_stream", "")
        handover_stream_obj = (
            Stream.objects.filter(id=handover_stream_id, is_active=True).first() if handover_stream_id else None
        )
        location_id = request.POST.get("location", "")
        location = Location.objects.filter(id=location_id, stream=stream_obj).first() if location_id else None
        if not category_id.isdigit():
            return render(
                request,
                "products/product_form.html",
                {
                    "form_error": "Please select a valid category before submitting the form.",
                    "categories": categories,
                    "selected_category": None,
                    "category": None,
                    "next_serial": next_serial,
                    "locations": locations,
                    "all_streams": all_streams,
                    "stream": stream,
                    "selected_stream": stream,
                    "product": {
                        "name": name,
                        "serial_number": serial_number,
                        "description": description,
                        "issue_description": issue_description,
                        "twelve_nc": twelve_nc,
                        "device_serial_number": device_serial_number,
                        "status": status,
                        "handover_team_type": handover_team_type,
                        "handover_external_team": handover_external_team,
                        "handover_owner": handover_owner,
                        "handover_stream_id": int(handover_stream_id) if handover_stream_id else None,
                        "location": location,
                    },
                    "edit": False,
                },
            )
        try:
            category = Category.objects.get(pk=category_id, stream=stream_obj)
        except Category.DoesNotExist:
            return render(
                request,
                "products/product_form.html",
                {
                    "form_error": "No category matches the given query. Please select a valid category.",
                    "categories": categories,
                    "selected_category": None,
                    "category": None,
                    "next_serial": next_serial,
                    "locations": locations,
                    "all_streams": all_streams,
                    "stream": stream,
                    "selected_stream": stream,
                    "product": {
                        "name": name,
                        "serial_number": serial_number,
                        "description": description,
                        "issue_description": issue_description,
                        "twelve_nc": twelve_nc,
                        "device_serial_number": device_serial_number,
                        "status": status,
                        "handover_team_type": handover_team_type,
                        "handover_external_team": handover_external_team,
                        "handover_owner": handover_owner,
                        "handover_stream_id": int(handover_stream_id) if handover_stream_id else None,
                        "location": location,
                    },
                    "edit": False,
                },
            )
        _bu = get_current_bu(request)  # noqa: F841
        bu_streams = get_bu_streams(request)
        if Product.objects.filter(serial_number=serial_number, stream__in=bu_streams).exists():
            return render(
                request,
                "products/product_form.html",
                {
                    "form_error": f"A product with serial number '{serial_number}' already exists in this Business Unit.",  # noqa: E501
                    "categories": categories,
                    "selected_category": selected_category,
                    "category": selected_category,
                    "next_serial": next_serial,
                    "locations": locations,
                    "all_streams": all_streams,
                    "stream": stream,
                    "selected_stream": stream,
                    "product": {
                        "name": name,
                        "serial_number": serial_number,
                        "description": description,
                        "issue_description": issue_description,
                        "twelve_nc": twelve_nc,
                        "device_serial_number": device_serial_number,
                        "status": status,
                        "handover_team_type": handover_team_type,
                        "handover_external_team": handover_external_team,
                        "handover_owner": handover_owner,
                        "handover_stream_id": int(handover_stream_id) if handover_stream_id else None,
                        "location": location,
                    },
                    "edit": False,
                },
            )
        try:
            product = Product.objects.create(
                name=name,
                serial_number=serial_number,
                description=description,
                issue_description=issue_description,
                twelve_nc=twelve_nc,
                device_serial_number=device_serial_number,
                category=category,
                status=status,
                handover_team_type=handover_team_type if status == "Hand-Overed" else "",
                handover_stream=(
                    handover_stream_obj if status == "Hand-Overed" and handover_team_type == "Internal" else None
                ),
                handover_external_team=(
                    handover_external_team if status == "Hand-Overed" and handover_team_type == "External" else ""
                ),
                handover_owner=handover_owner if status == "Hand-Overed" else "",
                location=location,
                created_by=request.user,
                updated_by=request.user,
                stream=stream_obj,
                is_draft=save_as_draft,
            )
        except IntegrityError:
            return render(
                request,
                "products/product_form.html",
                {
                    "form_error": f"A product with serial number '{serial_number}' already exists in this Business Unit.",  # noqa: E501
                    "categories": categories,
                    "selected_category": selected_category,
                    "category": selected_category,
                    "next_serial": next_serial,
                    "locations": locations,
                    "all_streams": all_streams,
                    "stream": stream,
                    "selected_stream": stream,
                    "product": {
                        "name": name,
                        "serial_number": serial_number,
                        "description": description,
                        "issue_description": issue_description,
                        "twelve_nc": twelve_nc,
                        "device_serial_number": device_serial_number,
                        "status": status,
                        "handover_team_type": handover_team_type,
                        "handover_external_team": handover_external_team,
                        "handover_owner": handover_owner,
                        "handover_stream_id": int(handover_stream_id) if handover_stream_id else None,
                        "location": location,
                    },
                    "edit": False,
                },
            )
        images = request.FILES.getlist("images")
        for img in images:
            is_valid, error_msg = validate_uploaded_file(
                img, ALLOWED_IMAGE_TYPES, ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_SIZE
            )
            if is_valid:
                ProductImage.objects.create(product=product, image=img)
            else:
                messages.warning(request, f'Skipped "{img.name}": {error_msg}')
        draft_label = " (Draft)" if save_as_draft else ""
        ProductHistory.objects.create(
            product=product,
            action="created",
            user=request.user,
            details=f"Product created{draft_label} with name: {name}, serial: {serial_number}",
        )
        AuditLog.log(
            "create",
            f'Created product "{name}"{draft_label}',
            user=request.user,
            request=request,
            obj=product,
            module="products",
            severity="info",
            description=f'Created product "{name}" (SN: {serial_number}) in {stream}{draft_label}',
        )
        if not save_as_draft:
            try:
                _ensure_lifecycle_stages_exist()
                default_stage = AssetLifecycleStage.objects.filter(stage_type="procurement", is_active=True).first()
                AssetLifecycleRecord.objects.create(
                    product=product,
                    current_stage=default_stage,
                    condition="new",
                    created_by=request.user,
                )
            except Exception:
                pass  # Lifecycle enrollment is non-critical; don't block product creation
        if save_as_draft:
            messages.success(request, f'Product "{name}" saved as draft successfully.')
        url = reverse("product_list_stream", kwargs={"stream": product.stream})
        if product.category:
            url += f"?category={product.category.pk}"
        return redirect(url)
    return render(
        request,
        "products/product_form.html",
        {
            "categories": categories,
            "selected_category": selected_category,
            "category": selected_category,
            "next_serial": next_serial,
            "locations": locations,
            "all_streams": all_streams,
            "stream": stream,
            "selected_stream": stream,
            "product": None,
            "edit": False,
        },
    )


@login_not_required
def product_detail(request, stream, pk):
    """Public product detail view accessible via QR code.

    No login required - allows anyone to view basic product information.
    """
    stream_obj = get_stream_or_404(stream)

    product = get_object_or_404(Product, pk=pk, stream=stream_obj)
    product_url = request.build_absolute_uri(reverse("product_detail_stream", args=[stream, product.pk]))
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(product_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_image = base64.b64encode(buffer.getvalue()).decode()

    history = product.history.order_by("-timestamp") if request.user.is_authenticated else []

    lifecycle_record = None
    try:
        lifecycle_record = product.lifecycle
    except Exception:
        pass

    return render(
        request,
        "products/product_detail.html",
        {
            "product": product,
            "qr_image": qr_image,
            "history": history,
            "stream": stream,
            "selected_stream": stream,
            "is_public_view": not request.user.is_authenticated,
            "lifecycle": lifecycle_record,
        },
    )


@login_not_required
def check_availability(request):
    """AJAX endpoint to check if username or email already exists."""
    field = request.GET.get("field", "")
    value = request.GET.get("value", "").strip()
    if field == "username" and value:
        exists = User.objects.filter(username=value).exists()
        return JsonResponse({"exists": exists, "message": "Username already exists." if exists else ""})
    elif field == "email" and value:
        exists = User.objects.filter(email=value).exists()
        return JsonResponse({"exists": exists, "message": "Email already registered." if exists else ""})
    return JsonResponse({"exists": False, "message": ""})
