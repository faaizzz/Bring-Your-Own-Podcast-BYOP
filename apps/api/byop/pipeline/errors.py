class RunStopped(Exception):
    """The run was cancelled (or ended some other way); the stage must stop now."""


class StageFailed(Exception):
    """The stage cannot succeed, retrying will not help; the message is shown to the user."""


class TransientStageError(Exception):
    """Something that may pass on its own (a provider hiccup): the stage is retried."""
