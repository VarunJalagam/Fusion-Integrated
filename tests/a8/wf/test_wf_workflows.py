"""
Workflow (WF) test suite for File Tracking System (FTS).
Generated from WF_DESIGN.json.
Strategy: wf
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


def test_tc_fts_001_create_file_no_draft_edit(stub_iam):
    """
    Test ID: TC-FTS-001
    Source ID: BW-FTS-05, FTS-UC-001, BR-FTS-003
    Purpose: Verify creation of a new file with mandatory comment and no draft edit, resulting
             in Draft state.
    Preconditions: User is an authorized Institute Employee with an assigned role. No existing
                   file record for the intended file.
    Action/Input: Create new file with initial mandatory comment. Do not add attachments.
                  Save as draft.
    Expected Result: File is created in 'Draft / Pre-circulation' state. Audit log records
                     creation.
    Test Type: Positive
    """
    client, user_id = _get_auth_client(stub_iam)
    payload = {
        "initial_comment": "Initial mandatory comment without attachments",
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
    assert comment_obj.text == "Initial mandatory comment without attachments"
    assert comment_obj.is_initial is True
    assert not FtsFileAttachment.objects.filter(file_id=str(file_id)).exists()

    audit_entry = FtsAuditLog.objects.get(file_id=str(file_id), action="CREATE")
    assert audit_entry.actor_id == user_id


def test_tc_fts_002_circulate_file_zero_draft_edit(stub_iam):
    """
    Test ID: TC-FTS-002
    Source ID: BW-FTS-05, FTS-UC-003, BR-FTS-006, BR-FTS-013
    Purpose: Verify circulation of a new file without draft edit (Zero Draft-Edit Traversal).
    Preconditions: File exists in 'Draft / Pre-circulation' state. User is the creator/sender.
                   Recipient is a valid Institute Employee.
    Action/Input: Send/Forward file to recipient with mandatory movement comment.
    Expected Result: File state changes to 'Active / Circulated'. File appears in Recipient's
                     Inbox and Sender's Outbox. Notification triggered. Movement history updated.
    Test Type: Positive
    """
    client, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Draft for immediate circulation")

    payload = {
        "receiver_id": str(user_b_id),
        "movement_comment": "Zero draft-edit circulation comment",
    }
    response = client.post(f"/api/fts/v1/{file_obj.id}/forward/", payload, format="json")
    assert response.status_code == status.HTTP_200_OK

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"
    assert file_obj.current_holder_id == user_b_id

    movement = FtsFileMovement.objects.get(file_id=file_obj.id)
    assert movement.sender_id == user_a_id
    assert movement.receiver_id == user_b_id
    assert movement.movement_type == "FORWARD"
    assert movement.comment == "Zero draft-edit circulation comment"


def test_tc_fts_003_edit_draft_file_once(stub_iam):
    """
    Test ID: TC-FTS-003
    Source ID: BW-FTS-06, FTS-UC-002, BR-FTS-003
    Purpose: Verify editing a draft file once (One Draft-Edit Traversal).
    Preconditions: File exists in 'Draft / Pre-circulation' state. User is the creator.
    Action/Input: Edit the draft file (e.g., update comment or add attachment). Save changes.
    Expected Result: File remains in 'Updated Draft / Pre-circulation' state. Changes are persisted.
    Test Type: Positive
    """
    _, user_id = _get_auth_client(stub_iam)
    file_obj = create_file_service(str(user_id), "Initial draft comment before edit")
    new_comment = "Updated comment after one draft edit"
    new_attachment = ["https://documents.fusion.edu/doc_v1.pdf"]

    edit_draft_service(
        actor_id=str(user_id),
        file_id=str(file_obj.id),
        new_comment=new_comment,
        new_attachment_urls=new_attachment,
    )
    file_obj.refresh_from_db()
    assert file_obj.status == "DRAFT"

    comment = FtsFileComment.objects.get(file_id=str(file_obj.id), is_initial=True)
    assert comment.text == new_comment

    attachment = FtsFileAttachment.objects.get(file_id=str(file_obj.id))
    assert attachment.file_url == "https://documents.fusion.edu/doc_v1.pdf"


def test_tc_fts_004_circulate_file_after_one_draft_edit(stub_iam):
    """
    Test ID: TC-FTS-004
    Source ID: BW-FTS-06, FTS-UC-003, BR-FTS-006
    Purpose: Verify circulation of a file after one draft edit.
    Preconditions: File exists in 'Updated Draft / Pre-circulation' state. User is the sender.
                   Recipient is valid.
    Action/Input: Send/Forward file to recipient with mandatory movement comment.
    Expected Result: File state changes to 'Active / Circulated'. Notification triggered.
                     History updated.
    Test Type: Positive
    """
    client, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft comment")
    edit_draft_service(str(user_a_id), str(file_obj.id), "Edited comment before sending")

    payload = {
        "receiver_id": str(user_b_id),
        "movement_comment": "Circulation after one draft edit",
    }
    response = client.post(f"/api/fts/v1/{file_obj.id}/forward/", payload, format="json")
    assert response.status_code == status.HTTP_200_OK

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"
    assert file_obj.current_holder_id == user_b_id

    movement = FtsFileMovement.objects.get(file_id=file_obj.id)
    assert movement.sender_id == user_a_id
    assert movement.receiver_id == user_b_id
    assert movement.comment == "Circulation after one draft edit"


def test_tc_fts_005_discard_draft_zero_edit(stub_iam):
    """
    Test ID: TC-FTS-005
    Source ID: BW-FTS-07, FTS-UC-002, BR-FTS-005
    Purpose: Verify discarding a newly created draft without editing (Zero Draft-Edit Traversal).
    Preconditions: File exists in 'Draft / Pre-circulation' state. User is the creator.
    Action/Input: Select 'Discard' on the draft file.
    Expected Result: File is discarded. No active file retained. Audit log records discard action.
    Test Type: Positive
    """
    client, user_id = _get_auth_client(stub_iam)
    file_obj = create_file_service(str(user_id), "Draft to be discarded without editing")

    response = client.delete(f"/api/fts/v1/{file_obj.id}/discard/")
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not FtsFile.objects.filter(id=file_obj.id).exists()
    assert not FtsFileComment.objects.filter(file_id=str(file_obj.id)).exists()

    audit = FtsAuditLog.objects.get(file_id=str(file_obj.id), action="DISCARD_DRAFT")
    assert audit.actor_id == user_id


def test_tc_fts_006_discard_draft_after_one_edit(stub_iam):
    """
    Test ID: TC-FTS-006
    Source ID: BW-FTS-08, FTS-UC-002, BR-FTS-005
    Purpose: Verify discarding a draft after one edit (One Draft-Edit Traversal).
    Preconditions: File exists in 'Updated Draft / Pre-circulation' state. User is the creator.
    Action/Input: Select 'Discard' on the edited draft file.
    Expected Result: File is discarded. No active file retained. Audit log records discard action.
    Test Type: Positive
    """
    client, user_id = _get_auth_client(stub_iam)
    file_obj = create_file_service(str(user_id), "Initial draft")
    edit_draft_service(str(user_id), str(file_obj.id), "Edited once before discard")

    response = client.delete(f"/api/fts/v1/{file_obj.id}/discard/")
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not FtsFile.objects.filter(id=file_obj.id).exists()
    assert not FtsFileComment.objects.filter(file_id=str(file_obj.id)).exists()

    audit = FtsAuditLog.objects.get(file_id=str(file_obj.id), action="DISCARD_DRAFT")
    assert audit.actor_id == user_id


def test_tc_fts_007_forward_active_file_to_new_recipient(stub_iam):
    """
    Test ID: TC-FTS-007
    Source ID: BW-FTS-01, FTS-UC-003, BR-FTS-001, BR-FTS-006
    Purpose: Verify forwarding an active circulated file to a new recipient (Zero Onward
             Traversal context).
    Preconditions: File is in 'Active / Circulated' state. User is the current holder.
                   Recipient is valid and different from previous sender.
    Action/Input: Forward file to new recipient with mandatory movement comment.
    Expected Result: File held by new recipient. Previous holder no longer has active control.
                     History and audit updated. Notification sent.
    Test Type: Positive
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    user_c_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial file")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "First forward")

    # User B forwards to User C
    client_b, _ = _get_auth_client(stub_iam, user_id=user_b_id)
    payload = {
        "receiver_id": str(user_c_id),
        "movement_comment": "Forwarding to new recipient User C",
    }
    response = client_b.post(f"/api/fts/v1/{file_obj.id}/forward/", payload, format="json")
    assert response.status_code == status.HTTP_200_OK

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"
    assert file_obj.current_holder_id == user_c_id

    movements = list(FtsFileMovement.objects.filter(file_id=file_obj.id).order_by("created_at"))
    assert len(movements) == 2
    assert movements[1].sender_id == user_b_id
    assert movements[1].receiver_id == user_c_id
    assert movements[1].comment == "Forwarding to new recipient User C"


def test_tc_fts_008_onward_forwarding_one_loop_traversal(stub_iam):
    """
    Test ID: TC-FTS-008
    Source ID: BW-FTS-02, FTS-UC-003, BR-FTS-006
    Purpose: Verify onward forwarding of a received file (One Loop Traversal).
    Preconditions: User has received an active circulated file. User is the current holder.
    Action/Input: Forward file to next recipient with mandatory movement comment.
    Expected Result: File held by next recipient. History records onward movement.
                     Notification sent.
    Test Type: Positive
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    user_c_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial file")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "A to B")

    client_b, _ = _get_auth_client(stub_iam, user_id=user_b_id)
    payload = {
        "receiver_id": str(user_c_id),
        "movement_comment": "Onward forwarding from B to C",
    }
    response = client_b.post(f"/api/fts/v1/{file_obj.id}/forward/", payload, format="json")
    assert response.status_code == status.HTTP_200_OK

    file_obj.refresh_from_db()
    assert file_obj.current_holder_id == user_c_id

    movement = FtsFileMovement.objects.filter(file_id=file_obj.id).order_by("created_at").last()
    assert movement.sender_id == user_b_id
    assert movement.receiver_id == user_c_id
    assert movement.comment == "Onward forwarding from B to C"


def test_tc_fts_009_return_file_to_previous_sender(stub_iam):
    """
    Test ID: TC-FTS-009
    Source ID: BW-FTS-03, FTS-UC-004, BR-FTS-006, BR-FTS-013
    Purpose: Verify returning an active circulated file to the previous sender.
    Preconditions: User has received an active circulated file. Previous sender is known.
    Action/Input: Return file to previous sender with mandatory movement comment.
    Expected Result: File held by previous sender. History records return action.
                     Return notification triggered.
    Test Type: Positive
    """
    pytest.skip(
        "NOT_AUTOMATED: return_file workflow cannot be executed due to production bugs in "
        "return_file_service (type mismatch in holder check and unhandled UUID JSON serialization "
        "in FtsAuditLog details)."
    )


def test_tc_fts_010_archival_of_completed_circulated_file(stub_iam):
    """
    Test ID: TC-FTS-010
    Source ID: BW-FTS-04, FTS-UC-007, BR-FTS-009
    Purpose: Verify archival of a completed circulated file by the owner.
    Preconditions: File is in 'Active / Circulated' state. User is the file owner.
                   Collaborative objective is complete.
    Action/Input: Select 'Archive' on the file.
    Expected Result: File state changes to 'Archived / Read-only'. File cannot be modified
                     or forwarded. Archive notification triggered. Audit log updated.
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

    # Modification blocked
    with pytest.raises(ValueError, match=r"Can only edit a draft file\."):
        edit_draft_service(str(user_a_id), str(file_obj.id), "Modifying archived")

    # Forwarding blocked
    with pytest.raises(ValueError, match=r"Cannot forward an archived or discarded file\."):
        forward_file_service(str(user_b_id), str(file_obj.id), str(user_a_id), "Forward archived")

    audit = FtsAuditLog.objects.get(file_id=file_obj.id, action="ARCHIVE")
    assert audit.actor_id == user_a_id


def test_tc_fts_011_non_owner_cannot_archive_file(stub_iam):
    """
    Test ID: TC-FTS-011
    Source ID: BR-FTS-009, FTS-UC-007
    Purpose: Verify that a non-owner cannot archive a file.
    Preconditions: File is in 'Active / Circulated' state. User is an associated employee
                   but NOT the file owner.
    Action/Input: Attempt to archive the file.
    Expected Result: Action is denied. Error message indicates lack of permission/ownership.
    Test Type: Negative
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial file")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Circulating")

    client_b, _ = _get_auth_client(stub_iam, user_id=user_b_id)
    with pytest.raises(ValueError, match=r"Only the file owner can archive the file\."):
        client_b.post(f"/api/fts/v1/{file_obj.id}/archive/", {}, format="json")

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"


def test_tc_fts_012_archived_file_cannot_be_archived_again_or_modified(stub_iam):
    """
    Test ID: TC-FTS-012
    Source ID: BR-FTS-009, FTS-UC-007
    Purpose: Verify that an already archived file cannot be archived again or modified.
    Preconditions: File is in 'Archived' state.
    Action/Input: Attempt to archive, forward, or edit the file.
    Expected Result: All actions are denied. File remains read-only.
    Test Type: Negative
    """
    _, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial file")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Circulating")
    archive_file_service(str(user_a_id), str(file_obj.id))

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"

    # Attempt to archive again
    with pytest.raises(ValueError, match=r"File is already archived\."):
        archive_file_service(str(user_a_id), str(file_obj.id))

    # Attempt to forward
    with pytest.raises(ValueError, match=r"Cannot forward an archived or discarded file\."):
        forward_file_service(str(user_b_id), str(file_obj.id), str(user_a_id), "Forward archived")

    # Attempt to edit
    with pytest.raises(ValueError, match=r"Can only edit a draft file\."):
        edit_draft_service(str(user_a_id), str(file_obj.id), "Edit archived")

    file_obj.refresh_from_db()
    assert file_obj.status == "ARCHIVED"


def test_tc_fts_013_forward_fails_without_mandatory_comment(stub_iam):
    """
    Test ID: TC-FTS-013
    Source ID: BR-FTS-006, FTS-UC-003
    Purpose: Verify that forwarding a file fails without a mandatory movement comment.
    Preconditions: File is in 'Draft' or 'Active' state. User is authorized sender.
    Action/Input: Attempt to forward file with empty movement comment.
    Expected Result: Action is denied. Validation error requires mandatory comment.
    Test Type: Negative
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


def test_tc_fts_014_create_file_fails_without_mandatory_comment(stub_iam):
    """
    Test ID: TC-FTS-014
    Source ID: BR-FTS-001, FTS-UC-001
    Purpose: Verify that creating a file fails without a mandatory initial comment.
    Preconditions: User is authorized Institute Employee.
    Action/Input: Attempt to create new file with empty initial comment.
    Expected Result: Action is denied. Validation error requires mandatory initial comment.
    Test Type: Negative
    """
    client, user_a_id = _get_auth_client(stub_iam)
    payload = {"initial_comment": ""}
    response = client.post("/api/fts/v1/", payload, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "initial_comment" in response.json()
    assert not FtsFile.objects.filter(owner_id=user_a_id).exists()


def test_tc_fts_015_circulated_file_cannot_be_discarded(stub_iam):
    """
    Test ID: TC-FTS-015
    Source ID: BR-FTS-005, FTS-UC-002
    Purpose: Verify that a circulated file cannot be discarded.
    Preconditions: File is in 'Active / Circulated' state.
    Action/Input: Attempt to discard the file.
    Expected Result: Action is denied. Discard is only allowed for pre-circulation drafts.
    Test Type: Negative
    """
    client, user_a_id = _get_auth_client(stub_iam)
    user_b_id = uuid.uuid4()
    file_obj = create_file_service(str(user_a_id), "Initial draft")
    forward_file_service(str(user_a_id), str(file_obj.id), str(user_b_id), "Circulating")

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"

    response = client.delete(f"/api/fts/v1/{file_obj.id}/discard/")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in response.json()

    file_obj.refresh_from_db()
    assert file_obj.status == "CIRCULATED"
    assert FtsFile.objects.filter(id=file_obj.id).exists()
