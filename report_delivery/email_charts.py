"""Bounded, offline PNG charts for email; the captured facts are never modified."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


PALETTE = ('#2481cc', '#168354', '#d49a16', '#8b5cc7')
WIDTH = 840
INK = '#1f2a4d'
MUTED = '#4a5578'
AXIS = '#526173'
GRID = '#dce1ed'


def _png(image):
    output = BytesIO()
    image.save(output, format='PNG', optimize=True)
    return output.getvalue()


def _doughnut(labels, series, colors):
    """Two-part compositions with legible values, including a single full ring."""
    if len(series) != 1 or not 1 <= len(labels) <= 4:
        return None
    values = series[0]
    if any(value is None or value < 0 for value in values):
        return None
    total = sum(values)
    if total <= 0:
        return None
    image = Image.new('RGB', (WIDTH, 440), '#ffffff')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30)
    small = ImageFont.load_default(size=28)
    large = ImageFont.load_default(size=58)
    wrapped = [_wrap(draw, label, font, 338) for label in labels]
    if any(lines is None or len(lines) > 2 for lines in wrapped):
        return None
    centre, radius = (213, 220), 164
    bounds = (centre[0] - radius, centre[1] - radius, centre[0] + radius, centre[1] + radius)
    angle = Decimal(-90)
    for index, value in enumerate(values):
        end = angle + value * 360 / total
        if value:
            draw.pieslice(bounds, start=float(angle), end=float(end), fill=colors[index % len(colors)])
        angle = end
    hole = 112
    draw.ellipse((centre[0] - hole, centre[1] - hole, centre[0] + hole, centre[1] + hole), fill='#ffffff')
    if draw.textlength(_label(total), font=large) > hole * 2 - 16:
        return None
    draw.text((centre[0], centre[1] - 18), _label(total), font=large, fill=INK, anchor='mm')
    draw.text((centre[0], centre[1] + 31), 'Complaints', font=small, fill=MUTED, anchor='mm')
    row_heights = [len(lines) * 36 + 42 for lines in wrapped]
    y = (440 - sum(row_heights) - 20 * (len(labels) - 1)) // 2
    if y < 10:
        return None
    for index, (value, lines) in enumerate(zip(values, wrapped)):
        color = colors[index % len(colors)]
        draw.rounded_rectangle((430, y + 7, 450, y + 27), radius=3, fill=color)
        for line in lines:
            draw.text((464, y), line, font=font, fill=INK)
            y += 36
        draw.text((464, y), f'{_label(value)}  ({value * 100 / total:.0f}%)', font=small, fill=color)
        y += 62
    return _png(image)


def _number(value):
    if value is None:
        return None
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Non-finite chart value')
    return number


def _label(number):
    if number is None:
        return '-'
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


def _chart_text(value):
    # Pillow's bundled font lacks several punctuation glyphs. Keep rendered
    # labels portable without changing the captured facts or Excel values.
    return str(value).translate(str.maketrans({'–': '-', '—': '-', '−': '-', '·': ' ', '\u00a0': ' '}))


def chart_png(chart):
    """Return a PNG or None when a complete chart would be unreadable on mobile.

    Up to 31 line points (one calendar month), eight bar groups/four series,
    or four doughnut categories
    bound rendering work. Date labels are thinned, never the captured points.
    Missing values remain missing, never zero. Unsupported/dense data stays in
    the HTML breakdown. No font files, URLs, browser, or native SVG backend.
    """
    image_width = WIDTH
    labels = [_chart_text(label) for label in chart.get('labels', [])]
    datasets = chart.get('datasets', [])
    line_chart = chart.get('type') == 'line'
    temporal = line_chart or chart.get('temporal', False)
    if not 0 < len(labels) <= (31 if temporal else 8) or not 0 < len(datasets) <= 4:
        return None
    if chart.get('type', 'bar') not in {'bar', 'line', 'doughnut'}:
        return None
    try:
        series = [[_number(dataset.get('values', [])[i]) if i < len(dataset.get('values', [])) else None
                   for i in range(len(labels))] for dataset in datasets]
    except (InvalidOperation, ValueError, TypeError):
        return None
    numbers = [value for values in series for value in values if value is not None]
    if not numbers:
        return None
    colors = chart.get('colors') or PALETTE
    if chart.get('type') == 'doughnut':
        return _doughnut(labels, series, colors)
    low, high = min(numbers + [Decimal(0)]), max(numbers + [Decimal(0)])
    span = high - low or Decimal(1)
    font = ImageFont.load_default(size=30)
    small = ImageFont.load_default(size=28)
    measure = ImageDraw.Draw(Image.new('RGB', (image_width, 1)))
    wrapped = [_wrap(measure, label, font, image_width - 48) for label in labels]
    legends = ([_wrap(measure, _chart_text(dataset.get('label', '')), small, image_width - 76) for dataset in datasets]
               if len(datasets) > 1 else [])
    if any(lines is None for lines in wrapped + legends):
        return None
    # Extremely large formatted amounts are better read in a table, not clipped.
    if any(measure.textlength(_label(value), font=font) > image_width - 48 for value in numbers):
        return None
    line_height = 34
    # Series names sit in one compact row, preserving the plot's height.
    legend_widths = [int(measure.textlength(' '.join(lines), font=small)) + 52 for lines in legends]
    horizontal_legend = bool(legends) and sum(legend_widths) <= image_width - 48
    legend_height = 38 if horizontal_legend else sum(max(1, len(lines)) * line_height + 8 for lines in legends)
    if temporal:
        # Horizontal bars accommodate long category labels; time-series ticks
        # must fit in their own slot or the complete HTML table is safer.
        # Thin axis labels only, never points or captured values. Three evenly
        # spaced dates avoid colliding labels in paired panels and on phones.
        visible_ticks = set(range(len(labels))) if len(labels) <= 3 else {0, len(labels) // 2, len(labels) - 1}
        tick_width = (image_width - 96) / max(1, len(visible_ticks))
        # The year is already in the period stamp; keep date ticks compact.
        from datetime import datetime
        tick_labels = []
        for label in labels:
            try:
                day = datetime.strptime(label, '%d %b %Y')
                tick_labels.append(f'{day.day} {day:%b}')
            except ValueError:
                tick_labels.append(label)
        ticks = [_wrap(measure, label, small, tick_width - 4) for label in tick_labels]
        if any(ticks[i] is None or len(ticks[i]) > 2 for i in visible_ticks):
            return None
        required_height = 440
    else:
        required_height = legend_height + sum(max(1, len(lines)) * 34 + len(series) * 34 + 8 for lines in wrapped) + 90
    if required_height > 440 or legend_height > 110:
        return None
    height = 440
    image = Image.new('RGB', (image_width, height), '#ffffff')
    draw = ImageDraw.Draw(image)
    y = 12
    x = 24
    for index, lines in enumerate(legends):
        draw.rounded_rectangle((x, y + 7, x + 18, y + 25), radius=3, fill=colors[index % len(colors)])
        if horizontal_legend:
            draw.text((x + 28, y), ' '.join(lines), font=small, fill=MUTED)
            x += legend_widths[index]
        else:
            for line in lines:
                draw.text((52, y), line, font=small, fill=MUTED)
                y += line_height
            y += 8
    if horizontal_legend:
        y += legend_height
    unit = _chart_text(chart.get('unit', 'complaints')).capitalize()
    draw.text((24, y), unit, font=small, fill=MUTED)
    y += 34
    if temporal:
        top, bottom = y + 16, 330
        # Rounded scale with interior horizontal guides, plus vertical guides
        # at the labelled dates. Real axes stay distinct from the light grid.
        count_axis = chart.get('unit') in {'cases', 'complaints', 'actions'}
        if count_axis:
            high = max(high, Decimal(3))
            span = high - low
        rough = span / 4
        magnitude = Decimal(10) ** rough.adjusted()
        interval = next(Decimal(value) * magnitude for value in ('1', '2', '2.5', '5', '10')
                        if Decimal(value) * magnitude >= rough)
        if count_axis:
            interval = interval.to_integral_value(rounding=ROUND_CEILING)
        low = (low / interval).to_integral_value(rounding=ROUND_FLOOR) * interval
        high = (high / interval).to_integral_value(rounding=ROUND_CEILING) * interval
        if high == low:
            high = low + interval * 4
        span = high - low
        values = [low + interval * i for i in range(int(span / interval) + 1)]
        left = max(100, int(max(draw.textlength(_label(value), font=small) for value in values)) + 18)
        right = image_width - 36
        if left > 240:
            return None
        for value in values:
            position = bottom - int((value - low) / span * (bottom - top))
            draw.line((left, position, right, position), fill=GRID, width=2)
            draw.text((left - 12, position), _label(value), anchor='rm', font=small, fill=MUTED)
        step = Decimal(right - left) / (max(1, len(labels) - 1) if line_chart else len(labels))
        def x_position(i):
            return left + int((Decimal(i) + (0 if line_chart else Decimal('.5'))) * step)
        for i in sorted(visible_ticks):
            x = x_position(i)
            draw.line((x, top, x, bottom), fill=GRID, width=2)
        for index, values in enumerate(series):
            previous = None
            for i, value in enumerate(values):
                if value is None:
                    previous = None
                    continue
                point = (x_position(i), bottom - int((value - low) / span * (bottom - top)))
                if line_chart:
                    if previous:
                        draw.line((*previous, *point), fill=colors[index % len(colors)], width=5)
                    draw.ellipse((point[0] - 6, point[1] - 6, point[0] + 6, point[1] + 6), fill=colors[index % len(colors)])
                elif value != 0:
                    bar_width = max(2, int(step * Decimal('.75') / len(series)))
                    x = point[0] - int(step * Decimal('.375')) + index * bar_width
                    baseline = bottom - int((Decimal(0) - low) / span * (bottom - top))
                    draw.rectangle((x, min(baseline, point[1]), x + bar_width - 1, max(baseline, point[1])), fill=colors[index % len(colors)])
                previous = point
        # Axes are drawn last so series touching zero never conceal them.
        draw.line((left, top, left, bottom), fill=AXIS, width=4)
        draw.line((left, bottom, right, bottom), fill=AXIS, width=4)
        # Equally spaced category slots below the plot preserve every tick.
        for i, lines in enumerate(ticks):
            if i not in visible_ticks:
                continue
            centre = x_position(i)
            for row, line in enumerate(lines):
                x = max(24, min(image_width - 24 - draw.textlength(line, font=small),
                                centre - draw.textlength(line, font=small) / 2))
                draw.text((x, bottom + 22 + row * 30), line, font=small, fill=MUTED)
    else:
        # Label column, real count axis and equal category slots. No floating
        # progress tracks whose endpoints could be mistaken for an axis.
        wrapped = [_wrap(draw, label, small, 220) for label in labels]
        if any(lines is None or len(lines) > 2 for lines in wrapped):
            return None
        left, right, top, bottom = 256, image_width - 76, y + 12, height - 64
        count_axis = chart.get('unit', 'complaints') in {'cases', 'complaints', 'actions'}
        if count_axis:
            high = max(Decimal(4), (high / 4).to_integral_value(rounding=ROUND_CEILING) * 4)
            low = (low / 4).to_integral_value(rounding=ROUND_FLOOR) * 4
            span = high - low
        zero = left + int(-low / span * (right - left))
        for i in range(5):
            x = left + int((right - left) * i / 4)
            draw.line((x, top, x, bottom), fill=GRID, width=2)
            draw.text((x, bottom + 16), _label(low + span * i / 4), anchor='mt', font=small, fill=MUTED)
        slot = (bottom - top) / len(labels)
        if slot < max(max(len(lines) * 32 for lines in wrapped), len(series) * 22) + 8:
            return None
        for i, lines in enumerate(wrapped):
            centre = top + slot * (i + .5)
            label_y = centre - len(lines) * 32 / 2
            for line in lines:
                draw.text((24, label_y), line, font=small, fill=INK)
                label_y += 32
            for index, values in enumerate(series):
                value = values[i]
                bar_y = centre - len(series) * 22 / 2 + index * 22
                color = colors[(i if len(series) == 1 and chart.get('colors') else index) % len(colors)]
                if value is not None:
                    end = left + int((value - low) / span * (right - left))
                    if end != zero:
                        draw.rectangle((min(zero, end), bar_y, max(zero, end), bar_y + 16), fill=color)
                draw.text((image_width - 16, bar_y + 8), _label(value), anchor='rm', font=small, fill=color)
        draw.line((left, top, left, bottom), fill=AXIS, width=4)
        draw.line((left, bottom, right, bottom), fill=AXIS, width=4)
    return _png(image)
