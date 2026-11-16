"""Portal lifecycle around the existing published Origination document engine."""

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from types import SimpleNamespace

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from pypdf import PdfReader, PdfWriter

from core.models import JawabuFarmerMaster
from core.services.portal_permissions import portal_access_decision
from origination.models import OriginationDocumentTemplate
from origination.services.loan_origination import (
    validate_form_payload,
    normalize_form_payload,
    apply_choice_display_values,
)
from origination.services.origination_fields import template_form_contract
from origination.services.origination_value_contracts import project_document_schema
from document_signing.appearance import _validated_signature_capture, _slot_overlay

from .models import PortalLaf, PortalLafVersion, PortalLafSignature, PortalLafRequest

STAGES = {
    "bro_1": "visit",
    "bro_2": "visit",
    "officer": "visit",
    "loan_officer": "visit",
    "credit_analyst": "credit",
    "branch_manager": "final",
}
CAPABILITIES = {
    "visit": "portal.jbl_visit.write",
    "credit": "portal.credit.write",
    "final": "portal.final_review.write",
}
WORKFLOW_STAGES = {"visit": "jbl_visit", "credit": "credit", "final": "final_review"}
CASE_FIELDS = (
    "customer_name",
    "national_id",
    "primary_phone",
    "branch",
    "county",
    "sub_county",
    "village",
    "repayment_day",
    "repayment_tenor_months",
    "product_quote_snapshot",
    "product_terms_snapshot",
)


class LafError(ValueError):
    def __init__(self, message, *, errors=None, status=400):
        super().__init__(message)
        self.errors = errors or {}
        self.status = status


def enabled():
    return bool(getattr(settings, "PORTAL_LAF_FORM_ENABLED", False))


def sha(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def authorize(case, actor, access, stage=None):
    if not actor or not actor.is_active:
        raise PermissionDenied
    if access is None:
        from core.services.telegram_identity import user_access

        access = user_access(actor, "jawabu_portal")
    capability = CAPABILITIES[stage] if stage else "portal.jbl_media.view"
    allowed = portal_access_decision(actor, capability, access=access, resource=case).allowed
    if not allowed and stage in {"credit", "final"}:
        from core.services.jawabu_approvals import approval_authority

        allowed, _role, _delegation = approval_authority(
            user=actor, access=access, gate="credit" if stage == "credit" else "final_review", farmer=case
        )
    if not allowed:
        raise PermissionDenied
    if stage:
        from core.services.jawabu_pipeline import current_workflow_state

        state = current_workflow_state(case)
        deferred = (
            state == "deferred"
            and case.deferred_stage == {"visit": "jbl_visit", "credit": "credit", "final": "final"}[stage]
        )
        if state != WORKFLOW_STAGES[stage] and not deferred:
            raise LafError("This signature belongs to a different Portal stage.", status=409)


def template_contract(case):
    templates = (
        OriginationDocumentTemplate.objects.filter(
            document_type="lipa_mdogo_mdogo_laf",
            status="active",
            document_role="primary",
            published_configuration_revision__isnull=False,
            product_eligibilities__product_id=case.product_id,
        )
        .distinct()
        .select_related("published_configuration_revision", "product_definition")
    )
    if templates.count() != 1:
        raise LafError(
            "IT must publish one product-compatible Biogas LAF with its field and signing placements. Upload remains available."
        )
    template = templates.get()
    configuration = deepcopy(template.published_configuration_revision.configuration)
    schema, rules = template_form_contract(template)
    schema = project_document_schema(schema, configuration)
    placements = (configuration.get("signature_overlay_manifest") or {}).get("slots", {})
    slots = []
    for rule in rules:
        role = rule["role"]
        if role not in STAGES and role not in {"borrower", "customer", "guarantor_1", "guarantor_2"}:
            if rule.get("required", True):
                raise LafError("IT must map this LAF’s signer roles to the Portal stages. Upload remains available.")
            continue
        retained = []
        for raw in rule.get("slots", []):
            slot = {"key": raw} if isinstance(raw, str) else deepcopy(raw)
            key = slot.get("placement_key") or role + "." + slot["key"]
            placement = placements.get(key)
            if not placement:
                if slot.get("required", rule.get("required", True)):
                    raise LafError("IT must place every required LAF signature before form filling is available.")
                continue
            box = placement.get("allowed_area") or placement.get("box") or {}
            try:
                import math

                coords = [float(box[k]) for k in ("x", "y", "width", "height")]
                if not all(math.isfinite(v) for v in coords) or min(coords[:2]) < 0 or min(coords[2:]) <= 0:
                    raise ValueError
                if not 1 <= int(placement["page_number"]) <= template.page_count:
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise LafError("IT must correct the LAF signing placement.") from None
            retained.append({**slot, "placement": placement})
        if retained:
            slots.append(
                {
                    **rule,
                    "required": rule.get("required", True) or any(s.get("required") for s in retained),
                    "stage": STAGES.get(role, "visit"),
                    "external": role not in STAGES,
                    "slots": retained,
                }
            )
    if not slots or not any(s["role"] in {"bro_1", "officer", "loan_officer"} for s in slots):
        raise LafError("IT must configure the Biogas LAF’s BRO signature. Upload remains available.")
    return template, schema, configuration, slots


def case_snapshot(case):
    return {key: getattr(case, key, None) for key in CASE_FIELDS}


def prefill(case, schema):
    # Full source names stay intact; never guess how to split multi-person names.
    mapping = {
        "applicant_full_name": "customer_name",
        "customer_name": "customer_name",
        "applicant_id_number": "national_id",
        "applicant_national_id": "national_id",
        "applicant_phone": "primary_phone",
        "applicant_primary_phone": "primary_phone",
        "applicant_county": "county",
        "applicant_sub_county": "sub_county",
        "applicant_residence_address": "village",
        "repayment_day": "repayment_day",
        "loan_tenor_months": "repayment_tenor_months",
    }
    values = {
        f["key"]: getattr(case, mapping[f["key"]])
        for f in schema.get("fields", [])
        if f["key"] in mapping and getattr(case, mapping[f["key"]], None) not in (None, "")
    }
    quoted_amount = (case.product_quote_snapshot or {}).get("inputs", {}).get("amount")
    if quoted_amount not in (None, "") and any(
        f["key"] == "loan_amount" and f.get("type") == "money" for f in schema.get("fields", [])
    ):
        values["loan_amount"] = str(quoted_amount)
    return values


def context(version):
    case = version.laf.case
    values = deepcopy(version.values)
    values.update(
        {
            "reference_number": str(case.pk),
            "loan_officer_name": version.officer.get_full_name() or version.officer.get_username(),
            "branch_code": case.branch,
            "application_date": timezone.localdate(version.created_at).isoformat(),
            "_date_fields": [f["key"] for f in version.schema.get("fields", []) if f.get("type") == "date"]
            + ["application_date"],
        }
    )
    from origination.services.origination_value_contracts import (
        enabled as value_contract_enabled,
        build_packet_contract,
        resolve_values,
    )

    if value_contract_enabled(version.schema):
        contract = build_packet_contract(version.schema, [])
        resolved = resolve_values(
            contract, version.values, quote=case.product_quote_snapshot or {}, system=values, workflow={}
        )
        values.update(resolved["values"])
    return apply_choice_display_values(values, version.schema)


def validate(version, complete=False):
    resolved = context(version)
    result = validate_form_payload(
        version.schema,
        {f["key"]: resolved.get(f["key"], "") for f in version.schema.get("fields", [])},
        require_complete=complete,
    )
    if not result.valid:
        raise LafError("Check the highlighted LAF fields.", errors=result.errors)
    # Repayment dates and day-of-month are distinct meanings, never coerced.
    case = version.laf.case
    quoted_amount = (case.product_quote_snapshot or {}).get("inputs", {}).get("amount")
    entered_amount = version.values.get("loan_amount")
    if quoted_amount not in (None, "") and entered_amount not in (None, ""):
        from decimal import Decimal

        if Decimal(str(quoted_amount)) != Decimal(str(entered_amount)):
            raise LafError("The LAF amount differs from the saved case quote. Correct the case quote before signing.")
    for field, canonical in [("repayment_day", "repayment_day"), ("loan_tenor_months", "repayment_tenor_months")]:
        saved = getattr(case, canonical, None)
        if saved and version.values.get(field) not in (None, "", str(saved), saved):
            raise LafError("The LAF repayment terms differ from the case. Correct the case terms before signing.")
    for field, canonical in [
        ("applicant_id_number", "national_id"),
        ("applicant_national_id", "national_id"),
        ("applicant_phone", "primary_phone"),
        ("applicant_primary_phone", "primary_phone"),
    ]:
        if field in version.values and version.values[field] not in (None, ""):
            left, right = str(version.values[field]).strip(), str(getattr(case, canonical, "")).strip()
            if canonical == "primary_phone":
                from core.services.identifiers import normalize_kenyan_phone

                left, right = normalize_kenyan_phone(left), normalize_kenyan_phone(right)
            if right and left != right:
                raise LafError("The LAF identity differs from this case. Correct the case identity before signing.")
    if version.base_pdf and any(case_snapshot(case).get(k) != v for k, v in version.frozen_case.items()):
        raise LafError("Case details changed after this LAF was signed. Replace the LAF before proceeding.", status=409)


def render(version):
    if version.base_pdf:
        base = bytes(version.base_pdf)
        if version.signatures.exclude(base_digest=sha(base)).exists():
            raise LafError("The signed document failed its integrity check. Ask IT to review its retained evidence.")
    else:
        from core.services.partnership_laf_preview import render_template, PartnershipLafPreviewError
        from origination.services.origination_templates import load_template_source, OriginationTemplateError

        try:
            base = render_template(load_template_source(version.template), version.configuration, context(version))
        except OriginationTemplateError:
            raise LafError(
                "The Biogas LAF template could not be loaded. Your draft is saved. Retry preview or use the upload option.",
                status=503,
            ) from None
        except PartnershipLafPreviewError as exc:
            raise LafError(str(exc)) from exc
    reader, writer = PdfReader(BytesIO(base)), PdfWriter()
    signatures = {item.role: item for item in version.signatures.all()}
    for number, page in enumerate(reader.pages, 1):
        overlays = []
        for rule in version.slots:
            signature = signatures.get(rule["role"])
            if not signature:
                continue
            for slot in rule["slots"]:
                placement = slot["placement"]
                if int(placement["page_number"]) != number:
                    continue
                evidence = signature.evidence
                action = SimpleNamespace(
                    action_type=slot.get("type", "signature"),
                    stamp_asset_id=evidence.get("stamp_id"),
                    stamp_asset=SimpleNamespace(image_png=bytes.fromhex(evidence.get("stamp_png", ""))),
                    metadata={
                        "signature_capture": signature.capture,
                        "signed_date": timezone.localdate(signature.created_at).isoformat(),
                    },
                )
                overlays.append((placement, action))
        page.merge_page(
            PdfReader(
                BytesIO(
                    _slot_overlay(float(page.mediabox.width), float(page.mediabox.height), overlays, test_mode=False)
                )
            ).pages[0]
        )
        writer.add_page(page)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def ready(version, stage):
    required_stages = (
        {"visit"} | ({"credit"} if stage in {"credit", "final"} else set()) | ({"final"} if stage == "final" else set())
    )
    done = set(version.signatures.values_list("role", flat=True))
    return all(r["role"] in done for r in version.slots if r["stage"] in required_stages and r.get("required", True))


def active_version(case):
    laf = PortalLaf.objects.filter(case=case, active_source="form").select_related("current").first()
    return laf.current if laf else None


def require_stage(case, stage):
    version = active_version(case)
    if version:
        validate(version, complete=True)
        if not ready(version, stage):
            raise LafError("Complete the required LAF signatures for this stage before proceeding.")


def evidence_ready(case):
    try:
        version = active_version(case)
        if not version:
            return False
        validate(version, complete=True)
        return bool(version.pdf and ready(version, "visit"))
    except LafError:
        return False


def serialize(case, actor, access):
    laf = PortalLaf.objects.filter(case=case).select_related("current").first()
    available, message = enabled(), ""
    if available and not (laf and laf.current):
        try:
            template_contract(case)
        except LafError as exc:
            available, message = False, str(exc)
    version = laf.current if laf else None
    result = {
        "enabled": enabled() or bool(laf and laf.current),
        "available": available or bool(laf and laf.current),
        "message": message,
        "active_source": laf.active_source if laf else "upload",
        "version": None,
        "evidence_ready": evidence_ready(case),
        "case_revision": case.workflow_revision,
    }
    if not version:
        return result
    signatures = {s.role: s for s in version.signatures.select_related("actor")}
    slots = []
    for rule in version.slots:
        can_sign = False
        try:
            authorize(case, actor, access, rule["stage"])
            can_sign = rule["role"] not in signatures and (
                rule["stage"] != "visit" or rule["role"] == "bro_2" or version.officer_id == actor.pk
            )
        except (PermissionDenied, LafError):
            pass
        slots.append(
            {
                "role": rule["role"],
                "label": rule.get("label") or rule["role"],
                "stage": rule["stage"],
                "external": rule["external"],
                "required": rule.get("required", True),
                "signed": rule["role"] in signatures,
                "needs_stamp": any(s.get("type") == "stamp" for s in rule["slots"]),
                "can_sign": can_sign,
                "signed_at": signatures[rule["role"]].created_at.isoformat() if rule["role"] in signatures else "",
            }
        )
    progress = (
        "Completed"
        if ready(version, "final")
        else "Awaiting Head of Rural Signature"
        if ready(version, "credit")
        else "Awaiting Credit Signature"
        if ready(version, "visit")
        else "Awaiting Visit Signatures"
        if version.base_pdf
        else "Draft"
    )
    result["version"] = {
        "id": str(version.pk),
        "revision": version.revision,
        "schema": version.schema,
        "values": {
            **version.values,
            **{
                f["key"]: context(version).get(f["key"], "")
                for f in version.schema.get("fields", [])
                if f.get("editable") is False
            },
        },
        "frozen": bool(signatures),
        "digest": version.digest,
        "progress": progress,
        "slots": slots,
        "page_count": version.template.page_count,
        "can_edit": version.officer_id == actor.pk and not signatures,
        "archive_status": "Archived"
        if version.archive_file_id
        else "Waiting"
        if version.pdf and ready(version, "final")
        else "",
        "archive_error": version.archive_error,
    }
    if version.pdf and ready(version, "final") and not version.archive_file_id:
        from .publication import wake

        transaction.on_commit(wake)
    from origination.models import OriginationStampAsset

    result["stamps"] = list(
        OriginationStampAsset.objects.filter(active=True, environment="production")
        .filter(Q(branch__isnull=True) | Q(branch_id=case.branch_ref_id))
        .values("id", "name")
    )
    return result


def _freeze(version):
    if not version.base_pdf:
        validate(version, complete=True)
        if version.pdf and version.frozen_case != case_snapshot(version.laf.case):
            raise LafError("Case details changed after preview. Preview the LAF again before signing.", status=409)
        version.base_pdf = bytes(version.pdf) if version.pdf else render(version)
        version.frozen_case = {k: v for k, v in case_snapshot(version.laf.case).items() if v not in (None, "")}
        version.pdf = version.base_pdf
        version.digest = sha(bytes(version.pdf))
        version.save()


def record_signature(version, rule, capture, actor, evidence):
    if version.signatures.filter(role=rule["role"]).exists():
        raise LafError("This signer has already signed this LAF.", status=409)
    if actor and version.signatures.filter(actor=actor).exists():
        raise LafError("Independent LAF signers must be different people.")
    _freeze(version)
    validate(version, complete=True)
    PortalLafSignature.objects.create(
        version=version,
        role=rule["role"],
        actor=actor,
        capture=capture,
        base_digest=sha(bytes(version.base_pdf)),
        evidence=evidence,
    )
    version.pdf = render(version)
    version.digest = sha(bytes(version.pdf))
    version.revision += 1
    version.archive_file_id = ""
    version.archive_error = ""
    version.save()


@transaction.atomic
def mutate(case_id, actor, access, payload, request_id):
    if not enabled() and not PortalLaf.objects.filter(case_id=case_id, current__isnull=False).exists():
        raise LafError("Form filling is not enabled. Upload the LAF instead.", status=409)
    case = JawabuFarmerMaster.objects.select_for_update().get(pk=case_id)
    authorize(case, actor, access)
    action = payload.get("action")
    stage = {"start": "visit", "save": "visit", "replace": "visit", "source": "visit"}.get(action)
    if stage:
        authorize(case, actor, access, stage)
    laf, _ = PortalLaf.objects.get_or_create(case=case)
    fingerprint = sha([str(actor.pk), payload])
    if not request_id or len(request_id) > 128:
        raise LafError("A valid request key is required.")
    replay = laf.requests.filter(key=request_id).first()
    if replay:
        if replay.digest != fingerprint:
            raise LafError("This request key was used for different LAF data.", status=409)
        return {**serialize(case, actor, access), **replay.result}
    version = laf.current
    if action not in {"start", "save", "replace", "preview", "sign", "source", "archive"}:
        raise LafError("Choose a valid LAF action.")
    if action not in {"start"}:
        if not version or payload.get("version_id") != str(version.pk) or payload.get("revision") != version.revision:
            raise LafError("This LAF changed. Reload it before continuing.", status=409)
    receipt = {}
    if version and not version.signatures.exists() and action in {"preview", "sign"}:
        template, _schema, configuration, _slots = template_contract(case)
        if template.pk != version.template_id or sha(configuration) != sha(version.configuration):
            raise LafError(
                "A newer Biogas LAF is available. Save the draft to adopt it, then review the updated form.", status=409
            )
    if action in {"start", "replace"}:
        if action == "replace" and payload.get("confirm") is not True:
            raise LafError("Confirm replacement. Previous documents and signatures will remain in history.")
        if action == "replace" or not version:
            template, schema, configuration, slots = template_contract(case)
            values = prefill(case, schema)
            if version:
                keys = {f["key"]: f.get("type") for f in version.schema.get("fields", [])}
                values.update(
                    {
                        f["key"]: version.values[f["key"]]
                        for f in schema.get("fields", [])
                        if f["key"] in version.values and keys.get(f["key"]) == f.get("type")
                    }
                )
                from core.services.jawabu_approvals import invalidate_material_approvals

                invalidate_material_approvals(
                    farmer=case, changed_fields=["jbl_media"], actor=actor, reason="Biogas LAF replaced."
                )
            version = PortalLafVersion.objects.create(
                laf=laf,
                template=template,
                schema=schema,
                configuration=configuration,
                slots=slots,
                values=values,
                officer=actor,
            )
            laf.current = version
            laf.active_source = "upload"
            laf.save()
    elif action == "save":
        if version.signatures.exists() or version.officer_id != actor.pk:
            raise LafError("Signed answers are locked. Replace the LAF to make a correction.", status=409)
        values = payload.get("values")
        if not isinstance(values, dict):
            raise LafError("LAF answers must be an object.")
        fields = {f["key"]: f for f in version.schema.get("fields", [])}
        if any(k not in fields or fields[k].get("editable") is False for k in values):
            raise LafError("Only the displayed editable LAF fields may be changed.")
        normalized = normalize_form_payload(version.schema, {**version.values, **values})
        if normalized != version.values or version.base_pdf and version.frozen_case != case_snapshot(case):
            version.values = normalized
            version.base_pdf, version.pdf, version.digest, version.frozen_case = b"", b"", "", {}
            validate(version)
            version.revision += 1
            version.save()
        else:
            validate(version)
        template, schema, configuration, slots = template_contract(case)
        if template.pk != version.template_id or sha(configuration) != sha(version.configuration):
            old_fields = {
                f["key"]: (f.get("type"), f.get("value_contract"), f.get("source_type"))
                for f in version.schema.get("fields", [])
            }
            compatible = {
                f["key"]
                for f in schema.get("fields", [])
                if old_fields.get(f["key"]) == (f.get("type"), f.get("value_contract"), f.get("source_type"))
            }
            successor = PortalLafVersion.objects.create(
                laf=laf,
                template=template,
                schema=schema,
                configuration=configuration,
                slots=slots,
                officer=actor,
                values={k: v for k, v in version.values.items() if k in compatible},
            )
            laf.current = version = successor
            laf.save()
            receipt["form_updated"] = True
    elif action == "preview":
        validate(version)
        if not version.pdf or not version.base_pdf and version.frozen_case != case_snapshot(case):
            version.pdf = render(version)
        if not version.base_pdf:
            version.frozen_case = case_snapshot(case)
        version.digest = sha(bytes(version.pdf))
        version.save()
        receipt["preview_digest"] = version.digest
    elif action == "sign":
        rule = next((r for r in version.slots if r["role"] == payload.get("role")), None)
        if not rule:
            raise LafError("Choose a configured signer.")
        authorize(case, actor, access, rule["stage"])
        if rule["stage"] == "visit" and rule["role"] != "bro_2" and version.officer_id != actor.pk:
            raise PermissionDenied
        if rule["stage"] != "visit" and not ready(version, "visit" if rule["stage"] == "credit" else "credit"):
            raise LafError("The preceding LAF signatures must be completed first.")
        if payload.get("consent") is not True or payload.get("digest") != version.digest or not version.digest:
            raise LafError("Preview this exact document and confirm your signature before signing.")
        if not laf.requests.filter(result__preview_digest=version.digest, result__actor_id=str(actor.pk)).exists():
            raise LafError("Preview the current LAF before signing.")
        pages = set(
            laf.requests.filter(result__page_digest=version.digest, result__actor_id=str(actor.pk)).values_list(
                "result__page", flat=True
            )
        )
        if pages != set(range(1, version.template.page_count + 1)):
            raise LafError("Open every page of this LAF before signing.")
        capture = _validated_signature_capture(payload.get("capture"))
        evidence = {"consent": True, "preview_digest": version.digest, "request_id": request_id}
        if rule["external"]:
            if payload.get("signing_mode") != "in_person" or payload.get("witnessed") is not True:
                raise LafError(
                    "The officer must confirm that the client or guarantor personally signed in their presence."
                )
            evidence.update(signing_mode="in_person", witnessed_by=str(actor.pk))
        if any(s.get("type") == "stamp" for s in rule["slots"]):
            from origination.models import OriginationStampAsset

            stamp = (
                OriginationStampAsset.objects.filter(pk=payload.get("stamp_id"), active=True, environment="production")
                .filter(Q(branch__isnull=True) | Q(branch_id=case.branch_ref_id))
                .first()
            )
            if not stamp or sha(bytes(stamp.image_png)) != stamp.content_sha256:
                raise LafError("Choose an active production stamp for this branch.")
            evidence.update(stamp_id=str(stamp.pk), stamp_png=bytes(stamp.image_png).hex())
        record_signature(version, rule, capture, None if rule["external"] else actor, evidence)
    elif action == "source":
        source = payload.get("source")
        if source not in {"form", "upload"}:
            raise LafError("Choose upload or form.")
        if source == "form":
            validate(version, complete=True)
            if not ready(version, "visit"):
                raise LafError("Complete the visit-stage LAF signatures first.")
        if laf.active_source != source:
            if payload.get("confirm") is not True:
                raise LafError("Confirm which LAF this case should use.")
            from core.services.jawabu_approvals import invalidate_material_approvals

            invalidate_material_approvals(
                farmer=case, changed_fields=["jbl_media"], actor=actor, reason="Active LAF source changed."
            )
            laf.active_source = source
            laf.save()
    elif action == "archive":
        if not ready(version, "final") or not version.pdf:
            raise LafError("Complete signing before archiving.")
        receipt["archive_requested"] = True
    PortalLafRequest.objects.create(
        laf=laf,
        key=request_id,
        digest=fingerprint,
        result={
            **receipt,
            "actor_id": str(actor.pk),
            "action": action,
        },
    )
    if version and ready(version, "final") and version.pdf and not version.archive_file_id:
        from .publication import queue_archive

        queue_archive(version.pk, retry=action == "archive")
    return {**serialize(case, actor, access), **receipt}


def archive(version_id):
    version = PortalLafVersion.objects.select_related("laf__case").get(pk=version_id)
    if version.archive_file_id or not ready(version, "final"):
        return
    try:
        from core.services.order_approval import GoogleDriveMediaStorage
        from django.utils.text import slugify

        case = version.laf.case
        name = f"{slugify(case.customer_name)}-{slugify(case.national_id)}-biogas-laf-{version.pk}.pdf"
        file_id, _url = GoogleDriveMediaStorage().upload(
            BytesIO(bytes(version.pdf)),
            name,
            "application/pdf",
            id_number=f"case-{case.pk}",
            received_at=timezone.now(),
            workflow_key="jawabu_portal",
            record_type="biogas-laf",
            record_key=str(version.pk),
            publication_key=f"portal-laf:{version.pk}:{version.digest}",
            recover_uncertain=True,
            attempt_budget=1,
        )
        if not file_id:
            raise ValueError("Missing archive receipt")
        PortalLafVersion.objects.filter(pk=version.pk, digest=version.digest).update(
            archive_file_id=file_id, archive_error=""
        )
    except Exception:
        PortalLafVersion.objects.filter(pk=version.pk).update(
            archive_error="Drive archive unavailable. Your signed LAF is saved. Retry archive."
        )
        raise RuntimeError("Portal LAF archive unavailable") from None
