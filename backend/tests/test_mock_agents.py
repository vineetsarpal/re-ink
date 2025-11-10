import os
import sys
from pathlib import Path

# Configure environment before importing application modules
TEST_DB_PATH = Path("test_agents.db")
os.environ["SECRET_KEY"] = "test-secret"
os.environ["LANDINGAI_API_KEY"] = "dummy-key"
os.environ["DATABASE_URL"] = f"sqlite:///./{TEST_DB_PATH.name}"
os.environ["AGENT_OFFLINE_MODE"] = "true"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.main import app  # noqa: E402
from app.db.database import Base, get_db  # noqa: E402


client: TestClient | None = None
TestingSessionLocal: sessionmaker | None = None
test_engine = None


def setup_module(_: object) -> None:
    """Ensure a clean SQLite database prior to running tests."""
    global client, TestingSessionLocal, test_engine
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    test_engine = create_engine(
        f"sqlite:///./{TEST_DB_PATH.name}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    def get_test_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = get_test_db
    client = TestClient(app)


def teardown_module(_: object) -> None:
    """Delete the temporary SQLite database after tests complete."""
    global client, TestingSessionLocal, test_engine
    if client is not None:
        client.close()
        client = None
    app.dependency_overrides.pop(get_db, None)
    if test_engine is not None:
        test_engine.dispose()
        test_engine = None
    TestingSessionLocal = None
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def test_mock_agent_flow_offline():
    assert client is not None
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
