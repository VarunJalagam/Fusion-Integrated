from rest_framework import generics, permissions
from modules.elm.models import LeaveType, LeaveBalance, LeaveApplication, SubstituteNominee
from modules.elm.api.serializers import (
    LeaveTypeSerializer, LeaveBalanceSerializer,
    LeaveApplicationSerializer, SubstituteNomineeSerializer,
)

class LeaveTypeListView(generics.ListAPIView):
    queryset = LeaveType.objects.all()
    serializer_class = LeaveTypeSerializer
    permission_classes = [permissions.IsAuthenticated]

class LeaveBalanceListView(generics.ListAPIView):
    serializer_class = LeaveBalanceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return LeaveBalance.objects.filter(user=self.request.user)

class LeaveApplicationListView(generics.ListCreateAPIView):
    serializer_class = LeaveApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return LeaveApplication.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class SubstituteNomineeListView(generics.ListCreateAPIView):
    serializer_class = SubstituteNomineeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SubstituteNominee.objects.filter(leave_application__user=self.request.user)

    def perform_create(self, serializer):
        application = LeaveApplication.objects.get(
            user=self.request.user, id=self.request.data['leave_application']
        )
        serializer.save(leave_application=application)