"""Bounded, offline PNG charts for email; the captured facts are never modified."""
from decimal import Decimal, InvalidOperation
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


PALETTE = ('#2e3480', '#438323', '#c8247a', '#a36b08')
WIDTH = 840
INK = '#1f2a4d'
MUTED = '#4a5578'


def _number(value):
    if value is None:
        return None
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Non-finite chart value')
    return number


def _label(number):
    if number is None:
        return '—'
    return f'{number:,.0f}' if number == number.to_integral_value() else f'{number:,.2f}'


def _wrap(draw, text, font, width):
    """Wrap without ellipses; use the HTML table if a label cannot fit."""
    lines, line = [], ''
    for word in str(text).split():
        candidate = f'{line} {word}'.strip()
        if draw.textlength(candidate, font=font) <= width:
            line = candidate
        else:
            if not line or draw.textlength(word, font=font) > width:
                return None
            lines.append(line)
            line = word
    lines.append(line)
    return lines if len(lines) <= 4 else None


def chart_png(chart):
    """Return a PNG or None when a complete chart would be unreadable on mobile.

    Eight groups/four series bound both rendering work and mobile density.
    Missing values remain missing, never zero. Unsupported/dense data stays in
    the HTML breakdown. No font files, URLs, browser, or native SVG backend.
    """
    labels, datasets = chart.get('labels', []), chart.get('datasets', [])
    if not 0 < len(labels) <= 8 or not 0 < len(datasets) <= 4:
        return None
    if chart.get('type', 'bar') not in {'bar', 'line'}:
        return None
    try:
        series = [[_number(dataset.get('values', [])[i]) if i < len(dataset.get('values', [])) else None
                   for i in range(len(labels))] for dataset in datasets]
    except (InvalidOperation, ValueError, TypeError):
        return None
    numbers = [value for values in series for value in values if value is not None]
    if not numbers:
        return None
    low, high = min(numbers + [Decimal(0)]), max(numbers + [Decimal(0)])
    span = high - low or Decimal(1)
    line_chart = chart.get('type') == 'line'
    font = ImageFont.load_default(size=40 if line_chart else 26)
    small = ImageFont.load_default(size=36 if line_chart else 23)
    measure = ImageDraw.Draw(Image.new('RGB', (WIDTH, 1)))
    wrapped = [_wrap(measure, label, font, WIDTH - 48) for label in labels]
    legends = [_wrap(measure, dataset.get('label', ''), small, WIDTH - 76) for dataset in datasets]
    if any(lines is None for lines in wrapped + legends):
        return None
    # Extremely large formatted amounts are better read in a table, not clipped.
    if any(measure.textlength(_label(value), font=font) > WIDTH - 48 for value in numbers):
        return None
    line_height = 44 if line_chart else 34
    legend_height = sum(max(1, len(lines)) * line_height + 8 for lines in legends)
    if line_chart:
        # Horizontal bars accommodate long category labels; time-series ticks
        # must fit in their own slot or the complete HTML table is safer.
        # Thin axis labels only, never points or captured values. Three evenly
        # spaced dates avoid colliding labels in paired panels and on phones.
        visible_ticks = set(range(len(labels))) if len(labels) <= 3 else {0, len(labels) // 2, len(labels) - 1}
        tick_width = (WIDTH - 96) / max(1, len(visible_ticks))
        ticks = [_wrap(measure, label, small, tick_width - 4) for label in labels]
        if any(ticks[i] is None for i in visible_ticks):
            return None
        height = 440
    else:
        height = legend_height + sum(max(1, len(lines)) * 30 + len(series) * 30 + 8 for lines in wrapped) + 40
    if height > 440 or legend_height > 110:
        return None
    image = Image.new('RGB', (WIDTH, height), '#ffffff')
    draw = ImageDraw.Draw(image)
    y = 12
    for index, lines in enumerate(legends):
        draw.rounded_rectangle((24, y + 7, 42, y + 25), radius=3, fill=PALETTE[index])
        for line in lines:
            draw.text((52, y), line, font=small, fill=MUTED)
            y += line_height
        y += 8
    if line_chart:
        top, bottom = y + 30, 330
        left, right = 100, WIDTH - 36
        for value, position in ((high, top), (low, bottom)):
            draw.line((left, position, right, position), fill='#e1e4ee', width=1)
            if draw.textlength(_label(value), font=small) > left - 12:
                return None
            draw.text((left - 12, position), _label(value), anchor='ra', font=small, fill=MUTED)
        step = Decimal(right - left) / max(1, len(labels) - 1)
        for index, values in enumerate(series):
            previous = None
            for i, value in enumerate(values):
                if value is None:
                    previous = None
                    continue
                point = (left + int(i * step), bottom - int((value - low) / span * (bottom - top)))
                if previous:
                    draw.line((*previous, *point), fill=PALETTE[index], width=4)
                draw.ellipse((point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5), fill=PALETTE[index])
                previous = point
        # Equally spaced category slots below the plot preserve every tick.
        for i, lines in enumerate(ticks):
            if i not in visible_ticks:
                continue
            centre = left + int(i * step)
            for row, line in enumerate(lines):
                x = max(24, min(WIDTH - 24 - draw.textlength(line, font=small),
                                centre - draw.textlength(line, font=small) / 2))
                draw.text((x, bottom + 22 + row * 38), line, font=small, fill=MUTED)
    else:
        zero = 24 + int(-low / span * (WIDTH - 204))
        for i, lines in enumerate(wrapped):
            for line in lines:
                draw.text((24, y), line, font=font, fill=INK)
                y += 30
            for index, values in enumerate(series):
                value = values[i]
                draw.text((WIDTH - 24, y), _label(value), anchor='ra', font=font, fill=PALETTE[index])
                draw.line((24, y + 20, WIDTH - 180, y + 20), fill='#eef0f8', width=8)
                if value is not None:
                    end = 24 + int((value - low) / span * (WIDTH - 204))
                    if end != zero:
                        draw.rectangle((min(zero, end), y + 16, max(zero, end), y + 24), fill=PALETTE[index])
                y += 30
            y += 8
        draw.text((24, y), _label(low), font=small, fill=MUTED)
        draw.text((WIDTH - 24, y), _label(high), anchor='ra', font=small, fill=MUTED)
    output = BytesIO()
    image.save(output, format='PNG', optimize=True)
    return output.getvalue()
