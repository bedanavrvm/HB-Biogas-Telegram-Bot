"""Retention and ownership metadata for the database catalogue."""

MODEL_METADATA = {
    f"portal_lafs.{name}": {
        "domain": "portal_lafs",
        "purpose": purpose,
        "classification": classification,
        "source_of_truth": True,
        "lifecycle": "active",
        "retention": "Retain with the Portal case and signed evidence. No automatic deletion; reviewed evidence export before schema rollback.",
    }
    for name, purpose, classification in (
        ("PortalLaf", "Portal case active LAF source and current-version ownership.", "authoritative_record"),
        (
            "PortalLafVersion",
            "Captured Biogas document contract, draft answers and immutable signed bytes.",
            "source_evidence",
        ),
        ("PortalLafSignature", "Append-only signature, consent and exact-document evidence.", "immutable_event"),
        ("PortalLafRequest", "Idempotent mutation receipts and document access audit.", "immutable_event"),
    )
}
