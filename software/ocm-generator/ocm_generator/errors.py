# SPDX-License-Identifier: AGPL-3.0-or-later
"""Base error type shared across ocm_generator's stages (scene/, and later
planner/, emitters/, validate/)."""

from __future__ import annotations


class OcmGeneratorError(Exception):
    """Base class for all ocm_generator errors."""
