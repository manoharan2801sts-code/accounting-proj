import os
from pathlib import Path
from django.http import FileResponse, Http404
from django.conf import settings


def serve_frontend_page(request, path="index.html"):
    """
    Serves static HTML pages (index.html, dashboard.html, etc.) from the workspace root.
    Allows running the entire frontend + backend as a single unified service on Render.
    Supports clean URLs (e.g. /dashboard loads dashboard.html).
    """
    if not path or path == "" or path == "/":
        path = "index.html"

    clean_name = os.path.basename(path.rstrip("/"))
    if not clean_name:
        clean_name = "index.html"

    # If filename has no extension, check if .html file exists
    if not clean_name.endswith(".html"):
        clean_name = f"{clean_name}.html"

    file_path = (settings.PROJECT_DIR / clean_name).resolve()

    # Prevent directory traversal
    if not str(file_path).startswith(str(settings.PROJECT_DIR.resolve())):
        raise Http404("Not found")

    if file_path.exists() and file_path.is_file():
        return FileResponse(open(file_path, "rb"), content_type="text/html")

    raise Http404(f"Page '{clean_name}' not found")
