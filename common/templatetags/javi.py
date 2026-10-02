"""Template filters shared by the cabinet and the tracking pages."""

from django import template

from common.timewindow import format_eta_label

register = template.Library()


@register.filter
def eta_label(value):
    """`{{ d.eta_at|eta_label }}` → «14:00» today, «03.10. 14:00» another day (SERBITO-356)."""
    return format_eta_label(value) if value else ""
