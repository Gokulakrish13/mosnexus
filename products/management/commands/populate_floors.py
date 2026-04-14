# pylint: disable=missing-class-docstring,unused-variable
from products.models import Floor, Stream

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Populate default floor options for all streams"

    def add_arguments(self, parser):
        parser.add_argument(
            "--stream",
            type=str,
            help="Populate floors for specific stream only",
        )

    def handle(self, *args, **options):
        floors = [
            ("Ground Floor", "Ground level of the building"),
            ("1st Floor", "First floor"),
            ("2nd Floor", "Second floor"),
            ("3rd Floor", "Third floor"),
            ("4th Floor", "Fourth floor"),
            ("5th Floor", "Fifth floor"),
            ("Basement", "Basement level"),
            ("Mezzanine", "Mezzanine level"),
        ]

        if options["stream"]:
            try:
                streams = [Stream.objects.get(name=options["stream"])]
                self.stdout.write(f'Populating floors for {options["stream"]} stream only...')
            except Stream.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Stream "{options["stream"]}" does not exist'))
                return
        else:
            streams = Stream.objects.all()
            self.stdout.write("Populating floors for all streams...")

        if not streams:
            self.stdout.write(self.style.ERROR("No streams found. Please create streams first."))
            return

        total_created = 0
        for stream in streams:
            self.stdout.write(f"\nProcessing {stream.name} stream:")

            for floor_name, description in floors:
                floor, created = Floor.objects.get_or_create(
                    name=floor_name, stream=stream, defaults={"description": description, "is_active": True}
                )
                if created:
                    total_created += 1
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Created floor: {floor_name}"))
                else:
                    self.stdout.write(self.style.WARNING(f"  - Floor already exists: {floor_name}"))

        self.stdout.write(self.style.SUCCESS(f"\nSuccessfully populated floors! Created {total_created} new floors."))
