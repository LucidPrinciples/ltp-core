"""Adapter-test fixtures. Helpers live in ltp_adapter_testkit (uniquely named
to avoid clashing with the ltp-core suite). All offline: no network, no key."""

import pytest

from ltp_adapter_testkit import FakeOpenAI, MockLLM, crypto_entropy, make_fetch_json


@pytest.fixture
def entropy():
    return crypto_entropy


@pytest.fixture
def fetch_json():
    return make_fetch_json()


@pytest.fixture
def mock_llm():
    return MockLLM()


@pytest.fixture
def fake_openai():
    return FakeOpenAI
