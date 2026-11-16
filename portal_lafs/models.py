"""Portal-owned LAF evidence; retained with its case, never rewritten after signing."""

import uuid

from django.conf import settings
from django.db import models


class PortalLaf(models.Model):
    case = models.OneToOneField(
        "core.JawabuFarmerMaster",
        on_delete=models.PROTECT,
        related_name="digital_laf",
        db_comment="Owning Portal case; no cross-workflow authority.",
    )
    active_source = models.CharField(
        max_length=12,
        default="upload",
        db_comment="Chosen evidence source: upload or form. Draft creation does not select form.",
    )
    current = models.ForeignKey(
        "PortalLafVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_for",
        db_comment="Current version; previous versions remain retained.",
    )

    class Meta:
        db_table = "portal_lafs_case_record"
        db_table_comment = (
            "Canonical Portal LAF selection. Retained for case/evidence lifecycle; explicit reviewed deletion only."
        )


class PortalLafVersion(models.Model):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, db_comment="Immutable version identifier."
    )
    laf = models.ForeignKey(PortalLaf, on_delete=models.PROTECT, related_name="versions", db_comment="Owning case LAF.")
    template = models.ForeignKey(
        "origination.OriginationDocumentTemplate",
        on_delete=models.PROTECT,
        related_name="portal_laf_versions",
        db_comment="Published source document, protected for reproducibility.",
    )
    schema = models.JSONField(default=dict, db_comment="Captured placed-field contract.")
    configuration = models.JSONField(default=dict, db_comment="Captured PDF geometry; immutable once signed.")
    slots = models.JSONField(default=list, db_comment="Captured configured signer slots and Portal stages.")
    values = models.JSONField(default=dict, db_comment="Draft answers, frozen at first signature.")
    revision = models.PositiveIntegerField(default=1, db_comment="Optimistic concurrency token.")
    base_pdf = models.BinaryField(default=bytes, db_comment="Hash-bound unsigned bytes frozen at first signature.")
    pdf = models.BinaryField(default=bytes, db_comment="Durable current rendered PDF, independent of Drive.")
    digest = models.CharField(max_length=64, blank=True, db_comment="SHA256 of current rendered PDF.")
    frozen_case = models.JSONField(
        default=dict, db_comment="Canonical case fields at first signature; detects later conflicts."
    )
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="portal_laf_versions",
        db_comment="Assigned BRO who owns draft completion.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="Version creation timestamp.")
    archive_file_id = models.CharField(
        max_length=255, blank=True, db_comment="Published Drive copy; not workflow authority."
    )
    archive_error = models.CharField(
        max_length=240, blank=True, db_comment="Safe archive failure; retry never replays signing."
    )

    class Meta:
        db_table = "portal_lafs_document_version"
        db_table_comment = "Canonical versioned Biogas LAF. Signed bytes and snapshots retained with case; no automatic expiry/deletion."


class PortalLafSignature(models.Model):
    version = models.ForeignKey(
        PortalLafVersion,
        on_delete=models.PROTECT,
        related_name="signatures",
        db_comment="Exact frozen LAF version signed.",
    )
    role = models.CharField(max_length=80, db_comment="Configured signer role.")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.PROTECT,
        related_name="portal_laf_signatures",
        db_comment="Authenticated staff signer; null for a client or guarantor witnessed in person.",
    )
    capture = models.JSONField(db_comment="Validated immutable signature appearance.")
    base_digest = models.CharField(max_length=64, db_comment="SHA256 of signed base document.")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="Signature and consent timestamp.")
    evidence = models.JSONField(
        default=dict, db_comment="Exact-document consent and authenticated officer witness for in-person signing."
    )

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            from django.core.exceptions import ValidationError

            raise ValidationError("LAF signature evidence is append-only.")
        return super().save(*args, **kwargs)

    class Meta:
        db_table = "portal_lafs_signature_evidence"
        db_table_comment = (
            "Append-only signature evidence; retained with signed LAF and protected from automatic deletion."
        )
        constraints = [models.UniqueConstraint(fields=["version", "role"], name="portal_laf_one_signature_per_role")]


class PortalLafRequest(models.Model):
    laf = models.ForeignKey(
        PortalLaf, on_delete=models.PROTECT, related_name="requests", db_comment="Case mutex and audit owner."
    )
    key = models.CharField(max_length=128, db_comment="Caller idempotency key, unique within case LAF.")
    digest = models.CharField(max_length=64, db_comment="Request fingerprint including actor and operation.")
    result = models.JSONField(default=dict, db_comment="Non-sensitive replay receipt.")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="Audit timestamp; same retention as LAF.")

    class Meta:
        db_table = "portal_lafs_request_event"
        db_table_comment = (
            "Canonical idempotency/audit receipts for LAF mutations; retained with case, no customer values."
        )
        constraints = [models.UniqueConstraint(fields=["laf", "key"], name="portal_laf_unique_request")]
