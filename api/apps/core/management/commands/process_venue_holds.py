"""Week 7 change 4 - warn coordinators about holds that will expire soon, and expire
holds that are past their deadline.

Schedule it every few minutes (cron, or a platform scheduler):

    */5 * * * *  cd api && python manage.py process_venue_holds

It is safe to run at any time and as often as you like. The API also runs the
same step before showing bookings, so a late schedule never leaves an expired
hold looking current.
"""

from django.core.management.base import BaseCommand

from apps.venues.bookings import process_holds


class Command(BaseCommand):
    help = "Expire tentative venue holds past their deadline and warn about ones expiring soon."

    def handle(self, *args, **options):
        result = process_holds()
        self.stdout.write(
            self.style.SUCCESS(
                f"Expired {result['expired']} hold(s); warned about {result['warned']}."
            )
        )
