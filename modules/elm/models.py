from django.db import models

from core.db.mixins import TimeStampedModel


class LeaveType(TimeStampedModel):
    """Represents different types of leaves available."""
    code = models.CharField(max_length=48, unique=True)
    label = models.CharField(max_length=80)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "elm_leave_type"
        ordering = ["label"]

    def __str__(self) -> str:
        return self.label


class LeaveBalance(TimeStampedModel):
    """Represents the balance of leaves for a user."""
    user = models.ForeignKey('directory.UserRef', on_delete=models.CASCADE)
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "elm_leave_balance"
        unique_together = ("user", "leave_type")
        ordering = ["user", "leave_type"]

    def __str__(self) -> str:
        return f"{self.user} - {self.leave_type}"


class LeaveApplication(TimeStampedModel):
    """Represents a leave application made by a user."""
    user = models.ForeignKey('directory.UserRef', on_delete=models.CASCADE)
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="pending",
    )
    reason = models.TextField()

    class Meta:
        db_table = "elm_leave_application"
        ordering = ["user", "start_date"]

    def __str__(self) -> str:
        return f"{self.user} - {self.leave_type} - {self.start_date} to {self.end_date}"


class SubstituteNominee(TimeStampedModel):
    """Represents a substitute nominee for a leave application."""
    leave_application = models.ForeignKey(LeaveApplication, on_delete=models.CASCADE)
    user = models.ForeignKey('directory.UserRef', on_delete=models.CASCADE)
    status = models.CharField(
        max_length=16,
        choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="pending",
    )

    class Meta:
        db_table = "elm_substitute_nominee"
        unique_together = ("leave_application", "user")
        ordering = ["leave_application", "user"]

    def __str__(self) -> str:
        return f"{self.leave_application} - {self.user}"
