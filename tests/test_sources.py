from __future__ import annotations

from fastapi.testclient import TestClient


def valid_config(name: str = "javbus") -> dict:
    return {
        "name": name,
        "enabled": True,
        "priority": 10,
        "type": "feature",
        "feature": "jav_code",
        "request": {"url": "https://www.javbus.com/{jav_code}", "method": "GET"},
        "extract": {"title": "xpath: //h3/text()"},
        "validators": [{"field": "title", "required": True}],
    }


def test_source_crud(client: TestClient) -> None:
    response = client.post("/api/sources", json=valid_config())
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["name"] == "javbus"
    assert source["builtin"] is False
    assert source["config"]["feature"] == "jav_code"

    response = client.get("/api/sources")
    assert response.json()["items"][0]["id"] == source["id"]

    updated = valid_config()
    updated["priority"] = 5
    updated["extract"]["cover_url"] = "css: .bigImage img@src"
    response = client.put(f"/api/sources/{source['id']}", json=updated)
    assert response.status_code == 200, response.text
    assert response.json()["priority"] == 5
    assert response.json()["version"] == 2

    response = client.patch(f"/api/sources/{source['id']}", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["config"]["enabled"] is False

    response = client.delete(f"/api/sources/{source['id']}")
    assert response.status_code == 204
    assert client.get("/api/sources").json()["items"] == []


def test_duplicate_source_name(client: TestClient) -> None:
    assert client.post("/api/sources", json=valid_config()).status_code == 201
    response = client.post("/api/sources", json=valid_config())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_invalid_source_config(client: TestClient) -> None:
    bad_type = valid_config()
    bad_type["type"] = "bogus"
    response = client.post("/api/sources", json=bad_type)
    assert response.status_code == 422

    bad_extract = valid_config()
    bad_extract["extract"]["title"] = "//h3/text()"
    response = client.post("/api/sources", json=bad_extract)
    assert response.status_code == 422
    assert "xpath" in response.json()["error"]["message"]


def test_missing_query_source_requires_feature(client: TestClient) -> None:
    config = valid_config()
    config["type"] = "feature"
    config.pop("feature")
    response = client.post("/api/sources", json=config)
    assert response.status_code == 422
    assert "feature" in response.json()["error"]["message"]


def test_actress_source_allowed(client: TestClient) -> None:
    config = {
        "name": "actress-demo",
        "enabled": True,
        "priority": 50,
        "type": "actress",
        "request": {"url": "https://example.com/star/{actress_name}"},
        "extract": {
            "birth_date": "css: .birth@text",
            "nationality": "css: .country@text",
        },
    }
    response = client.post("/api/sources", json=config)
    assert response.status_code == 201, response.text
    assert response.json()["config"]["type"] == "actress"
