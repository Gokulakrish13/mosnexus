# pylint: disable=invalid-name
import os

from products import views

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404
from django.shortcuts import redirect
from django.urls import include, path, re_path
from django.utils.http import urlencode
from django.views.static import serve


def protected_media_view(request, file_path):  # pylint: disable=redefined-outer-name
    """
    Serve media files only to authenticated users.
    Prevents unauthenticated access to uploaded documents, backups, etc.
    Health-check related files and product images remain public for QR scanning.
    """
    # Allow unauthenticated access to product images only (for QR code scanning)
    public_prefixes = ("product_images/",)
    is_public = any(file_path.startswith(prefix) for prefix in public_prefixes)

    if not is_public and not request.user.is_authenticated:
        return redirect("/please_login/?" + urlencode({"next": request.get_full_path()}))

    # Prevent path traversal
    full_path = os.path.join(settings.MEDIA_ROOT, file_path)
    if not os.path.realpath(full_path).startswith(os.path.realpath(str(settings.MEDIA_ROOT))):
        raise Http404
    return serve(request, file_path, document_root=settings.MEDIA_ROOT)


urlpatterns = [
    path("phnx-admin-secure/", admin.site.urls),  # Obscured admin URL
    path("", include("products.urls")),
    path("please_login/", views.please_login, name="please_login"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
else:
    # Serve media files with authentication when DEBUG=False
    urlpatterns += [
        re_path(r"^media/(?P<file_path>.*)$", protected_media_view),
    ]
