"""Main menu item builder API."""

from __future__ import annotations

from components.main_menu.src.commands import MainMenuCommandItemsService, main_menu_command_items_service
from components.main_menu.src.items import MainMenuBuilder, main_menu_builder
from components.main_menu.src.setup import MainMenuSetupItemsService, main_menu_setup_items_service

__all__ = [
    "MainMenuBuilder",
    "MainMenuCommandItemsService",
    "MainMenuSetupItemsService",
    "main_menu_builder",
    "main_menu_command_items_service",
    "main_menu_setup_items_service",
]
