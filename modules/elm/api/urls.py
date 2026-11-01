from django.urls import path

from modules.elm.api.views import (
    LeaveApplicationListView,
    LeaveBalanceListView,
    LeaveTypeListView,
    ProcessCancellationDecisionAPIView,
    RequestLeaveCancellationAPIView,
    SubstituteNomineeListView,
    WithdrawLeaveAPIView,
)

urlpatterns = [
    path('leave-types/', LeaveTypeListView.as_view(), name='leave-type-list'),
    path('leave-balances/', LeaveBalanceListView.as_view(), name='leave-balance-list'),
    path('leave-applications/', LeaveApplicationListView.as_view(), name='leave-application-list'),
    path(
        'substitute-nominees/',
        SubstituteNomineeListView.as_view(),
        name='substitute-nominee-list'
    ),
    path(
        'leave/<int:application_id>/withdraw/',
        WithdrawLeaveAPIView.as_view(),
        name='leave-withdraw'
    ),
    path(
        'leave/<int:application_id>/cancel/',
        RequestLeaveCancellationAPIView.as_view(),
        name='leave-cancel'
    ),
    path(
        'leave/<int:application_id>/cancel/decision/',
        ProcessCancellationDecisionAPIView.as_view(),
        name='leave-cancel-decision'
    ),
]
