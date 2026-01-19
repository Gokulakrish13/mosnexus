from django.http import Http404
from .models import Stream


def get_stream_or_404(name, default=None):
    """Resolve a Stream by name or raise Http404.

    - If name is falsy and default is provided, default will be used.
    - Raises Http404 when stream is not found.
    """
    if not name or str(name).strip() == '':
        if default is not None:
            name = default
        else:
            raise Http404('Stream not specified')
    try:
        return Stream.objects.get(name=name)
    except Stream.DoesNotExist:
        raise Http404(f"Stream '{name}' not found")
