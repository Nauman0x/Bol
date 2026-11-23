import pytest


@pytest.mark.asyncio
async def test_create_session_and_progress(client):
    response = await client.post("/api/session", json={
        "consent": True,
        "gender": "Male",
        "age_band": "25-34",
        "region": "Lahore",
        "mother_tongue": "Urdu",
        "device": "Phone",
        "environment": "Quiet room",
        "script": "urdu",
    })
    assert response.status_code == 200
    speaker_id = response.json()["speakerId"]

    progress = await client.get("/api/progress", params={"speaker": speaker_id})
    assert progress.status_code == 200
    assert progress.json() == {"done": []}


@pytest.mark.asyncio
async def test_session_requires_consent(client):
    response = await client.post("/api/session", json={
        "consent": False,
        "gender": "Female",
        "age_band": "18-24",
        "region": "Karachi",
        "environment": "Quiet room",
    })
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_clip_contract(client, tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "voice_data_dir", str(tmp_path))

    session = await client.post("/api/session", json={
        "consent": True,
        "gender": "Female",
        "age_band": "18-24",
        "region": "Karachi",
        "mother_tongue": "Urdu",
        "device": "Laptop",
        "environment": "Quiet room",
        "script": "urdu",
    })
    speaker_id = session.json()["speakerId"]

    clip = await client.post(
        "/api/clip",
        params={"speaker": speaker_id, "sentence": "urdu_001", "duration": 2500},
        content=b"fake-webm-content",
        headers={"Content-Type": "audio/webm"},
    )
    assert clip.status_code == 200
    assert clip.json()["speakerId"] == speaker_id

    progress = await client.get("/api/progress", params={"speaker": speaker_id})
    assert progress.json() == {"done": ["urdu_001"]}
