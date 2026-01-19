from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver
from django.utils import timezone
from .models import UserSession


@receiver(user_logged_out)
def mark_session_inactive(sender, request, user, **kwargs):
    """Mark user session as inactive when they log out"""
    if hasattr(request, 'session') and request.session.session_key:
        try:
            session = UserSession.objects.get(
                session_key=request.session.session_key,
                user=user
            )
            session.is_active = False
            session.save()
        except UserSession.DoesNotExist:
            pass  # Session might not exist if user was never tracked
