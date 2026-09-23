from django.urls import path, include, re_path
from django.views.generic.base import RedirectView
from .views import serve_frontend_page

urlpatterns = [
    path("api/", include("accounting.urls")),
    path("favicon.ico", RedirectView.as_view(url="/assets/img/favicon.png", permanent=True)),
    path("", serve_frontend_page, name="home"),
    re_path(r"^(?P<path>[a-zA-Z0-9_\-]+(?:\.html)?)$", serve_frontend_page, name="frontend_page"),
]
