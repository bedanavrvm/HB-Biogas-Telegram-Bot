"""
WhatsApp Message PARSER ENGINE

Regex-based extraction of structured fields from messy WhatsApp messages.

Supported patterns:
1. "Sold {qty} {item} {price} each to {sender}"
2. "{sender} paid {price} for {qty} {item}"
3. "{sender} bought {qty} {item} @ {price}"
4. "📍 {gps_url} ... {transaction_text}"
5. Mixed formats with flexible ordering

Extracted fields:
- timestamp
- sender
- item
- quantity
- price
- gps_link
- image_flag
"""
import re
import logging
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from typing import Optional
from enum import Enum
from django.utils import timezone

logger = logging.getLogger(__name__)


class MessageIntent(Enum):
    """Enum for different message intents."""
    SALE = "sale"  # "Sold X item Y each to Z"
    PURCHASE = "purchase"  # "X bought Y item @ Z"
    PAYMENT = "payment"  # "X paid Y for Z item"
    COMPLAINT = "complaint"  # Customer complaint/case report messages
    LOCATION = "location"  # Messages with GPS/location info
    STATUS = "status"  # Non-transaction status messages
    UNKNOWN = "unknown"  # Could not determine intent


# ─────────────────────────────────────────────
# REGEX PATTERNS
# ─────────────────────────────────────────────

# URL/GPS pattern
GPS_URL_PATTERN = re.compile(
    r'(https?://[^\s]+|maps\.app\.goo\.gl/[^\s]+|goo\.gl/maps/[^\s]+)',
    re.IGNORECASE
)

# WhatsApp timestamp pattern: [14/03/2026, 10:30:15] or 14/03/2026 10:30
TIMESTAMP_PATTERN = re.compile(
    r'\[?(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})[\s,]+(\d{1,2}:\d{2}(?::\d{2})?)\]?'
)

# Sender patterns
SENDER_PATTERN_SOLD_TO = re.compile(
    r'\bto\s+([A-Z][a-zA-Z\s]+?)(?:\s+(?:at|for|@)|\s*$|$)',
    re.IGNORECASE
)

SENDER_PATTERN_PAID = re.compile(
    r'^([A-Z][a-zA-Z\s\.]+?)\s+(?:paid|sent|gave|transferred)',
    re.IGNORECASE
)

SENDER_PATTERN_BOUGHT = re.compile(
    r'^([A-Z][a-zA-Z\s\.]+?)\s+(?:bought|purchased|ordered|took)',
    re.IGNORECASE
)

# Transaction patterns - improved for better matching
SOLD_PATTERN = re.compile(
    r'(?:sold|delivered|gave)\s+(\d+(?:\.\d+)?)\s+'
    r'([a-zA-Z][a-zA-Z\s]*?)(?=\s+(?:at|for|@|each|per|\d)|$)\s*'
    r'(?:ksh|kes|sh|shillings?\s+)?(\d+(?:,\d{3})*(?:\.\d+)?)?(?:\s*(?:each|per|a\s+piece|per\s+unit))?',
    re.IGNORECASE
)

PAID_PATTERN = re.compile(
    r'(?:paid|sent|gave|transferred)\s+(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:for|in\s+exchange\s+for)?\s*(\d+(?:\.\d+)?)?(?:\s+(?:for|in\s+exchange\s+for)\s+)?([a-zA-Z\s]+)?',
    re.IGNORECASE
)

BOUGHT_PATTERN = re.compile(
    r'(?:bought|purchased|ordered|took)\s+(\d+(?:\.\d+)?)\s+'
    r'([a-zA-Z][a-zA-Z\s]*?)(?=\s+(?:at|for|@|\d)|$)\s*'
    r'(?:\s*(?:at|for|@)\s*)?(\d+(?:,\d{3})*(?:\.\d+)?)?',
    re.IGNORECASE
)

# Price patterns
PRICE_EACH_PATTERN = re.compile(
    r'(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:each|per|a\s+piece|per\s+unit)',
    re.IGNORECASE
)

TOTAL_PRICE_PATTERN = re.compile(
    r'(?:ksh|kes|sh|shillings?|\btotal\b.*?)(\d+(?:,\d{3})*(?:\.\d+)?)',
    re.IGNORECASE
)

# Quantity patterns
QUANTITY_PATTERN = re.compile(
    r'(\d+(?:\.\d+)?)\s*(?:bags?|pieces?|units?|liters?|litres?|kilos?|kgs?|boxes?|bundles?)',
    re.IGNORECASE
)

# Item extraction - common items
ITEM_NAMES = [
    'bread', 'milk', 'maize', 'bags', 'maize flour', 'wheat', 'rice',
    'sugar', 'salt', 'cement', 'fertilizer', 'seeds', 'eggs', 'chicken',
    'gas', 'biogas', 'manure', 'compost', 'firewood', 'charcoal',
    'tomatoes', 'onions', 'potatoes', 'cabbages', 'spinach',
]

COMPLAINT_PREFIX_PATTERN = re.compile(
    r'\bCUSTOMER\s*COMPLAIN(?:T|E)?\b',
    re.IGNORECASE
)

COMPLAINT_CATEGORY_PATTERN = re.compile(
    r'\bCATEGORY\s*[:\-]?\s*([^\n\r]+)',
    re.IGNORECASE
)

NAME_PATTERN = re.compile(
    r'\*?NAME\*?\s*[:\-]\s*([^\n\r]+)',
    re.IGNORECASE
)

PHONE_PATTERN = re.compile(
    r'\*?(?:TEL|P/no|P\.no|PHONE|P\/no|P/no)\*?\s*[:\-]?\s*([+\d\s\/\-]+)',
    re.IGNORECASE
)

ID_PATTERN = re.compile(
    r'\*?(?:ID|I\.D)\*?\s*[:\-]\s*([A-Za-z0-9\-]+)',
    re.IGNORECASE
)

PROBLEM_PATTERN = re.compile(
    r'\b(?:NATURE OF THE PROBLEM|PROBLEM)\b\s*[:\-]?\s*([\s\S]+?)(?=(?:\n\s*(?:\*NAME\b|\bNAME\b|\bTEL\b|\bP/no\b|\bP\.no\b|\bPHONE\b|\bID\b|\*CUSTOMER\b|@)|$))',
    re.IGNORECASE
)

ITEM_PATTERN = re.compile(
    r'(?:of|for)\s+((?:' + '|'.join(ITEM_NAMES) + r')(?:s)?(?:\s+[a-zA-Z]+)?)',
    re.IGNORECASE
)


class ParsedResult:
    """Container for parsed message fields."""
    
    def __init__(self):
        self.intent: MessageIntent = MessageIntent.UNKNOWN
        self.timestamp: Optional[datetime] = None
        self.sender: str = ''
        self.item: str = ''
        self.quantity: Optional[Decimal] = None
        self.price: Optional[Decimal] = None
        self.gps_link: str = ''
        self.image_flag: bool = False
        self.customer_name: str = ''
        self.customer_phone: str = ''
        self.customer_id: str = ''
        self.complaint_category: str = ''
        self.problem_description: str = ''
        self.confidence: float = 0.0  # 0-1 indicating parse confidence
        self.warnings: list[str] = []
    
    def to_dict(self) -> dict:
        return {
            'intent': self.intent.value,
            'timestamp': self.timestamp,
            'sender': self.sender,
            'item': self.item,
            'quantity': self.quantity,
            'price': self.price,
            'gps_link': self.gps_link,
            'image_flag': self.image_flag,
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'customer_id': self.customer_id,
            'complaint_category': self.complaint_category,
            'problem_description': self.problem_description,
            'confidence': self.confidence,
            'warnings': self.warnings,
        }


def detect_message_intent(content: str) -> MessageIntent:
    """
    Detect the intent of a message based on its content.
    
    Returns the most likely intent based on keyword and pattern matching.
    Priority: Complaint > Transaction types > Location > Status > Unknown
    """
    content_lower = content.lower().strip()
    
    # Complaints are higher priority than transaction or location patterns
    if COMPLAINT_PREFIX_PATTERN.search(content):
        return MessageIntent.COMPLAINT
    
    # Check for transaction keywords first (highest priority)
    transaction_keywords = ['sold', 'bought', 'paid', 'purchased', 'delivered', 'ordered', 'sent', 'gave', 'transferred', 'took']
    if any(keyword in content_lower for keyword in transaction_keywords):
        if re.search(r'\b(sold|delivered|gave)\b', content_lower):
            return MessageIntent.SALE
        elif re.search(r'\b(bought|purchased|ordered|took)\b', content_lower):
            return MessageIntent.PURCHASE
        elif re.search(r'\b(paid|sent|gave|transferred|received)\b', content_lower):
            return MessageIntent.PAYMENT
    
    # Check for GPS/location messages
    if GPS_URL_PATTERN.search(content) or '📍' in content or 'location' in content_lower:
        return MessageIntent.LOCATION
    
    # Check for status/non-transaction messages
    status_keywords = ['arrived', 'delivered', 'ready', 'available', 'status', 'update', 'info']
    if any(keyword in content_lower for keyword in status_keywords):
        return MessageIntent.STATUS
    
    # Default to unknown
    return MessageIntent.UNKNOWN


def parse_message(content: str, sender: str = None, has_image: bool = False,
                  received_at: datetime = None) -> ParsedResult:
    """
    Main entry point for parsing a WhatsApp message.
    
    Uses intent detection and rule-based extraction for improved accuracy.
    
    Args:
        content: Raw message text
        sender: Sender name (from Telegram metadata)
        has_image: Whether message includes an image
        received_at: When message was received
        
    Returns:
        ParsedResult with extracted fields
    """
    result = ParsedResult()
    result.image_flag = has_image
    
    if not content or not content.strip():
        result.warnings.append("Empty message content")
        return result
    
    content = content.strip()
    
    try:
        # Detect message intent first
        result.intent = detect_message_intent(content)
        
        # Extract GPS/URL first (before other processing)
        result.gps_link = _extract_gps(content)
        
        # Remove GPS URLs from content for cleaner parsing
        clean_content = GPS_URL_PATTERN.sub('', content).strip()
        
        # Extract timestamp
        result.timestamp = _extract_timestamp(clean_content) or received_at
        
        # Extract sender (from content or fallback to metadata)
        result.sender = _extract_sender(clean_content) or (sender or '').strip()
        
        # Apply intent-based extraction rules
        _extract_by_intent(clean_content, result)
        
        # Calculate confidence
        result.confidence = _calculate_confidence(result)
        
    except Exception as e:
        logger.error(f"Error parsing message: {e}", exc_info=True)
        result.warnings.append(f"Parsing error: {str(e)}")
    
    return result


def _extract_gps(content: str) -> str:
    """Extract GPS URL from message."""
    match = GPS_URL_PATTERN.search(content)
    if match:
        url = match.group(1)
        logger.debug(f"Extracted GPS URL: {url[:50]}...")
        return url
    return ''


def _extract_timestamp(content: str) -> Optional[datetime]:
    """Extract timestamp from WhatsApp format."""
    match = TIMESTAMP_PATTERN.search(content)
    if match:
        date_str, time_str = match.groups()
        try:
            # Try common formats
            for fmt in ['%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d-%m-%Y %H:%M:%S', '%d-%m-%Y %H:%M']:
                try:
                    dt = datetime.strptime(f"{date_str} {time_str}", fmt)
                    # Make timezone-aware (assume UTC for WhatsApp timestamps)
                    return timezone.make_aware(dt, timezone=dt_timezone.utc)
                except ValueError:
                    continue
        except Exception as e:
            logger.warning(f"Could not parse timestamp '{date_str} {time_str}': {e}")
    return None


def _extract_sender(content: str) -> Optional[str]:
    """Extract sender name from message patterns."""
    # Try different sender patterns
    for pattern in [SENDER_PATTERN_PAID, SENDER_PATTERN_BOUGHT, SENDER_PATTERN_SOLD_TO]:
        match = pattern.search(content)
        if match:
            sender = match.group(1).strip()
            if sender and len(sender) > 1:
                logger.debug(f"Extracted sender: {sender}")
                return sender
    return None


def _extract_by_intent(content: str, result: ParsedResult):
    """
    Extract transaction details based on detected intent.
    
    Uses rule-based extraction tailored to each message type.
    """
    intent = result.intent
    
    if intent == MessageIntent.SALE:
        _extract_sale_transaction(content, result)
    elif intent == MessageIntent.PURCHASE:
        _extract_purchase_transaction(content, result)
    elif intent == MessageIntent.PAYMENT:
        _extract_payment_transaction(content, result)
    elif intent == MessageIntent.COMPLAINT:
        _extract_complaint_transaction(content, result)
    elif intent == MessageIntent.LOCATION:
        _extract_location_transaction(content, result)
    else:
        # Fallback for unknown/status messages
        _extract_generic_transaction(content, result)


def _extract_complaint_transaction(content: str, result: ParsedResult):
    """Extract customer complaint details from a WhatsApp case report.
    
    Expected format:
    *CUSTOMER COMPLAIN*
    *NAME*: Customer Name
    TEL: Phone Number
    *ID*: ID Number
    *NATURE OF THE PROBLEM*
    *CUSTOMER COMPLAIN: Complaint Description
    
    Note: item, quantity, price are NOT extracted for complaints.
    These are transaction fields not applicable to complaint intake.
    """
    # Extract structured fields
    result.customer_name = _extract_field(NAME_PATTERN, content)
    result.customer_phone = _extract_field(PHONE_PATTERN, content)
    result.customer_id = _extract_field(ID_PATTERN, content)
    
    # Complaint category is a dropdown - do not extract from text to avoid filling with description
    # Leave blank for human selection from dropdown
    result.complaint_category = ''
    
    # Extract complaint description - the actual complaint text
    complaint_match = re.search(
        r'\*?CUSTOMER\s+COMPLAIN(?:T|E)?\*?\s*[:\-]\s*([\s\S]+?)(?=(?:\n\s*(?:\*|@|NATURE)|$))',
        content,
        re.IGNORECASE | re.MULTILINE
    )
    if complaint_match:
        description_text = complaint_match.group(1).strip()
        # Clean up description - remove trailing bot mentions or metadata
        description_text = re.sub(r'\s*@\S+\s*$', '', description_text)
        result.problem_description = description_text
    
    # Fallback: if no description found, try generic extraction
    if not result.problem_description:
        result.problem_description = _extract_complaint_description(content)
    
    # Fallback: if still nothing, use sender
    if not result.customer_name and result.sender:
        result.customer_name = result.sender
    
    # If still no description, use the raw content as a fallback
    if not result.problem_description:
        result.problem_description = content.strip()
    
    # DO NOT extract item, quantity, price for complaints
    # These are transaction fields and don't apply to complaint intake



def _extract_field(pattern, content: str, group_index: int = 1) -> str:
    """Extract a single text field using a regex pattern."""
    if isinstance(pattern, str):
        pattern = re.compile(pattern, re.IGNORECASE | re.DOTALL)
    match = pattern.search(content)
    if match:
        return match.group(group_index).strip()
    return ''


def _extract_complaint_description(content: str) -> str:
    """Extract complaint problem description from structured case data."""
    # Prefer explicit problem label blocks
    match = PROBLEM_PATTERN.search(content)
    if match:
        description = match.group(1)
        description = re.sub(r'\s+', ' ', description).strip()
        return description

    # Fallback: extract text following the complaint header, excluding structured labels
    complaint_match = re.search(
        r'\bCUSTOMER\s*COMPLAIN(?:T|E)?\b[:\*\s]*(.+)',
        content,
        re.IGNORECASE | re.DOTALL,
    )
    if complaint_match:
        description = complaint_match.group(1).strip()
        description = re.split(
            r'\n\s*(?:\*NAME\b|\bNAME\b|\bTEL\b|\bP/no\b|\bP\.no\b|\bPHONE\b|\bID\b|\*CUSTOMER\b|@)',
            description,
            maxsplit=1,
        )[0]
        description = re.sub(r'\s+', ' ', description).strip()
        return description

    return ''


def _extract_sale_transaction(content: str, result: ParsedResult):
    """Extract details from sale messages: 'Sold X item Y each to Z'"""
    # Primary pattern: "Sold 3 bread 50 each to John"
    match = SOLD_PATTERN.search(content)
    if match:
        qty_str, item, price_str = match.groups()
        result.quantity = _safe_decimal(qty_str)
        result.item = _clean_item_name(item)  # Clean currency from item
        if price_str:
            result.price = _safe_decimal(price_str)
        logger.debug(f"SALE pattern: qty={result.quantity}, item={result.item}, price={result.price}")
        return
    
    # Fallback patterns for sales
    _extract_generic_transaction(content, result)


def _extract_purchase_transaction(content: str, result: ParsedResult):
    """Extract details from purchase messages: 'X bought Y item @ Z'"""
    # Primary pattern: "John bought 3 bags maize @ 100"
    match = BOUGHT_PATTERN.search(content)
    if match:
        qty_str, item, price_str = match.groups()
        result.quantity = _safe_decimal(qty_str)
        result.item = _clean_item_name(item)
        if price_str:
            result.price = _safe_decimal(price_str)
        logger.debug(f"PURCHASE pattern: qty={result.quantity}, item={result.item}, price={result.price}")
        return
    
    # Fallback patterns for purchases
    _extract_generic_transaction(content, result)


def _extract_payment_transaction(content: str, result: ParsedResult):
    """Extract details from payment messages: 'X paid Y for Z item'"""
    # Primary pattern: "John paid 200 for 4 milk"
    match = PAID_PATTERN.search(content)
    if match:
        price_str, qty_str, item = match.groups()
        result.price = _safe_decimal(price_str)
        if qty_str:
            result.quantity = _safe_decimal(qty_str)
        if item:
            # Clean the item by extracting the actual item name
            result.item = _extract_item_from_text(item)
        logger.debug(f"PAYMENT pattern: price={result.price}, qty={result.quantity}, item={result.item}")
        return
    
    # Fallback: look for payment amounts
    price_match = TOTAL_PRICE_PATTERN.search(content)
    if price_match:
        result.price = _safe_decimal(price_match.group(1))
        logger.debug(f"PAYMENT fallback: price={result.price}")


def _extract_location_transaction(content: str, result: ParsedResult):
    """Extract details from location messages, may include transactions."""
    # Location messages might still have transaction info
    _extract_generic_transaction(content, result)


def _extract_generic_transaction(content: str, result: ParsedResult):
    """Generic extraction for unknown or mixed message types."""
    
    # Extract quantity
    qty_match = QUANTITY_PATTERN.search(content)
    if qty_match:
        result.quantity = _safe_decimal(qty_match.group(1))
        logger.debug(f"Extracted quantity: {result.quantity}")
    
    # Extract item
    item_match = ITEM_PATTERN.search(content)
    if item_match:
        result.item = _clean_item_name(item_match.group(1))
        logger.debug(f"Extracted item: {result.item}")
    else:
        # Try to extract item from context
        item = _extract_item_from_text(content)
        if item:
            result.item = _clean_item_name(item)
    
    # Extract price - try multiple patterns
    price_match = PRICE_EACH_PATTERN.search(content)
    if price_match:
        result.price = _safe_decimal(price_match.group(1))
    else:
        price_match = TOTAL_PRICE_PATTERN.search(content)
        if price_match:
            result.price = _safe_decimal(price_match.group(1))
    
    if result.price:
        logger.debug(f"Extracted price: {result.price}")


def _extract_transaction(content: str, result: ParsedResult):
    """Legacy function - now delegates to intent-based extraction."""
    _extract_by_intent(content, result)


def _extract_item_from_text(text: str) -> str:
    """Extract item name from a text string by finding known items."""
    if not text:
        return ''
    
    text_lower = text.lower().strip()
    
    # First, try to find exact matches of known items
    for item in ITEM_NAMES:
        if item in text_lower:
            return item
    
    # If no exact match, try to find items with word boundaries
    for item in ITEM_NAMES:
        if re.search(r'\b' + re.escape(item) + r'\b', text_lower):
            return item
    
    # Fallback: return the cleaned text if it's short enough
    cleaned = _clean_item_name(text)
    if len(cleaned.split()) <= 3:  # If it's a short phrase
        return cleaned
    
    return ''


def _clean_item_name(item: str) -> str:
    """Clean and normalize item name."""
    if not item:
        return ''
    # Remove extra whitespace and normalize
    item = ' '.join(item.strip().lower().split())
    # Remove trailing prepositions
    item = re.sub(r'\s+(to|for|at|from|by)\s*$', '', item)
    # Remove currency words
    item = re.sub(r'\s+(ksh|kes|sh|shillings?)\s*$', '', item, re.IGNORECASE)
    return item.strip()


def _safe_decimal(value: str) -> Optional[Decimal]:
    """Safely convert string to Decimal."""
    if not value:
        return None
    try:
        # Remove commas
        cleaned = value.replace(',', '')
        return Decimal(cleaned)
    except (InvalidOperation, ValueError) as e:
        logger.warning(f"Could not parse decimal from '{value}': {e}")
        return None


def _calculate_confidence(result: ParsedResult) -> float:
    """
    Calculate parsing confidence (0-1) based on intent type.
    Different message types have different field requirements.
    """
    base_confidence = 0.0
    
    # Intent detection contributes to confidence
    if result.intent != MessageIntent.UNKNOWN:
        base_confidence += 0.2
    
    # Field extraction confidence depends on message intent
    if result.intent == MessageIntent.COMPLAINT:
        # Complaint messages require: customer_name, customer_phone, problem_description
        complaint_fields = 0
        total_complaint_fields = 3
        
        if result.customer_name:
            complaint_fields += 1
        if result.customer_phone:
            complaint_fields += 1
        if result.problem_description:
            complaint_fields += 1
        
        field_confidence = (complaint_fields / total_complaint_fields) * 0.8
        
    elif result.intent in (MessageIntent.SALE, MessageIntent.PURCHASE, MessageIntent.PAYMENT):
        # Transaction messages require: item, quantity, price
        transaction_fields = 0
        total_transaction_fields = 3
        
        if result.item:
            transaction_fields += 1
        if result.quantity is not None:
            transaction_fields += 1
        if result.price is not None:
            transaction_fields += 1
        
        field_confidence = (transaction_fields / total_transaction_fields) * 0.8
        
    elif result.intent == MessageIntent.LOCATION:
        # Location messages just need GPS and optional sender
        location_fields = 0
        total_location_fields = 1
        
        if result.gps_link:
            location_fields += 1
        
        field_confidence = (location_fields / total_location_fields) * 0.8
        
    else:
        # For other intents, check sender minimum
        field_confidence = 0.4 if result.sender else 0.0
    
    # GPS presence boosts confidence for location messages
    gps_boost = 0.1 if (result.gps_link and result.intent == MessageIntent.LOCATION) else 0.0
    
    total_confidence = base_confidence + field_confidence + gps_boost
    return round(min(total_confidence, 1.0), 2)


def split_batch_message(content: str) -> list[dict]:
    """
    Split a batch forwarded message into individual messages.
    
    WhatsApp forwards may contain multiple messages separated by:
    - Timestamps like [14/03/2026, 10:30:15]
    - Sender names followed by colon
    - Double newlines
    
    Args:
        content: Full batch message content
        
    Returns:
        List of dicts with 'sender' and 'content' keys
    """
    messages = []
    
    # Pattern: [timestamp] sender: message
    timestamp_sender_pattern = re.compile(
        r'\[?\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}[\s,]+\d{1,2}:\d{2}(?::\d{2})?\]?\s*[-–—]?\s*([^:\n]+):',
        re.MULTILINE
    )
    
    # Split by timestamp+sender pattern
    parts = timestamp_sender_pattern.split(content)
    
    if len(parts) > 1:
        # First part might be empty or contain the first sender
        current_sender = None
        current_content = []
        
        for i, part in enumerate(parts):
            if i == 0 and part.strip():
                # Check if first part has a sender
                sender_match = re.match(r'^([^:\n]+):', part)
                if sender_match:
                    current_sender = sender_match.group(1).strip()
                    current_content.append(part[sender_match.end():].strip())
            elif i % 2 == 1:
                # Odd indices are sender names
                current_sender = part.strip()
            else:
                # Even indices are message content
                if current_sender and part.strip():
                    messages.append({
                        'sender': current_sender,
                        'content': part.strip()
                    })
    else:
        # No timestamp pattern found, treat as single message
        # Try to extract sender from first line
        first_line_match = re.match(r'^([^:\n]+):(.+)$', content, re.DOTALL)
        if first_line_match:
            messages.append({
                'sender': first_line_match.group(1).strip(),
                'content': first_line_match.group(2).strip()
            })
        else:
            # Single message, sender may be in metadata
            messages.append({
                'sender': '',
                'content': content.strip()
            })
    
    logger.info(f"Split batch into {len(messages)} individual messages")
    return messages
