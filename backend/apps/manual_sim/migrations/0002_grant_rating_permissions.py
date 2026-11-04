# Adds the two simulation permissions to the roles that should have them, once.
#
# Django creates `Permission` rows in a post-migrate step, *after* every migration has run, so
# a plain data migration would find nothing to grant. We create the rows here (the same helper
# Django uses) and then add them — additively — to the built-in roles that already exist.
# A fresh database gets the same grants from `seed_roles`. This runs once, so a permission an
# administrator later removes in the Console stays removed. Custom roles are never touched.

from django.contrib.auth.management import create_permissions
from django.db import migrations

GRANTS = {
    "mentor": ["rate_submissions"],
    "trainer": ["rate_submissions", "manage_reviews"],
    "admin": ["rate_submissions", "manage_reviews"],
}


def grant(apps, schema_editor):
    app_config = apps.get_app_config("manual_sim")
    app_config.models_module = True  # `create_permissions` skips apps without models
    try:
        create_permissions(app_config, apps=apps, verbosity=0)
    finally:
        app_config.models_module = None
    Permission = apps.get_model("auth", "Permission")
    Role = apps.get_model("accounts", "Role")
    for role_name, codenames in GRANTS.items():
        role = Role.objects.filter(name=role_name).first()
        if role is None:
            continue
        perms = Permission.objects.filter(
            content_type__app_label="manual_sim", codename__in=codenames
        )
        role.permissions.add(*perms)


def revoke(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Role = apps.get_model("accounts", "Role")
    perms = Permission.objects.filter(
        content_type__app_label="manual_sim",
        codename__in=["rate_submissions", "manage_reviews"],
    )
    for role in Role.objects.filter(name__in=list(GRANTS)):
        role.permissions.remove(*perms)


class Migration(migrations.Migration):
    dependencies = [
        ("manual_sim", "0001_initial"),
        ("accounts", "0005_role_label_and_custom_roles"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(grant, revoke)]
