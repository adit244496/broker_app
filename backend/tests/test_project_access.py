"""Admin control over which brokers see which project."""

from conftest import ABC_EMAIL, admin_token, bearer, broker_token

SKYLINE_EMAIL = "contact@skylinerealty.in"  # Skyline Realty, 001A2, active in the demo data
ABC = "001A1"


def _ids(client, token):
    return {p["Id"] for p in client.get("/projects", headers=token).json()["records"]}


def _set(client, admin, project, restricted, broker_ids=()):
    return client.put(f"/admin/projects/{project}/access", headers=admin, json={"restricted": restricted, "brokerIds": list(broker_ids)})


def _lead(project):
    return {"FirstName": "Asha", "LastName": "Roy", "MobilePhone": "9876501234", "Project__c": project}


def test_projects_are_open_to_all_brokers_by_default(client, mail):
    admin = bearer(admin_token(client))
    records = client.get("/admin/projects", headers=admin).json()["records"]
    assert records and all(r["access"] == {"restricted": False, "brokerIds": []} for r in records)
    assert _ids(client, bearer(broker_token(client, mail, ABC_EMAIL))) == {r["Id"] for r in records}


def test_restricted_project_is_seen_only_by_selected_brokers(client, mail):
    admin = bearer(admin_token(client))
    abc = bearer(broker_token(client, mail, ABC_EMAIL))
    skyline = bearer(broker_token(client, mail, SKYLINE_EMAIL))

    res = _set(client, admin, "a0P001", True, [ABC])
    assert res.status_code == 200, res.text
    assert res.json()["access"] == {"restricted": True, "brokerIds": [ABC]}

    assert "a0P001" in _ids(client, abc)
    assert "a0P001" not in _ids(client, skyline)
    assert client.get("/projects/a0P001", headers=skyline).status_code == 404
    assert client.post("/enquiries", headers=skyline, json=_lead("a0P001")).status_code == 422
    assert client.post("/enquiries", headers=abc, json=_lead("a0P001")).status_code == 201

    # Back to everyone.
    assert _set(client, admin, "a0P001", False, [ABC]).json()["access"] == {"restricted": False, "brokerIds": []}
    assert "a0P001" in _ids(client, skyline)


def test_restricted_with_nobody_hides_the_project(client, mail):
    admin = bearer(admin_token(client))
    abc = bearer(broker_token(client, mail, ABC_EMAIL))
    _set(client, admin, "a0P002", True)
    assert "a0P002" not in _ids(client, abc)
    listed = {r["Id"]: r["access"] for r in client.get("/admin/projects", headers=admin).json()["records"]}
    assert listed["a0P002"] == {"restricted": True, "brokerIds": []}


def test_access_changes_are_validated_and_admin_only(client, mail):
    admin = bearer(admin_token(client))
    assert _set(client, admin, "a0P999", True, [ABC]).status_code == 404
    assert _set(client, admin, "a0P001", True, ["001ZZZZZZZZZZZZ"]).status_code == 400
    assert _set(client, admin, "a0P001", True, ["x' OR 1=1"]).status_code == 422
    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    assert _set(client, broker, "a0P001", True, [ABC]).status_code == 401
