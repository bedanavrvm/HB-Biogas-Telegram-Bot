# Origination: Product and Document workspaces

## Open the right workspace

- **Product:** Django Admin → Origination product definitions → Guided product setup.
- **Document:** Django Admin → Origination document templates → New document, or open a document's editor.
- Configuration requires an active Django Superuser. Mini App grants are separate.

A Product owns lending terms and chooses documents. A Document owns its PDF,
signers, applicant fields and placement. Products do not own editable PDF copies.
See [ADR 0041](adr/0041-independent-origination-authoring.md).

## Product: three tasks, any order

Open a product to see three cards with **Not started**, **Needs attention**, or
**Done**. Each card opens its own task; there is no forced next step.

- **Details:** name, available branches and optional descriptive information.
- **Lending terms:** amount limits, tenor, interest and repayment. Fees and
  additional requirements stay collapsed until needed.
- **Documents:** select eligible published Main LAFs and optional supporting
  documents. Open a document to author it in the separate editor.

Changes autosave after a short pause. **Saved** means the server confirmed the
save. If saving fails, entered values remain; fix the inline error or tap the
save status to retry. Relevant changes in another tab produce a conflict rather
than overwriting them.

The sticky footer shows how many tasks remain and one **Publish** button.

- Publish documents separately before selecting them for a usable product.
- Product Publish atomically publishes its lending terms and Origination
  profile. A failure does not leave only the terms enabled.
- Existing consent and final-approver checks remain mandatory.
- Incomplete drafts can be saved and reopened.
- Publishing a product never publishes an unfinished PDF.

## Document: PDF → Signers → Fields → Placement → Preview

### Start

- Prefer **Start from an existing document** to reuse its PDF, signers, fields
  and placement as an independent copy.
- Alternatively expand **Upload a PDF instead** and select a PDF.
- Give it a name and choose Main LAF or supporting-document purpose.
- Optionally choose products that may use it, including draft products.
- Select **Create document** to enter the editor.
- A failed upload retains its reserved document and retry identity. Retry the
  same file instead of creating another document.

### Signers

- Choose a signer pack, then adjust it; or add signers individually.
- Edit the displayed signer names and required status in this same editor.
- Remove a signer with confirmation. Only that draft's signing placements are
  removed; published documents and existing applications do not change.
- External signer identity fields are added to the draft form automatically.
- Approval roles still come from the product's governed approval policy. A
  signer pack never changes that policy or activates consent wording.

### Fields and placement

- Add existing canonical fields or create fields through the established field
  dialog.
- Use **Add lending fields** for the standard amount and repayment-tenor inputs.
- Edit labels, required status and order. Canonical keys and types stay governed.
- Use the server's **To do** list to find missing work.
- Select a **Place** item, then click the PDF where it belongs.
- Select a placed field to move or resize it.
- Coordinates, rotation and padding are under **Advanced** controls.
- A removed field loses its draft placement, not its historical application
  values.

### Preview and publish

- Switch between the original PDF and **Filled sample** without leaving the
  editor.
- Fields, signers, product choices and placement autosave. There is no separate
  Save draft / Save & return / Check again sequence.
- Readiness is recomputed on the server after saves.
- One **Publish** validates the saved layout, source file, contract and
  affected products before activating it.
- Missing required signers, consent, lending inputs or valid placement still
  block publication with repair tasks or a specific error.
- Published documents are read-only. Choose **Edit** to make the next change.

Readiness is deliberately a cheap database projection: it does not download a
PDF during every refresh. Final publication retains full source and geometry
validation; an external file failure cannot be mistaken for a successful publish.

## Editing a published document

Choose explicitly:

- **Change for all products:** reopen/create the next shared editable version.
  Publishing names the affected products and validates the current impact.
- **Make a copy for one product:** choose a product that uses the document.
  The copy keeps the original PDF and mapping but belongs to an independent
  document family. Publishing it replaces only that product's eligibility.

No automatic product-specific fork is created by simply selecting a document.
Old published versions and application snapshots are retained.

On a published Product, change document choices without cloning unchanged
lending terms. Removing its last Main LAF requires confirmation that new
applications will stop. Existing applications remain unchanged. Editing
commercial terms uses the existing next-draft Product action.

## Safety and compatibility

- Django owns configuration; Drive stores the source PDF, not workflow state.
- Every new write checks active-Superuser authority server-side.
- Request keys bind retries to saved content; stale revisions do not overwrite
  another editor's work.
- Product autosaves and their retry receipts commit in the same transaction.
- Document publication and eligibility replacement are transactional.
- The selected Main LAF owns its signer contract. Stale product mirrors cannot
  silently inject additional signers; configured final approval roles are
  still validated.
- Existing applications retain their exact terms, schema, documents, mappings,
  signer rules, consent and approval policy.
- Legacy advanced model routes and signed setup-return links remain supported.
  Old Form/Calibration links lead to Documents; old terms-publication links
  lead to Product publication.
- No new model, migration, setting or external dependency is required.

## Verification

The local synthetic browser journey exercises:

- custom PDF upload from the new-document form;
- signer pack, signer edit and lending fields;
- required field/signature placement through the server to-do list;
- successful filled-PDF rendering and document publication;
- selecting that document and publishing a draft Product;
- shared-document editing and explicit last-Main-LAF withdrawal;
- 320, 390, 430 and 1280px layouts, including light/dark Product screens.

Evidence is under `test-results/origination-authoring/` and
`test-results/origination-maintenance-live/`, including Playwright traces.
The baseline recording began at a synthetic **post-upload editor checkpoint**:
zero signers and one add-signature dead end. It was not a complete recording of
the former upload flow. The replacement run starts with the actual upload form
and finishes with document and product publication.

These are localhost synthetic fixtures with mocked Drive. No production data,
external writes or deployment are included. See [KNOWN_GAPS](../KNOWN_GAPS.md)
for the latest passed, failed and unverified validation scope.

## Code ownership

- `origination/services/document_editor.py`: document creation, signer edits,
  readiness, independent copies and publication.
- `origination/document_editor_admin.py`: Superuser forms and JSON adapters.
- `origination/origination_setup_admin.py`: Product task projection, autosaves
  and transactional Product publication.
- Existing catalogue, commercial-term, field and template services remain the
  authoritative contracts; no parallel setup database is introduced.
