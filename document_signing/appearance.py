"""Shared signature validation and PDF ink; callers retain workflow authorization."""

from __future__ import annotations
import hashlib
from datetime import date
from io import BytesIO
from typing import Any
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from origination.models import OriginationSigningAction
from origination.services.loan_origination import OriginationError


def _validated_signature_capture(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OriginationError("Draw or type your signature before confirming this slot.")
    method = str(value.get("method") or "").strip().casefold()
    if method == "typed":
        if value.get("appearance_version") == 2:
            from origination.services.signature_appearance import freeze_capture

            return freeze_capture(value)
        name = " ".join(str(value.get("name") or "").split())
        if len(name) < 2 or len(name) > 120:
            raise OriginationError("Enter the signer name using 2 to 120 characters.")
        return {"method": "typed", "name": name}
    if method != "drawn":
        raise OriginationError("Choose Draw signature or Type signature.")
    raw_strokes = value.get("strokes")
    if not isinstance(raw_strokes, list) or not raw_strokes or len(raw_strokes) > 40:
        raise OriginationError("Draw your signature before confirming this slot.")
    strokes = []
    total_points = 0
    for raw_stroke in raw_strokes:
        if not isinstance(raw_stroke, list) or len(raw_stroke) < 2 or len(raw_stroke) > 500:
            raise OriginationError("The drawn TEST signature contains an invalid stroke.")
        stroke = []
        for raw_point in raw_stroke:
            if not isinstance(raw_point, (list, tuple)) or len(raw_point) != 2:
                raise OriginationError("The drawn TEST signature contains an invalid point.")
            try:
                x, y = float(raw_point[0]), float(raw_point[1])
            except (TypeError, ValueError) as exc:
                raise OriginationError("The drawn TEST signature contains an invalid point.") from exc
            if not 0 <= x <= 1 or not 0 <= y <= 1:
                raise OriginationError("The drawn TEST signature must stay inside the signature pad.")
            stroke.append([round(x, 4), round(y, 4)])
        strokes.append(stroke)
        total_points += len(stroke)
    if total_points > 2000:
        raise OriginationError("The drawn TEST signature is too detailed. Clear it and try again.")
    return {"method": "drawn", "strokes": strokes}


def _slot_overlay(
    width: float,
    height: float,
    items: list[tuple[dict, OriginationSigningAction]],
    *,
    test_mode: bool,
) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    if test_mode:
        pdf.saveState()
        pdf.setFillColorRGB(0.78, 0.08, 0.08, alpha=0.18)
        pdf.setFont("Helvetica-Bold", 34)
        pdf.translate(width / 2, height / 2)
        pdf.rotate(35)
        pdf.drawCentredString(0, 0, "TEST ONLY - NOT LEGALLY SIGNED")
        pdf.restoreState()
    for spec, action in items:
        box = spec.get("allowed_area") or spec.get("box") or {}
        scale = 72 / 25.4 if spec.get("units", "pt") == "mm" else 1
        try:
            x, y = float(box["x"]) * scale, float(box["y"]) * scale
            box_width, box_height = float(box["width"]) * scale, float(box["height"]) * scale
        except (KeyError, TypeError, ValueError):
            continue
        padding = spec.get("padding") if isinstance(spec.get("padding"), dict) else {}
        try:
            padding_x = max(0, float(padding.get("x", 0)) * scale)
            padding_y = max(0, float(padding.get("y", 0)) * scale)
            rotation = float(spec.get("rotation", 0))
        except (TypeError, ValueError):
            padding_x = padding_y = rotation = 0
        content_x = -box_width / 2 + padding_x
        content_y = -box_height / 2 + padding_y
        content_width = max(1, box_width - padding_x * 2)
        content_height = max(1, box_height - padding_y * 2)
        pdf.saveState()
        pdf.translate(x + box_width / 2, y + box_height / 2)
        pdf.rotate(rotation)
        if action.action_type == OriginationSigningAction.TYPE_STAMP and action.stamp_asset_id:
            stamp_image = ImageReader(BytesIO(bytes(action.stamp_asset.image_png)))
            stamp_x, stamp_y = content_x, content_y
            stamp_width, stamp_height = content_width, content_height
            if str(spec.get("stamp_fit") or "contain") != "stretch":
                image_width, image_height = stamp_image.getSize()
                fit_scale = min(content_width / max(1, image_width), content_height / max(1, image_height))
                stamp_width, stamp_height = image_width * fit_scale, image_height * fit_scale
                align = str(spec.get("align") or "center")
                vertical = str(spec.get("vertical_align") or "center")
                stamp_x = (
                    content_x
                    if align == "left"
                    else content_x + content_width - stamp_width
                    if align == "right"
                    else content_x + (content_width - stamp_width) / 2
                )
                stamp_y = (
                    content_y
                    if vertical == "bottom"
                    else content_y + content_height - stamp_height
                    if vertical == "top"
                    else content_y + (content_height - stamp_height) / 2
                )
            pdf.drawImage(
                stamp_image,
                stamp_x,
                stamp_y,
                width=stamp_width,
                height=stamp_height,
                preserveAspectRatio=False,
                mask="auto",
            )
        elif action.action_type == OriginationSigningAction.TYPE_DATE_SIGNED:
            signed_date = str((action.metadata or {}).get("signed_date") or "")
            try:
                signed_date = date.fromisoformat(signed_date).strftime("%d/%m/%Y")
            except ValueError:
                pass
            pdf.setFillColorRGB(0.09, 0.14, 0.12)
            try:
                font_size = max(6, min(14, float(spec.get("font_size") or 9)))
            except (TypeError, ValueError):
                font_size = 9
            pdf.setFont("Helvetica", font_size)
            text_y = content_y + max(0, (content_height - font_size) / 2)
            align = str(spec.get("align") or "center")
            if align == "left":
                pdf.drawString(content_x, text_y, signed_date)
            elif align == "right":
                pdf.drawRightString(content_x + content_width, text_y, signed_date)
            else:
                pdf.drawCentredString(content_x + content_width / 2, text_y, signed_date)
        else:
            if test_mode:
                pdf.setStrokeColorRGB(0.48, 0.23, 0.93)
                pdf.rect(-box_width / 2, -box_height / 2, box_width, box_height, stroke=1, fill=0)
            ink = {
                "black": (0.09, 0.14, 0.12),
                "blue": (0.04, 0.24, 0.58),
                "purple": (0.34, 0.12, 0.65),
            }.get(str(spec.get("ink_color") or "black"), (0.09, 0.14, 0.12))
            pdf.setStrokeColorRGB(*ink)
            pdf.setFillColorRGB(*ink)
            capture = (action.metadata or {}).get("signature_capture") or {}
            if capture.get("method") == "drawn":
                pdf.setLineCap(1)
                pdf.setLineJoin(1)
                try:
                    stroke_width = float(spec.get("stroke_width") or 2)
                except (TypeError, ValueError):
                    stroke_width = 2
                pdf.setLineWidth(max(0.5, min(8, stroke_width)))
                for stroke in capture.get("strokes") or []:
                    if len(stroke) < 2:
                        continue
                    path = pdf.beginPath()
                    path.moveTo(
                        content_x + stroke[0][0] * content_width, content_y + (1 - stroke[0][1]) * content_height
                    )
                    for point in stroke[1:]:
                        path.lineTo(content_x + point[0] * content_width, content_y + (1 - point[1]) * content_height)
                    pdf.drawPath(path, stroke=1, fill=0)
            elif capture.get("appearance_version") == 2:
                import base64

                image_bytes = base64.b64decode(capture["image_png"], validate=True)
                if hashlib.sha256(image_bytes).hexdigest() != capture["image_sha256"]:
                    raise OriginationError("The saved signature image could not be verified.")
                signature_image = ImageReader(BytesIO(image_bytes))
                image_width, image_height = signature_image.getSize()
                fit = min(content_width / image_width, content_height / image_height)
                image_width, image_height = image_width * fit, image_height * fit
                pdf.drawImage(
                    signature_image,
                    content_x + (content_width - image_width) / 2,
                    content_y + (content_height - image_height) / 2,
                    width=image_width,
                    height=image_height,
                    mask="auto",
                )
            else:
                name = str(capture.get("name") or ("TEST SIGNATURE" if test_mode else ""))
                font_name = str(spec.get("typed_font") or "Helvetica-BoldOblique")
                try:
                    font_size = float(spec.get("font_size") or 15)
                    text_width = max(1, pdf.stringWidth(name[:120], font_name, font_size))
                except (TypeError, ValueError, KeyError):
                    font_name, font_size = "Helvetica-BoldOblique", 15
                    text_width = max(1, pdf.stringWidth(name[:120], font_name, font_size))
                name = name[:120]
                horizontal_scale = min(1, max(0.1, content_width / text_width))
                vertical = str(spec.get("vertical_align") or "center")
                text_y = (
                    content_y
                    if vertical == "bottom"
                    else content_y + max(0, content_height - font_size)
                    if vertical == "top"
                    else content_y + max(0, (content_height - font_size) / 2)
                )
                align = str(spec.get("align") or "center")
                pdf.saveState()
                anchor_x = (
                    content_x
                    if align == "left"
                    else content_x + content_width
                    if align == "right"
                    else content_x + content_width / 2
                )
                pdf.translate(anchor_x, text_y)
                pdf.scale(horizontal_scale, 1)
                pdf.setFont(font_name, font_size)
                if align == "left":
                    pdf.drawString(0, 0, name)
                elif align == "right":
                    pdf.drawRightString(0, 0, name)
                else:
                    pdf.drawCentredString(0, 0, name)
                pdf.restoreState()
        pdf.restoreState()
        if test_mode and action.action_type != OriginationSigningAction.TYPE_STAMP:
            pdf.setFillColorRGB(0.78, 0.08, 0.08)
            pdf.setFont("Helvetica-Bold", min(6, max(4, box_height * 0.16)))
            pdf.drawRightString(x + box_width - 2, y + 2, "TEST")
    # ReportLab does not emit a page when a verified package page has no
    # signature/stamp items. Multi-page packets legitimately contain such
    # pages, and callers always merge the first overlay page. Finalize the
    # current page explicitly so the overlay contract remains exactly one PDF
    # page even when it is intentionally blank.
    pdf.showPage()
    pdf.save()
    return output.getvalue()
