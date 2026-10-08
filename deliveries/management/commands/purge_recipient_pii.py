"""SERBITO-467: erase recipient name/phone/address past RECIPIENT_PII_RETENTION_DAYS.

Dry run by default (counts only). `--apply` changes the data. Prints counts, never data.
Production runs the same code daily through POST /tasks/purge-recipient-pii/ (Cloud Scheduler).
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from deliveries.retention import purge_recipient_pii, retention_cutoff


class Command(BaseCommand):
    help = (
        "Erase recipient name, phone and address on deliveries final for more than "
        "RECIPIENT_PII_RETENTION_DAYS. Dry run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Change the data (else dry run)")
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help="Rows per batch (default: RECIPIENT_PII_PURGE_BATCH_SIZE)",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        result = purge_recipient_pii(apply=apply, batch_size=options["batch_size"])
        mode = "applied" if apply else "dry run"
        self.stdout.write(
            f"Recipient PII purge ({mode}), retention {settings.RECIPIENT_PII_RETENTION_DAYS} "
            f"days, cutoff {retention_cutoff():%Y-%m-%d}:"
        )
        for name, value in result.as_dict().items():
            if name != "complete":
                self.stdout.write(f"  {name}: {value}")
        if not apply:
            self.stdout.write("Nothing changed. Run with --apply to erase.")
