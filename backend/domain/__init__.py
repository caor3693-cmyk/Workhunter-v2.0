"""Business vocabulary shared by sources, services, storage and API."""

KINDS = ("campus_talk", "job_fair", "online_recruitment", "announcement")
FIELD_STATES = (
    "known", "not_collected", "pending_extraction", "parse_failed",
    "not_disclosed", "not_applicable", "conflict",
)
VIEWS = ("recent", "upcoming", "history", "undated")
SCOPES = ("electrical", "all")
