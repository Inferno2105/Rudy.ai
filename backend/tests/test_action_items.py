"""Tests for LLM-based action-item extraction, against a fake LLM transport."""

from __future__ import annotations

from meeting_assistant.intel.action_items import extract_action_items


def _segments():
    return [
        {
            "start": 0,
            "speaker": "SPEAKER_00",
            "text": "Diya, can you finish the frontend by Friday?",
        },
        {"start": 5, "speaker": "SPEAKER_01", "text": "Yes, I'll get it done."},
    ]


def test_successful_extraction_normalizes_every_key(fake_llm):
    client, _ = fake_llm(
        [
            '{"action_items": [{"person": "Diya", "task": "finish the frontend", '
            '"deadline": "Friday", "status": null}]}'
        ]
    )
    result = extract_action_items(_segments(), client)

    assert result.ok is True
    assert result.action_items == [
        {"person": "Diya", "task": "finish the frontend", "deadline": "Friday", "status": None}
    ]


def test_missing_keys_are_filled_in_as_none(fake_llm):
    """Downstream code must be able to rely on all four keys always being present."""
    client, _ = fake_llm(['{"action_items": [{"task": "review the PR"}]}'])
    result = extract_action_items(_segments(), client)

    assert result.action_items == [
        {"person": None, "task": "review the PR", "deadline": None, "status": None}
    ]


def test_empty_action_items_is_a_valid_result_not_a_failure(fake_llm):
    """A meeting with no concrete assignments is a correct, not a suspicious, outcome."""
    client, _ = fake_llm(['{"action_items": []}'])
    result = extract_action_items(_segments(), client)
    assert result.ok is True
    assert result.action_items == []


def test_item_with_no_task_text_is_dropped():
    from meeting_assistant.intel.action_items import _normalize_item

    normalized = _normalize_item({"person": "A", "task": "", "deadline": None, "status": None})
    assert normalized["task"] == ""


def test_items_with_no_task_text_are_filtered_out_of_the_result(fake_llm):
    """The prompt forbids empty tasks, but a model can still emit one -- must be junk-filtered."""
    client, _ = fake_llm(
        [
            '{"action_items": ['
            '{"person": "A", "task": "real work", "deadline": null, "status": null},'
            '{"person": "B", "task": "", "deadline": null, "status": null}'
            "]}"
        ]
    )
    result = extract_action_items(_segments(), client)
    assert len(result.action_items) == 1
    assert result.action_items[0]["task"] == "real work"


def test_non_dict_items_in_the_list_are_ignored_rather_than_crashing(fake_llm):
    client, _ = fake_llm(['{"action_items": ["not a dict", 5, null]}'])
    result = extract_action_items(_segments(), client)
    assert result.action_items == []
    assert result.ok is True


def test_malformed_llm_response_is_a_soft_failure(fake_llm):
    client, _ = fake_llm(["no json here"])
    result = extract_action_items(_segments(), client)
    assert result.ok is False
    assert result.error is not None
    assert result.action_items == []


def test_empty_transcript_short_circuits_without_calling_the_model(fake_llm):
    client, transport = fake_llm(["unused"])
    result = extract_action_items([], client)
    assert result.ok is True
    assert result.action_items == []
    assert transport.prompts == []


def test_as_dict_matches_the_artifact_contract(fake_llm):
    client, _ = fake_llm(['{"action_items": []}'])
    result = extract_action_items(_segments(), client)
    assert result.as_dict() == {"action_items": []}


def test_prompt_version_is_recorded(fake_llm):
    client, _ = fake_llm(['{"action_items": []}'])
    result = extract_action_items(_segments(), client)
    assert result.prompt_version == "action_items_v1"


def test_falls_back_to_speaker_label_when_no_name_is_mentioned(fake_llm):
    """The prompt's own rule: use the speaker label rather than inventing a name."""
    client, _ = fake_llm(
        [
            '{"action_items": [{"person": "SPEAKER_01", "task": "send the report", '
            '"deadline": null, "status": null}]}'
        ]
    )
    result = extract_action_items(_segments(), client)
    assert result.action_items[0]["person"] == "SPEAKER_01"


def test_manifest_dict_reports_count_and_status(fake_llm):
    client, _ = fake_llm(
        ['{"action_items": [{"person": null, "task": "x", "deadline": null, "status": null}]}']
    )
    result = extract_action_items(_segments(), client)
    manifest = result.as_manifest_dict()
    assert manifest["count"] == 1
    assert manifest["ok"] is True
