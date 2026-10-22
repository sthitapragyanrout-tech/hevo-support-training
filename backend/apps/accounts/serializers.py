from django.conf import settings
from rest_framework import serializers

from .models import Role, User
from .rbac import capabilities_for


class UserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()
    password_change_required = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "employee_id",
            "must_change_password",
            "password_change_required",
            "is_superuser",
            "roles",
            "capabilities",
        ]

    def get_password_change_required(self, obj: User) -> bool:
        """Whether the app should *force* a change now: the account is flagged
        and enforcement is switched on (`ENFORCE_PASSWORD_CHANGE`)."""
        return bool(settings.ENFORCE_PASSWORD_CHANGE and obj.must_change_password)

    def get_roles(self, obj: User) -> list[str]:
        return list(Role.objects.filter(assignments__user=obj).values_list("name", flat=True))

    def get_capabilities(self, obj: User) -> list[str]:
        return capabilities_for(obj)


class LoginSerializer(serializers.Serializer):
    # Accepts either username or email — resolved to the real username
    # before Django's own authenticate() is called (see views.LoginView).
    login = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)
