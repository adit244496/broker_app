"""Admin-added project icon, cover image and videos."""

from conftest import ABC_EMAIL, admin_token, bearer, broker_token

from app.project_media import youtube_id

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _upload(client, admin, project, kind, data, name="x.png"):
    return client.put(f"/admin/projects/{project}/media/{kind}", headers=admin, files={"file": (name, data, "image/png")})


def _project(client, token, project="a0P001"):
    return client.get(f"/projects/{project}", headers=token).json()


def test_icon_and_cover_reach_the_app(client, mail):
    admin = bearer(admin_token(client))
    res = _upload(client, admin, "a0P001", "icon", PNG)
    assert res.status_code == 200, res.text
    icon = res.json()["media"]["iconUrl"]
    assert icon.startswith("/media/") and icon.endswith(".png")
    cover = _upload(client, admin, "a0P001", "cover", JPG, "c.jpg").json()["media"]["coverUrl"]
    assert cover.endswith(".jpg")

    # Served publicly so the app's <Image> can load it.
    served = client.get(icon)
    assert served.status_code == 200 and served.content == PNG

    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    p = _project(client, broker)
    assert p["Icon_URL__c"] == icon and p["Cover_Image_URL__c"] == cover
    listed = {x["Id"]: x for x in client.get("/projects", headers=broker).json()["records"]}
    assert listed["a0P001"]["Icon_URL__c"] == icon
    assert listed["a0P002"]["Icon_URL__c"] is None and listed["a0P002"]["Videos"] == []

    # Replacing drops the old file; removing clears it.
    new_icon = _upload(client, admin, "a0P001", "icon", PNG + b"2").json()["media"]["iconUrl"]
    assert new_icon != icon and client.get(icon).status_code == 404
    assert client.delete("/admin/projects/a0P001/media/icon", headers=admin).json()["media"]["iconUrl"] is None
    assert client.get(new_icon).status_code == 404


def test_uploads_are_checked(client):
    admin = bearer(admin_token(client))
    assert _upload(client, admin, "a0P001", "icon", b"<svg onload=alert(1)>", "evil.png").status_code == 400
    assert _upload(client, admin, "a0P001", "icon", b"").status_code == 400
    assert _upload(client, admin, "a0P001", "icon", PNG + b"\x00" * (1024 * 1024)).status_code == 400  # over 1 MB
    assert _upload(client, admin, "a0P001", "banner", PNG).status_code == 422
    assert _upload(client, admin, "a0P999", "icon", PNG).status_code == 404


def test_videos(client, mail):
    admin = bearer(admin_token(client))
    res = client.put(
        "/admin/projects/a0P001/videos",
        headers=admin,
        json={"videos": [
            {"title": "Walkthrough", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            {"title": "Drone view", "url": "https://vimeo.com/123456"},
        ]},
    )
    assert res.status_code == 200, res.text
    v = res.json()["media"]["videos"]
    assert v[0]["Thumbnail_URL__c"] == "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert v[1]["Thumbnail_URL__c"] is None and v[1]["URL__c"] == "https://vimeo.com/123456"

    broker = bearer(broker_token(client, mail, ABC_EMAIL))
    assert [x["Title"] for x in _project(client, broker)["Videos"]] == ["Walkthrough", "Drone view"]

    bad = client.put("/admin/projects/a0P001/videos", headers=admin, json={"videos": [{"title": "x", "url": "javascript:alert(1)"}]})
    assert bad.status_code == 400
    assert client.put("/admin/projects/a0P001/videos", headers=admin, json={"videos": [{"title": " ", "url": "https://youtu.be/dQw4w9WgXcQ"}]}).status_code == 400
    assert client.put("/admin/projects/a0P001/videos", headers=broker, json={"videos": []}).status_code == 401


def test_youtube_links():
    for url in (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtube.com/shorts/dQw4w9WgXcQ",
        "https://m.youtube.com/embed/dQw4w9WgXcQ",
    ):
        assert youtube_id(url) == "dQw4w9WgXcQ", url
    assert youtube_id("https://example.com/watch?v=dQw4w9WgXcQ") is None
