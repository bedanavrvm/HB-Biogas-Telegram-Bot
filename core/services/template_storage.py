"""Durable Google Drive backing for admin-uploaded workbook templates."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

from django.utils import timezone

from core.services.order_approval import GoogleDriveMediaStorage, drive_file_url


WORKBOOK_MIME_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
REQUISITION_TEMPLATE_FILENAME = 'JBL_Requisition_Form_Reconciled.xlsx'


class TemplateStorageError(RuntimeError):
    pass


def canonical_template_filename(category: str, filename: str) -> str:
    """Return the stable Drive name for a known template family.

    Django may append a random suffix to a repeated FileField upload. That
    suffix must not become a new Drive template. Only the known requisition
    family is canonicalised here; other categories retain the administrator's
    supplied filename until their naming convention is explicitly defined.
    """
    name = Path(str(filename or '')).name
    if str(category or '').strip().casefold() == 'requisition':
        return REQUISITION_TEMPLATE_FILENAME
    return name or 'template.xlsx'


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

    def _same_name_templates(
        self, folder_id: str, filename: str, *, mime_type: str = WORKBOOK_MIME_TYPE,
    ) -> list[dict[str, Any]]:
        """Return live workbook files with this name, newest first.

        Drive permits duplicate names in a folder. Template files are a
        replacement resource, not an append-only media stream, so callers use
        this list to update one canonical file and retire any older copies.
        """
        escaped_folder = folder_id.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            f"mimeType = '{mime_type}' and "
            f"'{escaped_folder}' in parents and trashed = false"
        )
        files = self.service.files()
        results: list[dict[str, Any]] = []
        page_token = None
        while True:
            params = {
                'q': query,
                'spaces': 'drive',
                'fields': 'nextPageToken, files(id, name, modifiedTime, webViewLink)',
                'pageSize': 1000,
                'orderBy': 'modifiedTime desc',
                'includeItemsFromAllDrives': True,
                'supportsAllDrives': True,
            }
            if page_token:
                params['pageToken'] = page_token
            response = files.list(**params).execute()
            results.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            if not page_token:
                break
        base_stem = Path(filename).stem.casefold()
        matching = []
        for item in results:
            candidate_stem = Path(str(item.get('name') or '')).stem.casefold()
            if candidate_stem == base_stem or candidate_stem.startswith(base_stem + '_'):
                matching.append(item)
        return sorted(matching, key=lambda item: str(item.get('modifiedTime') or ''), reverse=True)

    def upload_template(
        self, data: bytes, *, filename: str, category: str,
        mime_type: str = WORKBOOK_MIME_TYPE,
    ) -> tuple[str, str]:
        from googleapiclient.http import MediaIoBaseUpload

        filename = canonical_template_filename(category, filename)
        folder_id = self._template_folder(category)
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
        files = self.service.files()
        existing = self._same_name_templates(folder_id, filename, mime_type=mime_type)
        if existing:
            # Keep the newest Drive ID stable so links and audit references do
            # not change when an administrator replaces a template.
            current = existing[0]
            uploaded_at = timezone.now().isoformat()
            updated = (
                files.update(
                    fileId=current['id'],
                    body={
                        'name': filename,
                        'description': f'JBL {category} template; latest upload {uploaded_at}',
                    },
                    media_body=media,
                    fields='id, webViewLink',
                    supportsAllDrives=True,
                )
                .execute()
            )
            # Clean up duplicates already created by the previous create-only
            # implementation. Trashing them keeps the folder unambiguous while
            # preserving Drive recovery/audit history.
            for duplicate in existing[1:]:
                files.update(
                    fileId=duplicate['id'],
                    body={'trashed': True},
                    fields='id',
                    supportsAllDrives=True,
                ).execute()
            file_id = updated['id']
            return file_id, updated.get('webViewLink') or drive_file_url(file_id)

        created = (
            files.create(
                body={
                    'name': filename,
                    'parents': [folder_id],
                    'description': f'JBL {category} template; latest upload {timezone.now().isoformat()}',
                },
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


def upload_template_record_to_drive(
    template: Any, *, category: str, mime_type: str = WORKBOOK_MIME_TYPE,
) -> tuple[bool, str]:
    """Upload the admin FileField contents to Drive and persist metadata on the model."""
    try:
        data, filename = _read_template_file(template)
        checksum = hashlib.sha256(data).hexdigest()
        file_id, url = GoogleDriveTemplateStorage().upload_template(
            data,
            filename=filename,
            category=category,
            mime_type=mime_type,
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
    template.content_type = mime_type
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
