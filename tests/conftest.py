import json
import pytest
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def v4_content():
    return load_fixture("content_v4.json")


@pytest.fixture
def v5_content():
    return load_fixture("content_v5.json")


@pytest.fixture
def schedule_old():
    return load_fixture("schedule_old.json")


@pytest.fixture
def schedule_clean():
    return load_fixture("schedule_clean.json")


@pytest.fixture
def schedule_mixed():
    return load_fixture("schedule_mixed.json")


@pytest.fixture
def tmp_schedule(tmp_path):
    return tmp_path / "schedule.json"


@pytest.fixture
def tmp_content(tmp_path):
    return tmp_path / "curriculum_content.json"
