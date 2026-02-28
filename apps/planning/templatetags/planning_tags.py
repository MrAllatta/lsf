"""planning/templatetags/planning_tags.py"""

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Look up dict by key in template."""
    if isinstance(dictionary, dict):
        return dictionary.get(key, [])
    return []


@register.simple_tag
def render_planting_bar(row, weeks):
    """Render a planting as cells spanning the correct columns."""
    cells = []
    week_nums = [w["num"] for w in weeks]
    col_start = row["col_start"]
    col_span = row["col_span"]
    css = row["css_class"]
    planting = row["planting"]

    # Empty cells before the planting
    for i in range(col_start):
        wk = week_nums[i]
        cells.append(
            f'<td class="week-cell fallow" '
            f'data-block="{planting.block_id}" data-week="{wk}"></td>'
        )

    # The planting bar itself
    cells.append(
        f'<td class="week-cell planting-bar {css}" '
        f'colspan="{col_span}" '
        f'data-planting="{planting.id}" '
        f'title="{planting.crop.name} — {planting.planned_bedfeet}bf">'
        f'<span class="planting-label">{row["label"]}</span>'
        f"</td>"
    )

    # Empty cells after the planting
    remaining = len(week_nums) - col_start - col_span
    for i in range(remaining):
        wk = week_nums[col_start + col_span + i]
        cells.append(
            f'<td class="week-cell fallow" '
            f'data-block="{planting.block_id}" data-week="{wk}"></td>'
        )

    return mark_safe("".join(cells))
