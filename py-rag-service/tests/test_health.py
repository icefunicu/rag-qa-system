from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_healthz() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_query_returns_placeholder() -> None:
    resp = client.post(
        "/v1/rag/query",
        json={
            "question": "主角第一次出场在哪一章？",
            "scope": {
                "mode": "single",
                "corpus_ids": ["abc"],
                "document_ids": [],
                "allow_common_knowledge": False,
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["answer_sentences"]) == 1
    assert body["answer_sentences"][0]["evidence_type"] == "common_knowledge"

