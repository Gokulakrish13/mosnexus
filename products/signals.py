# pylint: disable=import-outside-toplevel,logging-too-many-args,unused-argument
import logging
import os
import shutil

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_out
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import UserSession

User = get_user_model()  # pylint: disable=invalid-name

logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def assign_app_admin_to_superuser(sender, instance, created, **kwargs):
    """Auto-assign app_admin role to superusers only on first creation
    (e.g. created via createsuperuser). Subsequent role changes are managed
    explicitly through the UI so the signal does not re-add removed roles."""
    if created and instance.is_superuser:
        from .models import CustomUser, UserRole

        cp, _ = CustomUser.objects.get_or_create(user=instance)
        if not cp.user_roles.filter(role="app_admin").exists():
            UserRole.objects.get_or_create(custom_user=cp, role="app_admin")
            logger.info('Auto-assigned app_admin role to new superuser "%s"', instance.username)


@receiver(user_logged_out)
def mark_session_inactive(sender, request, user, **kwargs):
    """Mark user session as inactive when they log out"""
    if hasattr(request, "session") and request.session.session_key:
        try:
            session = UserSession.objects.get(session_key=request.session.session_key, user=user)
            session.is_active = False
            session.save()
        except UserSession.DoesNotExist:
            pass  # Session might not exist if user was never tracked


@receiver(post_save, sender="products.BusinessUnit")
def create_bu_showcase_folder(sender, instance, created, **kwargs):
    """Create a showcase image folder when a new Business Unit is created.
    Note: app_admin users automatically have access to all BUs via the
    runtime bypass in can_access_bu() — no explicit UserBUAccess records needed."""
    # Validate slug to prevent path traversal (only allow alphanumeric, hyphens, underscores)
    import re

    if not re.match(r"^[a-zA-Z0-9_-]+$", instance.slug):
        logger.warning("Refusing to create showcase folder for BU with unsafe slug: %s", instance.slug)
        return
    folder_path = os.path.join(settings.MEDIA_ROOT, "bu_showcase", instance.slug)
    # Verify the resolved path stays within MEDIA_ROOT
    resolved = os.path.realpath(folder_path)
    if not resolved.startswith(os.path.realpath(str(settings.MEDIA_ROOT))):
        logger.warning("Path traversal attempt blocked for BU slug: %s", instance.slug)
        return
    if not os.path.exists(folder_path):
        os.makedirs(folder_path, exist_ok=True)


@receiver(post_delete, sender="products.BusinessUnit")
def delete_bu_showcase_folder(sender, instance, **kwargs):
    """Delete the showcase image folder (and its contents) when a BU is deleted."""
    # Validate slug to prevent path traversal
    import re

    if not re.match(r"^[a-zA-Z0-9_-]+$", instance.slug):
        logger.warning("Refusing to delete showcase folder for BU with unsafe slug: %s", instance.slug)
        return
    folder_path = os.path.join(settings.MEDIA_ROOT, "bu_showcase", instance.slug)
    # Verify the resolved path stays within MEDIA_ROOT
    resolved = os.path.realpath(folder_path)
    if not resolved.startswith(os.path.realpath(str(settings.MEDIA_ROOT))):
        logger.warning("Path traversal attempt blocked for BU slug: %s", instance.slug)
        return
    if os.path.exists(folder_path):
        shutil.rmtree(folder_path, ignore_errors=True)
