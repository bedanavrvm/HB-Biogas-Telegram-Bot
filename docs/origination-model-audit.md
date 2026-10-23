# Origination model and alignment audit

23 October 2026. Scope: all 31 models present before this change, their current
writers/readers, Admin exposure, and compatibility dependencies. The resulting
runtime app has 29 models. This is a source and isolated-test audit; production
row counts, Drive files, OTP delivery and handset behaviour were not inspected.

## Findings and changes

1. The test-deletion confirmation bound the deletion mode as well as the actor
   and selected IDs. Switching the mode and pressing Confirm raised a 403. A
   mode change now displays a fresh impact and confirmation; actor or selection
   tampering still fails. No deletion occurs on the refreshed preview.
2. Document publication allowed alignment warnings, but product attachment and
   readiness reapplied completeness checks. Published supporting documents now
   remain attachable with warnings. Integrity, valid supplied geometry,
   compatible field types, permissions and revision checks remain enforced.
   Signing-package/link creation still checks required signature geometry.
3. Signature duplication was disabled in the editor. It now adds signature and
   paired date slots to the same participant. One verified capture supplies
   every slot owned by that participant; it does not add another signer or OTP.
4. The old form projection explicitly exposed unplaced identity, signer, lending
   and dependency fields. This caused the SME's guarantor ID signing section.
   Version 2 accepts only fields actually placed on the captured selected PDFs.
   Empty sections disappear, hidden required fields cannot block a save, and
   retained hidden answers cannot become active calculation inputs. Existing
   drafts and correction forms adopt this rule on an audited write. Previously
   submitted version-1 packets retain their interpretation and signed bytes.
   A missing layout also yields no filling inputs, rather than a full-schema fallback.
5. Signature rows lacked Edit. Edit now opens the owning signer's label,
   required status and name/OTP-phone/ID links. The ID link can be explicitly omitted.
   Placing linked fields remains necessary to collect their values in the form.
6. Two legacy authoring models are retired below. Other apparently empty models
   are conditional workflow/evidence records with live writers and readers.
   Empty does not establish that they are obsolete.

## Which records control alignment and OTP?

| Record / field | Owns |
| --- | --- |
| `OriginationDataField.key`, `data_type`, `value_contract` | Canonical meaning and validation of a reusable data variable. There is no OTP control in an ordinary data field. |
| `OriginationDocumentTemplate.form_schema` | Fields available to that PDF, required-field flags, sections and value contracts. Availability in the catalogue does not make a field visible in filling. |
| `OriginationDocumentTemplate.signer_rules` | Individual participants, `role`, optional `participant_key`, `required`, `identity_fields` and `slots`. `identity_fields.phone` names the saved field used for external OTP dispatch. Name and optional national-ID links bind identity. |
| `OriginationTemplateConfigurationRevision.configuration` | `field_overlay_manifest.fields[*].context_key` and page/box control placed data fields. `signature_overlay_manifest.slots` controls signature/stamp/date geometry keyed by `role.slot_key`. |
| `OriginationDocumentTemplate.published_configuration_revision` | Exact immutable published layout selected for new captures. Editing a successor does not upgrade existing applications. |
| `OriginationDocumentTemplateEvent.metadata.warnings` | Publication-time warning evidence. Live warnings are computed by `document_editor.readiness()` from the saved source, schema, signers and layout; they are not stored in a dedicated warning model. |
| `OriginationSigningPackage.participants_snapshot` | Frozen participant identity and document/slot obligations for that package. |
| `OriginationSignerSession` → `OriginationOtpChallenge.session` | Session-bound OTP challenge and capture. OTP verification is a signing operation, not an ordinary form input. |
| `OriginationSigningAction` | Per-document/per-slot verification evidence using the same capture hash when one person signs multiple slots. |

For example, copying `borrower.signature` creates `borrower.signature_copy`
under the same borrower rule, plus a paired date slot. Editing that signature
opens that borrower, rather than creating another person. Published documents
are immutable; create an editable successor to change their signer configuration.

The SME seed declares borrower and two guarantor signers. Their default identity
links previously triggered unplaced fields in “Signing details.” Document signer
settings now determine the chosen people and links, while PDF placement alone
determines the filling inputs. Staff signers use their authorized staff identity;
workflow grants remain independent and cannot be configured through a PDF.

## Complete model inventory

The producer column names current services, not historical migrations. Ordinary
operational/audit rows remain retained with their owning record; testing cleanup
uses the existing reviewed, gated scope. Global fields, shared documents,
identities, compliance evidence and external files retain their own boundaries.

| Model | Purpose, writer and reader | Why it can be empty / decision |
| --- | --- | --- |
| `OriginationDataField` | Global canonical variables. `origination_fields.create_data_field`, commercial catalogue and reviewed LAF seeds write; editor, schema snapshots and reporting read. | Empty before catalogue/bootstrap. Keep. Key/type and captured semantics are governed. |
| `OriginationDataFieldEvent` | Append-only field creation/change/attachment evidence written by field services and seeds; Admin/audit readers. | Empty until a governed field operation. Keep. |
| `OriginationProductDefinition` | Immutable published form/product-version configuration; setup, cloning and reviewed seeds write; application creation and catalogue read. | Empty before product setup. Keep. Old technical editor URLs now open the current guided workspace. |
| `OriginationProductDefinitionEvent` | Product lifecycle/setup/version audit; setup, field and template services write. | Empty until a product operation. Keep. |
| `OriginationFieldReviewIssue` | Old schema reconciliation queue, produced by legacy binding/cloning and resolved in its own Admin. | **Retired.** It is not the alignment-warning list. Current binding rejects incompatible canonical types directly. Migration refuses to drop nonempty tables. |
| `OriginationDocumentTemplate` | Independent Drive-backed Main LAF/supporting PDF version with schema, signers and publication state; editor, uploads and reviewed seeds write; packets/rendering read. | Empty before document setup. Keep. Source bytes must match their saved hash. |
| `OriginationDocumentProductEligibility` | Current explicit document/global-product allowlist; editor and setup write; product selection and catalogue read. | Empty until a document is assigned eligible products. Keep; through-table editing belongs in the document workspace. |
| `OriginationProductDocumentAssignment` | Old per-form-version document family assignment and pinned/latest-compatible policy. | **Retired**, including its Admin, packet routes, resolver, inheritance and obsolete packet demo seed. Current catalogue uses exact document eligibility and captured versions. Migration refuses to drop nonempty tables. |
| `OriginationDocumentTemplateEvent` | Template source, editing, publication and warning history; editor/template/setup services write. | Empty before document operations. Keep. |
| `OriginationTemplateConfigurationRevision` | Saved/revision-checked PDF alignment and immutable publication; calibration services write; editor and packets read. | Empty until an alignment save. Keep; not interchangeable with the template's current draft JSON. |
| `LoanOriginationApplication` | Canonical revision-controlled captured application; `loan_origination` creates and transitions; Mini App, Admin and signing read. | Empty before application capture. Keep. Snapshots and history are authoritative. |
| `OriginationCommercialException` | Exact-revision commercial policy exception evidence; commercial-term approval service writes; submit/approval checks read. | Empty if no exception is requested. Keep. |
| `OriginationReportingValue` | Typed, allowlisted reporting projection; `origination_fields.project_reporting_values` writes; reporting reads. | Empty for nonreportable/restricted fields or before projection. Keep; rebuildable projection, not raw form truth. |
| `OriginationApplicationEvent` | Application save, transition, correction and projection-adoption audit; `loan_origination._record_event` and workflow services write. | Empty before application actions. Keep. |
| `OriginationReviewerNotice` | Application/package-specific reviewer notifications; Origination review/dispatch services write; authorized Mini App queues read. | Empty until a notice condition. Keep; lack of a standalone Admin is intentional. |
| `OriginationCorrectionRequest` | Reviewer-requested revision correction; final-review service writes; officer/reviewer flows read. | Empty if no corrections requested. Keep. |
| `OriginationCorrectionItem` | Exact targets within a correction request; final-review service writes; correction UI/save validation reads. | Empty without a targeted correction. Keep. |
| `OriginationRequirementEvidence` | Requirement and ID upload evidence with saved identity/revision binding; evidence/identity-copy services write; review/signing read. | Empty without uploads or optional ID collection. Keep; independent Drive retention still applies. |
| `OriginationApplicationDocument` | Selected/unselected captured packet document, schema, signer rules and local answers; packet and document-choice services write; filling/rendering/signing read. | Empty before packet capture. Keep. Removed nullable legacy assignment FK does not remove template/schema snapshots. |
| `OriginationSigningParticipant` | Named participants in optional Admin-configured all-required plans; signing-plan service writes; dispatch/workspace/completion read. | Role-based/historical applications need no rows. Keep. |
| `OriginationConsentPolicyVersion` | Approved immutable consent wording managed in Admin; consent selection and frozen signing packages read. | New short-acknowledgement packages need no policy row; historical/custom approved consent still does. Keep; do not infer legal approval from template publication. |
| `OriginationSigningPackage` | Frozen document bytes, manifest, participants and consent; prepare/signing services write; preview/review/OTP/completion/downloads read. | Empty before preparation. Keep; no reconstruction of historical signed bytes. |
| `OriginationStampAsset` | Versioned Admin-managed stamp PNG; signing actions/renderers read. | Empty if no configured stamp obligation. Keep. |
| `OriginationSignerSession` | Exact package/participant signing link, identity, consent and capture; e-signing service writes; public signing and completion read. | Empty until a signer session/link is created. Keep; not a staff access grant. |
| `OriginationOtpChallenge` | Session-bound hashed OTP with expiry/attempt evidence; e-signing issue/verify writes. | Empty until OTP issuance. Keep; SMS acceptance does not itself prove verification. |
| `OriginationSigningRequestEvent` | Signing request/abuse-throttle evidence; public e-signing handlers write and throttle reads. | Empty before relevant requests. Keep; required security evidence. |
| `OriginationSigningAction` | Immutable signature/stamp proof per package/document/slot; signing/e-signing write; completion/rendering read. | Empty before a successful signing action. Keep. Multiple slots may share one capture. |
| `OriginationSigningActionInvalidation` | Append-only supersession/invalidation evidence; correction/review/workflow services write; current-action readers exclude invalidated proof. | Empty when no signed action has been invalidated. Keep; do not delete old proof to express invalidation. |
| `OriginationPhoneIdentitySubject` | Exact phone/ID pilot subject and serialization lock; `phone_identity` uses its `Subject` alias. | Optional Daraja pilot disabled or unused. Keep; alias-based writers explain misleading zero literal-name search results. |
| `OriginationPhoneIdentityCheck` | Retained check/provider and application receipt evidence; `phone_identity` uses its `Check` alias; scoped IT check status/reuse reads. | Empty until pilot use. Keep; phone registration is not OTP or consent. |
| `OriginationPhoneIdentityDailyUsage` | Pilot dispatch reservations and Nairobi daily cap; `phone_identity` uses its `Usage` alias. | Empty until a paid pilot dispatch reservation. Keep; no automatic paid retries. |

Twenty-seven models originally retained historical physical `core_...` table
names after domain ownership transfer; named signing participants and the three
phone-pilot tables use domain names. A table prefix does not establish that a model is obsolete. Historical
migrations remain intact so old installations can traverse the checked-in graph.

## Migration and rollback

`origination.0012_remove_legacy_authoring_models` checks **both legacy tables
before any schema change**. It stops with counts if either contains records.
PostgreSQL locks both tables through the atomic migration to prevent a legacy
writer racing that check.
Reconcile and retain those records under the old release before rollout; no
automatic conversion, bulk deletion or production reconciliation was performed.
After that precondition it removes the two tables and the nullable packet
assignment FK and updates PostgreSQL comments. Application/template snapshots,
document bytes, signing evidence, current eligibility rows and external files
are retained. Reversing to `0011_phone_identity_pilot_capability` recreates the
empty legacy tables/FK; restore the corresponding code release with the schema.

## Verification evidence

Validation uses synthetic records, isolated loopback PostgreSQL and mocked
Drive/SMS. Native authenticated Admin browser checks exercise save/reload,
repeated signature slots, signer ID configuration and publication immutability
at mobile/desktop widths in light/dark. Mini App browser checks exercise the
version-2 projection and retained-hidden-answer filtering. Migration checks
exercise nonempty guards, empty upgrade and rollback while retaining application
payload and frozen bytes. Exact outcomes and known pre-existing suite failures
are recorded in the session validation notes in `KNOWN_GAPS.md`.
