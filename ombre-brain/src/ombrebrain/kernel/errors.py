class OmbreError(Exception):
    code = "ombre_error"


class ConfigError(OmbreError):
    code = "config_error"


class CapabilityLoadError(OmbreError):
    code = "capability_load_error"


class PolicyViolation(OmbreError):
    code = "policy_violation"


class ClusterUnavailable(OmbreError):
    code = "cluster_unavailable"


class NotLeader(OmbreError):
    code = "not_leader"


class QuorumTimeout(OmbreError):
    code = "quorum_timeout"


class LogIntegrityError(OmbreError):
    code = "log_integrity_error"


class SnapshotRestoreError(OmbreError):
    code = "snapshot_restore_error"


class VectorRebuildError(OmbreError):
    code = "vector_rebuild_error"


class HotUpdateRejected(OmbreError):
    code = "hot_update_rejected"


class MigrationFailed(OmbreError):
    code = "migration_failed"
