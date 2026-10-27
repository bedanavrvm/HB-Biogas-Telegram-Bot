"""English PDF presentation without changing the underlying Decimal value."""
from decimal import Decimal, InvalidOperation

ONES = ('Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen Fifteen Sixteen Seventeen Eighteen Nineteen').split()
TENS = ('Zero Ten Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety').split()
SCALES = ('', 'Thousand', 'Million', 'Billion', 'Trillion', 'Quadrillion', 'Quintillion')


def number_words(value):
    try:
        number = Decimal(str(value).replace(',', ''))
    except (InvalidOperation, ValueError):
        raise ValueError('Enter a valid number to display in words.') from None
    if not number.is_finite() or number.copy_abs() >= Decimal('1e21') or number.as_tuple().exponent < -20:
        raise ValueError('This number is outside the supported words format.')
    def under_thousand(n):
        if n < 20:
            return ONES[n]
        if n < 100:
            return TENS[n // 10] + (' ' + ONES[n % 10] if n % 10 else '')
        return ONES[n // 100] + ' Hundred' + (' And ' + under_thousand(n % 100) if n % 100 else '')
    whole, _, fraction = format(number.copy_abs(), 'f').partition('.')
    integer, groups, scale = int(whole), [], 0
    while integer:
        integer, group = divmod(integer, 1000)
        if group:
            groups.append(under_thousand(group) + (' ' + SCALES[scale] if scale else ''))
        scale += 1
    text = ' '.join(reversed(groups)) or 'Zero'
    if len(groups) > 1 and 0 < int(whole) % 1000 < 100:
        prefix, tail = text.rsplit(groups[0], 1)
        text = prefix + 'And ' + groups[0] + tail
    if fraction and int(fraction):
        text += ' Point ' + ' '.join(ONES[int(digit)] for digit in fraction)
    return ('Minus ' if number < 0 else '') + text
