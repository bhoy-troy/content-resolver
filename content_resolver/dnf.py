import libdnf5

from libdnf5.base import Base
from libdnf5.repo import Repo


# DNF5 compatibility shim - provides dnf.Base() and dnf.repo.Repo() interface
# This minimizes code changes during migration while using correct DNF5 API

class _DNF5SubstitutionsDict:
    """Dict-like wrapper around DNF5 Vars for DNF4 compatibility"""

    def __init__(self, base):
        self._base = base
        self._vars = base.get_vars()

    def __setitem__(self, key, value):
        """Support conf.substitutions['key'] = value"""
        self._vars.set(key, value)

    def __getitem__(self, key):
        """Support conf.substitutions['key']"""
        return self._vars.get_value(key)

    def get(self, key, default=None):
        """Support conf.substitutions.get('key')"""
        try:
            return self._vars.get_value(key)
        except Exception as ex:
            return default


class _DNF5ConfigAdapter:
    """Wrapper around DNF5 ConfigMain that adds DNF4-compatible substitutions"""

    def __init__(self, config, base, base_wrapper):
        self._config = config
        self._base = base
        self._base_wrapper = base_wrapper
        self.substitutions = _DNF5SubstitutionsDict(base)

    def __getattr__(self, name):
        """Forward all other attributes to the underlying config"""
        return getattr(self._config, name)

    def __setattr__(self, name, value):
        """Forward attribute setting to underlying config, except for our wrappers"""
        if name in ('_config', '_base', 'substitutions'):
            object.__setattr__(self, name, value)
        else:
            setattr(self._config, name, value)


class _DNF5RepoWrapper:
    """Wrapper around DNF5 Repo to provide DNF4-compatible attribute access"""

    def __init__(self, dnf5_repo):
        self._repo = dnf5_repo
        self._config = dnf5_repo.get_config()

    def __setattr__(self, name, value):
        """Intercept attribute setting for DNF4 compatibility"""
        if name in ('_repo', '_config'):
            object.__setattr__(self, name, value)
        elif name in ('baseurl', 'priority', 'exclude'):
            # DNF4: repo.baseurl = value
            # DNF5: repo.get_config().baseurl = value
            setattr(self._config, name, value)
        else:
            # Try setting on the repo object itself
            setattr(self._repo, name, value)

    def __getattr__(self, name):
        """Forward other attributes to the underlying repo"""
        return getattr(self._repo, name)


class _DNF5RepoAdapter:
    """Wrapper around libdnf5 RepoSack that provides DNF4-compatible methods"""

    def __init__(self, repo_sack, base):
        self._repo_sack = repo_sack
        self._base = base
        # Track created repos since DNF5 doesn't provide easy iteration
        self._created_repos = []

    def _register_repo(self, repo):
        """Internal method to track a created repo"""
        if repo not in self._created_repos:
            self._created_repos.append(repo)

    def iter_enabled(self):
        """DNF4-compatible method - iterate over enabled repos

        Returns all created repos. In DNF5, repos are created via create_repo()
        and we track them in this wrapper.
        """
        return iter(self._created_repos)

    def all(self):
        """DNF4-compatible method - get all repos

        DNF4: repos.all()
        DNF5: We track repos created via our wrapper
        """
        return self._created_repos

    def add(self, repo):
        """DNF4-compatible method - add a repo

        In DNF5, repos are added via create_repo(), so if we receive
        a _DNF5RepoWrapper, it's already been added to the sack.
        We just need to track it for iteration.
        """
        if isinstance(repo, _DNF5RepoWrapper):
            self._register_repo(repo)

    def __getattr__(self, name):
        """Forward any other attributes to the underlying repo sack"""
        return getattr(self._repo_sack, name)


class _DNF5BaseAdapter:
    """Wrapper around libdnf5.base.Base that provides DNF4-compatible interface"""

    def __init__(self):
        self._base = Base()
        # Create a conf proxy that intercepts attribute access
        self._conf_proxy = None
        self._repos_proxy = None

    @property
    def conf(self):
        """Provide DNF4-style conf attribute access with substitutions support"""
        if self._conf_proxy is None:
            raw_config = self._base.get_config()
            self._conf_proxy = _DNF5ConfigAdapter(raw_config, self._base, self)
        return self._conf_proxy

    @property
    def repos(self):
        """Provide DNF4-style repos attribute access"""
        if self._repos_proxy is None:
            self._repos_proxy = _DNF5RepoAdapter(self._base.get_repo_sack(), self._base)
        return self._repos_proxy

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # DNF5 cleanup if needed
        return False

    def __getattr__(self, name):
        """Forward any other attributes to the underlying Base object"""
        return getattr(self._base, name)


class _DNFAdapter:
    """Compatibility shim for DNF5 API - mimics old dnf module structure"""

    @staticmethod
    def Base():
        """Return DNF4-compatible Base wrapper"""
        return _DNF5BaseAdapter()

    class repo:
        @staticmethod
        def Repo(name, parent_conf):
            """Create Repo with DNF4-compatible signature

            DNF4: Repo(name, parent_conf) creates a repo that must be added later
            DNF5: repo_sack.create_repo(name) creates AND adds the repo

            We need to extract the base from our wrapped config and use create_repo.
            """
            # If parent_conf is our wrapped config, get the base and adapter
            if isinstance(parent_conf, _DNF5ConfigAdapter):
                base_wrapper = parent_conf._base_wrapper
                base = base_wrapper._base
            # If it's a raw config from a non-wrapped base, we have a problem
            # This shouldn't happen in normal usage, but handle it gracefully
            else:
                raise ValueError(
                    "DNF5 requires Base object for Repo creation, but got raw config. "
                    "Make sure you're using dnf.Base() from content_resolver.dnf"
                )

            # DNF5: use create_repo() which both creates and adds the repo
            repo_sack = base.get_repo_sack()
            dnf5_repo = repo_sack.create_repo(name)

            # Wrap it to provide DNF4-compatible attribute access
            wrapped_repo = _DNF5RepoWrapper(dnf5_repo)

            # Register it with the repos adapter for iteration
            base_wrapper.repos._register_repo(wrapped_repo)

            return wrapped_repo

    # DNF5 exception mappings - libdnf5 uses different exception hierarchy
    class exceptions:
        # Map common DNF exceptions to libdnf5 equivalents
        # In DNF5, many exceptions are in libdnf5.common module
        Error = Exception  # Generic fallback
        RepoError = libdnf5.common.RepoError if hasattr(libdnf5.common, 'RepoError') else Exception
        MarkingError = Exception  # DNF5 may not have exact equivalent
        DepsolveError = Exception  # DNF5 handles differently
        DownloadError = Exception  # DNF5 handles differently
        TransactionCheckError = Exception  # DNF5 handles differently
