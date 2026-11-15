"""Git error and local command budget without loading the adapter."""


class GitError(RuntimeError):
    pass


LOCAL_GIT_TIMEOUT_SECONDS = 30
