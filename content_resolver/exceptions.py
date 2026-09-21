class SettingsError(Exception):
    """Raised when a required global setting is missing or invalid.

    Currently, settings are largely hard-coded; this exception is reserved for
    future validation of the settings dict passed to the analyser.
    """


class ConfigError(Exception):
    """Raised when a user-provided YAML configuration file is invalid.

    Examples include missing required keys, wrong value types, or referencing
    an unknown repository / environment / workload.
    """


class RepoDownloadError(Exception):
    """Raised when repository metadata cannot be downloaded or parsed."""


class BuildGroupAnalysisError(Exception):
    """Raised when the buildroot build-group configuration cannot be processed."""


class KojiRootLogError(Exception):
    """Raised when a Koji root.log file cannot be fetched or parsed."""


class AnalysisError(Exception):
    """Raised for general errors that occur during the package resolution analysis."""
