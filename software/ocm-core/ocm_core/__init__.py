# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_core — load and validate OCM module manifests and cell compositions.

The first link in the generator chain (ROADMAP Step 1): scene/, planner/,
and emitters/ all consume a typed Module or Cell instead of walking raw YAML.
"""

from .cell import (
    Base,
    Cell,
    CellSafety,
    Consumable,
    Controller,
    InstanceAddress,
    InstanceMount,
    ModuleInstance,
    ModuleRef,
    Pose,
    validate_cell_dict,
)
from .errors import CellLoadError, ManifestValidationError, OcmCoreError
from .loader import load_cell, load_module, load_schema, validate_module_dict
from .module import (
    Capability,
    Comms,
    Connector,
    Electrical,
    Geometry,
    Maintenance,
    Mechanical,
    Module,
    Motion,
    Mount,
    PathSpec,
    Process,
    Safety,
    Signal,
    StateMachine,
    Supply,
    WearItem,
)
from .parameter import Frame, Parameter

__all__ = [
    "Base",
    "Capability",
    "Cell",
    "CellLoadError",
    "CellSafety",
    "Comms",
    "Connector",
    "Consumable",
    "Controller",
    "Electrical",
    "Frame",
    "Geometry",
    "InstanceAddress",
    "InstanceMount",
    "Maintenance",
    "ManifestValidationError",
    "Mechanical",
    "Module",
    "ModuleInstance",
    "ModuleRef",
    "Motion",
    "Mount",
    "OcmCoreError",
    "Parameter",
    "PathSpec",
    "Pose",
    "Process",
    "Safety",
    "Signal",
    "StateMachine",
    "Supply",
    "WearItem",
    "load_cell",
    "load_module",
    "load_schema",
    "validate_cell_dict",
    "validate_module_dict",
]
