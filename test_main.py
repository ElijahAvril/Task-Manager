import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from database import Base, get_db

# Separate, throwaway database just for tests
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(autouse=True)
def setup_and_teardown():
    Base.metadata.create_all(bind=engine)  # fresh tables before each test
    yield
    Base.metadata.drop_all(bind=engine)    # wipe them after each test

client = TestClient(app)

def test_register_user():
    response = client.post("/register", json={"username": "testuser", "password": "testpass123"})
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"
    assert "hashed_password" not in data

def test_register_duplicate_username():
    client.post("/register", json={"username": "testuser", "password": "testpass123"})
    response2 = client.post("/register", json={"username": "testuser", "password": "testpass123"})
    assert response2.status_code == 409

def test_login_success():
    client.post("/register", json={"username": "testuser", "password": "testpass123"})
    response2 = client.post("/login", data= {"username": "testuser", "password": "testpass123"})
    assert response2.status_code == 200
    assert "access_token" in response2.json()

def test_login_wrong_password():
    client.post("/register", json={"username": "testuser", "password": "testpass123"})
    response2 = client.post("/login", data= {"username": "testuser", "password": "testpass"})
    assert response2.status_code == 401

def test_create_task_requires_auth():
    response = client.post("/tasks", json={"title": "Test task", "description": "A task"})
    assert response.status_code == 401

def test_create_task_with_auth():
    client.post("/register", json={"username": "testuser", "password": "testpass123"})
    login_response = client.post("/login", data={"username": "testuser", "password": "testpass123"})
    token = login_response.json()["access_token"]

    response = client.post(
        "/tasks",
        json={"title": "Test task", "description": "A task"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Test task"

def test_user_cannot_see_others_tasks():
        alice = client.post("/register", json={"username": "alice", "password": "testpass123"})
        alice1 = client.post("/login", data={"username": "alice", "password": "testpass123"})
        alicetoken = alice1.json()["access_token"]
        response = client.post(
        "/tasks",
        json={"title": "Test task", "description": "A task"},
        headers={"Authorization": f"Bearer {alicetoken}"})
        bob = client.post("/register", json={"username": "bob", "password": "testpass12"})
        bob1 = client.post("/login", data={"username": "bob", "password": "testpass12"})
        bobtoken = bob1.json()["access_token"]
        response2 = client.get(
        "/tasks",
        headers={"Authorization": f"Bearer {bobtoken}"})
        response3 = client.get(
        "/tasks/1",
        headers={"Authorization": f"Bearer {bobtoken}"})
        assert response2.json() == []
        assert response3.status_code == 404


