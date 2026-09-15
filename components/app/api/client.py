"""Application client facade API."""

from __future__ import annotations

from components.app.src.client import ClientAppDependencies, client_app_class

__all__ = [
    "ClientAppDependencies",
    "client_app_class",
]
