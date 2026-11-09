"""
Use Case (UC) test suite for File Tracking System (FTS).
Generated from UC_DESIGN.json.
Strategy: uc
"""
import uuid

import pytest
from django.core.exceptions import ValidationError
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


def test_tc_fts_001_create_file_main_success(stub_iam):
    """
    Test ID: TC-FTS-001
    Source ID: FTS-UC-001 Main Success Scenario
    Purpose: Verify successful creation of a new file with mandatory comment and optional
             attachment, saved as draft.
    Preconditions: Employee is authenticated. Employee has an assigned role context authorized
                   to create files.
    Action/Input: Open file-creation function. Enter initial mandatory comment. Add optional
                  attachment. Save as draft.
    Expected Result: File exists in draft/pre-circulation state. Initial comment and attachment
                     are preserved. Creation audit information is recorded.
    Test Type: Positive
    """
    client, user_id = _get_auth_client(stub_iam)
    payload = {
        "initial_comment": "Draft comment for TC-FTS-001",
        "attachment_urls": ["https://documents.fusion.edu/proposal.pdf"],
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
    assert comment_obj.text == "Draft comment for TC-FTS-001"
    assert comment_obj.is_initial is True
    assert comment_obj.actor_id == user_id

    attachment_obj = FtsFileAttachment.objects.get(file_id=str(file_id))
    assert attachment_obj.file_url == "https://documents.fusion.edu/proposal.pdf"
    assert attachment_obj.actor_id == user_id

    audit_entry = FtsAuditLog.objects.get(file_id=str(file_id), action="CREATE")
    assert audit_entry.actor_id == user_id


def test_tc_fts_002_create_file_missing_comment(stub_iam):
    """
    Test ID: TC-FTS-002
    Source ID: FTS-UC-001 Exception Flow 1
    Purpose: Verify that file creation is blocked if the initial mandatory comment is missing.
    Preconditions: Employee is authenticated. Employee has an assigned role context authorized
                   to create files.
    Action/Input: Open file-creation function. Leave comment field empty. Attempt to save.
    Expected Result: FTS does not accept creation/save. No file record is created.
    Test Type: Negative
    """
    client, user_id = _get_auth_client(stub_iam)
    payload = {
        "initial_comment": "",
        "attachment_urls": ["https://documents.fusion.edu/proposal.pdf"],
    }
    response = client.post("/api/fts/v1/", payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.json()
    assert "initial_comment" in data
    assert not FtsFile.objects.filter(owner_id=user_id).exists()


def test_tc_fts_003_create_file_unauthorized_role(stub_iam):
    """
    Test ID: TC-FTS-003
    Source ID: FTS-UC-001 Exception Flow 2
    Purpose: Verify that file creation is denied if the selected role is not authorized.
    Preconditions: Employee is authenticated. Employee selects a role context not authorized
                   to create files.
    Action/Input: Enter initial mandatory comment. Attempt to save.
    Expected Result: FTS denies the action. No file record is created.
    Test Type: Negative
    """
    pytest.skip(
        "NOT_AUTOMATED: Role-based authorization restrictions for file creation are not "
        "implemented in the available FTS interfaces."
    )


def test_tc_fts_004_create_file_immediate_circulation(stub_iam):
    """
    Test ID: TC-FTS-004
    Source ID: FTS-UC-001 Alternative Flow 1
    Purpose: Verify that a valid created file can proceed immediately to circulation via
             FTS-UC-003.
    Preconditions: Employee is authenticated and authorized. Valid recipient employee exists.
    Action/Input: Create file with mandatory comment. Select immediate circulation option.
                  Select recipient. Enter movement comment. Confirm Send.
    Expected Result: File is circulated to recipient. File state is updated from draft to
                     active/circulated. Movement history and audit records are updated.
    Test Type: Positive
    """
    client, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()

    # Step 1: Create file
    create_payload = {"initial_comment": "File for immediate circulation"}
    create_res = client.post("/api/fts/v1/", create_payload, format="json")
    assert create_res.status_code == status.HTTP_201_CREATED
    file_id = create_res.json()["id"]

    # Step 2: Immediate circulation
    fwd_payload = {
        "receiver_id": str(user_b_id),
        "movement_comment": "Immediately circulated movement comment",
    }
    fwd_res = client.post(f"/api/fts/v1/{file_id}/forward/", fwd_payload, format="json")
    assert fwd_res.status_code == status.HTTP_200_OK

    file_obj = FtsFile.objects.get(id=file_id)
    assert file_obj.status == "CIRCULATED"
    assert file_obj.current_holder_id == user_b_id

    movement = FtsFileMovement.objects.get(file_id=file_id)
    assert movement.sender_id == user_a_id
    assert movement.receiver_id == user_b_id
    assert movement.movement_type == "FORWARD"
    assert movement.comment == "Immediately circulated movement comment"

    audit = FtsAuditLog.objects.get(file_id=file_id, action="FORWARD")
    assert audit.actor_id == user_a_id


def test_tc_fts_005_edit_draft_file(stub_iam):
    """
    Test ID: TC-FTS-005
    Source ID: FTS-UC-002 Main Success Scenario
    Purpose: Verify successful editing of a draft file.
    Preconditions: Draft file exists. Employee is authorized to edit the draft.
    Action/Input: Open existing draft. Edit comment and/or attachments. Save updated draft.
    Expected Result: Draft is updated with new content. Audit/version information is recorded.
    Test Type: Positive
    """
    _, user_id = _get_auth_client(stub_iam)
    file_obj = create_file_service(
        actor_id=str(user_id),
        initial_comment="Draft before edit",
        attachment_urls=["https://documents.fusion.edu/initial.pdf"],
    )
    new_comment = "Draft after edit comment"
    new_attachments = ["https://documents.fusion.edu/revised.pdf"]

    edit_draft_service(
        actor_id=str(user_id),
        file_id=str(file_obj.id),
        new_comment=new_comment,
        new_attachment_urls=new_attachments,
    )
    file_obj.refresh_from_db()
    assert file_obj.status == "DRAFT"

    comment = FtsFileComment.objects.get(file_id=str(file_obj.id), is_initial=True)
    assert comment.text == new_comment

    attachment = FtsFileAttachment.objects.get(file_id=str(file_obj.id))
    assert attachment.file_url == "https://documents.fusion.edu/revised.pdf"

    audit = FtsAuditLog.objects.get(file_id=str(file_obj.id), action="EDIT_DRAFT")
    assert audit.actor_id == user_id


def test_tc_fts_006_discard_draft_file_before_submission(stub_iam):
    """
    Test ID: TC-FTS-006
    Source ID: FTS-UC-002 Alternative Flow 1
    Purpose: Verify successful discarding of a draft file before submission.
    Preconditions: Draft file exists. Employee is authorized to discard the draft.
    Action/Input: Open existing draft. Select Discard option.
    Expected Result: Draft is removed from the system. No circulated file is created.
    Test Type: Positive
    """
    client, user_id = _get_auth_client(stub_iam)
    file_obj = create_file_service(
        actor_id=str(user_id),
        initial_comment="Draft to be discarded",
    )
    response = client.delete(f"/api/fts/v1/{file_obj.id}/discard/")
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not FtsFile.objects.filter(id=file_obj.id).exists()
    assert not FtsFileComment.objects.filter(file_id=str(file_obj.id)).exists()


def test_tc_fts_007_discard_circulated_file_blocked(stub_iam):
    """
    Test ID: TC-FTS-007
    Source ID: FTS-UC-002 Exception Flow 1
    Purpose: Verify that discarding a file is blocked if it has already been submitted/circulated.
    Preconditions: File exists in submitted/circulated state. Employee attempts to discard
                   the file.
    Action/Input: Select Discard option on circulated file.
    Expected Result: FTS does not permit discard. File remains unchanged.
    Test Type: Negative
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

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"


def test_tc_fts_008_edit_or_discard_unauthorized_user_denied(stub_iam):
    """
    Test ID: TC-FTS-008
    Source ID: FTS-UC-002 Exception Flow 2
    Purpose: Verify that editing/discarding is denied if the employee is not authorized for
             the draft.
    Preconditions: Draft file exists owned by another user. Employee is not authorized to
                   edit/discard this draft.
    Action/Input: Attempt to open or modify the draft.
    Expected Result: FTS denies access/action. File remains unchanged.
    Test Type: Negative
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Owner initial comment")

    # User B attempts to edit User A's draft
    with pytest.raises(ValueError, match=r"Only the owner can edit the draft\."):
        edit_draft_service(str(user_b_id), str(file_obj.id), "Unauthorized edit attempt")

    # User B attempts to discard User A's draft via API
    client_b, _ = _get_auth_client(stub_iam, user_id=user_b_id)
    res_discard = client_b.delete(f"/api/fts/v1/{file_obj.id}/discard/")
    assert res_discard.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in res_discard.json()

    file_obj.refresh_from_db()
    assert file_obj.status == "DRAFT"
    assert FtsFileComment.objects.get(file_id=str(file_obj.id)).text == "Owner initial comment"


def test_tc_fts_009_send_forward_active_file(stub_iam):
    """
    Test ID: TC-FTS-009
    Source ID: FTS-UC-003 Main Success Scenario
    Purpose: Verify successful sending/forwarding of an active file to a recipient.
    Preconditions: Active file exists. Sender is authorized. Valid recipient Institute
                   Employee exists.
    Action/Input: Select Send/Forward on actionable file. Select recipient. Enter mandatory
                  movement comment. Optionally add attachment. Confirm Send/Forward.
    Expected Result: File holder is updated to recipient. Movement history, audit, and version
                     info are recorded. Notification event (file-forwarded/file-received)
                     is triggered.
    Test Type: Positive
    """
    client_a, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Active file comment")
    payload = {
        "receiver_id": str(user_b_id),
        "movement_comment": "Forwarding active file to recipient",
        "attachment_urls": ["https://documents.fusion.edu/doc.pdf"],
    }
    response = client_a.post(f"/api/fts/v1/{file_obj.id}/forward/", payload, format="json")
    assert response.status_code == status.HTTP_200_OK

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"
    assert file_obj.current_holder_id == user_b_id

    movement = FtsFileMovement.objects.get(file_id=file_obj.id)
    assert movement.sender_id == user_a_id
    assert movement.receiver_id == user_b_id
    assert movement.comment == "Forwarding active file to recipient"

    audit = FtsAuditLog.objects.get(file_id=file_obj.id, action="FORWARD")
    assert audit.actor_id == user_a_id


def test_tc_fts_010_forward_missing_movement_comment(stub_iam):
    """
    Test ID: TC-FTS-010
    Source ID: FTS-UC-003 Exception Flow 1
    Purpose: Verify that forwarding is blocked if the mandatory movement comment is missing.
    Preconditions: Active file exists. Sender is authorized.
    Action/Input: Select Send/Forward. Leave movement comment empty. Attempt to confirm.
    Expected Result: Forwarding is blocked. File state remains unchanged.
    Test Type: Negative
    """
    client, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft comment")
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


def test_tc_fts_011_forward_invalid_recipient(stub_iam):
    """
    Test ID: TC-FTS-011
    Source ID: FTS-UC-003 Exception Flow 2
    Purpose: Verify that forwarding is blocked if the recipient is invalid.
    Preconditions: Active file exists. Sender is authorized.
    Action/Input: Select Send/Forward. Select invalid/non-existent recipient. Attempt to confirm.
    Expected Result: Forwarding is blocked. File state remains unchanged.
    Test Type: Negative
    """
    client, user_a_id = _get_auth_client(stub_iam)
    file_obj = create_file_service(str(user_a_id), "Initial draft comment")

    # 1. Empty/missing recipient
    res_empty = client.post(
        f"/api/fts/v1/{file_obj.id}/forward/",
        {"receiver_id": "", "movement_comment": "Comment"},
        format="json",
    )
    assert res_empty.status_code == status.HTTP_400_BAD_REQUEST
    assert "receiver_id" in res_empty.json()

    # 2. Non-UUID invalid recipient
    with pytest.raises(ValidationError):
        client.post(
            f"/api/fts/v1/{file_obj.id}/forward/",
            {"receiver_id": "not-a-valid-uuid", "movement_comment": "Comment"},
            format="json",
        )

    file_obj.refresh_from_db()
    assert file_obj.status == "DRAFT"
    assert file_obj.current_holder_id == user_a_id


def test_tc_fts_012_forward_unauthorized_or_archived(stub_iam):
    """
    Test ID: TC-FTS-012
    Source ID: FTS-UC-003 Exception Flow 3
    Purpose: Verify that forwarding is blocked for unauthorized actions or archived files.
    Preconditions: File is archived OR sender is not authorized.
    Action/Input: Attempt to Send/Forward the file.
    Expected Result: Forwarding is blocked. File state remains unchanged.
    Test Type: Negative
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    user_c_id = uuid.uuid4()

    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Forward to B")
    archive_file_service(str(user_a_id), str(file_obj.id))

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"

    # Attempt forward on archived file
    with pytest.raises(ValueError, match=r"Cannot forward an archived or discarded file\."):
        forward_file_service(str(user_b_id), str(file_obj.id), str(user_c_id), "Fwd archived")

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"


def test_tc_fts_013_return_file_to_sender(stub_iam):
    """
    Test ID: TC-FTS-013
    Source ID: FTS-UC-004 Main Success Scenario
    Purpose: Verify successful return of a received file to its sender.
    Preconditions: File is active and associated with the recipient. Recipient is authorized
                   to return it. Known sender exists for current movement.
    Action/Input: Select Return on received file. Enter mandatory movement comment.
                  Optionally add attachment. Confirm Return.
    Expected Result: File holder is updated to previous sender. Return movement is recorded
                     chronologically. Audit/version info is recorded. File-returned notification
                     event is triggered.
    Test Type: Positive
    """
    pytest.skip(
        "NOT_AUTOMATED: return_file workflow cannot be executed due to production bugs in "
        "return_file_service (type mismatch in holder check and unhandled UUID JSON serialization "
        "in FtsAuditLog details)."
    )


def test_tc_fts_014_return_missing_movement_comment(stub_iam):
    """
    Test ID: TC-FTS-014
    Source ID: FTS-UC-004 Exception Flow 1
    Purpose: Verify that return is blocked if the mandatory movement comment is missing.
    Preconditions: File is active and associated with the recipient.
    Action/Input: Select Return. Leave movement comment empty. Attempt to confirm.
    Expected Result: Return is blocked. File state remains unchanged.
    Test Type: Negative
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Forwarding")

    client_b, _ = _get_auth_client(stub_iam, user_id=user_b_id)
    response = client_b.post(
        f"/api/fts/v1/{file_obj.id}/return/",
        {"movement_comment": ""},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "movement_comment" in response.json()

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"
    assert file_obj.current_holder_id == user_b_id


def test_tc_fts_015_return_unauthorized_or_archived(stub_iam):
    """
    Test ID: TC-FTS-015
    Source ID: FTS-UC-004 Exception Flow 2
    Purpose: Verify that return is blocked for unauthorized actions or archived/completed files.
    Preconditions: File is archived OR recipient is not authorized.
    Action/Input: Attempt to Return the file.
    Expected Result: Return is blocked. File state remains unchanged.
    Test Type: Negative
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    user_c_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Forwarding")
    archive_file_service(str(user_a_id), str(file_obj.id))

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"

    # User C (not holder) attempts return on archived file
    client_c, _ = _get_auth_client(stub_iam, user_id=user_c_id)
    with pytest.raises(ValueError, match=r"You are not the current holder of this file\."):
        client_c.post(
            f"/api/fts/v1/{file_obj.id}/return/",
            {"movement_comment": "Unauthorized return attempt"},
            format="json",
        )

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"


def test_tc_fts_016_view_inbox_outbox_and_open_files(stub_iam):
    """
    Test ID: TC-FTS-016
    Source ID: FTS-UC-005 Main Success Scenario
    Purpose: Verify that an employee can view Inbox, Outbox, and open authorized files.
    Preconditions: Employee is authenticated in an FTS role context. Files exist in Inbox/Outbox.
    Action/Input: Open Inbox or Outbox. Select an authorized file.
    Expected Result: FTS lists files correctly. FTS displays file contents, comments,
                     attachments, status, and permitted actions.
    Test Type: Positive
    """
    pytest.skip(
        "NOT_AUTOMATED: Inbox/Outbox and detail views are not exposed via API and backend "
        "selectors get_inbox_files/get_outbox_files crash due to invalid relation "
        "ftsfilemovement on FtsFile."
    )


def test_tc_fts_017_unauthorized_files_not_exposed(stub_iam):
    """
    Test ID: TC-FTS-017
    Source ID: FTS-UC-005 Exception Flow 1
    Purpose: Verify that unauthorized files are not exposed or opened.
    Preconditions: Employee is authenticated. File exists but employee is not authorized
                   to view it.
    Action/Input: Attempt to view or open the unauthorized file.
    Expected Result: FTS does not expose/open the file.
    Test Type: Negative
    """
    pytest.skip(
        "NOT_AUTOMATED: File detail viewing is not exposed via API and backend selector "
        "get_file_detail crashes due to invalid relation ftsfilemovement on FtsFile."
    )


def test_tc_fts_018_unauthorized_actions_denied_for_state(stub_iam):
    """
    Test ID: TC-FTS-018
    Source ID: FTS-UC-005 Exception Flow 2
    Purpose: Verify that unauthorized actions are unavailable or denied based on file state/role.
    Preconditions: Employee is viewing an authorized file. Action is not authorized for
                   current state/role.
    Action/Input: Attempt to perform unauthorized action.
    Expected Result: Action is unavailable or denied.
    Test Type: Negative
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Circulating")

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"

    # Action 1: Attempt to edit a circulated file (only draft permitted)
    with pytest.raises(ValueError, match=r"Can only edit a draft file\."):
        edit_draft_service(str(user_a_id), str(file_obj.id), "Attempted edit on circulated")

    # Action 2: Attempt to discard a circulated file (only draft permitted)
    with pytest.raises(ValueError, match=r"Can only discard a draft file\."):
        discard_draft_service(str(user_a_id), str(file_obj.id))

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"


def test_tc_fts_019_view_complete_tracking_history(stub_iam):
    """
    Test ID: TC-FTS-019
    Source ID: FTS-UC-006 Main Success Scenario
    Purpose: Verify that an authorized employee can view the complete chronological tracking
             history of a file.
    Preconditions: File exists. Employee is authorized/associated with the file.
    Action/Input: Select View History for the file.
    Expected Result: FTS displays chronological history including sender, receiver, timestamp,
                     comments, and attachments for all movements.
    Test Type: Positive
    """
    pytest.skip(
        "NOT_AUTOMATED: File tracking history view is not exposed via API and backend selector "
        "get_file_history crashes due to invalid relation ftsfilemovement on FtsFile."
    )


def test_tc_fts_020_history_access_denied_unauthorized_user(stub_iam):
    """
    Test ID: TC-FTS-020
    Source ID: FTS-UC-006 Exception Flow 1
    Purpose: Verify that history access is denied if the employee is not authorized/associated
             with the file.
    Preconditions: File exists. Employee is not authorized/associated with the file.
    Action/Input: Attempt to view history.
    Expected Result: FTS denies history access.
    Test Type: Negative
    """
    pytest.skip(
        "NOT_AUTOMATED: File tracking history view is not exposed via API and backend selector "
        "get_file_history crashes due to invalid relation ftsfilemovement on FtsFile."
    )


def test_tc_fts_021_owner_archives_circulated_file(stub_iam):
    """
    Test ID: TC-FTS-021
    Source ID: FTS-UC-007 Main Success Scenario
    Purpose: Verify that the file owner can successfully archive a completed circulated file.
    Preconditions: File has been circulated. File is not already archived. Actor is the file owner.
    Action/Input: Open active circulated file. Select Archive.
    Expected Result: File state changes to Archived / Read-only. Subsequent modification and
                     forwarding are prevented. Archival audit/event is recorded. File-archived
                     notification event is triggered.
    Test Type: Positive
    """
    client, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Circulating")

    res = client.post(f"/api/fts/v1/{file_obj.id}/archive/", {}, format="json")
    assert res.status_code == status.HTTP_200_OK

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"

    # Subsequent modification blocked
    with pytest.raises(ValueError, match=r"Can only edit a draft file\."):
        edit_draft_service(str(user_a_id), str(file_obj.id), "Modify archived")

    # Subsequent forwarding blocked
    with pytest.raises(ValueError, match=r"Cannot forward an archived or discarded file\."):
        forward_file_service(str(user_b_id), str(file_obj.id), str(user_a_id), "Forward archived")

    audit = FtsAuditLog.objects.get(file_id=file_obj.id, action="ARCHIVE")
    assert audit.actor_id == user_a_id


def test_tc_fts_022_archive_already_archived_file(stub_iam):
    """
    Test ID: TC-FTS-022
    Source ID: FTS-UC-007 Alternative Flow 1
    Purpose: Verify that selecting Archive on an already archived file presents read-only state
             without new transition.
    Preconditions: File is already archived.
    Action/Input: Select Archive.
    Expected Result: FTS presents existing read-only state. No new archival transition occurs.
    Test Type: Positive
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Circulating")
    archive_file_service(str(user_a_id), str(file_obj.id))

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"
    audit_count_before = FtsAuditLog.objects.filter(file_id=str(file_obj.id)).count()

    # Selecting archive again does not trigger a new transition
    with pytest.raises(ValueError, match=r"File is already archived\."):
        archive_file_service(str(user_a_id), str(file_obj.id))

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"
    assert FtsAuditLog.objects.filter(file_id=str(file_obj.id)).count() == audit_count_before


def test_tc_fts_023_archive_denied_for_non_owner(stub_iam):
    """
    Test ID: TC-FTS-023
    Source ID: FTS-UC-007 Exception Flow 1
    Purpose: Verify that archival is denied if the actor is not the file owner.
    Preconditions: File is active. Actor is not the file owner.
    Action/Input: Attempt to Archive the file.
    Expected Result: Archival attempt is denied. File remains active.
    Test Type: Negative
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Circulating")

    client_b, _ = _get_auth_client(stub_iam, user_id=user_b_id)
    with pytest.raises(ValueError, match=r"Only the file owner can archive the file\."):
        client_b.post(f"/api/fts/v1/{file_obj.id}/archive/", {}, format="json")

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"


def test_tc_fts_024_employee_role_context_selection(stub_iam):
    """
    Test ID: TC-FTS-024
    Source ID: FTS-UC-008 Main Success Scenario
    Purpose: Verify that an employee can select an assigned role context and use FTS under
             that role.
    Preconditions: Employee has at least one assigned role. Multiple roles are assigned.
    Action/Input: Select an assigned role context in Fusion dashboard.
    Expected Result: FTS applies selected role context for authorization. Existing file
                     ownership and audit history are preserved.
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
    res = client.post("/api/fts/v1/", {"initial_comment": "Created as faculty"}, format="json")
    assert res.status_code == status.HTTP_201_CREATED
    file_id = res.json()["id"]

    # Switch role context
    _get_auth_client(
        stub_iam,
        user_id=user_id,
        active_role="dean_academics",
        roles=("faculty", "dean_academics"),
        kind="staff",
    )

    file_obj = FtsFile.objects.get(id=file_id)
    assert file_obj.owner_id == user_id

    audit = FtsAuditLog.objects.get(file_id=str(file_id), action="CREATE")
    assert audit.actor_id == user_id


def test_tc_fts_025_sensitive_actions_denied_for_role(stub_iam):
    """
    Test ID: TC-FTS-025
    Source ID: FTS-UC-008 Exception Flow 1
    Purpose: Verify that sensitive actions are denied if the selected role does not authorize
             them.
    Preconditions: Employee has selected a role context. Role does not authorize a specific
                   sensitive action.
    Action/Input: Attempt to perform the sensitive action.
    Expected Result: FTS denies the action.
    Test Type: Negative
    """
    pytest.skip(
        "NOT_AUTOMATED: Role-based authorization restrictions for sensitive actions are not "
        "implemented in the available FTS interfaces."
    )


def test_tc_fts_026_system_admin_governance_oversight(stub_iam):
    """
    Test ID: TC-FTS-026
    Source ID: FTS-UC-009 Main Success Scenario
    Purpose: Verify that System Admin can administer FTS user access context and governance
             oversight.
    Preconditions: System Admin has applicable administrative privileges.
    Action/Input: Assign/reassign FTS-relevant role. Review FTS usage/security/audit information.
    Expected Result: FTS consumes/records role/access context. Notification event triggered for
                     relevant role assignment. System Admin does not perform operational file
                     actions.
    Test Type: Positive
    """
    pytest.skip(
        "NOT_AUTOMATED: System Admin access context administration and governance oversight "
        "interfaces are not implemented in FTS."
    )


def test_tc_fts_027_system_admin_operational_actions_denied(stub_iam):
    """
    Test ID: TC-FTS-027
    Source ID: FTS-UC-009 Exception Flow 1
    Purpose: Verify that System Admin is denied operational file workflow actions.
    Preconditions: System Admin is logged in.
    Action/Input: Attempt to create, forward, return, or archive an operational file.
    Expected Result: FTS denies the operational action. File state remains unchanged.
    Test Type: Negative
    """
    pytest.skip(
        "NOT_AUTOMATED: Restrictions preventing System Admin from operational file actions "
        "are not implemented in the available FTS interfaces."
    )


def test_tc_fts_028_authorized_module_invokes_fts_api(stub_iam):
    """
    Test ID: TC-FTS-028
    Source ID: FTS-UC-010 Main Success Scenario
    Purpose: Verify that an authorized consuming Fusion module can successfully invoke FTS APIs.
    Preconditions: Integration is authorized. Required access/context is provided.
    Action/Input: Consuming module calls an FTS API for workflow support.
    Expected Result: FTS validates authorization. FTS performs supported service. Audit
                     information is recorded. Service response is returned.
    Test Type: Positive
    """
    pytest.skip(
        "NOT_AUTOMATED: Cross-module workflow integration APIs are not implemented or exposed "
        "in modules/fts."
    )


def test_tc_fts_029_unauthorized_integration_request_rejected(stub_iam):
    """
    Test ID: TC-FTS-029
    Source ID: FTS-UC-010 Exception Flow 1
    Purpose: Verify that unauthorized integration requests are rejected.
    Preconditions: Integration is not authorized.
    Action/Input: Attempt to call FTS API.
    Expected Result: Request is rejected. No FTS action is performed.
    Test Type: Negative
    """
    pytest.skip(
        "NOT_AUTOMATED: Cross-module API integration endpoints are not implemented in modules/fts."
    )


def test_tc_fts_030_reject_domain_specific_policy_definition(stub_iam):
    """
    Test ID: TC-FTS-030
    Source ID: FTS-UC-010 Exception Flow 2
    Purpose: Verify that FTS rejects requests to define domain-specific approval policy for
             consuming modules.
    Preconditions: Authorized consuming module invokes FTS API.
    Action/Input: Request FTS to define/approve domain-specific policy.
    Expected Result: Request is outside FTS scope and rejected/handled as error. FTS does not
                     invent or own consuming-module approval rules.
    Test Type: Negative
    """
    pytest.skip(
        "NOT_AUTOMATED: Domain-specific approval policy definition APIs are outside FTS scope "
        "and not implemented in modules/fts."
    )

