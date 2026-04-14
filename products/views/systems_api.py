"""Products app — Systems Api views."""

# pylint: disable=import-error,inconsistent-return-statements,no-else-return,relative-beyond-top-level
# pylint: disable=wrong-import-position

from ._helpers import (
    BinariesSystemType,
    Category,
    HttpResponse,
    JsonResponse,
    OSSystemType,
    ProductEntry,
    Q,
    SubLevel,
    Workbook,
    ZenitionProduct,
    _fac_granted,
    _parse_json_body,
    datetime,
    get_column_letter,
    get_current_bu,
    login_required,
    render,
    require_GET,
)
from .user_data import get_user_product_data

__all__ = [
    "build_os_info",
    "product_entries_api",
    "add_zenition_product_api",
    "delete_zenition_product_api",
    "os_system_types_api",
    "binaries_system_types_api",
    "system_types_category_mapping_api",
    "download_inventory_with_os_binaries_excel",
]


@login_required
def build_os_info(request):  # noqa: CCR001
    """Build os info."""
    # pylint: disable=too-many-branches
    # Get all products assigned to a Zenition category, scoped to current BU
    bu = get_current_bu(request)
    _zenition_category_qs = Category.objects.filter(name__icontains="Zenition")  # noqa: F841
    if bu:
        zenition_products = ZenitionProduct.objects.filter(Q(business_unit=bu) | Q(business_unit__isnull=True))
    else:
        zenition_products = ZenitionProduct.objects.all()
    selected_product_id = request.GET.get("selected_product_id")
    warning = None
    delete_result = None
    if request.method == "POST":
        new_product = request.POST.get("new_zenition_product", "").strip()
        if new_product:
            if ZenitionProduct.objects.filter(name=new_product, business_unit=bu).exists():
                warning = f"Product '{new_product}' already exists."
            else:
                ZenitionProduct.objects.create(name=new_product, business_unit=bu)
                if bu:
                    zenition_products = ZenitionProduct.objects.filter(
                        Q(business_unit=bu) | Q(business_unit__isnull=True)
                    )
                else:
                    zenition_products = ZenitionProduct.objects.all()
        elif "delete_product_id" in request.POST:
            product_id = request.POST.get("delete_product_id")
            password = request.POST.get("delete_product_password", "").strip()
            if product_id:
                # Password check: use Django's check_password for the current user
                if not password or not request.user.check_password(password):
                    delete_result = "Incorrect password."
                else:
                    ZenitionProduct.objects.filter(id=product_id).delete()
                    if bu:
                        zenition_products = ZenitionProduct.objects.filter(
                            Q(business_unit=bu) | Q(business_unit__isnull=True)
                        )
                    else:
                        zenition_products = ZenitionProduct.objects.all()
                    delete_result = "Product deleted successfully."
    return render(
        request,
        "products/build_os_info.html",
        {
            "zenition_products": zenition_products,
            "selected_product_id": selected_product_id,
            "warning": warning,
            "delete_result": delete_result,
        },
    )


from ..models import ProductEntry, ZenitionProduct  # noqa: E402, F811


@login_required
def product_entries_api(request):  # noqa: C901, CCR001
    """Product entries api."""
    # pylint: disable=too-complex,too-many-locals,too-many-return-statements,too-many-statements
    if request.method == "GET":
        product_id = request.GET.get("product_id")
        category = request.GET.get("category")  # OS/Binaries
        type_ = request.GET.get("type")  # MVS/Stand PC/Apps PC
        entries = ProductEntry.objects.filter(zenition_product_id=product_id, entry_type=category, category=type_)
        data = [
            {
                "id": e.id,
                "subcategory": e.subcategory,
                "category": e.subcategory,
                "link": e.link,
                "os_system_type": e.os_system_type.id if e.os_system_type else None,
                "os_system_type_name": e.os_system_type.name if e.os_system_type else "",
                "binaries_system_type": e.binaries_system_type.id if e.binaries_system_type else None,
                "binaries_system_type_name": e.binaries_system_type.name if e.binaries_system_type else "",
            }
            for e in entries
        ]
        return JsonResponse({"entries": data})
    elif request.method == "POST":
        body, err = _parse_json_body(request)
        if err:
            return err
        product_id = body.get("product_id")
        entry_type = body.get("category")  # OS/Binaries
        type_ = body.get("type")  # MVS/Stand PC/Apps PC
        subcategory = body.get("subcategory")
        link = body.get("link")
        os_system_type_id = body.get("os_system_type_id")
        binaries_system_type_id = body.get("binaries_system_type_id")

        entry = ProductEntry.objects.create(
            zenition_product_id=product_id,
            entry_type=entry_type,
            category=type_,
            subcategory=subcategory,
            link=link,
            os_system_type_id=os_system_type_id if os_system_type_id else None,
            binaries_system_type_id=binaries_system_type_id if binaries_system_type_id else None,
        )
        return JsonResponse(
            {
                "id": entry.id,
                "subcategory": entry.subcategory,
                "category": entry.subcategory,
                "link": entry.link,
                "os_system_type": entry.os_system_type.id if entry.os_system_type else None,
                "os_system_type_name": entry.os_system_type.name if entry.os_system_type else "",
                "binaries_system_type": entry.binaries_system_type.id if entry.binaries_system_type else None,
                "binaries_system_type_name": entry.binaries_system_type.name if entry.binaries_system_type else "",
            }
        )
    elif request.method == "PUT":
        body, err = _parse_json_body(request)
        if err:
            return err
        entry_id = body.get("id")
        product_id = body.get("product_id")
        entry_type = body.get("category")  # OS/Binaries
        type_ = body.get("type")  # MVS/Stand PC/Apps PC
        subcategory = body.get("subcategory")
        link = body.get("link")
        os_system_type_id = body.get("os_system_type_id")
        binaries_system_type_id = body.get("binaries_system_type_id")

        # Authorization: scope to BU-accessible products
        bu = get_current_bu(request)
        entry_qs = ProductEntry.objects.filter(id=entry_id)
        if bu:
            entry_qs = entry_qs.filter(
                Q(zenition_product__business_unit=bu) | Q(zenition_product__business_unit__isnull=True)
            )
        entry = entry_qs.first()
        if not entry:
            return JsonResponse({"error": "Entry not found or access denied"}, status=404)
        entry.category = type_
        entry.subcategory = subcategory
        entry.link = link
        entry.os_system_type_id = os_system_type_id if os_system_type_id else None
        entry.binaries_system_type_id = binaries_system_type_id if binaries_system_type_id else None
        entry.save()
        return JsonResponse(
            {
                "id": entry.id,
                "subcategory": entry.subcategory,
                "category": entry.subcategory,
                "link": entry.link,
                "os_system_type": entry.os_system_type.id if entry.os_system_type else None,
                "os_system_type_name": entry.os_system_type.name if entry.os_system_type else "",
                "binaries_system_type": entry.binaries_system_type.id if entry.binaries_system_type else None,
                "binaries_system_type_name": entry.binaries_system_type.name if entry.binaries_system_type else "",
            }
        )
    elif request.method == "DELETE":
        body, err = _parse_json_body(request)
        if err:
            return err
        entry_id = body.get("id")
        # Authorization: scope to BU-accessible products
        bu = get_current_bu(request)
        entry_qs = ProductEntry.objects.filter(id=entry_id)
        if bu:
            entry_qs = entry_qs.filter(
                Q(zenition_product__business_unit=bu) | Q(zenition_product__business_unit__isnull=True)
            )
        deleted_count = entry_qs.delete()[0]
        if not deleted_count:
            return JsonResponse({"error": "Entry not found or access denied"}, status=404)
        return JsonResponse({"deleted": True})


@login_required
def add_zenition_product_api(request):
    """Add zenition product api."""
    if request.method == "POST":
        data, err = _parse_json_body(request)
        if err:
            return err
        name = data.get("name", "").strip()
        bu = get_current_bu(request)
        if not name:
            return JsonResponse({"success": False, "error": "Product name required."})
        if ZenitionProduct.objects.filter(name__iexact=name, business_unit=bu).exists():
            return JsonResponse({"success": False, "error": "Product already exists."})
        product = ZenitionProduct.objects.create(name=name, business_unit=bu)
        return JsonResponse({"success": True, "id": product.id, "name": product.name})
    return JsonResponse({"success": False, "error": "Invalid request method."})


@login_required
def delete_zenition_product_api(request):
    """Delete zenition product api."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request method."}, status=400)
    data, err = _parse_json_body(request)
    if err:
        return err
    product_id = data.get("id")
    password = data.get("password")
    user = request.user
    if not password or not user.check_password(password):
        return JsonResponse({"success": False, "error": "Incorrect password."}, status=403)
    try:
        product = ZenitionProduct.objects.get(id=product_id)
        product.delete()
        return JsonResponse({"success": True, "message": "Product deleted successfully."})
    except ZenitionProduct.DoesNotExist:
        return JsonResponse({"success": False, "error": "Product not found."}, status=404)


@login_required
def os_system_types_api(request):  # noqa: C901, CCR001
    """API for managing OS System Types."""
    # pylint: disable=too-complex,too-many-return-statements
    if request.method == "GET":
        types = OSSystemType.objects.all().order_by("name")
        data = [{"id": t.id, "name": t.name, "description": t.description} for t in types]
        return JsonResponse({"types": data})

    elif request.method == "POST":
        data, err = _parse_json_body(request)
        if err:
            return err
        name = data.get("name", "").strip()
        description = data.get("description", "").strip()

        if not name:
            return JsonResponse({"success": False, "error": "Name is required."}, status=400)

        if OSSystemType.objects.filter(name__iexact=name).exists():
            return JsonResponse({"success": False, "error": "OS System Type already exists."}, status=400)

        os_type = OSSystemType.objects.create(
            name=name, description=description, created_by=request.user if request.user.is_authenticated else None
        )
        return JsonResponse(
            {"success": True, "id": os_type.id, "name": os_type.name, "description": os_type.description}
        )

    elif request.method == "DELETE":
        data, err = _parse_json_body(request)
        if err:
            return err
        type_id = data.get("id")

        if not type_id:
            return JsonResponse({"success": False, "error": "ID is required."}, status=400)

        try:
            os_type = OSSystemType.objects.get(id=type_id)
            os_type.delete()
            return JsonResponse({"success": True, "message": "OS System Type deleted successfully."})
        except OSSystemType.DoesNotExist:
            return JsonResponse({"success": False, "error": "OS System Type not found."}, status=404)

    return JsonResponse({"success": False, "error": "Invalid request method."}, status=400)


@login_required
def binaries_system_types_api(request):  # noqa: C901, CCR001
    """API for managing Binaries System Types."""
    # pylint: disable=too-complex,too-many-return-statements
    if request.method == "GET":
        types = BinariesSystemType.objects.all().order_by("name")
        data = [{"id": t.id, "name": t.name, "description": t.description} for t in types]
        return JsonResponse({"types": data})

    elif request.method == "POST":
        data, err = _parse_json_body(request)
        if err:
            return err
        name = data.get("name", "").strip()
        description = data.get("description", "").strip()

        if not name:
            return JsonResponse({"success": False, "error": "Name is required."}, status=400)

        if BinariesSystemType.objects.filter(name__iexact=name).exists():
            return JsonResponse({"success": False, "error": "Binaries System Type already exists."}, status=400)

        binaries_type = BinariesSystemType.objects.create(
            name=name, description=description, created_by=request.user if request.user.is_authenticated else None
        )
        return JsonResponse(
            {
                "success": True,
                "id": binaries_type.id,
                "name": binaries_type.name,
                "description": binaries_type.description,
            }
        )

    elif request.method == "DELETE":
        data, err = _parse_json_body(request)
        if err:
            return err
        type_id = data.get("id")

        if not type_id:
            return JsonResponse({"success": False, "error": "ID is required."}, status=400)

        try:
            binaries_type = BinariesSystemType.objects.get(id=type_id)
            binaries_type.delete()
            return JsonResponse({"success": True, "message": "Binaries System Type deleted successfully."})
        except BinariesSystemType.DoesNotExist:
            return JsonResponse({"success": False, "error": "Binaries System Type not found."}, status=404)

    return JsonResponse({"success": False, "error": "Invalid request method."}, status=400)


@login_required
@require_GET
def system_types_category_mapping_api(request):
    """API for fetching system types with their mapped category counts."""
    os_types_data = []
    os_types = OSSystemType.objects.all().order_by("name")
    for os_type in os_types:
        category_count = ProductEntry.objects.filter(os_system_type=os_type).values("category").distinct().count()

        os_types_data.append({"id": os_type.id, "name": os_type.name, "type": "OS", "category_count": category_count})

    binaries_types_data = []
    binaries_types = BinariesSystemType.objects.all().order_by("name")
    for binaries_type in binaries_types:
        category_count = (
            ProductEntry.objects.filter(binaries_system_type=binaries_type).values("category").distinct().count()
        )

        binaries_types_data.append(
            {"id": binaries_type.id, "name": binaries_type.name, "type": "Binaries", "category_count": category_count}
        )

    return JsonResponse(
        {
            "os_types": os_types_data,
            "binaries_types": binaries_types_data,
            "total_os_types": len(os_types_data),
            "total_binaries_types": len(binaries_types_data),
        }
    )


@login_required
def download_inventory_with_os_binaries_excel(request):  # noqa: C901, CCR001
    """Download inventory with os binaries excel."""
    # pylint: disable=too-complex,too-many-locals
    if not _fac_granted(request.user) and not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=401)
    wb = Workbook()
    ws_inventory = wb.active
    ws_inventory.title = "Inventory Data"
    headers = [
        "S. NO",
        "Category name",
        "Category Serial Number",
        "Product Name",
        "Product Serial Number",
        "Product Description",
        "Product Added date",
        "Product added by",
        "Stream",
        "Location Name",
        "Location Address",
    ]
    ws_inventory.append(headers)
    for row in get_user_product_data():
        ws_inventory.append(row)
    for col in range(1, len(headers) + 1):
        ws_inventory.column_dimensions[get_column_letter(col)].width = 22

    ws_os = wb.create_sheet(title="OS Data")
    os_headers = ["Zenition Product", "Type", "Subcategory", "Link"]
    ws_os.append(os_headers)
    for product in ZenitionProduct.objects.all():
        os_entries = ProductEntry.objects.filter(zenition_product=product, entry_type="OS")
        for entry in os_entries:
            ws_os.append([product.name, entry.category, entry.subcategory or "", entry.link])
    for col in range(1, len(os_headers) + 1):
        ws_os.column_dimensions[get_column_letter(col)].width = 22

    ws_bin = wb.create_sheet(title="Binaries Data")
    bin_headers = ["Zenition Product", "Type", "Subcategory", "Link"]
    ws_bin.append(bin_headers)
    for product in ZenitionProduct.objects.all():
        bin_entries = ProductEntry.objects.filter(zenition_product=product, entry_type="Binaries")
        for entry in bin_entries:
            ws_bin.append([product.name, entry.category, entry.subcategory or "", entry.link])
    for col in range(1, len(bin_headers) + 1):
        ws_bin.column_dimensions[get_column_letter(col)].width = 22

    ws_sublevel = wb.create_sheet(title="SubLevel Data")
    sublevel_headers = [
        "Item Name",
        "In stock",
        "In use",
        "Scrapped",
        "Stream",
        "Last modified by",
        "Last modified date",
    ]
    ws_sublevel.append(sublevel_headers)
    sublevels = SubLevel.objects.all()
    for sub in sublevels:
        last_history = sub.history.order_by("-at").first()
        last_by = last_history.by if last_history else ""
        last_at = last_history.at.strftime("%Y-%m-%d %H:%M:%S") if last_history else ""
        ws_sublevel.append([sub.name, sub.in_stock, sub.in_use, sub.scraped, sub.stream or "", last_by, last_at])
    for col in range(1, len(sublevel_headers) + 1):
        ws_sublevel.column_dimensions[get_column_letter(col)].width = 22

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _bu_slug = request.session.get("selected_bu_code", "Inventory")
    filename = f"{timestamp}_{_bu_slug}_Inventory_with_OS_Binaries.xlsx"
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response
