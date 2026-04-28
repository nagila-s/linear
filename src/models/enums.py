from enum import Enum


class JobType(str, Enum):
    LINEARIZAR = "linearizar"
    CONTEXTUALIZAR = "contextualizar"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    PARTIAL_SUCCESS = "partial_success"
    DONE = "done"
    FAILED = "failed"
