"""
Group Configuration Service

Manages multi-tenant routing: groups → sheets/configs.
Config-driven, no code changes needed to add groups.

DESIGN:
- Groups are identified by Telegram chat_id
- Each group routes to a specific Google Sheet
- Per-group rules (optional future: permissions, parsers, etc.)
- Single source of truth: GROUP_MAPPING in settings.py
"""
import logging
from typing import Optional, Dict, Any
from django.conf import settings

logger = logging.getLogger(__name__)


class GroupConfig:
    """Represents configuration for a single group."""
    
    def __init__(
        self,
        group_id: str,
        sheet_id: str,
        sheet_name: str = 'Complaints Register',
        enabled: bool = True,
        metadata: Dict[str, Any] = None
    ):
        """
        Args:
            group_id: Telegram chat_id (string, e.g., "-100123456789")
            sheet_id: Google Sheet ID
            sheet_name: Worksheet name within sheet
            enabled: Whether this group is active
            metadata: Additional config (future: permissions, parsers, etc.)
        """
        self.group_id = str(group_id)
        self.sheet_id = sheet_id
        self.sheet_name = sheet_name
        self.enabled = enabled
        self.metadata = metadata or {}
        
        if not self.sheet_id:
            logger.warning(f"Group {group_id} has no sheet_id configured")
    
    def __repr__(self):
        return f"GroupConfig(id={self.group_id}, sheet={self.sheet_id}, enabled={self.enabled})"


class GroupRegistry:
    """
    Central registry for all groups.
    Reads from settings.GROUP_MAPPING at startup.
    
    FORMAT in .env or settings.py:
    
    GROUP_MAPPING = {
        "-100123456789": {
            "sheet_id": "1a2b3c...",
            "sheet_name": "Complaints Register",
        },
        "-100987654321": {
            "sheet_id": "xyz789...",
            "sheet_name": "Support Tickets",
        },
    }
    """
    
    _instance = None
    _groups: Dict[str, GroupConfig] = {}
    
    @classmethod
    def get_instance(cls):
        """Singleton access."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        """Initialize from settings.GROUP_MAPPING."""
        self._load_groups()
    
    def _load_groups(self):
        """Load group mappings from settings."""
        group_mapping = getattr(settings, 'GROUP_MAPPING', {})
        
        if not group_mapping:
            # Fallback: single group from legacy config
            if settings.GOOGLE_SHEET_ID:
                group_id = getattr(settings, 'DEFAULT_GROUP_ID', 'default')
                self._groups['default'] = GroupConfig(
                    group_id=group_id,
                    sheet_id=settings.GOOGLE_SHEET_ID,
                    sheet_name=settings.GOOGLE_SHEET_TAB_NAME,
                )
                logger.info(f"Loaded legacy single-group config: {group_id}")
        else:
            # Load all configured groups
            for group_id, config_dict in group_mapping.items():
                group_config = GroupConfig(
                    group_id=group_id,
                    sheet_id=config_dict.get('sheet_id'),
                    sheet_name=config_dict.get('sheet_name', 'Complaints Register'),
                    enabled=config_dict.get('enabled', True),
                    metadata=config_dict.get('metadata', {}),
                )
                self._groups[str(group_id)] = group_config
                logger.debug(f"Loaded group {repr(str(group_id))} (sheet: {config_dict.get('sheet_id')})")
            
            logger.info(f"Loaded {len(self._groups)} group(s) from GROUP_MAPPING")
            logger.debug(f"Configured group IDs: {list(self._groups.keys())}")
    
    def get_group(self, group_id: str) -> Optional[GroupConfig]:
        """
        Get config for a specific group.
        
        Args:
            group_id: Telegram chat_id
            
        Returns:
            GroupConfig if found and enabled, None otherwise
        """
        group_id = str(group_id)
        config = self._groups.get(group_id)
        
        if not config:
            logger.warning(f"Unknown group_id: {group_id}")
            logger.debug(f"Available groups: {list(self._groups.keys())}")
            logger.debug(f"Received group_id repr: {repr(group_id)}")
            return None
        
        if not config.enabled:
            logger.warning(f"Group {group_id} is disabled")
            return None
        
        if not config.sheet_id:
            logger.error(f"Group {group_id} has no sheet configured")
            return None
        
        return config
    
    def list_groups(self) -> Dict[str, GroupConfig]:
        """Get all registered groups."""
        return dict(self._groups)
    
    def reload(self):
        """Reload groups from settings (for dynamic config)."""
        self._groups.clear()
        self._load_groups()
        logger.info("Group registry reloaded")


def get_sheet_id_for_group(group_id: str) -> Optional[str]:
    """
    Utility: Get sheet ID for a group.
    
    Usage:
        sheet_id = get_sheet_id_for_group(message['chat']['id'])
        if not sheet_id:
            logger.error(f"Unknown group: {message['chat']['id']}")
            return error_response(...)
    """
    registry = GroupRegistry.get_instance()
    config = registry.get_group(group_id)
    return config.sheet_id if config else None


def get_sheet_name_for_group(group_id: str) -> Optional[str]:
    """Utility: Get worksheet name for a group."""
    registry = GroupRegistry.get_instance()
    config = registry.get_group(group_id)
    return config.sheet_name if config else None
