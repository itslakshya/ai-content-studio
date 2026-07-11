# tests/test_agents.py
# Run: pytest tests/test_agents.py -v

import pytest
import uuid
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from agents.state import create_initial_state
from agents.supervisor_agent import supervisor_node
from agents.graph import build_graph


def test_initial_state_defaults():
    state = create_initial_state(
        topic="AI in Healthcare",
        tone="professional",
        target_platforms=["blog", "linkedin"],
        session_id=str(uuid.uuid4()),
    )
    assert state["topic"] == "AI in Healthcare"
    assert state["tone"] == "professional"
    assert state["rewrite_count"] == 0
    assert state["hitl_status"] == "pending"
    assert state["needs_rewrite"] == False
    assert state["critique_score"] == 0.0
    assert state["blog_post"] == ""
    assert state["sources"] == []


def test_state_with_context():
    state = create_initial_state(
        topic="LangGraph tutorial",
        tone="educational",
        target_platforms=["blog"],
        session_id="test-123",
        additional_context="Focus on Python examples",
    )
    assert state["additional_context"] == "Focus on Python examples"
    assert state["session_id"] == "test-123"


def test_supervisor_valid_input():
    state = create_initial_state(
        topic="Generative AI trends",
        tone="professional",
        target_platforms=["blog", "twitter"],
        session_id=str(uuid.uuid4()),
    )
    result = supervisor_node(state)
    assert result.get("error") is None
    assert result.get("current_agent") == "research"
    assert len(result.get("search_queries_used", [])) > 0


def test_supervisor_empty_topic():
    state = create_initial_state(
        topic="",
        tone="professional",
        target_platforms=["blog"],
        session_id=str(uuid.uuid4()),
    )
    result = supervisor_node(state)
    assert result.get("error") is not None
    assert "Topic" in result["error"]


def test_supervisor_short_topic():
    state = create_initial_state(
        topic="AI",
        tone="professional",
        target_platforms=["blog"],
        session_id=str(uuid.uuid4()),
    )
    result = supervisor_node(state)
    assert result.get("error") is not None


def test_supervisor_unknown_tone_normalizes():
    state = create_initial_state(
        topic="AI in Healthcare",
        tone="sarcastic",
        target_platforms=["blog"],
        session_id=str(uuid.uuid4()),
    )
    result = supervisor_node(state)
    assert result.get("error") is None


def test_graph_compiles():
    graph = build_graph()
    assert graph is not None