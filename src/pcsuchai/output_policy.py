"""Explicit scientific output policies, separate from benchmark observation."""

from __future__ import annotations

POLICIES = ("onboard", "validation")


def validate_output_policy(value: str) -> str:
    """Reject unknown policies before doing science or opening output files."""

    if value not in POLICIES:
        raise ValueError("output_policy must be onboard or validation")
    return value


def effective_output_policy(settings: dict) -> str:
    """Interpret missing historical fields without rewriting saved documents.

    Earlier runs always wrote full scientific arrays/tables. They retain that
    validation behavior and are labelled as historical by readers separately.
    """

    return validate_output_policy(settings.get("output_policy", "validation"))


def policy_origin(settings: dict) -> str:
    """Expose whether a saved policy was declared or predates this feature."""

    return "explicit" if "output_policy" in settings else "historical_implicit_validation"
