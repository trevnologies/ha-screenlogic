"""Pick the schema library the running Home Assistant release expects.

Home Assistant core replaced voluptuous with probatio for config flows and
service schemas (core 2026.10, home-assistant/core#182112). Older releases
this fork still supports use voluptuous. Rather than guessing from version
numbers, schemas are built with the same library Home Assistant's own
data_entry_flow uses.
"""

from __future__ import annotations

import importlib
from types import ModuleType

from homeassistant import data_entry_flow


def _schema_lib() -> ModuleType:
    """Return the library data_entry_flow validates form schemas with."""
    lib = getattr(data_entry_flow, "probatio", None) or getattr(
        data_entry_flow, "vol", None
    )
    if lib is None:  # pragma: no cover - defensive, should never happen
        lib = importlib.import_module("voluptuous")
    return lib


vol: ModuleType = _schema_lib()
