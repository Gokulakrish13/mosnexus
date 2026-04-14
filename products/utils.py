from django.http import Http404

from .models import Stream


def get_default_stream_for_bu(request):
    """Return the first active stream name for the current BU, or 'HIC' as fallback."""
    bu = getattr(request, "current_bu", None)
    if bu:
        first = (
            Stream.objects.filter(business_unit=bu, is_active=True)
            .order_by("name")
            .values_list("name", flat=True)
            .first()
        )
        if first:
            return first
    return "HIC"


def get_stream_or_404(name, default=None, request=None):
    """Resolve a Stream by name or raise Http404.

    - If name is falsy and default is provided, default will be used.
    - If name is falsy, default is None, and request is provided,
      falls back to the first stream in the current BU.
    - Raises Http404 when stream is not found.
    """
    if not name or str(name).strip() == "":
        if default is not None:
            name = default
        elif request is not None:
            name = get_default_stream_for_bu(request)
        else:
            raise Http404("Stream not specified")
    try:
        return Stream.objects.get(name=name)
    except Stream.DoesNotExist as exc:
        raise Http404(f"Stream '{name}' not found") from exc
