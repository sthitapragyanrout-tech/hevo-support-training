# Data migration for the 6-role -> 4-role collapse. `panel_member` and
# `function_head` are deleted outright: they carried zero permissions in
# ROLE_PERMISSIONS and, as of this migration, no real user held either via
# RoleAssignment (confirmed against the dev DB) — CASCADE on any that did
# exist would just drop that empty-permission assignment, not change
# anyone's effective access. `trainee` is renamed to `learner` in place
# (same row, same id) so existing RoleAssignment/FK relationships are
# untouched.

from django.db import migrations


def rename_and_prune(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(name="trainee").update(name="learner")
    Role.objects.filter(name__in=["panel_member", "function_head"]).delete()


def reverse(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(name="learner").update(name="trainee")
    # panel_member/function_head are not recreated: they carried no
    # permissions and no assignments, so there is nothing meaningful to
    # restore — re-add them by hand if the collapse is ever reverted.


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_alter_role_name"),
    ]

    operations = [
        migrations.RunPython(rename_and_prune, reverse),
    ]
