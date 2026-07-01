def test_mock_agent_flow_offline(client):
    # Seed a mock extraction job
    job_resp = client.post("/api/documents/mock-job", json={"job_id": "mock-agent-job"})
    assert job_resp.status_code == 200
    job_payload = job_resp.json()
    assert job_payload["status"] == "completed"
    job_id = job_payload["job_id"]

    # Run guided intake agent against the mock job
    intake_resp = client.post(
        "/api/agents/intake",
        json={
            "job_id": job_id,
            "user_input": "Is this contract ready for approval?",
            "chat_history": [],
        },
    )
    assert intake_resp.status_code == 200
    intake_data = intake_resp.json()
    assert intake_data["status"] == "ready"
    assert intake_data["analysis"]["summary"].startswith("Offline analysis")
    assert intake_data["suggested_review_payload"] is not None

    review_payload = intake_data["suggested_review_payload"]

    # Approve the suggested payload to create records in the database
    approve_resp = client.post("/api/review/approve", json=review_payload)
    assert approve_resp.status_code == 200
    approval_data = approve_resp.json()
    contract_id = approval_data["contract_id"]
    assert contract_id > 0

    # Run automated review agent offline
    review_agent_resp = client.post(
        "/api/agents/review",
        json={
            "contract_id": contract_id,
            "user_input": "Provide an offline compliance summary.",
            "chat_history": [],
        },
    )
    assert review_agent_resp.status_code == 200
    review_data = review_agent_resp.json()
    assert review_data["status"] == "complete"
    assert review_data["analysis"]["summary"].startswith("Offline review summary")
    assert isinstance(review_data["analysis"]["recommended_actions"], list)
