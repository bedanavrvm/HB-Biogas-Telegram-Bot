"""Document-owned completion for newly captured catalogue applications only."""


def without_signing(application):
    """Never infer a new completion policy for historical applications.

    Required signers on any selected supporting document still require signing.
    Product signer mirrors cannot add obligations absent from the chosen PDFs.
    """
    if (application.schema_snapshot or {}).get('document_completion_version') != 1:
        return False
    documents = [document for document in application.packet_documents.all() if document.selected]
    if not any(document.document_role == 'primary' for document in documents):
        return False
    for document in documents:
        for rule in document.signer_rules_snapshot or []:
            # Malformed snapshots fail closed, rather than removing an obligation.
            if not isinstance(rule, dict) or not rule.get('role') or rule.get('required', True):
                return False
            for slot in rule.get('slots') or []:
                if isinstance(slot, str):
                    continue  # Optional legacy slot inherits its optional role.
                if not isinstance(slot, dict) or slot.get('required', False):
                    return False
    return True
