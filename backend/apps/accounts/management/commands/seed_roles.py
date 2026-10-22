from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role
from apps.accounts.rbac import ROLE_PERMISSIONS


class Command(BaseCommand):
    help = "Seed the six Hevo roles and their permissions. Idempotent."

    @transaction.atomic
    def handle(self, *args, **options):
        for role_name in Role.Name.values:
            role, created = Role.objects.get_or_create(name=role_name)

            codenames = ROLE_PERMISSIONS.get(role_name, [])
            perms = []
            for codename in codenames:
                app_label, codename_only = codename.split(".", 1)
                try:
                    perms.append(
                        Permission.objects.get(
                            content_type__app_label=app_label, codename=codename_only
                        )
                    )
                except Permission.DoesNotExist:
                    self.stderr.write(
                        self.style.WARNING(
                            f"Permission '{codename}' not found — run migrate first? Skipping."
                        )
                    )
            role.permissions.set(perms)

            verb = "created" if created else "updated"
            self.stdout.write(self.style.SUCCESS(f"Role '{role_name}' {verb}."))
