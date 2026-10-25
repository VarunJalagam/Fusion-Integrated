from datetime import date

from django.test import TestCase

from modules.directory.models import UserRef
from modules.elm.models import LeaveApplication, LeaveType, LeaveBalance, SubstituteNominee
from modules.elm.services.leave_application_service import (
    create_leave_application,
    respond_to_substitute_request,
    nominate_replacement_substitute,
)


class TestLeaveWorkflow(TestCase):
    def setUp(self):
        # Create UserRef objects using their actual fields (user_id is the PK)
        self.applicant = UserRef.objects.create(
            user_id=1001,
            username="applicant",
            display_name="Test Applicant",
            kind="staff",
            is_active=True
        )
        self.substitute = UserRef.objects.create(
            user_id=1002,
            username="substitute",
            display_name="Test Substitute",
            kind="staff",
            is_active=True
        )
        self.new_substitute = UserRef.objects.create(
            user_id=1003,
            username="new_substitute",
            display_name="Test New Substitute",
            kind="staff",
            is_active=True
        )
        
        self.leave_type = LeaveType.objects.create(code="CL", label="Casual Leave")
        self.leave_balance = LeaveBalance.objects.create(
            user=self.applicant, 
            leave_type=self.leave_type, 
            balance=8.0
        )

    def test_substitute_decline_and_replacement_workflow(self):
        # 1. Create Application
        application = create_leave_application(
            user=self.applicant,
            leave_type=self.leave_type,
            start_date=date(2023, 10, 1),
            end_date=date(2023, 10, 2),
            is_half_day=False,
            current_balance=8.0,
            existing_leaves=[],
            substitute_user_id=self.substitute.user_id,
        )
        self.assertEqual(application.status, LeaveApplication.Status.AWAITING_SUBSTITUTE_RESPONSE)
        self.assertEqual(SubstituteNominee.objects.filter(status=SubstituteNominee.NominationStatus.PENDING).count(), 1)
        
        # Refresh from DB to check balance (proves BR-EL-023: no deduction at creation)
        self.leave_balance.refresh_from_db()
        self.assertEqual(self.leave_balance.balance, 8.0)

        # 2. Substitute Declines
        nominee = application.substitutenominee_set.first()
        response = respond_to_substitute_request(
            nominee_id=nominee.id,
            user_id=self.substitute.user_id,
            response='declined',
        )
        self.assertTrue(response["success"])
        nominee.refresh_from_db()
        self.assertEqual(nominee.status, SubstituteNominee.NominationStatus.DECLINED)
        application.refresh_from_db()
        self.assertEqual(application.status, LeaveApplication.Status.APPLICANT_ACTION_REQUIRED)

        # 3. Nominate Replacement
        response = nominate_replacement_substitute(
            application_id=application.id,
            applicant_user_id=self.applicant.user_id,
            new_substitute_user_id=self.new_substitute.user_id,
        )
        self.assertTrue(response["success"])
        application.refresh_from_db()
        self.assertEqual(application.status, LeaveApplication.Status.AWAITING_SUBSTITUTE_RESPONSE)
        self.assertEqual(SubstituteNominee.objects.count(), 2)

        # 4. Replacement Accepts
        new_nominee = application.substitutenominee_set.filter(
            status=SubstituteNominee.NominationStatus.PENDING
        ).first()
        response = respond_to_substitute_request(
            nominee_id=new_nominee.id,
            user_id=self.new_substitute.user_id,
            response='accepted',
        )
        self.assertTrue(response["success"])
        application.refresh_from_db()
        self.assertEqual(application.status, LeaveApplication.Status.AWAITING_UNIT_HEAD_REVIEW)
