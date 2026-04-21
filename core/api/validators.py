"""
API request validation and error handling utilities.

Provides consistent validation, error responses, and API safety checks.
"""
import logging
from typing import Dict, Any, List, Tuple
from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when request validation fails."""
    def __init__(self, message: str, code: str = 'VALIDATION_ERROR', status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


def validate_request_size(request) -> bool:
    """
    Validate that request body doesn't exceed size limit.
    
    Args:
        request: Django request object
        
    Returns:
        True if valid, raises ValidationError if too large
        
    Raises:
        ValidationError: If request exceeds size limit
    """
    size_limit = settings.API_REQUEST_SIZE_LIMIT
    body_size = len(request.body)
    
    if body_size > size_limit:
        raise ValidationError(
            f'Request payload too large: {body_size} bytes (limit: {size_limit})',
            code='PAYLOAD_TOO_LARGE',
            status_code=413
        )
    
    return True


def validate_message_fields(message_data: Dict[str, Any]) -> bool:
    """
    Validate that message contains all required fields.
    
    Args:
        message_data: Telegram message object
        
    Returns:
        True if valid, raises ValidationError if missing fields
        
    Raises:
        ValidationError: If required fields are missing
    """
    required_fields = settings.REQUIRED_MESSAGE_FIELDS
    missing_fields = [f for f in required_fields if f not in message_data]
    
    if missing_fields:
        raise ValidationError(
            f'Missing required message fields: {", ".join(missing_fields)}',
            code='MISSING_FIELDS',
            status_code=400
        )
    
    return True


def validate_webhook_payload(body: Dict[str, Any]) -> bool:
    """
    Validate webhook payload structure.
    
    Args:
        body: Parsed JSON body from webhook
        
    Returns:
        True if valid, raises ValidationError if invalid
        
    Raises:
        ValidationError: If payload is malformed
    """
    if not isinstance(body, dict):
        raise ValidationError(
            'Webhook payload must be a JSON object',
            code='INVALID_PAYLOAD',
            status_code=400
        )
    
    if 'update_id' not in body:
        raise ValidationError(
            'Webhook payload missing update_id',
            code='INVALID_PAYLOAD',
            status_code=400
        )
    
    return True


def validate_batch_messages(messages: List[Dict]) -> Tuple[bool, List[str]]:
    """
    Validate batch processing request.
    
    Args:
        messages: List of message objects
        
    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []
    
    if not isinstance(messages, list):
        return False, ['messages must be a list']
    
    if len(messages) == 0:
        return False, ['messages list cannot be empty']
    
    if len(messages) > settings.PARSING_BATCH_SIZE:
        return False, [f'Too many messages: max {settings.PARSING_BATCH_SIZE} per batch']
    
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            errors.append(f'Message {idx} is not a dict')
        elif 'content' not in msg or 'telegram_message_id' not in msg:
            errors.append(f'Message {idx} missing content or telegram_message_id')
    
    return len(errors) == 0, errors


def error_response(
    message: str,
    code: str = 'ERROR',
    status_code: int = 400,
    data: Dict = None,
    details: str = None
) -> JsonResponse:
    """
    Create a standardized error response.
    
    Args:
        message: User-facing error message
        code: Machine-readable error code
        status_code: HTTP status code
        data: Optional additional data
        details: Optional technical details (logged but not returned to client)
        
    Returns:
        JsonResponse with error format
    """
    response = {
        'status': 'error',
        'error': message,
        'code': code,
    }
    
    if data:
        response['data'] = data
    
    if details:
        logger.error(f"API Error [{code}]: {details}")
    
    return JsonResponse(response, status=status_code)


def success_response(
    data: Dict = None,
    message: str = 'Success',
    status_code: int = 200
) -> JsonResponse:
    """
    Create a standardized success response.
    
    Args:
        data: Response data
        message: Optional message
        status_code: HTTP status code
        
    Returns:
        JsonResponse with success format
    """
    response = {
        'status': 'success',
        'message': message,
    }
    
    if data:
        response['data'] = data
    
    return JsonResponse(response, status=status_code)


def partial_response(
    data: Dict = None,
    warnings: List[str] = None,
    message: str = 'Partial success',
    status_code: int = 200
) -> JsonResponse:
    """
    Create a standardized partial success response.
    
    Args:
        data: Response data
        warnings: List of warnings
        message: Optional message
        status_code: HTTP status code
        
    Returns:
        JsonResponse with partial success format
    """
    response = {
        'status': 'partial',
        'message': message,
    }
    
    if data:
        response['data'] = data
    
    if warnings:
        response['warnings'] = warnings
    
    return JsonResponse(response, status=status_code)
