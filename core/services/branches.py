"""Shared workflow branch configuration helpers."""
from __future__ import annotations

from typing import Any


DEFAULT_WORKFLOW_BRANCHES = ['Biogas Unit', 'Embu', 'Nakuru', 'West Nairobi']
STALE_BRANCH_DEFAULTS = {'Corporate', 'Thika Road', 'East Nairobi', 'West Nairobi', 'Nakuru', 'Embu', 'Limuru'}


def normalize_branch_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        items = value.split(',')
    else:
        items = value
    branches: list[str] = []
    for item in items:
        branch = str(item or '').strip()
        if branch and branch not in branches:
            branches.append(branch)
    return branches


def workflow_branches(
    workflow: dict | None = None,
    *,
    default: list[str] | None = None,
    replace_stale_defaults: bool = False,
) -> list[str]:
    workflow = workflow or {}
    branches = normalize_branch_list(workflow.get('branches'))
    fallback = list(default or DEFAULT_WORKFLOW_BRANCHES)
    if replace_stale_defaults and branches and set(branches).issubset(STALE_BRANCH_DEFAULTS):
        return fallback
    return branches or fallback


def workflow_default_branch(workflow: dict | None = None, *, fallback: str = '') -> str:
    workflow = workflow or {}
    configured = str(workflow.get('default_branch') or workflow.get('branch') or '').strip()
    if configured:
        return configured
    branches = workflow_branches(workflow, default=[]).copy()
    return branches[0] if len(branches) == 1 else str(fallback or '').strip()


def validate_workflow_branch(branch: str, workflow: dict | None = None, *, allow_blank: bool = False) -> str:
    value = str(branch or '').strip()
    if not value:
        if allow_blank:
            return ''
        raise ValueError('Select a valid branch.')
    branches = workflow_branches(workflow, default=[])
    if branches and value not in branches:
        raise ValueError('Select a valid branch.')
    return value
