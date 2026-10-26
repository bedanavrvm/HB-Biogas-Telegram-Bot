# Origination-owned document and product configuration

Accepted 26 October 2026 under the user's implementation request.

Global `Product` identity and immutable `ProductVersion` financial terms remain
shared. Origination's existing versioned `OriginationProductDefinition` owns its
`workflow_configuration`: requirements and operational custom attributes. This
uses the existing app-owned extension instead of creating another product model.
An Origination successor can retain the same financial version. Editing shared
financial terms is a separate, explicitly labelled action.

Migration 0014 copies applicable existing configuration into each Origination
definition. Shared rows remain for TAT/SPIN and historical readers. New applications
capture local configuration in their existing terms snapshot; historical application
snapshots remain authoritative. Removing an Origination requirement never alters
another workflow's requirement. Published configuration changes use an editable
Origination successor and retain normal revision/idempotency checks.

Seed signer-role suggestions are authoring notes, not hidden requirements. Document
signer lists are authoritative, including an empty list. Removing a previously
placed signature/stamp also removes its configured obligation when no signing action
remains for that person on that document. Paired signing dates are removed together.
Newly configured but unplaced signing actions still need geometry before signing;
publication alone never supplies consent or proves a complete signing configuration.

Explicit compatible identity mappings may reference application/Main LAF values.
The editor does not recreate removed local fields to satisfy those references.
Actual selected-packet values supply signer identity; OTP still needs a valid saved
phone. An asset owner, spouse or other distinct person is never assumed to be the
applicant. Retained calculations and conditions must have valid dependencies.
The old seeded `applicant_v1` flag cannot force removed identity fields on forms
using placement policy v2; retained required fields and OTP validation still apply.
Document compatibility is checked for selected combinations rather than forcing
every allowed document to work with every other document.

New catalogue applications capture visible `loan_amount` and `repayment_tenor`
inputs in Loan details, independently of PDF placements. Those values remain
subject to the captured global financial policy. They are not extra document
fields and are entered only once, including when printed by multiple documents.
This is the explicit application-input exception to ADR 0047. Existing signed and
submitted policy snapshots are not backfilled; unsigned document refresh preserves
the application's captured input policy and financial values.

Origination reset touches only Origination-owned records. Global catalogue reset
refuses the whole action when another app has configuration, availability, grants
or operational/history references to an affected product. The service checks this
again while holding Product row locks. No force override or external deletion is
introduced. Unused-only catalogue reset retains its existing audited retry and
rollback behavior. Shared catalogue controls are separate from Origination setup.

Deploy migration 0014 before the application code is used. No reseed or production
reset is required. Back up local configuration before rolling back the new column;
reverse migration drops that configuration, while existing application snapshots
and shared financial terms survive. This change does not restore products affected
by a historical reset; recovery requires examining that reset's audit records.
