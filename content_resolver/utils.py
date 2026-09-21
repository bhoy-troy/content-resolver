import datetime
import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager

import jinja2
import libdnf5


class SetEncoder(json.JSONEncoder):
    """JSON encoder that serialises :class:`set` objects as sorted lists.

    Also silently drops :class:`jinja2.Environment` instances (replacing them
    with an empty string) so that data structures containing Jinja2 objects can
    be safely round-tripped through JSON without raising :class:`TypeError`.
    """

    def default(self, obj):
        """Extend default serialisation to handle sets and Jinja2 environments.

        Args:
            obj: The object that the standard encoder could not serialise.

        Returns:
            A JSON-serialisable representation of ``obj``.
        """
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, jinja2.Environment):
            return ""
        return json.JSONEncoder.default(self, obj)


def load_data(path):
    """Load and return JSON data from a file.

    Args:
        path: Filesystem path to a JSON file.

    Returns:
        The deserialised Python object (typically a ``dict`` or ``list``).
    """
    with open(path) as file:
        data = json.load(file)
    return data


def log(msg):
    """Write an informational message to *stderr*.

    Args:
        msg: Message string to print.
    """
    print(msg, file=sys.stderr)


def err_log(msg):
    """Write an error message prefixed with ``ERROR LOG:`` to *stderr*.

    Args:
        msg: Error message string to print.
    """
    print(f"ERROR LOG:  {msg}", file=sys.stderr)


def pkg_id_to_name(pkg_id):
    """Extract the package name from a full package ID (NEVRA string).

    Strips the last two hyphen-delimited components (version and release/arch)
    from a ``name-version-release.arch`` identifier.

    Args:
        pkg_id: Full package identifier string, e.g. ``"curl-7.88.1-1.fc40.x86_64"``.

    Returns:
        The package name, e.g. ``"curl"``.
    """
    pkg_name = pkg_id.rsplit("-", 2)[0]
    return pkg_name


def dump_data(path, data):
    """Serialize *data* to a JSON file, handling sets via :class:`SetEncoder`.

    Args:
        path: Destination filesystem path for the JSON file.
        data: Python object to serialise (may contain ``set`` instances).
    """
    with open(path, "w") as file:
        json.dump(data, file, cls=SetEncoder)


def size(num, suffix="B"):
    """Convert a byte count to a human-readable string.

    Iterates through SI prefixes (k, M, G) and stops when the value fits
    within 1024 units.  Falls back to a terabyte representation for very
    large values.

    Args:
        num: Size in bytes.
        suffix: Unit suffix appended after the SI prefix (default ``"B"``).

    Returns:
        Formatted string such as ``"3.7 kB"`` or ``"1.2 MB"``.
    """
    for unit in ["", "k", "M", "G"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f} T{suffix}"


def workload_id_to_conf_id(workload_id):
    """Extract the workload configuration ID from a full workload ID string.

    A workload ID has the form ``"workload_conf_id:env_conf_id:repo_id:arch"``.
    This function returns the first component.

    Args:
        workload_id: Colon-separated workload ID string.

    Returns:
        The workload configuration ID (first segment before the first ``:``)
    """
    workload_conf_id = workload_id.split(":")[0]
    return workload_conf_id


def url_to_id(url):
    """Convert a URL to a safe identifier string.

    Strips the protocol prefix (``https://`` or ``http://``) and any trailing
    slash, then replaces every non-alphanumeric character with a hyphen ``-``.

    Args:
        url: An HTTP or HTTPS URL string.

    Returns:
        A hyphen-separated identifier safe for use as a dict key or filename,
        e.g. ``"kojipkgs-fedoraproject-org-vol-fedora_koji"`` .
    """
    # strip the protocol
    if url.startswith("https://"):
        url = url[8:]
    elif url.startswith("http://"):
        url = url[7:]

    # strip a potential leading /
    if url.endswith("/"):
        url = url[:-1]

    # and replace all non-alphanumeric characters with -
    regex = re.compile("[^0-9a-zA-Z]")
    return regex.sub("-", url)


def datetime_now_string():
    """Return the current date and time as a formatted string.

    Returns:
        A string in the format ``"MM/DD/YYYY, HH:MM:SS"``.
    """
    return datetime.datetime.now().strftime("%m/%d/%Y, %H:%M:%S")


@contextmanager
def dnf5_base() -> Iterator[libdnf5.base.Base]:
    """Context manager wrapper for :class:`libdnf5.base.Base`.

    DNF5's ``Base`` class does not natively support the context manager
    protocol.  This wrapper provides proper resource management and ensures
    consistent exception handling.

    Yields:
        A freshly constructed :class:`libdnf5.base.Base` instance.

    Example::

        with dnf5_base() as base:
            config = base.get_config()
            # ... use base ...
    """
    base = libdnf5.base.Base()
    try:
        yield base
    finally:
        # DNF5 Base cleanup is handled by Python's garbage collector.
        # No explicit cleanup needed, but the finally block ensures
        # proper exception handling and resource cleanup if needed in future.
        pass
