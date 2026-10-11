"""SERBITO-593: monthly billing report. Read-only; counts and money, no personal data.

    uv run python manage.py billing_report                 # this month (Belgrade time)
    uv run python manage.py billing_report --month 2026-11

Production: gcloud run jobs execute javi-migrate --region europe-west1 --wait \
    --args=manage.py,billing_report,--month,2026-11
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from billing import services


class Command(BaseCommand):
    help = "Paying shops, gross and estimated net (after the Whop fee and refunds) for a month."

    def add_arguments(self, parser):
        parser.add_argument("--month", default="", help="YYYY-MM (default: this month)")

    def handle(self, *args, **options):
        value = options["month"]
        if value:
            try:
                year, month = (int(x) for x in value.split("-"))
                if not 1 <= month <= 12:
                    raise ValueError
            except ValueError as exc:
                raise CommandError("--month must be YYYY-MM") from exc
        else:
            today = timezone.localdate()
            year, month = today.year, today.month
        r = services.monthly_report(year, month)
        fee = services.fee_rate() * 100
        self.stdout.write(f"Javi billing report {r.month} (Belgrade time)")
        self.stdout.write(f"paying shops: {r.paying_shops}")
        self.stdout.write(f"payments: {r.payments}")
        for cur in sorted(r.gross) or [services.currency()]:
            self.stdout.write(
                f"gross {cur}: {r.gross.get(cur, 0):.2f} | refunded: {r.refunded.get(cur, 0):.2f} "
                f"| est. net after ~{fee:.0f}% fee: {r.est_net.get(cur, 0):.2f}"
            )
        self.stdout.write(
            "shops now: " + ", ".join(f"{name} {count}" for name, count in r.statuses.items())
        )
        if not services.enabled():
            self.stdout.write("JAVI_BILLING_ENABLED is off.")
