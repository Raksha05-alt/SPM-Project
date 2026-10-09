from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import AccountUpdateSerializer, LoginSerializer, UserSerializer
from apps.core.audit import record, record_denied


@method_decorator(ensure_csrf_cookie, name="get")
class CsrfView(APIView):
    """The SPA calls this once on start-up to obtain the CSRF cookie."""

    permission_classes = [AllowAny]

    def get(self, _request):
        return Response({"detail": "CSRF cookie set"})


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user = authenticate(
            request,
            username=email,
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
    permission_classes = [IsAuthenticated]

    # SCRUM-2 AC3 - a user may never change who they are to the system.
    PROTECTED_FIELDS = ("role", "organisation", "is_staff", "is_superuser", "is_active")

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        """SCRUM-2 - update my own contact details."""
        user = request.user
        attempted = [field for field in self.PROTECTED_FIELDS if field in request.data]
        if attempted:
            record_denied(
                user,
                action="PATCH /api/auth/me/",
                obj=user,
                detail=f"attempted to change {', '.join(attempted)}",
            )
            return Response(
                {"detail": "You cannot change your own role or organisation."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = AccountUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        record(user, action="PATCH /api/auth/me/", allowed=True, obj=user)
        return Response(UserSerializer(user).data)
