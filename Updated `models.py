from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from modules.elm.models import LeaveApplication, SubstituteNominee
from modules.elm.services import LeaveBalanceService

class LeaveType(models.Model):
    """Stores the different types of leaves available."""
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

class LeaveBalance(models.Model):
    """Tracks the leave balance for each user."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    balance = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user} - {self.leave_type}: {self.balance}"

class LeaveApplication(models.Model):
    """Stores the leave request details."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=50, choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending')
    reason = models.TextField()

    def __str__(self):
        return f"{self.user} - {self.leave_type}: {self.start_date} to {self.end_date}"

class SubstituteNominee(models.Model):
    """Stores the substitute nomination details."""
    leave_application = models.ForeignKey(LeaveApplication, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=50, choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending')

    def __str__(self):
        return f"{self.leave_application} - {self.user}"
