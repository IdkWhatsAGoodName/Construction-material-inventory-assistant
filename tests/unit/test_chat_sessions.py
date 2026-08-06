from __future__ import annotations

from inventory_assistant.agent.sessions import MAX_TRANSCRIPT_TURNS, ChatSessionRegistry


def test_session_expires_after_thirty_minutes_of_inactivity() -> None:
    now = [100.0]
    registry = ChatSessionRegistry(monotonic=lambda: now[0])
    session, created = registry.get_or_create(None)
    assert created

    now[0] += 1_799
    same, created = registry.get_or_create(session.id)
    assert same is session
    assert not created

    now[0] += 1_801
    replacement, created = registry.get_or_create(session.id)
    assert created
    assert replacement.id != session.id


def test_transcript_retains_only_the_latest_twenty_turns() -> None:
    registry = ChatSessionRegistry()
    session, _ = registry.get_or_create(None)

    for index in range(MAX_TRANSCRIPT_TURNS + 2):
        session.add_turn({"user_message": f"turn-{index}"})

    assert len(session.transcript) == MAX_TRANSCRIPT_TURNS
    assert session.transcript[0]["user_message"] == "turn-2"
