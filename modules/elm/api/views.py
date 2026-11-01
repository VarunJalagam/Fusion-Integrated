from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.elm.api.serializers import (
    CancellationDecisionRequestSerializer,
    LeaveApplicationSerializer,
    LeaveBalanceSerializer,
    LeaveTypeSerializer,
    SubstituteNomineeSerializer,
)
from modules.elm.models import (
    LeaveApplication,
    LeaveBalance,
    LeaveType,
    SubstituteNominee,
)
from modules.elm.services.leave_application_service import (
    process_cancellation_decision,
    request_leave_cancellation,
    withdraw_pending_request,
)


def get_authenticated_user_id(request):
    """Resolve the directory/IAM user id from the authenticated user."""
    if hasattr(request.user, "user_id"):
        return request.user.user_id
    return request.user.id


class LeaveTypeListView(generics.ListAPIView):
    queryset = LeaveType.objects.all()
    serializer_class = LeaveTypeSerializer
    permission_classes = [permissions.IsAuthenticated]


class LeaveBalanceListView(generics.ListAPIView):
    queryset = LeaveBalance.objects.none()
    serializer_class = LeaveBalanceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        uid = get_authenticated_user_id(self.request)
        return LeaveBalance.objects.filter(user_id=uid)


class LeaveApplicationListView(generics.ListCreateAPIView):
    queryset = LeaveApplication.objects.none()
    serializer_class = LeaveApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        uid = get_authenticated_user_id(self.request)
        return LeaveApplication.objects.filter(user_id=uid)

    def perform_create(self, serializer):
        uid = get_authenticated_user_id(self.request)
        serializer.save(user_id=uid)


class SubstituteNomineeListView(generics.ListCreateAPIView):
    queryset = SubstituteNominee.objects.none()
    serializer_class = SubstituteNomineeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        uid = get_authenticated_user_id(self.request)
        return SubstituteNominee.objects.filter(
            leave_application__user_id=uid
        )

    def perform_create(self, serializer):
        uid = get_authenticated_user_id(self.request)
        app_id = self.request.data.get("leave_application")
        application = LeaveApplication.objects.get(
            id=app_id, user_id=uid
        )
        serializer.save(leave_application=application, user_id=uid)


class WithdrawLeaveAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: {"type": "object"}, 400: {"type": "object"}},
        tags=["elm"],
    )
    def post(self, request, application_id):
        uid = get_authenticated_user_id(request)
        result = withdraw_pending_request(application_id, uid)
        if result["success"]:
            return Response(result, status=status.HTTP_200_OK)
        return Response(result, status=status.HTTP_400_BAD_REQUEST)


class RequestLeaveCancellationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: {"type": "object"}, 400: {"type": "object"}},
        tags=["elm"],
    )
    def post(self, request, application_id):
        uid = get_authenticated_user_id(request)
        result = request_leave_cancellation(application_id, uid)
        if result["success"]:
            return Response(result, status=status.HTTP_200_OK)
        return Response(result, status=status.HTTP_400_BAD_REQUEST)


class ProcessCancellationDecisionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CancellationDecisionRequestSerializer,
        responses={200: {"type": "object"}, 400: {"type": "object"}},
        tags=["elm"],
    )
    def post(self, request, application_id):
        serializer = CancellationDecisionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        decision = serializer.validated_data["decision"]
        if decision not in ["approved", "rejected"]:
            return Response(
                {"success": False, "message": "Invalid decision"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        uid = get_authenticated_user_id(request)
        result = process_cancellation_decision(
            application_id, uid, decision
        )
        if result["success"]:
            return Response(result, status=status.HTTP_200_OK)
        return Response(result, status=status.HTTP_400_BAD_REQUEST)
