from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import LoginSerializer, UserSerializer
from apps.core.audit import record, record_denied


@method_decorator(ensure_csrf_cookie, name="get")
class CsrfView(APIView):
    """The SPA calls this once on start-up to obtain the CSRF cookie."""

    permission_classes = [AllowAny]

    def get(self, _request):
        return Response({"detail": "CSRF cookie set"})


def stored_email(email: str) -> str:
    """The account's email as stored, matched without regard to case.

    Email addresses are compared case-insensitively (account updates already
    refuse a case-only duplicate), so ``Organiser@Acme.example`` signs in to
    ``organiser@acme.example``. Unknown addresses are returned unchanged and
    fail authentication with the usual message.
    """
    from apps.accounts.models import User

    matches = list(User.objects.filter(email__iexact=email).values_list("email", flat=True)[:2])
    return matches[0] if len(matches) == 1 else email


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user = authenticate(
            request,
            username=stored_email(email),
            password=serializer.validated_data["password"],
        )
        if user is None:
            # US-01.1 AC3 - refuse without revealing which field was wrong.
            record_denied(
                None, action="POST /api/auth/login/", detail=f"failed sign-in for {email}"
            )
            return Response(
                {"detail": "Those sign-in details were not recognised."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        login(request, user)
        record(user, action="POST /api/auth/login/", allowed=True)
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        record(request.user, action="POST /api/auth/logout/", allowed=True)
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """GET the signed-in user's account (SCRUM-2 AC1); PATCH their contact details."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        from apps.accounts.account import (
            EDITABLE_FIELDS,
            AccountChangeRefused,
            AccountDetailsInvalid,
            update_own_details,
        )

        try:
            user, changed = update_own_details(
                request.user, request.data, action="PATCH /api/auth/me/"
            )
        except AccountChangeRefused as exc:
            return Response(
                {
                    "detail": "You can only change your own name and email address here.",
                    "refused_fields": exc.fields,
                    "editable_fields": list(EDITABLE_FIELDS),
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        except AccountDetailsInvalid as exc:
            return Response(
                {
                    "detail": "Some details are missing or invalid.",
                    "missing_fields": [
                        f for f, m in exc.errors.items() if m.endswith("is required.")
                    ],
                    **{field: [message] for field, message in exc.errors.items()},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({**UserSerializer(user).data, "changed_fields": changed})
