# Architecture boundaries

## Rule

HTTP views authenticate, authorize, parse input, call a service, and map a
stable response. They do not add workflow, permission, financial, sheet, or
document business rules. Templates render supplied data; they do not decide
business state.

`scripts/check_architecture_boundaries.py` freezes the current direct ORM
mutation in `core/api` and fails CI if a new one appears. The single baselineed
media-access audit insertion will move to its service when that endpoint is
next changed; it is not permission to add other view-layer mutations.

## Review checklist

- A new state/role/amount/stage condition belongs in a model or service.
- A multi-table mutation uses `transaction.atomic()`; a concurrent transition
  locks the canonical record before checking its version.
- A workflow/permission/FSM rule has one allowed and one denied-path test.
- A Mini App write accepts and preserves the shared request retry key.
- An outbound call happens after canonical local state is committed and leaves
  a truthful retry/dead-letter state on failure.

## Dependencies

`requirements.txt` is the canonical runtime dependency manifest used by CI
and Render. `pyproject.toml` mirrors it for Poetry metadata. Dependabot checks
the canonical pip manifest monthly; the operator performs a quarterly review
for Django/Python security and compatibility notices before applying updates.
