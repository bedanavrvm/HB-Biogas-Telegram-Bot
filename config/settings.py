"""
Django settings for biogas_bot project.
Production-ready configuration for Render deployment.
"""
import os
from pathlib import Path
import dj_database_url
from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('DJANGO_SECRET_KEY', default='django-inchange-me-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = [
    host.strip()
    for host in config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in config('CSRF_TRUSTED_ORIGINS', default='').split(',')
    if origin.strip()
]

# Application definition
INSTALLED_APPS = [
    'unfold',
    'unfold.contrib.filters',
    'unfold.contrib.forms',
    'unfold.contrib.inlines',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'health_check',
    'health_check.db',
    'health_check.storage',
    'health_check.contrib.migrations',
    # Local apps
    'core',
]

UNFOLD = {
    'SITE_TITLE': 'JBL Workflow Admin',
    'SITE_HEADER': 'JBL/Jawabu HomeBiogas Operations',
    'SITE_URL': '/',
    'DASHBOARD_CALLBACK': 'core.admin_dashboard.dashboard_callback',
    'STYLES': [
        '/static/admin/css/compact_unfold.css',
    ],
    'COLORS': {
        'primary': {
            '50': '240 253 250',
            '100': '204 251 241',
            '200': '153 246 228',
            '300': '94 234 212',
            '400': '45 212 191',
            '500': '20 184 166',
            '600': '13 148 136',
            '700': '15 118 110',
            '800': '17 94 89',
            '900': '19 78 74',
            '950': '4 47 46',
        },
    },
}

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'core' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
DATABASES = {
    'default': dj_database_url.config(
        default=config('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db.sqlite3"}'),
        conn_max_age=config('DATABASE_CONN_MAX_AGE', default=600, cast=int),
    )
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Render terminates TLS before proxying requests to Gunicorn.  These defaults
# are safe for production while retaining a frictionless local DEBUG setup.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=not DEBUG, cast=bool)
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=not DEBUG, cast=bool)
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000 if not DEBUG else 0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
    'SECURE_HSTS_INCLUDE_SUBDOMAINS', default=not DEBUG, cast=bool
)
SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=not DEBUG, cast=bool)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'biogas_bot.log',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'core': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Ensure logs directory exists
if not (BASE_DIR / 'logs').exists():
    (BASE_DIR / 'logs').mkdir(parents=True)

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = config('TELEGRAM_BOT_TOKEN', default='')
TELEGRAM_WEBHOOK_SECRET = config('TELEGRAM_WEBHOOK_SECRET', default='')
TELEGRAM_BOT_USERNAME = config('TELEGRAM_BOT_USERNAME', default='').lstrip('@')
TELEGRAM_BOT_DISPLAY_NAME = config('TELEGRAM_BOT_DISPLAY_NAME', default='Telegram Bot')
APP_DISPLAY_NAME = config('APP_DISPLAY_NAME', default='Telegram Workflow Bot')
APP_BASE_URL = config('APP_BASE_URL', default='').rstrip('/')
APP_RELEASE = config('APP_RELEASE', default='').strip()

# Optional production error reporting.  No data is sent when SENTRY_DSN is
# blank; configure this in Render rather than committing a DSN.
SENTRY_DSN = config('SENTRY_DSN', default='').strip()
SENTRY_ENVIRONMENT = config('SENTRY_ENVIRONMENT', default='production' if not DEBUG else 'development')
SENTRY_TRACES_SAMPLE_RATE = config('SENTRY_TRACES_SAMPLE_RATE', default=0.0, cast=float)

# Spin Credit Analysts (Telegram usernames/user IDs)
SPIN_ANALYSTS = [
    username.strip().lower() 
    for username in config('SPIN_ANALYSTS', default='').split(',') 
    if username.strip()
]


# API protection for manual endpoints
API_AUTH_TOKEN = config('API_AUTH_TOKEN', default='')
ESIGNATURES_BASE_URL = config('ESIGNATURES_BASE_URL', default='')
ESIGNATURES_API_KEY = config('ESIGNATURES_API_KEY', default='')
ESIGNATURES_WEBHOOK_SECRET = config('ESIGNATURES_WEBHOOK_SECRET', default='')

# Google Sheets Configuration
GOOGLE_SHEET_ID = config('GOOGLE_SHEET_ID', default='')
GOOGLE_SERVICE_ACCOUNT_FILE = config('GOOGLE_SERVICE_ACCOUNT_FILE', default='credentials.json')
GOOGLE_SHEET_TAB_NAME = config('GOOGLE_SHEET_TAB_NAME', default='Complaints Register')

# Media storage for workflows that receive Telegram photos/documents.
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

MEDIA_STORAGE_PROVIDER = config('MEDIA_STORAGE_PROVIDER', default='google_drive')
MEDIA_MAX_FILE_SIZE_MB = config('MEDIA_MAX_FILE_SIZE_MB', default=20, cast=int)
ORDER_APPROVAL_MAX_FILES_PER_SLOT = config(
    'ORDER_APPROVAL_MAX_FILES_PER_SLOT',
    default=10,
    cast=int,
)
ORDER_APPROVAL_MAX_TOTAL_UPLOAD_MB = config(
    'ORDER_APPROVAL_MAX_TOTAL_UPLOAD_MB',
    default=30,
    cast=int,
)
FILE_UPLOAD_MAX_MEMORY_SIZE = config(
    'FILE_UPLOAD_MAX_MEMORY_SIZE',
    default=0,
    cast=int,
)
ORDER_APPROVAL_IMAGE_PREVIEWS_ENABLED = config(
    'ORDER_APPROVAL_IMAGE_PREVIEWS_ENABLED',
    default=False,
    cast=bool,
)
ORDER_APPROVAL_IMAGE_PREVIEW_LIMIT = config(
    'ORDER_APPROVAL_IMAGE_PREVIEW_LIMIT',
    default=3,
    cast=int,
)
GOOGLE_DRIVE_MEDIA_FOLDER_ID = config('GOOGLE_DRIVE_MEDIA_FOLDER_ID', default='')
ORDER_APPROVAL_WEBAPP_ENABLED = config('ORDER_APPROVAL_WEBAPP_ENABLED', default=True, cast=bool)
ORDER_APPROVAL_MINI_APP_SHORT_NAME = config('ORDER_APPROVAL_MINI_APP_SHORT_NAME', default='').strip().strip('/')
FARMUP_MINI_APP_SHORT_NAME = config('FARMUP_MINI_APP_SHORT_NAME', default='').strip().strip('/')
FCAUP_MINI_APP_SHORT_NAME = config('FCAUP_MINI_APP_SHORT_NAME', default='').strip().strip('/')
PORTAL_MINI_APP_SHORT_NAME = config('PORTAL_MINI_APP_SHORT_NAME', default='').strip().strip('/')
SPIN_MINI_APP_SHORT_NAME = config('SPIN_MINI_APP_SHORT_NAME', default='').strip().strip('/')
TAT_TRACKER_MINI_APP_SHORT_NAME = config('TAT_TRACKER_MINI_APP_SHORT_NAME', default='').strip().strip('/')
COMPLAINT_CASES_MINI_APP_SHORT_NAME = config('COMPLAINT_CASES_MINI_APP_SHORT_NAME', default='').strip().strip('/')
COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH = config('COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH', default=True, cast=bool)
COMPLAINT_CASES_WEBAPP_AUTH_MAX_AGE_SECONDS = config('COMPLAINT_CASES_WEBAPP_AUTH_MAX_AGE_SECONDS', default=86400, cast=int)
COMPLAINT_CASE_MAX_FILES_PER_UPDATE = config('COMPLAINT_CASE_MAX_FILES_PER_UPDATE', default=10, cast=int)
COMPLAINT_CASE_MAX_TOTAL_UPLOAD_MB = config('COMPLAINT_CASE_MAX_TOTAL_UPLOAD_MB', default=30, cast=int)
COMPLAINT_CASE_MAX_FILES_PER_UPDATE = config('COMPLAINT_CASE_MAX_FILES_PER_UPDATE', default=10, cast=int)
COMPLAINT_CASE_MAX_TOTAL_UPLOAD_MB = config('COMPLAINT_CASE_MAX_TOTAL_UPLOAD_MB', default=30, cast=int)
TAT_TRACKER_WEBAPP_REQUIRE_TELEGRAM_AUTH = config('TAT_TRACKER_WEBAPP_REQUIRE_TELEGRAM_AUTH', default=True, cast=bool)
TAT_TRACKER_WEBAPP_AUTH_MAX_AGE_SECONDS = config('TAT_TRACKER_WEBAPP_AUTH_MAX_AGE_SECONDS', default=86400, cast=int)
TAT_TRACKER_SYNC_SECONDARY_SHEETS = config('TAT_TRACKER_SYNC_SECONDARY_SHEETS', default=False, cast=bool)
TAT_TRACKER_SIGNATURES_ENABLED = config('TAT_TRACKER_SIGNATURES_ENABLED', default=False, cast=bool)
WORKFLOW_BRANCH_CHOICES = config('WORKFLOW_BRANCH_CHOICES', default='Biogas Unit,Embu,Nakuru,West Nairobi')
TAT_TRACKER_BRANCH_CHOICES = config('TAT_TRACKER_BRANCH_CHOICES', default='')
PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH = config(
    'PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH',
    default=True,
    cast=bool,
)
PORTAL_WEBAPP_AUTH_MAX_AGE_SECONDS = config(
    'PORTAL_WEBAPP_AUTH_MAX_AGE_SECONDS',
    default=86400,
    cast=int,
)
ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH = config(
    'ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH',
    default=True,
    cast=bool,
)
ORDER_APPROVAL_WEBAPP_AUTH_MAX_AGE_SECONDS = config(
    'ORDER_APPROVAL_WEBAPP_AUTH_MAX_AGE_SECONDS',
    default=86400,
    cast=int,
)
SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH = config(
    'SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH',
    default=True,
    cast=bool,
)
SPIN_WEBAPP_AUTH_MAX_AGE_SECONDS = config(
    'SPIN_WEBAPP_AUTH_MAX_AGE_SECONDS',
    default=86400,
    cast=int,
)
SPIN_MAX_FILES_PER_SLOT = config(
    'SPIN_MAX_FILES_PER_SLOT',
    default=2,
    cast=int,
)
SPIN_MAX_TOTAL_UPLOAD_MB = config(
    'SPIN_MAX_TOTAL_UPLOAD_MB',
    default=20,
    cast=int,
)
ORDER_APPROVAL_BRANCH_CHOICES = config(
    'ORDER_APPROVAL_BRANCH_CHOICES',
    default=WORKFLOW_BRANCH_CHOICES,
)

# Multi-Group/Multi-Tenant Configuration
# Maps Telegram group chat_id to Google Sheet configurations.
# Format:
#   GROUP_MAPPING = {
#       "-100123456789": {
#           "sheet_id": "1a2b3c...",
#           "sheet_name": "Complaints Register",
#       },
#   }
# If GROUP_MAPPING is empty, falls back to legacy single-group mode (GOOGLE_SHEET_ID).
import json
GROUP_MAPPING = {}
_group_mapping_json = config('GROUP_MAPPING_JSON', default='')
if _group_mapping_json:
    try:
        _raw_mapping = json.loads(_group_mapping_json)
        # Clean up any invisible whitespace from group ID keys (zero-width spaces, etc)
        GROUP_MAPPING = {
            str(group_id).strip(): config_dict 
            for group_id, config_dict in _raw_mapping.items()
        }
    except json.JSONDecodeError as e:
        import logging as _logging
        _logging.warning(f"Failed to parse GROUP_MAPPING_JSON: {e}")
        GROUP_MAPPING = {}

SHEET_SCHEMA = {}
_sheet_schema_json = config('SHEET_SCHEMA_JSON', default='')
if _sheet_schema_json:
    try:
        SHEET_SCHEMA = json.loads(_sheet_schema_json)
    except json.JSONDecodeError as e:
        import logging as _logging
        _logging.warning(f"Failed to parse SHEET_SCHEMA_JSON: {e}")
        SHEET_SCHEMA = {}

WORKFLOW_CONFIG = {}
_workflow_config_json = config('WORKFLOW_CONFIG_JSON', default='')
if _workflow_config_json:
    try:
        WORKFLOW_CONFIG = json.loads(_workflow_config_json)
    except json.JSONDecodeError as e:
        import logging as _logging
        _logging.warning(f"Failed to parse WORKFLOW_CONFIG_JSON: {e}")
        WORKFLOW_CONFIG = {}

PARSER_RULES = {}
_parser_rules_json = config('PARSER_RULES_JSON', default='')
if _parser_rules_json:
    try:
        PARSER_RULES = json.loads(_parser_rules_json)
    except json.JSONDecodeError as e:
        import logging as _logging
        _logging.warning(f"Failed to parse PARSER_RULES_JSON: {e}")
        PARSER_RULES = {}

# Default group ID for single-group deployments
DEFAULT_GROUP_ID = config('DEFAULT_GROUP_ID', default='default')

# Processing Configuration
DEDUPLICATION_WINDOW_MINUTES = config('DEDUPLICATION_WINDOW_MINUTES', default=5, cast=int)
BATCH_PROCESSING_DELAY = config('BATCH_PROCESSING_DELAY', default=1, cast=int)
WHATSAPP_BATCH_MAX_MESSAGES = config('WHATSAPP_BATCH_MAX_MESSAGES', default=0, cast=int)
WHATSAPP_BATCH_ASYNC_THRESHOLD = config('WHATSAPP_BATCH_ASYNC_THRESHOLD', default=100, cast=int)
WHATSAPP_BATCH_MAX_FILE_SIZE_MB = config('WHATSAPP_BATCH_MAX_FILE_SIZE_MB', default=5, cast=int)
FCA_BATCH_MAX_FILE_SIZE_MB = config('FCA_BATCH_MAX_FILE_SIZE_MB', default=10, cast=int)
INVOICE_UPLOAD_MAX_FILE_SIZE_MB = config('INVOICE_UPLOAD_MAX_FILE_SIZE_MB', default=8, cast=int)

# API Configuration & Security
API_REQUEST_SIZE_LIMIT = 1_000_000  # 1MB - Prevent DoS from large payloads
API_REQUEST_TIMEOUT = 10  # seconds - Timeout for external API calls
MAX_SYNC_ATTEMPTS = 5  # Max retries before giving up on Google Sheets sync
MIN_CONFIDENCE_THRESHOLD = 0.5  # Minimum confidence score to consider parse acceptable
PARSING_BATCH_SIZE = 50  # Process up to 50 messages per batch request

# Required Telegram Message Fields (must be present in webhook)
REQUIRED_MESSAGE_FIELDS = ['message_id', 'chat', 'date']

# Rate Limiting (if enabled with django-ratelimit)
RATELIMIT_ENABLE = config('RATELIMIT_ENABLE', default=False, cast=bool)
RATELIMIT_PER_IP = '100/h'  # 100 requests per hour per IP
