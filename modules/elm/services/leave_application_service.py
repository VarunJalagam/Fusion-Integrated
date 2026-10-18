from modules.elm.domain.validation import validate_leave_request
from modules.elm.models import LeaveApplication, LeaveBalance


def create_leave_application(
    user,
    leave_type,
    start_date,
    end_date,
    is_half_day,
    current_balance,
    existing_leaves,
    half=None
) -> LeaveApplication:
    is_valid, error_message = validate_leave_request(
        leave_type.code,
        start_date,
        end_date,
        is_half_day,
        current_balance,
        existing_leaves,
        half
    )

    if not is_valid:
        raise ValueError(error_message)

    application = LeaveApplication.objects.create(
        user=user,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        status="pending",
        reason=""
    )

    requested = 0.5 if is_half_day else (end_date - start_date).days + 1
    user_leave_balance = LeaveBalance.objects.get(user=user, leave_type=leave_type)
    user_leave_balance.balance -= requested
    user_leave_balance.save()

    return application
