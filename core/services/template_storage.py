"""Durable Google Drive backing for admin-uploaded workbook templates."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

from django.utils import timezone

from core.services.order_approval import GoogleDriveMediaStorage, drive_file_url


WORKBOOK_MIME_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class TemplateStorageError(RuntimeError):
    pass


class GoogleDriveTemplateStorage:
    """Store templates under the shared Drive media root without customer folders."""

    def __init__(self):
        self._media_storage = GoogleDriveMediaStorage()

    @property
    def service(self):
        return self._media_storage.service

    def _template_folder(self, category: str) -> str:
        root = self._media_storage.ensure_child_folder(self._media_storage.parent_folder_id, 'Templates')
        return self._media_storage.ensure_child_folder(root, category)

    def upload_template(self, data: bytes, *, filename: str, category: str) -> tuple[str, str]:
        from googleapiclient.http import MediaIoBaseUpload

        folder_id = self._template_folder(category)
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=WORKBOOK_MIME_TYPE, resumable=False)
        created = (
            self.service.files()
            .create(
                body={'name': filename, 'parents': [folder_id]},
                media_body=media,
                fields='id, webViewLink',
                supportsAllDrives=True,
            )
            .execute()
        )
        file_id = created['id']
        return file_id, created.get('webViewLink') or drive_file_url(file_id)

    def download_template(self, file_id: str) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload

        request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        stream = io.BytesIO()
        downloader = MediaIoBaseDownload(stream, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return stream.getvalue()


def _read_template_file(template: Any) -> tuple[bytes, str]:
    if not getattr(template, 'file', None):
        raise TemplateStorageError('Template has no uploaded file.')
    try:
        path = template.file.path
    except (NotImplementedError, ValueError) as exc:
        raise TemplateStorageError('Template file is not available on local storage.') from exc
    if not path or not Path(path).exists():
        raise TemplateStorageError('Template file is not available on local storage.')
    data = Path(path).read_bytes()
    filename = Path(path).name
    return data, filename


def upload_template_record_to_drive(template: Any, *, category: str) -> tuple[bool, str]:
    """Upload the admin FileField contents to Drive and persist metadata on the model."""
    try:
        data, filename = _read_template_file(template)
        checksum = hashlib.sha256(data).hexdigest()
        file_id, url = GoogleDriveTemplateStorage().upload_template(
            data,
            filename=filename,
            category=category,
        )
    except Exception as exc:
        template.drive_file_id = ''
        template.drive_url = ''
        template.drive_uploaded_at = None
        template.drive_upload_error = str(exc)
        template.save(update_fields=[
            'drive_file_id', 'drive_url', 'drive_uploaded_at',
            'drive_upload_error', 'updated_at',
        ])
        return False, str(exc)

    template.original_filename = filename
    template.content_type = WORKBOOK_MIME_TYPE
    template.size = len(data)
    template.checksum = checksum
    template.drive_file_id = file_id
    template.drive_url = url
    template.drive_uploaded_at = timezone.now()
    template.drive_upload_error = ''
    template.save(update_fields=[
        'original_filename', 'content_type', 'size', 'checksum',
        'drive_file_id', 'drive_url', 'drive_uploaded_at',
        'drive_upload_error', 'updated_at',
    ])
    return True, ''


def workbook_source_from_template(template: Any, *, fallback_path: str | Path | None = None) -> str | io.BytesIO:
    """Return a local path when present, otherwise a BytesIO downloaded from Drive."""
    if template and getattr(template, 'file', None):
        try:
            path = template.file.path
        except (NotImplementedError, ValueError):
            path = ''
        if path and Path(path).exists():
            return path

    if template and getattr(template, 'drive_file_id', ''):
        data = GoogleDriveTemplateStorage().download_template(template.drive_file_id)
        return io.BytesIO(data)

    if fallback_path and Path(fallback_path).exists():
        return str(fallback_path)

    raise TemplateStorageError('No local or Drive-backed template file is available.')
