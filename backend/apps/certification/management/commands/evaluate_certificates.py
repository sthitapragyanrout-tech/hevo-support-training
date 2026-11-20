"""Check everyone on courses with a certificate switched on, and issue any that are earned.

Certificates are normally issued the moment something changes; this is for back-filling (after
switching certificates on by hand in the database, restoring a backup, or a failed check).
It never revokes anything.

    manage.py evaluate_certificates                 every course with certificates on
    manage.py evaluate_certificates --course <slug> one course
"""

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import Course
from apps.certification import services
from apps.certification.models import CertificatePolicy


class Command(BaseCommand):
    help = "Issue certificates that have been earned but not yet issued."

    def add_arguments(self, parser):
        parser.add_argument("--course", help="Only this course (its slug).")

    def handle(self, *args, course=None, **options):
        policies = CertificatePolicy.objects.filter(enabled=True).select_related("course")
        if course:
            if not Course.objects.filter(slug=course).exists():
                raise CommandError(f"No course with the slug {course!r}.")
            policies = policies.filter(course__slug=course)
        total = 0
        for policy in policies:
            issued = services.evaluate_course(policy.course_id)
            total += issued
            self.stdout.write(f"{policy.course.slug}: {issued} issued")
        self.stdout.write(self.style.SUCCESS(f"{total} certificate(s) issued."))
