"""
Group Configuration Service

Manages multi-tenant routing: Telegram groups → Google Sheets.
Config-driven — no code changes needed to add a new group.

KEY FIXES (v2):
- Single-group (legacy) mode now uses a wildcard default config so
  ANY Telegram chat_id is accepted, not just the literal string 'default'.
- get_group() falls back to _default_config when the specific chat_id
  is not in GROUP_MAPPING, instead of hard-failing.
- reload() now clears _default_config so it is rebuilt from settings.
- __init__ initialises _default_config = None before _load_groups().

TELEGRAM CHAT-ID FORMAT:
  Supergroups arrive as *negative* integers, e.g. -1001234567890.
  After str() conversion that becomes "-1001234567890".
  Always use the full string including the leading minus in GROUP_MAPPING_JSON.

  Example .env entry:
    GROUP_MAPPING_JSON='{"-1001234567890": {"sheet_id": "abc123", "sheet_name": "Complaints Register"}}'
"""
import logging
from typing import Optional, Dict, Any
from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError
from core.services.sheet_schema import SheetSchema

logger = logging.getLogger(__name__)


class GroupConfig:
    """Represents configuration for a single group."""

    def __init__(
        self,
        group_id: str,
        sheet_id: str,
        sheet_name: str = 'Complaints Register',
        enabled: bool = True,
        metadata: Dict[str, Any] = None,
        sheet_schema: Dict[str, Any] = None,
        workflow: Dict[str, Any] = None,
        parser_rules: Dict[str, Any] = None,
    ):
        self.group_id = str(group_id)
        self.sheet_id = sheet_id
        self.sheet_name = sheet_name
        self.enabled = enabled
        self.metadata = metadata or {}
        self.sheet_schema_config = (
            sheet_schema
            or self.metadata.get('sheet_schema')
            or {}
        )
        self.sheet_schema = SheetSchema.from_config(self.sheet_schema_config)
        self.workflow = workflow or self.metadata.get('workflow') or {}
        self.parser_rules = parser_rules or self.metadata.get('parser_rules') or {}

        if not self.sheet_id:
            logger.warning(f"Group {group_id} has no sheet_id configured")

    def __repr__(self):
        return (
            f"GroupConfig(id={self.group_id}, "
            f"sheet={self.sheet_id}, "
            f"enabled={self.enabled})"
        )


class GroupRegistry:
    """
    Central registry for all groups.
    Reads from settings.GROUP_MAPPING at startup.

    Single-group (legacy) mode
    --------------------------
    Leave GROUP_MAPPING_JSON empty in .env.
    The registry creates a wildcard default config pointing at
    settings.GOOGLE_SHEET_ID.  Every incoming chat_id that is not
    explicitly listed will use this default.

    Multi-group mode
    ----------------
    Set GROUP_MAPPING_JSON in .env with the full Telegram chat_id
    (including the leading minus sign for supergroups):

      GROUP_MAPPING_JSON='{
        "-1001234567890": {"sheet_id": "abc...", "sheet_name": "Complaints"},
        "-1009876543210": {"sheet_id": "xyz...", "sheet_name": "Support"}
      }'
    """

    _instance = None
    _groups: Dict[str, GroupConfig] = {}

    @classmethod
    def get_instance(cls) -> "GroupRegistry":
        """Singleton access."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        # Initialise _default_config BEFORE _load_groups so the
        # attribute always exists, even if loading raises.
        self._default_config: Optional[GroupConfig] = None
        self._groups: Dict[str, GroupConfig] = {}
        self._load_groups()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_groups(self):
        """Load group mappings from admin configuration and settings."""
        group_mapping = getattr(settings, 'GROUP_MAPPING', {})
        admin_configs = self._load_admin_group_configs()

        if not group_mapping and not admin_configs:
            # ── Legacy / single-group mode ──────────────────────────
            # Store as a wildcard default so any chat_id is accepted.
            if getattr(settings, 'GOOGLE_SHEET_ID', ''):
                self._default_config = GroupConfig(
                    group_id='*',
                    sheet_id=settings.GOOGLE_SHEET_ID,
                    sheet_name=getattr(
                        settings, 'GOOGLE_SHEET_TAB_NAME', 'Complaints Register'
                    ),
                    sheet_schema=getattr(settings, 'SHEET_SCHEMA', {}),
                    workflow=getattr(settings, 'WORKFLOW_CONFIG', {}),
                    parser_rules=getattr(settings, 'PARSER_RULES', {}),
                )
                logger.info(
                    "Single-group mode active: all Telegram groups route to "
                    f"sheet {settings.GOOGLE_SHEET_ID}"
                )
            else:
                logger.warning(
                    "No GROUP_MAPPING and no GOOGLE_SHEET_ID configured. "
                    "Google Sheets sync will be disabled."
                )
        else:
            # ── Multi-group mode ────────────────────────────────────
            for raw_group_id, config_dict in group_mapping.items():
                group_id = str(raw_group_id).strip()
                group_config = GroupConfig(
                    group_id=group_id,
                    sheet_id=config_dict.get('sheet_id', ''),
                    sheet_name=config_dict.get(
                        'sheet_name', 'Complaints Register'
                    ),
                    enabled=config_dict.get('enabled', True),
                    metadata=config_dict.get('metadata', {}),
                    sheet_schema=config_dict.get('sheet_schema', {}),
                    workflow=config_dict.get('workflow', {}),
                    parser_rules=config_dict.get('parser_rules', {}),
                )
                self._groups[group_id] = group_config
                logger.debug(
                    f"Loaded group {repr(group_id)} -> "
                    f"sheet {config_dict.get('sheet_id')}"
                )

            for config_dict in admin_configs:
                group_id = str(config_dict.get('group_id', '')).strip()
                if not group_id:
                    continue
                group_config = GroupConfig(**config_dict)
                self._groups[group_id] = group_config
                logger.debug(
                    f"Loaded admin group {repr(group_id)} -> "
                    f"sheet {config_dict.get('sheet_id')}"
                )

            logger.info(
                f"Multi-group mode: {len(self._groups)} group(s) loaded. "
                f"IDs: {list(self._groups.keys())}"
            )

    def _load_admin_group_configs(self) -> list[dict]:
        """Return admin-managed configs when the database table is available."""
        try:
            from core.models import GroupSheetConfiguration

            return [
                config.as_group_config_kwargs()
                for config in GroupSheetConfiguration.objects.all()
            ]
        except (OperationalError, ProgrammingError) as exc:
            logger.debug(
                f"Admin group configuration table unavailable; using settings: {exc}"
            )
            return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_group(self, group_id: str) -> Optional[GroupConfig]:
        """
        Return the GroupConfig for *group_id*, or None if not routable.

        Lookup order:
        1. Explicit match in GROUP_MAPPING.
        2. Wildcard default (single-group / legacy mode).
        3. None — caller must handle the error.
        """
        group_id = str(group_id).strip()
        config = self._groups.get(group_id)

        if not config:
            # Try the wildcard default before giving up
            if self._default_config:
                logger.info(
                    f"Group {group_id} not in registry; "
                    "falling back to single-group default config"
                )
                return self._default_config

            logger.warning(
                f"Unknown group_id: {repr(group_id)}. "
                f"Available: {list(self._groups.keys())}"
            )
            return None

        if not config.enabled:
            logger.warning(f"Group {group_id} is disabled")
            return None

        if not config.sheet_id:
            logger.error(f"Group {group_id} has no sheet_id configured")
            return None

        return config

    def list_groups(self) -> Dict[str, GroupConfig]:
        """Return a copy of all explicitly registered groups."""
        return dict(self._groups)

    def reload(self):
        """Reload groups from settings (useful after config changes)."""
        self._groups.clear()
        self._default_config = None   # ← must reset before re-loading
        self._load_groups()
        logger.info("Group registry reloaded")


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def get_sheet_id_for_group(group_id: str) -> Optional[str]:
    """
    Return the Google Sheet ID for *group_id*, or None if not configured.

    Usage:
        sheet_id = get_sheet_id_for_group(message['chat']['id'])
        if not sheet_id:
            return error_response('Unknown group', ...)
    """
    registry = GroupRegistry.get_instance()
    config = registry.get_group(str(group_id))
    return config.sheet_id if config else None


def get_sheet_name_for_group(group_id: str) -> Optional[str]:
    """Return the worksheet name for *group_id*, or None if not configured."""
    registry = GroupRegistry.get_instance()
    config = registry.get_group(str(group_id))
    return config.sheet_name if config else None
