"""SERBITO-593: re-read every known Whop membership (a lost webhook). Safe to repeat.

uv run python manage.py billing_sync
"""

from django.core.management.base import BaseCommand

from billing import services, whop


class Command(BaseCommand):
    help = "Re-read javi Whop memberships and update shop subscription status."

    def handle(self, *args, **options):
        if not whop.is_configured():
            missing = ", ".join(whop.missing_settings())
            self.stdout.write(f"Whop is not configured ({missing}); nothing to do.")
            return
        counts = services.sync_all()
        self.stdout.write(
            f"checked {counts['checked']}, changed {counts['changed']}, errors {counts['errors']}"
        )
