"""Run the SCRUM-88 expiry and reminder worker."""

from time import sleep

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from apps.venues.holds import process_holds


class Command(BaseCommand):
    help = "Expire due venue holds and send coordinator reminders."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true", help="Keep processing periodically.")
        parser.add_argument("--interval", type=int, default=60, help="Seconds between checks.")

    def handle(self, *args, **options):
        interval = options["interval"]
        if interval < 1:
            raise CommandError("The interval must be at least one second.")

        try:
            while True:
                if options["watch"]:
                    close_old_connections()
                expired, reminded = process_holds()
                if expired or reminded or not options["watch"]:
                    self.stdout.write(f"Expired {expired} hold(s), sent {reminded} reminder(s).")
                if not options["watch"]:
                    return
                sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("Venue hold processing stopped.")
