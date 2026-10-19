"""Tests for the ASR result type.

``load_model`` and ``transcribe_audio`` themselves need a real model and are
exercised by the Phase 4 integration check (real audio, run manually / via the
``integration`` marker), not by this default-run suite. What's unit-testable
without a model is the result type's derived metrics.
"""

from __future__ import annotations

import pytest

from meeting_assistant.asr.whisper_asr import TranscriptionResult


def test_realtime_factor_below_one_means_faster_than_real_time():
    result = TranscriptionResult(
        segments=[], detected_language="en", language_probability=0.9,
        duration_sec=60.0, elapsed_sec=30.0,
    )
    assert result.realtime_factor == pytest.approx(0.5)


def test_realtime_factor_above_one_means_slower_than_real_time():
    result = TranscriptionResult(
        segments=[], detected_language="hi", language_probability=0.9,
        duration_sec=10.0, elapsed_sec=13.0,
    )
    assert result.realtime_factor == pytest.approx(1.3)


def test_realtime_factor_does_not_divide_by_zero_on_empty_audio():
    result = TranscriptionResult(
        segments=[], detected_language=None, language_probability=None,
        duration_sec=0.0, elapsed_sec=0.5,
    )
    assert result.realtime_factor == 0.0


def test_manifest_dict_has_the_reportable_fields():
    result = TranscriptionResult(
        segments=[{"start": 0, "end": 1, "text": "hi"}],
        detected_language="hi", language_probability=0.87,
        duration_sec=30.0, elapsed_sec=39.45,
    )
    manifest = result.as_manifest_dict()
    assert manifest["segments"] == 1
    assert manifest["detected_language"] == "hi"
    assert manifest["realtime_factor"] == pytest.approx(1.315)


class _FakeModel:
    """Records what transcribe_audio asks faster-whisper for."""

    def __init__(self):
        self.kwargs = None

    def transcribe(self, path, **kwargs):
        from types import SimpleNamespace

        self.kwargs = kwargs
        segment = SimpleNamespace(start=0.0, end=1.0, text=" hello ")
        return iter([segment]), SimpleNamespace(language="en", language_probability=0.9,
                                                duration=1.0)


def test_decoding_options_come_from_config_unless_given(monkeypatch):
    from meeting_assistant import config
    from meeting_assistant.asr.whisper_asr import transcribe_audio

    model = _FakeModel()
    monkeypatch.setattr(config, "WHISPER_CONDITION_ON_PREVIOUS", False)
    monkeypatch.setattr(config, "WHISPER_MULTILINGUAL", True)
    transcribe_audio(model, "a.wav")
    assert model.kwargs["condition_on_previous_text"] is False
    assert model.kwargs["multilingual"] is True

    transcribe_audio(model, "a.wav", condition_on_previous_text=True, multilingual=False)
    assert model.kwargs["condition_on_previous_text"] is True
    assert model.kwargs["multilingual"] is False


def test_decoding_options_change_the_config_hash_only_off_their_defaults(monkeypatch):
    from meeting_assistant import config, provenance

    baseline = provenance.config_hash()
    assert "whisper_multilingual" not in config.output_affecting_settings()
    monkeypatch.setattr(config, "WHISPER_MULTILINGUAL", True)
    with_multilingual = provenance.config_hash()
    monkeypatch.setattr(config, "WHISPER_CONDITION_ON_PREVIOUS", False)
    assert len({baseline, with_multilingual, provenance.config_hash()}) == 3


def test_a_batch_size_above_one_decodes_through_the_batched_pipeline(monkeypatch):
    import faster_whisper

    from meeting_assistant import config
    from meeting_assistant.asr.whisper_asr import transcribe_audio

    calls = {}

    class FakeBatched:
        def __init__(self, model):
            calls["model"] = model

        def transcribe(self, path, **kwargs):
            calls["kwargs"] = kwargs
            return _FakeModel().transcribe(path)

    monkeypatch.setattr(faster_whisper, "BatchedInferencePipeline", FakeBatched)
    model = _FakeModel()
    monkeypatch.setattr(config, "WHISPER_BATCH_SIZE", 8)

    result = transcribe_audio(model, "a.wav")

    assert calls["model"] is model and calls["kwargs"]["batch_size"] == 8
    assert model.kwargs is None  # the sequential path was not used
    assert [s["text"] for s in result.segments] == ["hello"]
    assert config.output_affecting_settings()["whisper_batch_size"] == "8"
