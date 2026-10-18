from django.core.exceptions import ValidationError
from django.utils import timezone
from modules.elm.models import LeaveApplication, SubstituteNominee
from modules.elm.services import LeaveBalanceService

class LeaveApplicationService:
    @staticmethod
    def create_application(user, leave_type, start_date, end_date, purpose, substitute_id=None):
        if not user or not leave_type or not start_date or not end_date or not purpose:
            raise ValidationError("All fields are required")

        if start_date > end_date:
            raise ValidationError("Start date must be before end date")

        if substitute_id:
            try:
                substitute = SubstituteNominee.objects.get(user=substitute_id, leave_application__user=user)
            except SubstituteNominee.DoesNotExist:
                raise ValidationError("Invalid substitute nomination")

        application = LeaveApplication.objects.create(
            user=user,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            purpose=purpose,
            status='pending'
        )

        if substitute_id:
            SubstituteNominee.objects.create(
                leave_application=application,
                user=substitute_id,
                status='pending'
            )

        LeaveBalanceService.update_balance(user, leave_type, -1)

        return application

class SubstituteNomineeService:
    @staticmethod
    def create_nominee(leave_application, user):
        if not leave_application or not user:
            raise ValidationError("All fields are required")

        if leave_application.user == user:
            raise ValidationError("Cannot nominate oneself as substitute")

        if leave_application.status != 'pending':
            raise ValidationError("Cannot nominate for a non-pending application")

        if SubstituteNominee.objects.filter(leave_application=leave_application, user=user).exists():
            raise ValidationError("Substitute nomination already exists")

        return SubstituteNominee.objects.create(
            leave_application=leave_application,
            user=user,
            status='pending'
        )
