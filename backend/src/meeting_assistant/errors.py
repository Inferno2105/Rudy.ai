"""Exception types for the pipeline.

Distinct types exist so the orchestrator can decide what to do rather than
guessing from a message string. In particular ``LLMError`` is recoverable — a
run whose Ollama stages fail is still worth keeping, because the expensive
transcription work already succeeded — whereas ``ConfigError`` means the run
should never have started.
"""


class MeetingAssistantError(Exception):
    """Base class, so callers can catch everything this package raises."""


class ConfigError(MeetingAssistantError):
    """Configuration or environment is unusable.

    Raised during pre-flight, before any expensive work begins. The message
    should always name the remediation, not just the symptom: these surface to
    someone setting the project up on a new machine, usually on Windows, and
    "ffmpeg not found" is far less useful than saying which variable to set and
    what the directory must contain.
    """


class StageError(MeetingAssistantError):
    """A pipeline stage failed.

    Carries the stage name so the manifest can record which step failed without
    parsing the message.
    """

    def __init__(self, stage: str, message: str):
        self.stage = stage
        super().__init__(f"[{stage}] {message}")


class LLMError(MeetingAssistantError):
    """The local LLM was unreachable, or returned something unusable.

    Treated as a soft failure by the orchestrator. The raw model output is
    included in the message (truncated) because a malformed response is almost
    always diagnosed by looking at what the model actually said.
    """


class ArtifactError(MeetingAssistantError):
    """A required artifact is missing, unreadable, or not what was expected."""


class ProvenanceError(MeetingAssistantError):
    """Continuing a run would mix outputs from incompatible configurations.

    Raised before anything is written, when a resume would run stages under a
    different output-affecting configuration than the run's earlier stages, or
    against a different recording than the one the run was created from. The
    run on disk is left exactly as it was: this is a refusal, not a failure.
    """
