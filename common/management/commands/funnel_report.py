"""SERBITO-595: weekly request-funnel counts. Read-only; prints counts, never personal data.

    uv run python manage.py funnel_report            # last 8 weeks
    uv run python manage.py funnel_report --weeks 12

Production: gcloud run jobs execute django-migrate --args=funnel_report (see the PR / Jira).
"""

from django.core.management.base import BaseCommand

from common.funnel import weekly


class Command(BaseCommand):
    help = "Weekly funnel: landing views, sign-up form opens, sign-ups, activated shops."

    def add_arguments(self, parser):
        parser.add_argument("--weeks", type=int, default=8, help="How many weeks (default 8)")

    def handle(self, *args, **options):
        weeks = max(1, options["weeks"])
        header = (
            f"{'week (Mon-Sun)':<25}{'landing_view':>13}{'signup_start':>13}"
            f"{'signup_complete':>16}{'shop_activated':>15}{'view->signup':>13}"
        )
        self.stdout.write(header)
        for w in weekly(weeks):
            self.stdout.write(
                f"{w.start:%Y-%m-%d} .. {w.end:%Y-%m-%d}  "
                f"{w.landing_view:>13}{w.signup_start:>13}{w.signup_complete:>16}"
                f"{w.shop_activated:>15}{w.view_to_signup:>13}"
            )
        self.stdout.write(
            "landing_view and signup_start are counted since SERBITO-595 (browsers only); "
            "signup_complete = new shops, shop_activated = first started delivery. "
            "The current week is partial."
        )
