"""Shared flow error contract, also exported from pipeline for compatibility."""


class PipelineError(RuntimeError):
    pass


class ApprovalRequired(PipelineError):
    pass


class ProviderInputTooLarge(PipelineError):
    pass


class ProviderTimeoutError(PipelineError):
    pass


class ProviderCapacityError(PipelineError):
    pass


class ProviderRequestLimitError(PipelineError):
    pass


class VerificationInputsChanged(PipelineError):
    pass
