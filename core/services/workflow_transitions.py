"""Shared integrity primitives for server-owned workflow transitions.

The workflows retain their own business guards.  This module only provides
the invariant every state-changing service must share: a caller cannot replace
newer work with a stale screen, and callers receive a stable conflict error.
"""

from __future__ import annotations


class WorkflowTransitionError(ValueError):
    """Base class for safe workflow transition validation failures."""

    code = 'workflow_transition_invalid'


class WorkflowRevisionRequired(WorkflowTransitionError):
    code = 'workflow_revision_required'

    def __init__(self) -> None:
        super().__init__('Reload this case before saving. A workflow revision is required.')


class WorkflowRevisionConflict(WorkflowTransitionError):
    code = 'workflow_revision_conflict'

    def __init__(self, *, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__('This case changed while you were working. Refresh and review the latest details before saving.')


def parse_expected_revision(value) -> int:
    """Normalize a client revision without accepting zero/negative values."""
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise WorkflowRevisionRequired() from exc
    if revision < 1:
        raise WorkflowRevisionRequired()
    return revision


def validate_workflow_revision(record, expected_revision: int | None, *, required: bool = False) -> None:
    """Reject stale writes after the caller has locked a fresh record."""
    if expected_revision is None:
        if required:
            raise WorkflowRevisionRequired()
        return
    expected = parse_expected_revision(expected_revision)
    actual = int(getattr(record, 'workflow_revision', 1) or 1)
    if expected != actual:
        raise WorkflowRevisionConflict(expected=expected, actual=actual)


def next_workflow_revision(record) -> tuple[int, int]:
    """Advance the in-memory revision exactly once for one committed mutation."""
    before = int(getattr(record, 'workflow_revision', 1) or 1)
    after = before + 1
    record.workflow_revision = after
    return before, after
