"""
Business Rule (BR) test suite for File Tracking System (FTS).
Generated from BR_DESIGN.json.
Strategy: br
"""
import uuid

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from conftest import make_session
from modules.fts.models import (
    FtsAuditLog,
    FtsFile,
    FtsFileAttachment,
    FtsFileComment,
    FtsFileMovement,
)
from modules.fts.services.file_archival import archive_file_service
from modules.fts.services.file_creation import (
    create_file_service,
    discard_draft_service,
    edit_draft_service,
)
from modules.fts.services.file_movement import forward_file_service

pytestmark = pytest.mark.django_db


def _get_auth_client(
    stub_iam,
    user_id=None,
    active_role="faculty",
    roles=("faculty",),
    kind="faculty",
):
    uid = user_id or uuid.uuid4()
    session = make_session(
        user_id=uid,
        kind=kind,
        active_role=active_role,
        roles=roles,
    )
    stub_iam(session)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token mock-auth-token")
    return client, uid


def test_tc_br001_01_system_admin_restricted_from_operational_actions(stub_iam):
    """
    Test ID: TC-BR001-01
    Source ID: BR-FTS-001
    Purpose: Verify that only Institute Employees can perform operational file actions,
             and System Admins are restricted from routine file processing.
    Preconditions: User A is logged in as System Admin. User B is logged in as Institute
                   Employee (Faculty).
    Action/Input: User A attempts to create a new file. User B attempts to create a new
                  file with a valid comment.
    Expected Result: User A's request is denied or the create option is unavailable.
                     User B successfully creates the file.
    Test Type: Authorization
    """
    pytest.skip(
        "NOT_AUTOMATED: System Admin operational action restrictions (BR-FTS-001) are not "
        "implemented in the available FTS interfaces."
    )


def test_tc_br002_01_role_switch_preserves_ownership_and_audit(stub_iam):
    """
    Test ID: TC-BR002-01
    Source ID: BR-FTS-002
    Purpose: Verify that switching role context does not alter file ownership or audit history.
    Preconditions: User A is an Institute Employee with two roles: Role X and Role Y. User A
                   creates File F while acting as Role X.
    Action/Input: User A switches context to Role Y. User A views File F details and audit log.
    Expected Result: File F owner remains User A (associated with Role X creation context).
                     Audit log shows creation by User A under Role X, unchanged by the switch.
    Test Type: Constraint
    """
    user_a_id = uuid.uuid4()
    client, _ = _get_auth_client(
        stub_iam,
        user_id=user_a_id,
        active_role="faculty",
        roles=("faculty", "dean_academics"),
        kind="faculty",
    )
    payload = {"initial_comment": "Created under Role X"}
    res = client.post("/api/fts/v1/", payload, format="json")
    assert res.status_code == status.HTTP_201_CREATED
    file_id = res.json()["id"]

    # Switch context to Role Y
    _get_auth_client(
        stub_iam,
        user_id=user_a_id,
        active_role="dean_academics",
        roles=("faculty", "dean_academics"),
        kind="staff",
    )

    file_obj = FtsFile.objects.get(id=file_id)
    assert file_obj.owner_id == user_a_id

    audit_entry = FtsAuditLog.objects.get(file_id=str(file_id), action="CREATE")
    assert audit_entry.actor_id == user_a_id


def test_tc_br003_01_circulated_files_persist_and_cannot_be_deleted(stub_iam):
    """
    Test ID: TC-BR003-01
    Source ID: BR-FTS-003
    Purpose: Verify that circulated files persist with all comments and attachments, and
             cannot be deleted like drafts.
    Preconditions: User A creates File F with Comment C1 and Attachment A1. User A forwards
                   File F to User B with Comment C2.
    Action/Input: User A attempts to delete File F. User B views File F.
    Expected Result: Deletion is blocked or not permitted for circulated files. User B sees
                     File F containing C1, A1, and movement record with C2.
    Test Type: Data/Lifecycle Constraint
    """
    client_a, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(
        actor_id=str(user_a_id),
        initial_comment="Comment C1",
        attachment_urls=["https://documents.fusion.edu/attachment_a1.pdf"],
    )
    forward_file_service(
        actor_id=str(user_a_id),
        file_id=str(file_obj.id),
        receiver_id=str(user_b_id),
        movement_comment="Comment C2",
    )

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"

    # User A attempts to delete circulated file
    response = client_a.delete(f"/api/fts/v1/{file_obj.id}/discard/")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in response.json()

    # Verify file, initial comment C1, attachment A1, and movement C2 persist
    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"
    assert FtsFileComment.objects.filter(file_id=str(file_obj.id), text="Comment C1").exists()
    assert FtsFileAttachment.objects.filter(
        file_id=str(file_obj.id),
        file_url="https://documents.fusion.edu/attachment_a1.pdf",
    ).exists()
    assert FtsFileMovement.objects.filter(
        file_id=file_obj.id,
        sender_id=user_a_id,
        receiver_id=user_b_id,
        comment="Comment C2",
    ).exists()


def test_tc_br004_01_creation_blocked_without_mandatory_comment(stub_iam):
    """
    Test ID: TC-BR004-01
    Source ID: BR-FTS-004
    Purpose: Verify that file creation is blocked without an initial mandatory comment.
    Preconditions: User A is logged in as Institute Employee.
    Action/Input: User A attempts to save/create a new file with an empty comment field.
    Expected Result: System rejects the creation request with a validation error indicating
                     missing comment.
    Test Type: Validation
    """
    client, user_a_id = _get_auth_client(stub_iam)
    payload = {"initial_comment": ""}
    response = client.post("/api/fts/v1/", payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "initial_comment" in response.json()
    assert not FtsFile.objects.filter(owner_id=user_a_id).exists()


def test_tc_br005_01_draft_operations_prohibited_after_circulation(stub_iam):
    """
    Test ID: TC-BR005-01
    Source ID: BR-FTS-005
    Purpose: Verify that draft operations (edit/discard) are allowed before submission but
             prohibited after circulation.
    Preconditions: User A creates Draft D1. User A submits/forwards Draft D1 to User B.
    Action/Input: User A attempts to discard Draft D1 after submission.
    Expected Result: Discard action is blocked because the file is no longer in draft state.
    Test Type: Lifecycle Constraint
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft D1")

    # Draft edit allowed before circulation
    edit_draft_service(str(user_a_id), str(file_obj.id), "Updated before submit")

    # Submit / forward to User B
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Submitting D1")
    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"

    # Attempt to discard after circulation
    with pytest.raises(ValueError, match=r"Can only discard a draft file\."):
        discard_draft_service(str(user_a_id), str(file_obj.id))

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"


def test_tc_br006_01_forward_blocked_without_mandatory_comment(stub_iam):
    """
    Test ID: TC-BR006-01
    Source ID: BR-FTS-006
    Purpose: Verify that forwarding a file is blocked without a mandatory movement comment.
    Preconditions: User A has received File F. User B is a valid recipient.
    Action/Input: User A attempts to forward File F to User B with an empty comment field.
    Expected Result: System rejects the forward request with a validation error indicating
                     missing comment.
    Test Type: Validation
    """
    client, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial file")

    payload = {
        "receiver_id": str(user_b_id),
        "movement_comment": "",
    }
    response = client.post(f"/api/fts/v1/{file_obj.id}/forward/", payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "movement_comment" in response.json()

    file_obj.refresh_from_db()
    assert file_obj.status == "DRAFT"
    assert file_obj.current_holder_id == user_a_id


def test_tc_br007_01_return_file_to_sender(stub_iam):
    """
    Test ID: TC-BR007-01
    Source ID: BR-FTS-007
    Purpose: Verify that a file can be returned to the sender by the current holder.
    Preconditions: User A forwarded File F to User B. User B has received File F.
    Action/Input: User B selects 'Return' on File F with a mandatory comment.
    Expected Result: File F is returned to User A's Inbox. A movement record is created
                     indicating return from User B to User A.
    Test Type: Eligibility/Routing
    """
    from modules.fts.services.file_movement import return_file_service

    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "BR-007 return test")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "BR-007 forward")

    # User B returns the file to User A
    return_file_service(
        actor_id=str(user_b_id),
        file_id=str(file_obj.id),
        movement_comment="BR-007 returning to sender",
    )

    file_obj.refresh_from_db()
    assert file_obj.current_holder_id == user_a_id
    assert file_obj.status == "CIRCULATED"

    # Movement record indicates return from B to A
    movement = FtsFileMovement.objects.filter(
        file_id=file_obj.id, movement_type="RETURN"
    ).first()
    assert movement is not None
    assert movement.sender_id == user_b_id
    assert movement.receiver_id == user_a_id
    assert movement.comment == "BR-007 returning to sender"


def test_tc_br008_01_forwarding_events_recorded_chronologically(stub_iam):
    """
    Test ID: TC-BR008-01
    Source ID: BR-FTS-008
    Purpose: Verify that forwarding events are recorded chronologically with all required details.
    Preconditions: File F exists. User A forwards File F to User B with Comment C and
                   Attachment Att.
    Action/Input: View the movement history of File F.
    Expected Result: History contains a record with Sender=User A, Receiver=User B,
                     Timestamp=Now, Comment=C, Attachment=Att. Records are ordered chronologically.
    Test Type: Audit/Record Constraint
    """
    from modules.fts.selectors.file_queries import get_file_history

    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()

    file_obj = create_file_service(
        actor_id=str(user_a_id),
        initial_comment="BR-008 initial",
        attachment_urls=["https://documents.fusion.edu/br008.pdf"],
    )
    forward_file_service(
        actor_id=str(user_a_id),
        file_id=str(file_obj.id),
        receiver_id=str(user_b_id),
        movement_comment="BR-008 forward comment",
    )

    # View movement history
    history = get_file_history(actor_id=str(user_a_id), file_id=str(file_obj.id))

    assert len(history) >= 2  # CREATE + FORWARD

    # Verify forward event details
    forward_events = [e for e in history if e.get("action") == "FORWARD"]
    assert len(forward_events) >= 1
    fwd = forward_events[0]
    assert fwd["sender_id"] == str(user_a_id)
    assert fwd["receiver_id"] == str(user_b_id)
    assert fwd["comment"] == "BR-008 forward comment"

    # Verify chronological ordering
    timestamps = [entry["created_at"] for entry in history]
    assert timestamps == sorted(timestamps)


def test_tc_br009_01_unauthorized_users_cannot_access_files(stub_iam):
    """
    Test ID: TC-BR009-01
    Source ID: BR-FTS-009
    Purpose: Verify that unauthorized users cannot access files they are not associated with.
    Preconditions: User A owns File F. User B is an Institute Employee not associated with File F.
    Action/Input: User B attempts to view File F via direct ID access or search.
    Expected Result: Access is denied; File F is not visible in User B's Inbox/Outbox or search
                     results.
    Test Type: Authorization
    """
    from modules.fts.selectors.file_queries import (
        get_file_detail,
        get_inbox_files,
        get_outbox_files,
    )

    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    user_c_id = uuid.uuid4()  # Unauthorized user

    # User A creates and sends file to B (C is not associated)
    file_obj = create_file_service(str(user_a_id), "BR-009 access control")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "A to B")

    # User C cannot view file detail
    with pytest.raises(Exception):
        get_file_detail(actor_id=str(user_c_id), file_id=str(file_obj.id))

    # User C's inbox does not contain the file
    inbox_c = get_inbox_files(actor_id=str(user_c_id))
    inbox_c_ids = [str(f["id"]) for f in inbox_c]
    assert str(file_obj.id) not in inbox_c_ids

    # User C's outbox does not contain the file
    outbox_c = get_outbox_files(actor_id=str(user_c_id))
    outbox_c_ids = [str(f["id"]) for f in outbox_c]
    assert str(file_obj.id) not in outbox_c_ids


def test_tc_br010_01_sensitive_actions_restricted_for_archived_state(stub_iam):
    """
    Test ID: TC-BR010-01
    Source ID: BR-FTS-010
    Purpose: Verify that sensitive actions are restricted based on RBAC and file state.
    Preconditions: File F is archived. User A is the owner of File F.
    Action/Input: User A attempts to forward File F.
    Expected Result: Forward action is blocked because the file is in archived state.
    Test Type: Authorization
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial comment")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Circulating")
    archive_file_service(str(user_a_id), str(file_obj.id))

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"

    # Forward action blocked because file is archived
    with pytest.raises(ValueError, match=r"Cannot forward an archived or discarded file\."):
        forward_file_service(str(user_b_id), str(file_obj.id), str(user_a_id), "Try forward")

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"


def test_tc_br011_01_audit_logs_maintained_without_rewriting_history(stub_iam):
    """
    Test ID: TC-BR011-01
    Source ID: BR-FTS-011
    Purpose: Verify that audit logs are maintained for creation, comments, attachments,
             and archival without rewriting history.
    Preconditions: File F exists. User A adds a comment to File F. User A archives File F.
    Action/Input: Retrieve the audit log for File F.
    Expected Result: Log contains entries for creation, comment addition, and archival.
                     Previous entries remain unchanged and ordered chronologically.
    Test Type: Audit/Lifecycle
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(
        actor_id=str(user_a_id),
        initial_comment="Initial creation comment",
        attachment_urls=["https://documents.fusion.edu/att1.pdf"],
    )
    edit_draft_service(
        actor_id=str(user_a_id),
        file_id=str(file_obj.id),
        new_comment="Added edited comment",
        new_attachment_urls=["https://documents.fusion.edu/att2.pdf"],
    )
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Forwarding")
    archive_file_service(str(user_a_id), str(file_obj.id))

    logs = list(FtsAuditLog.objects.filter(file_id=str(file_obj.id)).order_by("created_at"))
    actions = [log.action for log in logs]
    assert "CREATE" in actions
    assert "EDIT_DRAFT" in actions
    assert "FORWARD" in actions
    assert "ARCHIVE" in actions

    # Entries remain ordered chronologically
    timestamps = [log.created_at for log in logs]
    assert timestamps == sorted(timestamps)


def test_tc_br012_01_only_owner_can_archive_and_becomes_read_only(stub_iam):
    """
    Test ID: TC-BR012-01
    Source ID: BR-FTS-012
    Purpose: Verify that only the file owner can archive a file, and archived files
             become read-only.
    Preconditions: User A owns File F. User B is a participant in File F but not the owner.
    Action/Input: User B attempts to archive File F. User A archives File F. User A attempts
                  to add a comment to archived File F.
    Expected Result: User B's archive request is denied. User A successfully archives File F.
                     Comment addition to archived File F is denied.
    Test Type: Lifecycle/Authorization
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial file")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Forward to B")

    # User B's archive request is denied
    with pytest.raises(ValueError, match=r"Only the file owner can archive the file\."):
        archive_file_service(str(user_b_id), str(file_obj.id))

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"

    # User A successfully archives
    archive_file_service(str(user_a_id), str(file_obj.id))
    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"

    # Comment addition to archived file is denied
    with pytest.raises(ValueError, match=r"Can only edit a draft file\."):
        edit_draft_service(str(user_a_id), str(file_obj.id), "Attempt to add comment to archived")


def test_tc_br013_01_notifications_triggered_for_lifecycle_events(stub_iam):
    """
    Test ID: TC-BR013-01
    Source ID: BR-FTS-013
    Purpose: Verify that notifications are triggered for file receipt, forwarding, return,
             and archival.
    Preconditions: User A forwards File F to User B.
    Action/Input: Check notification service/logs for User B.
    Expected Result: A notification event for 'File Received' is generated for User B.
    Test Type: Trigger/Scope Boundary
    """
    pytest.skip(
        "NOT_AUTOMATED: Notification service and event generation are not implemented in the "
        "available FTS backend."
    )


def test_tc_br014_01_cross_module_api_rbac_enforcement(stub_iam):
    """
    Test ID: TC-BR014-01
    Source ID: BR-FTS-014
    Purpose: Verify that FTS APIs enforce RBAC when accessed by other Fusion modules.
    Preconditions: External Module M invokes FTS API to forward File F. The user context
                   associated with Module M does not have permission to forward File F.
    Action/Input: Module M calls the FTS forward API for File F.
    Expected Result: FTS API returns an authorization error, denying the forward action.
    Test Type: Scope/Integration Constraint
    """
    pytest.skip(
        "NOT_AUTOMATED: Cross-module APIs and module-level RBAC integration are not implemented "
        "in modules/fts."
    )

