from django.contrib.auth.models import AbstractUser, Permission
from django.db import models


class User(AbstractUser):
    """Custom user model — the SSO/identity seam lives in UserIdentity, not here.

    `username` is kept only because Django admin login and AbstractUser plumbing
    expect it; no application code should treat it as identity. Use `user.id`
    internally and `email` at integration boundaries (bot, outcome callbacks).
    """

    email = models.EmailField(unique=True)
    employee_id = models.CharField(max_length=32, unique=True, null=True, blank=True)
    must_change_password = models.BooleanField(default=True)
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")

    class Meta:
        permissions = [
            ("manage_users", "Can manage users (create/deactivate/reset password/assign roles)"),
        ]

    def __str__(self) -> str:
        return self.email or self.username


class UserIdentity(models.Model):
    """The SSO seam. Only `local` rows are written in V1; present from day one
    so adding Google/Okta later is an INSERT against a new provider value,
    never a User migration.
    """

    class Provider(models.TextChoices):
        LOCAL = "local", "Local"
        GOOGLE = "google", "Google"
        OKTA = "okta", "Okta"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="identities")
    provider = models.CharField(max_length=20, choices=Provider.choices)
    external_id = models.CharField(max_length=255)
    email = models.EmailField()

    class Meta:
        unique_together = [("provider", "external_id")]

    def __str__(self) -> str:
        return f"{self.provider}:{self.external_id}"


class Role(models.Model):
    """What a user can do. Permissions live directly on Role — not on a
    Django Group, which is reserved for isolation (which org-unit/team a
    user belongs to), a separate concern Role has nothing to do with.
    """

    class Name(models.TextChoices):
        """Collapsed from six roles to four (2026-09): `panel_member` and
        `function_head` carried zero permissions in ROLE_PERMISSIONS and
        were never assigned to a real user — their distinctions (rate *any*
        trainee vs. assigned-only; org-scoped admin vs. global) were always
        going to be a Group/relational-assignment difference on top of
        Mentor/Admin, not a separate capability set. See
        docs/architecture.md and the RBAC design discussion for the fuller
        reasoning. `trainee` renamed to `learner` to match.
        """

        LEARNER = "learner", "Learner"
        TRAINER = "trainer", "Trainer"
        MENTOR = "mentor", "Mentor"
        ADMIN = "admin", "Admin"

    # A stable key (`trainer`, `senior_support`). The four in `Name` are built
    # in and protected; administrators may add others (see admin_services).
    name = models.CharField(max_length=32, unique=True)
    # What people see. Blank for the built-ins, which use `Name`'s labels.
    label = models.CharField(max_length=64, blank=True)
    permissions = models.ManyToManyField(Permission, blank=True)

    class Meta:
        permissions = [
            ("manage_roles", "Can manage roles and role assignments"),
        ]

    @property
    def is_builtin(self) -> bool:
        return self.name in Role.Name.values

    @property
    def display_label(self) -> str:
        if self.label:
            return self.label
        try:
            return Role.Name(self.name).label
        except ValueError:
            return self.name.replace("_", " ").capitalize()

    def __str__(self) -> str:
        return self.display_label


class RoleAssignment(models.Model):
    """Lets a user hold a role. One row per (user, role) — a user can hold
    multiple roles; effective permissions are the union across all of them.

    A training-instance scope (this grant only applies to cohort X / course
    Y) used to live here as free-text `scope_type`/`scope_id` fields. Removed
    for now: unenforced, and `Program`/`Cohort` don't exist until the M2
    `enrollment` app. When they do, instance scoping should come back as its
    own proper FK-based field — a different axis from Role (what) and from
    Group-based isolation (which org-unit), not a replacement for either.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="role_assignments")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="assignments")

    class Meta:
        unique_together = [("user", "role")]

    def __str__(self) -> str:
        return f"{self.user} — {self.role}"
