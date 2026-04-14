"""Products app - User Data, Export, Import, Deactivate, and Reactivate views."""

# pylint: disable=bad-builtin,broad-exception-caught,import-error,invalid-name,protected-access,redefined-outer-name
# pylint: disable=relative-beyond-top-level,too-many-lines,unused-argument

from django.contrib.staticfiles import finders

from ..models import BusinessUnit as _BU  # noqa: N814
from ._helpers import (
    A3,
    ALLOWED_EXCEL_EXTENSIONS,
    ALLOWED_EXCEL_TYPES,
    MAX_EXCEL_SIZE,
    AuditLog,
    BytesIO,
    Category,
    ContentFile,
    HttpResponse,
    Location,
    Notification,
    Paragraph,
    Participant,
    Product,
    SimpleDocTemplate,
    Spacer,
    Stream,
    SubLevel,
    Table,
    TableStyle,
    User,
    UserDataVersion,
    _fac_granted,
    _get_role_level,
    _is_app_admin_user,
    colors,
    datetime,
    get_column_letter,
    get_default_stream_name,
    get_object_or_404,
    get_user_model,
    getSampleStyleSheet,
    is_super_admin,
    landscape,
    logger,
    login_required,
    messages,
    openpyxl,
    pd,
    re,
    redirect,
    render,
    require_POST,
    transaction,
    validate_uploaded_file,
)

__all__ = [
    "post_login_landing",
    "remove_user",
    "deactivate_user",
    "reactivate_user",
    "get_user_product_data",
    "download_users_excel",
    "download_users_pdf",
    "upload_products_excel",
    "restore_user_backup",
]


@login_required
def post_login_landing(request):
    """After login, show only the category management page (no products)."""
    categories = Category.objects.all().order_by("-created_at")
    return render(request, "products/category_list.html", {"categories": categories})


@login_required
@require_POST
def remove_user(request, user_id):
    """Remove user."""
    if not _fac_granted(request.user) and not request.user.is_superuser:
        messages.error(request, "Only super admins can remove users.")
        return redirect("user_list")
    User = get_user_model()  # noqa: N806
    user = get_object_or_404(User, id=user_id)

    # ── Hierarchy enforcement (app_admin exempt) ──
    if not _is_app_admin_user(request.user):
        if _get_role_level(request.user) >= _get_role_level(user):
            messages.error(request, "You cannot remove a user with equal or higher privilege than yours.")
            return redirect("user_list")

    if user == request.user:
        messages.error(request, "You cannot remove yourself.")
        return redirect("user_list")
    username = user.username  # type: ignore[attr-defined]
    AuditLog.log(
        action="delete",
        title=f"Permanently deleted user: {username}",
        user=request.user,
        request=request,
        module="users",
        severity="critical",
    )
    user.delete()
    messages.success(request, f"User removed: {username} has been successfully removed from the system.")
    return redirect("user_list")


@login_required
@require_POST
def deactivate_user(request, user_id):
    """Deactivate a user account. Only super admins and app admins can perform this action."""
    if not is_super_admin(request.user):
        messages.error(request, "Access denied. Only Super Admins and Application Admins can deactivate accounts.")
        return redirect("user_list")
    User = get_user_model()  # noqa: N806
    user = get_object_or_404(User, id=user_id)

    # ── Hierarchy enforcement (app_admin exempt) ──
    if not _is_app_admin_user(request.user):
        if _get_role_level(request.user) >= _get_role_level(user):
            messages.error(request, "You cannot deactivate a user with equal or higher privilege than yours.")
            return redirect("user_list")

    if user == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("user_profile")
    if not user.is_active:
        messages.info(request, f"Account for {user.username} is already deactivated.")  # type: ignore[attr-defined]
        return redirect("user_list")
    user.is_active = False
    user.save()
    AuditLog.log(
        action="update",
        title=f'Deactivated user account "{user.username}"',  # type: ignore[attr-defined]
        user=request.user,
        request=request,
        obj=user,
        module="other",
        severity="warning",
        description=(
            f'User "{user.username}" was deactivated by "{request.user.username}".'  # type: ignore[attr-defined]
        ),
        old_values={"is_active": True},
        new_values={"is_active": False},
    )
    messages.success(
        request,
        f"Account deactivated: {user.username} has been deactivated successfully.",  # type: ignore[attr-defined]
    )
    return redirect("user_list")


@login_required
@require_POST
def reactivate_user(request, user_id):
    """Reactivate a previously deactivated user account. Only super admins and app admins can perform this action."""
    if not is_super_admin(request.user):
        messages.error(request, "Access denied. Only Super Admins and Application Admins can reactivate accounts.")
        return redirect("user_list")
    User = get_user_model()  # noqa: N806
    user = get_object_or_404(User, id=user_id)

    # ── Hierarchy enforcement (app_admin exempt) ──
    if not _is_app_admin_user(request.user):
        if _get_role_level(request.user) >= _get_role_level(user):
            messages.error(request, "You cannot reactivate a user with equal or higher privilege than yours.")
            return redirect("user_list")

    if user.is_active:
        messages.info(request, f"Account for {user.username} is already active.")  # type: ignore[attr-defined]
        return redirect("user_list")
    user.is_active = True
    user.save()
    AuditLog.log(
        action="update",
        title=f'Reactivated user account "{user.username}"',  # type: ignore[attr-defined]
        user=request.user,
        request=request,
        obj=user,
        module="other",
        severity="info",
        description=(
            f'User "{user.username}" was reactivated by "{request.user.username}".'  # type: ignore[attr-defined]
        ),
        old_values={"is_active": False},
        new_values={"is_active": True},
    )
    messages.success(
        request,
        f"Account reactivated: {user.username} has been reactivated successfully.",  # type: ignore[attr-defined]
    )
    Notification.notify(
        user, f"Your account has been reactivated by {request.user.username}. You can now log in.", "user_access"
    )
    return redirect("user_list")


@login_required
def get_user_product_data():  # noqa: CCR001
    """Get user product data."""
    # Helper to get the required data for export
    data = []
    products = (
        Product.objects.select_related("category", "created_by", "location").all().order_by("category__name", "name")
    )
    for idx, product in enumerate(products, 1):
        # Ensure stream is a plain string (openpyxl cannot write model instances)
        stream_val = ""
        if hasattr(product, "stream") and product.stream is not None:
            # Prefer a .name attribute if Stream is a model with that field
            stream_val = getattr(product.stream, "name", str(product.stream))
        data.append(
            [
                idx,
                product.category.name if product.category else "",
                product.category.serial_number if product.category else "",
                product.name,
                product.serial_number,
                product.description,
                product.created_at.strftime("%Y-%m-%d %H:%M"),
                product.created_by.username if product.created_by else "",
                stream_val,
                product.location.name if product.location else "",
                product.location.address if product.location and hasattr(product.location, "address") else "",
            ]
        )
    return data


@login_required
def download_users_excel(request):
    """Download users excel."""
    if not _fac_granted(request.user) and not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=401)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inventory Data"
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
    ws.append(headers)
    for row in get_user_product_data():
        ws.append(row)
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 22
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _bu_slug = request.session.get("selected_bu_code", "Inventory")
    filename = f"{timestamp}_{_bu_slug}_Inventory list.xlsx"
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    AuditLog.log(
        "export",
        "Exported product inventory to Excel",
        user=request.user,
        request=request,
        module="products",
        severity="info",
    )
    return response


@login_required
def download_users_pdf(request):  # noqa: CCR001
    """Download users pdf."""
    # pylint: disable=too-many-locals,too-many-statements
    if not _fac_granted(request.user) and not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=401)

    buffer = BytesIO()
    page_width, page_height = landscape(A3)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=(page_width, page_height),
        leftMargin=30,
        rightMargin=30,
        topMargin=60,
        bottomMargin=30,
    )

    # Prepare data
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
    data = [headers] + get_user_product_data()
    table = Table(data, repeatRows=1)
    style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#005fa3")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
            ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]
    )
    table.setStyle(style)

    # Styles for titles
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.fontName = "Helvetica-Bold"
    title_style.fontSize = 22
    title_style.alignment = 1  # Center

    subtitle_style = styles["Heading2"]
    subtitle_style.fontName = "Helvetica-Bold"
    subtitle_style.fontSize = 18
    subtitle_style.alignment = 1

    subsubtitle_style = styles["Heading3"]
    subsubtitle_style.fontName = "Helvetica-Bold"
    subsubtitle_style.fontSize = 16
    subsubtitle_style.alignment = 1

    note_style = styles["Italic"]
    note_style.fontSize = 12
    note_style.alignment = 1

    # Logo path
    logo_path = finders.find("products/Philips_NoBG.png")

    # Dynamic BU name for PDF header
    _bu_obj = getattr(request, "current_bu", None)
    if not _bu_obj:
        _bu_id = request.session.get("selected_bu_id")
        if _bu_id:
            try:
                _bu_obj = _BU.objects.get(id=_bu_id)
            except _BU.DoesNotExist:
                pass
    _pdf_bu_line1 = _bu_obj.name if _bu_obj else "NexusOps"
    _pdf_bu_line2 = f"{_bu_obj.bu_name} {_bu_obj.division}" if _bu_obj else ""

    def draw_header(canvas, doc):
        # Draw logo
        if logo_path:
            logo_width = 50
            logo_height = 50
            x_logo = page_width - logo_width - 40
            y_logo = page_height - logo_height - 20
            canvas.drawImage(logo_path, x_logo, y_logo, width=logo_width, height=logo_height, mask="auto")
        # Draw titles
        canvas.setFont("Helvetica-Bold", 22)
        canvas.drawCentredString(page_width / 2, page_height - 60, _pdf_bu_line1)
        canvas.setFont("Helvetica-Bold", 18)
        canvas.drawCentredString(page_width / 2, page_height - 90, _pdf_bu_line2)
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawCentredString(page_width / 2, page_height - 120, "Inventory Data")
        canvas.setFont("Helvetica-Oblique", 12)
        canvas.drawCentredString(
            page_width / 2,
            page_height - 145,
            "(Note: Automated data output. Verification recommended to ensure reliability"
            " and compliance with organizational protocols.)",
        )

    elements = [Spacer(1, 120), table]  # Reduced gap above the table

    # SubLevel Data Table
    sublevel_headers = [
        "Item Name",
        "In stock",
        "In use",
        "Scrapped",
        "Stream",
        "Last modified by",
        "Last modified date",
    ]
    sublevel_data = [sublevel_headers]
    sublevels = SubLevel.objects.all()
    for sub in sublevels:
        last_history = sub.history.order_by("-at").first()
        last_by = last_history.by if last_history else ""
        last_at = last_history.at.strftime("%Y-%m-%d %H:%M:%S") if last_history else ""
        sublevel_data.append([sub.name, sub.in_stock, sub.in_use, sub.scraped, sub.stream or "", last_by, last_at])
    if len(sublevel_data) > 1:
        sublevel_table = Table(sublevel_data, repeatRows=1)
        sublevel_style = TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#005fa3")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
                ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
        sublevel_table.setStyle(sublevel_style)
        # Set column widths for SubLevel Data table
        col_widths = [130, 90, 90, 90, 100, 120, 140]
        sublevel_table._argW = col_widths
        elements.append(Spacer(1, 40))
        elements.append(Paragraph("SubLevel Data", title_style))
        elements.append(Spacer(1, 10))
        elements.append(sublevel_table)

    doc.build(elements, onFirstPage=draw_header, onLaterPages=draw_header)

    pdf = buffer.getvalue()
    buffer.close()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _bu_slug = request.session.get("selected_bu_code", "Inventory")
    filename = f"{timestamp}_{_bu_slug}_Inventory list.pdf"
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write(pdf)
    AuditLog.log(
        "export",
        "Exported product inventory to PDF",
        user=request.user,
        request=request,
        module="products",
        severity="info",
    )
    return response


@login_required
@require_POST
def upload_products_excel(request):  # noqa: C901, CCR001
    """Upload products excel."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    if not _fac_granted(request.user) and not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=401)
    # BACKUP LOGIC
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inventory Data"
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
    ]
    ws.append(headers)
    for idx, product in enumerate(Product.objects.all(), start=1):
        # Ensure we write a plain string for stream (don't pass Stream model instances to openpyxl)
        stream_val = ""
        if hasattr(product, "stream") and product.stream is not None:
            try:
                stream_val = product.stream.name
            except Exception:
                stream_val = str(product.stream)
        ws.append(
            [
                idx,
                product.category.name if product.category else "",
                product.category.serial_number if product.category else "",
                product.name,
                product.serial_number,
                product.description,
                product.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                product.created_by.username if product.created_by else "",
                stream_val,
            ]
        )
    backup_stream = BytesIO()
    wb.save(backup_stream)
    backup_stream.seek(0)
    # Version number logic
    last_backup = UserDataVersion.objects.order_by("-created_at").first()
    if last_backup and hasattr(last_backup, "version_str"):
        # Parse previous version_str
        m = re.match(r"v(\d+)\.(\d+)\.(\d+)\.(\d+)", last_backup.version_str)
        if m:
            major, minor, patch, build = map(int, m.groups())
            build += 1
            if build > 3:
                patch += 1
                build = 1
            if patch > 9:
                minor += 1
                patch = 0
            if minor > 9:
                major += 1
                minor = 0
            version_str = f"v{major}.{minor}.{patch}.{build}"
        else:
            version_str = "v1.0.0.0"
    else:
        version_str = "v1.0.0.0"
    backup_file = ContentFile(backup_stream.read(), name=f"user_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    UserDataVersion.objects.create(
        created_by=request.user,
        description=f"Backup before upload on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        data_file=backup_file,
        version_str=version_str,
    )
    # EXISTING UPLOAD LOGIC
    excel_file = request.FILES.get("excel_file")
    if not excel_file:
        messages.error(request, "No file uploaded.")
        return redirect("user_list")
    is_valid, error_msg = validate_uploaded_file(
        excel_file, ALLOWED_EXCEL_TYPES, ALLOWED_EXCEL_EXTENSIONS, MAX_EXCEL_SIZE
    )
    if not is_valid:
        messages.error(request, error_msg)
        return redirect("user_list")
    try:
        df = pd.read_excel(excel_file)
    except Exception:
        logger.exception("Error reading uploaded Excel file")
        messages.error(request, "Error reading Excel file. Please ensure it is a valid spreadsheet.")
        return redirect("user_list")
    required_columns = [
        "S. NO",
        "Category name",
        "Category Serial Number",
        "Product Name",
        "Product Serial Number",
        "Product Description",
        "Product Added date",
        "Product added by",
        "Stream",
    ]
    for col in required_columns:
        if col not in df.columns:
            messages.error(request, f"Missing column: {col}")
            return redirect("user_list")
    mode = request.GET.get("mode", "overwrite")
    imported_count = 0
    try:
        with transaction.atomic():
            if mode == "overwrite":
                Product.objects.all().delete()
                Category.objects.all().delete()
            elif mode == "refresh":
                Product.objects.all().delete()
                Category.objects.all().delete()
                Location.objects.all().delete()
                Participant.objects.all().delete()
            for _, row in df.iterrows():
                cat_name = str(row["Category name"]).strip()
                cat_serial = str(row["Category Serial Number"]).strip()
                prod_name = str(row["Product Name"]).strip()
                prod_serial = str(row["Product Serial Number"]).strip()
                prod_desc = str(row["Product Description"]).strip()
                prod_added_by = str(row["Product added by"]).strip()
                # Resolve stream name from uploaded data to a Stream instance (avoid storing raw strings into FK fields)
                prod_stream_name = get_default_stream_name(request)
                if "Stream" in df.columns and pd.notna(row["Stream"]) and str(row["Stream"]).strip():
                    prod_stream_name = str(row["Stream"]).strip()
                prod_stream_obj, _ = Stream.objects.get_or_create(name=prod_stream_name)
                category, created_cat = Category.objects.get_or_create(
                    name=cat_name,
                    defaults={"serial_number": cat_serial, "created_by": request.user, "stream": prod_stream_obj},
                )
                # If category exists, update serial_number if needed (avoid IntegrityError)
                if not created_cat:
                    if category.serial_number != cat_serial:
                        # Show warning if serial_number is different
                        # and already exists for another category in same stream
                        if (
                            Category.objects.filter(serial_number=cat_serial, stream=prod_stream_obj)
                            .exclude(pk=category.pk)
                            .exists()
                        ):
                            messages.warning(
                                request,
                                f"Category '{cat_name}' already exists with a different serial number. "
                                "Skipped row due to duplicate serial number.",
                            )
                            continue
                        category.serial_number = cat_serial
                        category.save()
                if hasattr(category, "stream") and category.stream != prod_stream_obj:
                    category.stream = prod_stream_obj
                    category.save()
                user_obj = User.objects.filter(username=prod_added_by).first() or request.user
                product, created = Product.objects.get_or_create(
                    serial_number=prod_serial,
                    stream=prod_stream_obj,
                    defaults={
                        "name": prod_name,
                        "category": category,
                        "description": prod_desc,
                        "created_by": user_obj,
                        "updated_by": user_obj,
                    },
                )
                if not created and mode == "append":
                    product.name = prod_name
                    product.category = category
                    product.description = prod_desc
                    product.updated_by = user_obj
                    product.stream = prod_stream_obj
                    product.save()
                imported_count += 1
    except Exception:
        logger.exception("Error during Excel import — transaction rolled back")
        messages.error(request, "An error occurred during import. All changes have been rolled back.")
        return redirect("user_list")
    messages.success(request, f"Successfully imported {imported_count} products.")
    AuditLog.log(
        "import",
        f"Imported {imported_count} products from Excel upload",
        user=request.user,
        request=request,
        module="products",
        severity="warning",
    )
    return redirect("user_list")


@login_required
@require_POST
def restore_user_backup(request, backup_id):  # noqa: C901, CCR001
    """Restore user backup."""
    # pylint: disable=too-complex,too-many-locals
    if not _fac_granted(request.user) and not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=401)
    backup = get_object_or_404(UserDataVersion, id=backup_id)
    # Restore logic: read backup Excel and overwrite current data
    try:
        df = pd.read_excel(backup.data_file)
    except Exception:
        logger.exception("Error reading backup file")
        messages.error(request, "Error reading backup file. The file may be corrupted.")
        return redirect("user_list")
    required_columns = [
        "S. NO",
        "Category name",
        "Category Serial Number",
        "Product Name",
        "Product Serial Number",
        "Product Description",
        "Product Added date",
        "Product added by",
        "Stream",
    ]
    for col in required_columns:
        if col not in df.columns:
            messages.error(request, f"Missing column in backup: {col}")
            return redirect("user_list")
    # Optionally clear current data
    try:
        with transaction.atomic():
            Product.objects.all().delete()
            Category.objects.all().delete()
            imported_count = 0
            for _, row in df.iterrows():
                cat_name = str(row["Category name"]).strip()
                cat_serial = str(row["Category Serial Number"]).strip()
                prod_name = str(row["Product Name"]).strip()
                prod_serial = str(row["Product Serial Number"]).strip()
                prod_desc = str(row["Product Description"]).strip()
                prod_added_by = str(row["Product added by"]).strip()
                # Normalize stream value and convert to Stream instance
                prod_stream_name = get_default_stream_name(request)
                if "Stream" in df.columns and pd.notna(row["Stream"]) and str(row["Stream"]).strip():
                    prod_stream_name = str(row["Stream"]).strip()
                prod_stream_obj, _ = Stream.objects.get_or_create(name=prod_stream_name)
                category, created_cat = Category.objects.get_or_create(
                    name=cat_name,
                    defaults={"serial_number": cat_serial, "created_by": request.user, "stream": prod_stream_obj},
                )
                # If category exists, update serial_number if needed (avoid IntegrityError)
                if not created_cat:
                    if category.serial_number != cat_serial:
                        if (
                            Category.objects.filter(serial_number=cat_serial, stream=prod_stream_obj)
                            .exclude(pk=category.pk)
                            .exists()
                        ):
                            messages.warning(
                                request,
                                f"Category '{cat_name}' already exists with a different serial number. "
                                "Skipped row due to duplicate serial number.",
                            )
                            continue
                        category.serial_number = cat_serial
                        category.save()
                user_obj = User.objects.filter(username=prod_added_by).first() or request.user
                product, created = Product.objects.get_or_create(
                    serial_number=prod_serial,
                    stream=prod_stream_obj,
                    defaults={
                        "name": prod_name,
                        "category": category,
                        "description": prod_desc,
                        "created_by": user_obj,
                        "updated_by": user_obj,
                    },
                )
                if not created:
                    product.name = prod_name
                    product.category = category
                    product.description = prod_desc
                    product.updated_by = user_obj
                    product.stream = prod_stream_obj
                    product.save()
                imported_count += 1
    except Exception:
        logger.exception("Error during backup restore — transaction rolled back")
        messages.error(request, "An error occurred during restore. All changes have been rolled back.")
        return redirect("user_list")
    messages.success(request, f"Restored {imported_count} products from backup.")
    AuditLog.log(
        "import",
        f"Restored {imported_count} products from backup (version: {backup.version_str})",
        user=request.user,
        request=request,
        module="products",
        severity="warning",
    )
    return redirect("user_list")
