from rest_framework import serializers

from apps.accounts.models import Role, User


class UserSerializer(serializers.ModelSerializer):
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    organisation_name = serializers.CharField(
        source="organisation.name", read_only=True, default=None
    )
    landing_path = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "role_label",
            "organisation",
            "organisation_name",
            "landing_path",
        ]
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class RoleSerializer(serializers.Serializer):
    value = serializers.ChoiceField(choices=Role.choices)
    label = serializers.CharField()
