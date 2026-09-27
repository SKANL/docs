"""Temporary compatibility facade for the former generic X20 persistence module.

New runtime code imports semantic persistence modules directly. This module keeps
legacy imports stable while downstream callers migrate.
"""

from docs.infrastructure.persistence import redis_job_queue as _redis_job_queue
from docs.infrastructure.persistence.filesystem_blob_store import FilesystemBlobStore
from docs.infrastructure.persistence.redis_job_queue import RedisJobQueue
from docs.infrastructure.persistence.sqlite_runtime import (
    SQLiteArtifactStore,
    SqliteArtifactStore,
    SqliteFindingStore,
    SQLiteGraphStore,
    SqliteGraphStore,
    SQLiteJobQueue,
    SqliteJobQueue,
    SQLiteLeaseStore,
    SqliteLeaseStore,
    SQLitePassportStore,
    SqlitePassportStore,
    SqlitePublicationStore,
    SQLiteRunStore,
    SqliteRunStore,
)

_REDIS_ACK_SCRIPT = _redis_job_queue._REDIS_ACK_SCRIPT
_REDIS_CLAIM_SCRIPT = _redis_job_queue._REDIS_CLAIM_SCRIPT
_REDIS_QUARANTINE_SCRIPT = _redis_job_queue._REDIS_QUARANTINE_SCRIPT

__all__ = [
    "FilesystemBlobStore",
    "RedisJobQueue",
    "SQLiteArtifactStore",
    "SQLiteGraphStore",
    "SQLiteJobQueue",
    "SQLiteLeaseStore",
    "SQLitePassportStore",
    "SQLiteRunStore",
    "SqliteArtifactStore",
    "SqliteFindingStore",
    "SqliteGraphStore",
    "SqliteJobQueue",
    "SqliteLeaseStore",
    "SqlitePassportStore",
    "SqlitePublicationStore",
    "SqliteRunStore",
]
