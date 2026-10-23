"""Public plugin model API."""

from components.plugins.src.model import (
    PLUGIN_API_VERSION,
    BoardProfile,
    PluginAction,
    PluginDefinition,
    PluginSetting,
    PluginView,
    PluginViewDefinition,
    UiEvent,
    plugin_config,
    plugin_enabled,
    set_plugin_enabled,
)

__all__ = [
    "PLUGIN_API_VERSION",
    "BoardProfile",
    "PluginAction",
    "PluginDefinition",
    "PluginSetting",
    "PluginView",
    "PluginViewDefinition",
    "UiEvent",
    "plugin_config",
    "plugin_enabled",
    "set_plugin_enabled",
]
