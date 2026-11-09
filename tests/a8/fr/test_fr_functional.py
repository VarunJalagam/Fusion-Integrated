"""
Functional Requirement (FR) test suite for File Tracking System (FTS).
Generated from FR_DESIGN.json.
Strategy: fr
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
from modules.fts.services.file_creation import (
    create_file_service,
    edit_draft_service,
)
from modules.fts.services.file_movement import forward_file_service
from modules.fts.services.file_archival import archive_file_service

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


def test_tc_fts_001_create_file(stub_iam):
    """
    Test ID: TC-FTS-001
    Source ID: AFR-FTS-011, AFR-FTS-012, AFR-FTS-013
    Purpose: Verify creation of a new file with mandatory comment and optional attachment.
    Preconditions: User is logged in as an Institute Employee with an assigned role.
    Action/Input: Initiate file creation, enter a comment, attach a file, and save as draft.
    Expected Result: File is created in 'Draft' state with the comment and attachment associated.
    Test Type: Positive
    """
    client, user_id = _get_auth_client(stub_iam)
    payload = {
        "initial_comment": "Initial draft comment for file creation",
        "attachment_urls": ["https://documents.fusion.edu/spec.pdf"],
    }
    response = client.post("/api/fts/v1/", payload, format="json")
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    file_id = data["id"]
    assert data["status"] == "DRAFT"

    file_obj = FtsFile.objects.get(id=file_id)
    assert file_obj.status == "DRAFT"
    assert file_obj.owner_id == user_id
    assert file_obj.current_holder_id == user_id

    comment_obj = FtsFileComment.objects.get(file_id=str(file_id))
    assert comment_obj.text == "Initial draft comment for file creation"
    assert comment_obj.is_initial is True
    assert comment_obj.actor_id == user_id

    attachment_obj = FtsFileAttachment.objects.get(file_id=str(file_id))
    assert attachment_obj.file_url == "https://documents.fusion.edu/spec.pdf"
    assert attachment_obj.actor_id == user_id


def test_tc_fts_002_create_file_missing_comment_fails(stub_iam):
    """
    Test ID: TC-FTS-002
    Source ID: AFR-FTS-012
    Purpose: Verify that file creation fails without a mandatory comment.
    Preconditions: User is logged in as an Institute Employee with an assigned role.
    Action/Input: Initiate file creation, leave comment field empty, attempt to save.
    Expected Result: System prevents saving and displays a validation error for missing comment.
    Test Type: Negative
    """
    client, user_id = _get_auth_client(stub_iam)
    payload = {
        "initial_comment": "",
        "attachment_urls": ["https://documents.fusion.edu/spec.pdf"],
    }
    response = client.post("/api/fts/v1/", payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert "initial_comment" in data
    assert not FtsFile.objects.filter(owner_id=user_id).exists()


def test_tc_fts_003_edit_saved_draft_file(stub_iam):
    """
    Test ID: TC-FTS-003
    Source ID: AFR-FTS-014, AFR-FTS-015
    Purpose: Verify editing a saved draft file.
    Preconditions: A draft file exists created by the logged-in user.
    Action/Input: Open the draft file, modify the comment or add an attachment, and save.
    Expected Result: Draft file is updated with the new content.
    Test Type: Positive
    """
    _, user_id = _get_auth_client(stub_iam)
    file_obj = create_file_service(
        actor_id=str(user_id),
        initial_comment="Original draft comment",
        attachment_urls=["https://documents.fusion.edu/orig.pdf"],
    )
    new_comment = "Updated draft comment content"
    new_attachments = ["https://documents.fusion.edu/updated.pdf"]

    edit_draft_service(
        actor_id=str(user_id),
        file_id=str(file_obj.id),
        new_comment=new_comment,
        new_attachment_urls=new_attachments,
    )
    file_obj.refresh_from_db()
    assert file_obj.status == "DRAFT"

    updated_comment = FtsFileComment.objects.get(file_id=str(file_obj.id), is_initial=True)
    assert updated_comment.text == new_comment

    updated_attachment = FtsFileAttachment.objects.get(file_id=str(file_obj.id))
    assert updated_attachment.file_url == "https://documents.fusion.edu/updated.pdf"


def test_tc_fts_004_discard_draft_file(stub_iam):
    """
    Test ID: TC-FTS-004
    Source ID: AFR-FTS-016
    Purpose: Verify discarding a draft file.
    Preconditions: A draft file exists created by the logged-in user.
    Action/Input: Select the draft file and choose the discard option.
    Expected Result: The draft file is removed from the user's list and no longer accessible.
    Test Type: Positive
    """
    client, user_id = _get_auth_client(stub_iam)
    file_obj = create_file_service(
        actor_id=str(user_id),
        initial_comment="Draft to discard",
    )
    response = client.delete(f"/api/fts/v1/{file_obj.id}/discard/")
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not FtsFile.objects.filter(id=file_obj.id).exists()
    assert not FtsFileComment.objects.filter(file_id=str(file_obj.id)).exists()


def test_tc_fts_005_submit_file_to_employee(stub_iam):
    """
    Test ID: TC-FTS-005
    Source ID: AFR-FTS-018, AFR-FTS-020, AFR-FTS-021, AFR-FTS-022, AFR-FTS-023
    Purpose: Verify submitting a file to another employee with mandatory comment and optional
             attachment.
    Preconditions: A valid file (draft or new) exists. Another Institute Employee exists in
                   the system.
    Action/Input: Submit the file to another employee, add a mandatory movement comment,
                  optionally add an attachment.
    Expected Result: File status changes to 'Circulated'. File appears in recipient's Inbox.
                     Movement is recorded.
    Test Type: Positive
    """
    client, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(
        actor_id=str(user_a_id),
        initial_comment="Draft file before submit",
    )
    payload = {
        "receiver_id": str(user_b_id),
        "movement_comment": "Please review and approve",
        "attachment_urls": ["https://documents.fusion.edu/submit.pdf"],
    }
    response = client.post(f"/api/fts/v1/{file_obj.id}/forward/", payload, format="json")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "CIRCULATED"
    assert data["current_holder_id"] == str(user_b_id)

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"
    assert file_obj.current_holder_id == user_b_id

    movement = FtsFileMovement.objects.get(file_id=file_obj.id)
    assert movement.sender_id == user_a_id
    assert movement.receiver_id == user_b_id
    assert movement.movement_type == "FORWARD"
    assert movement.comment == "Please review and approve"


def test_tc_fts_006_forward_or_return_fails_without_comment(stub_iam):
    """
    Test ID: TC-FTS-006
    Source ID: AFR-FTS-022
    Purpose: Verify that forwarding/returning a file fails without a mandatory comment.
    Preconditions: User has a received file in their Inbox.
    Action/Input: Attempt to forward or return the file without adding a comment.
    Expected Result: System prevents the action and displays a validation error.
    Test Type: Negative
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "First forward")

    client_b, _ = _get_auth_client(stub_iam, user_id=user_b_id)
    user_c_id = uuid.uuid4()

    # Attempt forward without comment
    fwd_payload = {"receiver_id": str(user_c_id), "movement_comment": ""}
    res_fwd = client_b.post(f"/api/fts/v1/{file_obj.id}/forward/", fwd_payload, format="json")
    assert res_fwd.status_code == status.HTTP_400_BAD_REQUEST
    assert "movement_comment" in res_fwd.json()

    # Attempt return without comment
    ret_payload = {"movement_comment": ""}
    res_ret = client_b.post(f"/api/fts/v1/{file_obj.id}/return/", ret_payload, format="json")
    assert res_ret.status_code == status.HTTP_400_BAD_REQUEST
    assert "movement_comment" in res_ret.json()


def test_tc_fts_007_forward_received_file_to_third_party(stub_iam):
    """
    Test ID: TC-FTS-007
    Source ID: AFR-FTS-024
    Purpose: Verify forwarding a received file to a third party.
    Preconditions: User has a received file in their Inbox. A third Institute Employee exists.
    Action/Input: Open the file from Inbox, forward it to a third employee with a mandatory comment.
    Expected Result: File moves to the third employee's Inbox. Original sender is notified if
                     applicable. History updated.
    Test Type: Positive
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    user_c_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Forwarding to B")

    client_b, _ = _get_auth_client(stub_iam, user_id=user_b_id)
    fwd_payload = {
        "receiver_id": str(user_c_id),
        "movement_comment": "Forwarding to third party employee C",
    }
    response = client_b.post(f"/api/fts/v1/{file_obj.id}/forward/", fwd_payload, format="json")
    assert response.status_code == status.HTTP_200_OK

    file_obj.refresh_from_db()
    assert file_obj.current_holder_id == user_c_id
    assert file_obj.status == "CIRCULATED"

    movements = list(FtsFileMovement.objects.filter(file_id=file_obj.id).order_by("created_at"))
    assert len(movements) == 2
    assert movements[1].sender_id == user_b_id
    assert movements[1].receiver_id == user_c_id
    assert movements[1].comment == "Forwarding to third party employee C"


def test_tc_fts_008_return_received_file_to_sender(stub_iam):
    """
    Test ID: TC-FTS-008
    Source ID: AFR-FTS-025
    Purpose: Verify returning a received file to the sender.
    Preconditions: User has a received file in their Inbox.
    Action/Input: Open the file from Inbox, select 'Return to Sender', add a mandatory comment.
    Expected Result: File returns to the previous sender's Inbox. Movement history records
                     the return.
    Test Type: Positive
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft for return test")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Forwarding to B")

    client_b, _ = _get_auth_client(stub_iam, user_id=user_b_id)
    ret_payload = {"movement_comment": "Returning file to original sender"}
    response = client_b.post(
        f"/api/fts/v1/{file_obj.id}/return/", ret_payload, format="json"
    )
    assert response.status_code == status.HTTP_200_OK

    file_obj.refresh_from_db()
    assert file_obj.current_holder_id == user_a_id
    assert file_obj.status == "CIRCULATED"

    movements = list(
        FtsFileMovement.objects.filter(file_id=file_obj.id).order_by("created_at")
    )
    assert len(movements) == 2
    assert movements[1].sender_id == user_b_id
    assert movements[1].receiver_id == user_a_id
    assert movements[1].movement_type == "RETURN"
    assert movements[1].comment == "Returning file to original sender"


def test_tc_fts_009_inbox_and_outbox_visibility(stub_iam):
    """
    Test ID: TC-FTS-009
    Source ID: AFR-FTS-029, AFR-FTS-030
    Purpose: Verify Inbox and Outbox visibility.
    Preconditions: User has sent at least one file and received at least one file.
    Action/Input: Navigate to Inbox and Outbox views.
    Expected Result: Inbox lists received files. Outbox lists sent files.
    Test Type: Positive
    """
    from modules.fts.selectors.file_queries import get_inbox_files, get_outbox_files

    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()

    # User A creates and sends a file to User B (appears in A's outbox, B's inbox)
    file_obj = create_file_service(str(user_a_id), "File for inbox/outbox test")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Sending to B")

    # User B creates and sends a file back to User A (appears in B's outbox, A's inbox)
    file_obj_2 = create_file_service(str(user_b_id), "Return file for visibility test")
    forward_file_service(str(user_b_id), str(file_obj_2.id), str(user_a_id), "Sending to A")

    # Verify User A's inbox contains file_obj_2 (received from B)
    inbox_a = get_inbox_files(actor_id=str(user_a_id))
    inbox_a_ids = [str(f["id"]) for f in inbox_a]
    assert str(file_obj_2.id) in inbox_a_ids

    # Verify User A's outbox contains file_obj (sent to B)
    outbox_a = get_outbox_files(actor_id=str(user_a_id))
    outbox_a_ids = [str(f["id"]) for f in outbox_a]
    assert str(file_obj.id) in outbox_a_ids


def test_tc_fts_010_open_files_from_inbox_and_outbox(stub_iam):
    """
    Test ID: TC-FTS-010
    Source ID: AFR-FTS-031, AFR-FTS-032
    Purpose: Verify opening files from Inbox and Outbox.
    Preconditions: User has files in Inbox and Outbox.
    Action/Input: Click on a file in Inbox and a file in Outbox.
    Expected Result: File details, comments, and attachments are displayed correctly for both.
    Test Type: Positive
    """
    from modules.fts.selectors.file_queries import get_file_detail

    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()

    # User A creates file with attachment and sends to B
    file_obj = create_file_service(
        actor_id=str(user_a_id),
        initial_comment="Detail view test comment",
        attachment_urls=["https://documents.fusion.edu/detail_test.pdf"],
    )
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Forward for detail")

    # User B opens the file from their Inbox (detail view)
    detail_b = get_file_detail(actor_id=str(user_b_id), file_id=str(file_obj.id))
    assert detail_b["id"] == str(file_obj.id)
    assert detail_b["status"] == "CIRCULATED"
    assert detail_b["current_holder_id"] == str(user_b_id)

    # User A opens the file from their Outbox (detail view)
    detail_a = get_file_detail(actor_id=str(user_a_id), file_id=str(file_obj.id))
    assert detail_a["id"] == str(file_obj.id)
    assert detail_a["owner_id"] == str(user_a_id)


def test_tc_fts_011_chronological_tracking_history_visibility(stub_iam):
    """
    Test ID: TC-FTS-011
    Source ID: AFR-FTS-035, AFR-FTS-036, AFR-FTS-037, AFR-FTS-038, AFR-FTS-039, AFR-FTS-040,
               AFR-FTS-041
    Purpose: Verify complete chronological tracking history visibility.
    Preconditions: A file has undergone multiple movements (creation, forward, return).
    Action/Input: View the tracking history of the file as an associated user.
    Expected Result: History displays all events chronologically with sender, receiver, timestamp,
                     comments, and attachments.
    Test Type: Positive
    """
    from modules.fts.selectors.file_queries import get_file_history
    from modules.fts.services.file_movement import return_file_service

    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()

    # Create file and forward to B
    file_obj = create_file_service(str(user_a_id), "History tracking test")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "First forward")

    # B returns to A
    return_file_service(str(user_b_id), str(file_obj.id), "Returning for history")

    # View history as User A (associated user)
    history = get_file_history(actor_id=str(user_a_id), file_id=str(file_obj.id))

    assert len(history) >= 3  # CREATE + FORWARD + RETURN

    # Verify chronological ordering
    timestamps = [entry["created_at"] for entry in history]
    assert timestamps == sorted(timestamps)

    # Verify forward event details
    forward_events = [e for e in history if e.get("action") == "FORWARD"]
    assert len(forward_events) >= 1
    assert forward_events[0]["sender_id"] == str(user_a_id)
    assert forward_events[0]["receiver_id"] == str(user_b_id)
    assert forward_events[0]["comment"] == "First forward"

    # Verify return event details
    return_events = [e for e in history if e.get("action") == "RETURN"]
    assert len(return_events) >= 1
    assert return_events[0]["sender_id"] == str(user_b_id)
    assert return_events[0]["receiver_id"] == str(user_a_id)
    assert return_events[0]["comment"] == "Returning for history"


def test_tc_fts_012_only_file_owner_can_archive(stub_iam):
    """
    Test ID: TC-FTS-012
    Source ID: AFR-FTS-042, AFR-FTS-043
    Purpose: Verify only file owner can archive a file.
    Preconditions: File is in 'Circulated' state. User A is the owner. User B is a non-owner
                   associated user.
    Action/Input: User B attempts to archive the file. User A attempts to archive the file.
    Expected Result: User B's action is blocked/denied. User A's action succeeds, changing
                     file state to 'Archived'.
    Test Type: Authorization/Negative
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Circulating file")

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"

    # User B (non-owner) attempts to archive
    client_b, _ = _get_auth_client(stub_iam, user_id=user_b_id)
    with pytest.raises(ValueError, match=r"Only the file owner can archive the file\."):
        client_b.post(f"/api/fts/v1/{file_obj.id}/archive/", {}, format="json")

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"

    # User A (owner) attempts to archive (re-install User A session)
    client_a, _ = _get_auth_client(stub_iam, user_id=user_a_id)
    res_a = client_a.post(f"/api/fts/v1/{file_obj.id}/archive/", {}, format="json")
    assert res_a.status_code == status.HTTP_200_OK

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"


def test_tc_fts_013_archived_file_readable_not_modifiable_or_forwardable(stub_iam):
    """
    Test ID: TC-FTS-013
    Source ID: AFR-FTS-045, AFR-FTS-046, AFR-FTS-047
    Purpose: Verify archived file is readable but not modifiable or forwardable.
    Preconditions: A file is in 'Archived' state.
    Action/Input: Attempt to edit the file. Attempt to forward the file. View the file.
    Expected Result: File is viewable. Edit and Forward actions are disabled or blocked.
    Test Type: Constraint
    """
    client, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Circulating")
    client.post(f"/api/fts/v1/{file_obj.id}/archive/", {}, format="json")

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"

    # File is readable / viewable
    read_file = FtsFile.objects.get(id=file_obj.id)
    assert read_file.status == "ARCHIVED"
    assert read_file.owner_id == user_a_id

    # Attempt to edit the archived file
    with pytest.raises(ValueError, match=r"Can only edit a draft file\."):
        edit_draft_service(str(user_a_id), str(file_obj.id), "New comment")

    # Attempt to forward the archived file (blocked for holder and non-holder alike)
    with pytest.raises(ValueError, match=r"Cannot forward an archived or discarded file\."):
        forward_file_service(str(user_b_id), str(file_obj.id), str(user_a_id), "Try forward")


def test_tc_fts_014_role_switching_preserves_ownership_and_audit(stub_iam):
    """
    Test ID: TC-FTS-014
    Source ID: AFR-FTS-009, AFR-FTS-010
    Purpose: Verify role switching preserves file ownership and audit identity.
    Preconditions: User has two roles (Role A and Role B). User created a file while acting
                   as Role A.
    Action/Input: Switch context to Role B. Check ownership of the previously created file.
    Expected Result: File remains owned by the user (associated with Role A context originally).
                     Audit log shows original creator identity.
    Test Type: Positive
    """
    user_id = uuid.uuid4()
    client, _ = _get_auth_client(
        stub_iam,
        user_id=user_id,
        active_role="faculty",
        roles=("faculty", "dean_academics"),
        kind="faculty",
    )
    payload = {"initial_comment": "Created as faculty role"}
    res = client.post("/api/fts/v1/", payload, format="json")
    assert res.status_code == status.HTTP_201_CREATED
    file_id = res.json()["id"]

    # Switch context to Role B
    _get_auth_client(
        stub_iam,
        user_id=user_id,
        active_role="dean_academics",
        roles=("faculty", "dean_academics"),
        kind="staff",
    )

    file_obj = FtsFile.objects.get(id=file_id)
    assert file_obj.owner_id == user_id

    audit_entry = FtsAuditLog.objects.get(file_id=str(file_id), action="CREATE")
    assert audit_entry.actor_id == user_id


def test_tc_fts_015_system_admin_cannot_perform_operational_file_actions(stub_iam):
    """
    Test ID: TC-FTS-015
    Source ID: AFR-FTS-006, AFR-FTS-007, AFR-FTS-008
    Purpose: Verify System Admin cannot perform operational file actions.
    Preconditions: User is logged in as System Admin.
    Action/Input: Attempt to create a file, forward a file, or archive a file.
    Expected Result: Actions are blocked or options are not available to System Admin.
    Test Type: Negative/Authorization
    """
    pytest.skip(
        "NOT_AUTOMATED: Restrictions preventing System Admin from operational file actions "
        "(AFR-FTS-006, AFR-FTS-007, AFR-FTS-008) are not implemented in the available FTS "
        "interfaces."
    )


def test_tc_fts_016_notifications_triggered_for_file_events(stub_iam):
    """
    Test ID: TC-FTS-016
    Source ID: AFR-FTS-061, AFR-FTS-062, AFR-FTS-063, AFR-FTS-064
    Purpose: Verify notifications are triggered for file events.
    Preconditions: Notification mechanism is mocked/integrated. Users are subscribed.
    Action/Input: Receive a file, forward a file, return a file, archive a file.
    Expected Result: Corresponding notifications are generated and handed to Fusion notification
                     mechanism for each event.
    Test Type: Integration
    """
    pytest.skip(
        "NOT_AUTOMATED: Notification mechanism is not implemented or integrated in the "
        "available FTS backend."
    )


def test_tc_fts_017_audit_logs_maintained_for_all_key_actions(stub_iam):
    """
    Test ID: TC-FTS-017
    Source ID: AFR-FTS-054, AFR-FTS-055, AFR-FTS-056, AFR-FTS-057, AFR-FTS-058, AFR-FTS-059
    Purpose: Verify audit logs are maintained for all key actions.
    Preconditions: Audit logging is enabled.
    Action/Input: Perform file creation, add comment, add attachment, forward, return, and archive.
    Expected Result: Audit log contains entries for each action with timestamps and user details.
    Test Type: Positive
    """
    from modules.fts.services.file_movement import return_file_service

    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()

    # Create file with comment and attachment
    file_obj = create_file_service(
        actor_id=str(user_a_id),
        initial_comment="Audit lifecycle comment",
        attachment_urls=["https://documents.fusion.edu/audit_test.pdf"],
    )

    # Edit draft (adds comment/attachment)
    edit_draft_service(
        actor_id=str(user_a_id),
        file_id=str(file_obj.id),
        new_comment="Edited for audit",
        new_attachment_urls=["https://documents.fusion.edu/audit_edited.pdf"],
    )

    # Forward to B
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Forward for audit")

    # Return to A
    return_file_service(str(user_b_id), str(file_obj.id), "Return for audit")

    # Archive
    archive_file_service(str(user_a_id), str(file_obj.id))

    # Verify audit log contains all actions
    logs = list(
        FtsAuditLog.objects.filter(file_id=str(file_obj.id)).order_by("created_at")
    )
    actions = [log.action for log in logs]

    assert "CREATE" in actions
    assert "EDIT_DRAFT" in actions
    assert "FORWARD" in actions
    assert "RETURN" in actions
    assert "ARCHIVE" in actions

    # Verify timestamps are chronological
    timestamps = [log.created_at for log in logs]
    assert timestamps == sorted(timestamps)

    # Verify actor IDs are recorded
    for log in logs:
        assert log.actor_id is not None


def test_tc_fts_018_fts_apis_exposed_for_other_modules(stub_iam):
    """
    Test ID: TC-FTS-018
    Source ID: AFR-FTS-067, AFR-FTS-068, AFR-FTS-069
    Purpose: Verify FTS APIs are exposed for other modules.
    Preconditions: API endpoints are deployed. Authenticated token from another module is available.
    Action/Input: Invoke API for workflow status, approval chain check, or request tracking.
    Expected Result: API responds with correct data within RBAC limits.
    Test Type: Integration
    """
    pytest.skip(
        "NOT_AUTOMATED: Cross-module APIs for workflow status, approval chain check, or request "
        "tracking are not implemented or exposed in modules/fts."
    )


def test_tc_fts_019_rbac_and_audit_controls_apply_to_api_integrations(stub_iam):
    """
    Test ID: TC-FTS-019
    Source ID: AFR-FTS-070, AFR-FTS-071
    Purpose: Verify RBAC and Audit controls apply to API integrations.
    Preconditions: API endpoint exists.
    Action/Input: Invoke API with unauthorized token/role. Invoke API and check audit log.
    Expected Result: Unauthorized access is denied. Action is recorded in audit log.
    Test Type: Security/Negative
    """
    pytest.skip(
        "NOT_AUTOMATED: Cross-module API integration endpoints and unauthorized audit logging "
        "are not implemented in modules/fts."
    )


def test_tc_fts_020_circulated_files_cannot_be_deleted(stub_iam):
    """
    Test ID: TC-FTS-020
    Source ID: AFR-FTS-017
    Purpose: Verify circulated files cannot be deleted.
    Preconditions: File is in 'Circulated' state.
    Action/Input: Attempt to delete the file via UI or API.
    Expected Result: Deletion is blocked. File remains in system.
    Test Type: Negative/Constraint
    """
    client_a, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Circulating")

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"

    response = client_a.delete(f"/api/fts/v1/{file_obj.id}/discard/")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in response.json()
    assert FtsFile.objects.filter(id=file_obj.id).exists()
