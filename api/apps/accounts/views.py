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

    def get(self, request):
        return Response(UserSerializer(request.user).data)
