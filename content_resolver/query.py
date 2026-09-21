###############################################################################
### Query gives an easy access to the data! ###################################
###############################################################################


from functools import cache

from content_resolver.utils import pkg_id_to_name


class Query:
    """Provides a high-level, cached read-only interface over resolved package data.

    All query methods accept ``None`` for any filter argument, which is treated as
    "match all".  Results are memoised with ``@cache`` / ``@lru_cache`` so repeated
    calls with the same arguments are free after the first invocation.

    Attributes:
        data: Raw resolved data dict produced by the analyser (workloads, envs, pkgs …).
        configs: Parsed YAML configuration dicts (workloads, envs, repos, views …).
        settings: Global settings dict (allowed_arches, etc.).
        computed_data: Scratch dict reserved for derived/aggregated values.
    """

    def __init__(self, data, configs, settings):
        """Initialise the Query with resolved data and configuration.

        Args:
            data: Resolved package data from the analyser.
            configs: Loaded YAML configuration objects.
            settings: Global run-time settings (e.g. ``allowed_arches``).
        """
        self.data = data
        self.configs = configs
        self.settings = settings

        self.computed_data = {}

    def size(self, num, suffix="B"):
        """Convert a byte count to a human-readable string (e.g. ``"1.2 MB"``).

        Note:
            A standalone version of this helper also lives in ``utils.py``.

        Args:
            num: Size in bytes.
            suffix: Unit suffix appended after the SI prefix (default ``"B"``).

        Returns:
            Formatted string such as ``"3.7 kB"`` or ``"1.2 TB"``.
        """
        # FIXME: is this method required or used, same function is in utils.
        for unit in ["", "k", "M", "G"]:
            if abs(num) < 1024.0:
                return f"{num:3.1f} {unit}{suffix}"
            num /= 1024.0
        return f"{num:.1f} T{suffix}"

    @cache
    def workloads(self, workload_conf_id, env_conf_id, repo_id, arch, list_all=False, output_change=None):
        """Check whether matching workloads exist, or return a list of their IDs/components.

        Accepts ``None`` for any filter argument to match all values of that dimension.
        When ``list_all=False`` (the default) the method short-circuits and returns
        ``True`` / ``False`` as soon as a match is found or exhausted.

        Args:
            workload_conf_id: Workload configuration ID to filter by, or ``None`` for all.
            env_conf_id: Environment configuration ID to filter by, or ``None`` for all.
            repo_id: Repository ID to filter by, or ``None`` for all.
            arch: Architecture to filter by, or ``None`` for all allowed arches.
            list_all: When ``True`` collect and return all matching IDs instead of a bool.
            output_change: If set, return a sorted list of a single ID component instead of
                full workload IDs.  Must be one of ``"workload_conf_ids"``,
                ``"env_conf_ids"``, ``"repo_ids"``, or ``"arches"``.

        Returns:
            ``True`` / ``False`` when ``list_all=False``, or a sorted list of ID strings /
            component strings when ``list_all=True`` or ``output_change`` is set.

        Raises:
            ValueError: If ``output_change`` is not a recognised component name.
        """
        # It can output just one part of the id.
        # That's useful to, for example, list all arches associated with a workload_conf_id
        if output_change:
            list_all = True
            if output_change not in ["workload_conf_ids", "env_conf_ids", "repo_ids", "arches"]:
                raise ValueError(
                    'output_change must be one of: "workload_conf_ids", "env_conf_ids", "repo_ids", "arches"'
                )

        matching_ids = set()

        # list considered workload_conf_ids
        workload_conf_ids = [workload_conf_id] if workload_conf_id else self.configs["workloads"].keys()

        # list considered env_conf_ids
        env_conf_ids = [env_conf_id] if env_conf_id else self.configs["envs"].keys()

        # list considered repo_ids
        repo_ids = [repo_id] if repo_id else self.configs["repos"].keys()

        # list considered arches
        arches = [arch] if arch else self.settings["allowed_arches"]

        # And now try looping through all of that, and return True on a first occurance
        # This is a terrible amount of loops. But most cases will have just one item
        # in most of those, anyway. No one is expected to run this method with
        # a "None" for every argument!
        for workload_conf_id in workload_conf_ids:
            for env_conf_id in env_conf_ids:
                for repo_id in repo_ids:
                    for arch in arches:
                        workload_id = f"{workload_conf_id}:{env_conf_id}:{repo_id}:{arch}"
                        if workload_id in self.data["workloads"].keys():
                            if not list_all:
                                return True
                            if output_change:
                                output_map = {
                                    "workload_conf_ids": workload_conf_id,
                                    "env_conf_ids": env_conf_id,
                                    "repo_ids": repo_id,
                                    "arches": arch,
                                }
                                matching_ids.add(output_map.get(output_change))
                            else:
                                matching_ids.add(workload_id)

        if not list_all:
            return False
        return sorted(matching_ids)

    @cache
    def workloads_id(self, workload_id, list_all=False, output_change=None):
        """Look up workloads using a pre-formed env or workload ID string.

        A convenience wrapper around :meth:`workloads` that accepts either a
        3-component env ID (``"env_conf_id:repo_id:arch"``) or a 4-component
        workload ID (``"workload_conf_id:env_conf_id:repo_id:arch"``).

        Args:
            workload_id: Colon-separated env or workload ID string.
            list_all: Forwarded to :meth:`workloads`.
            output_change: Forwarded to :meth:`workloads`.

        Returns:
            Same as :meth:`workloads`.

        Raises:
            ValueError: If ``id`` does not have 3 or 4 components.
        """
        id_components = workload_id.split(":")

        # It's an env!
        if len(id_components) == 3:
            env_conf_id = id_components[0]
            repo_id = id_components[1]
            arch = id_components[2]
            return self.workloads(None, env_conf_id, repo_id, arch, list_all, output_change)

        # It's a workload! Why would you want that, anyway?!
        if len(id_components) == 4:
            workload_conf_id = id_components[0]
            env_conf_id = id_components[1]
            repo_id = id_components[2]
            arch = id_components[3]
            return self.workloads(workload_conf_id, env_conf_id, repo_id, arch, list_all, output_change)

        raise ValueError("That seems to be an invalid ID!")

    @cache
    def envs(self, env_conf_id, repo_id, arch, list_all=False, output_change=None):
        """Check whether matching environments exist, or return a list of their IDs/components.

        Mirrors the behaviour of :meth:`workloads` for the environment dimension.
        Accepts ``None`` for any filter argument to match all values.

        Args:
            env_conf_id: Environment configuration ID to filter by, or ``None`` for all.
            repo_id: Repository ID to filter by, or ``None`` for all.
            arch: Architecture to filter by, or ``None`` for all allowed arches.
            list_all: When ``True`` collect and return all matching IDs instead of a bool.
            output_change: If set, return a sorted list of a single ID component.
                Must be one of ``"env_conf_ids"``, ``"repo_ids"``, or ``"arches"``.

        Returns:
            ``True`` / ``False`` when ``list_all=False``, or a sorted list of strings
            when ``list_all=True`` or ``output_change`` is set.

        Raises:
            ValueError: If ``output_change`` is not a recognised component name.
        """
        # It can output just one part of the id.
        # That's useful to, for example, list all arches associated with a workload_conf_id
        if output_change:
            list_all = True
            if output_change not in ["env_conf_ids", "repo_ids", "arches"]:
                raise ValueError('output_change must be one of: "env_conf_ids", "repo_ids", "arches"')

        matching_ids = set()

        # list considered env_conf_ids
        env_conf_ids = [env_conf_id] if env_conf_id else self.configs["envs"].keys()

        # list considered repo_ids
        repo_ids = [repo_id] if repo_id else self.configs["repos"].keys()

        # list considered arches
        arches = [arch] if arch else self.settings["allowed_arches"]

        # And now try looping through all of that, and return True on a first occurance
        # This is a terrible amount of loops. But most cases will have just one item
        # in most of those, anyway. No one is expected to run this method with
        # a "None" for every argument!
        for env_conf_id in env_conf_ids:
            for repo_id in repo_ids:
                for arch in arches:
                    env_id = f"{env_conf_id}:{repo_id}:{arch}"
                    if env_id in self.data["envs"].keys():
                        if not list_all:
                            return True
                        if output_change:
                            output_map = {
                                "env_conf_ids": env_conf_id,
                                "repo_ids": repo_id,
                                "arches": arch,
                            }
                            matching_ids.add(output_map.get(output_change))
                        else:
                            matching_ids.add(env_id)

        # This means nothing has been found!
        if not list_all:
            return False
        return sorted(list(matching_ids))

    @cache
    def envs_id(self, env_id, list_all=False, output_change=None):
        """Look up environments using a pre-formed env or workload ID string.

        A convenience wrapper around :meth:`envs` that parses a colon-separated
        3-component env ID or 4-component workload ID and extracts the env-relevant
        components before delegating.

        Args:
            env_id: Colon-separated env or workload ID string.
            list_all: Forwarded to :meth:`envs`.
            output_change: Forwarded to :meth:`envs`.

        Returns:
            Same as :meth:`envs`.

        Raises:
            ValueError: If ``id`` does not have 3 or 4 components.
        """
        id_components = env_id.split(":")

        # It's an env!
        if len(id_components) == 3:
            env_conf_id = id_components[0]
            repo_id = id_components[1]
            arch = id_components[2]
            return self.envs(env_conf_id, repo_id, arch, list_all, output_change)

        # It's a workload!
        if len(id_components) == 4:
            env_conf_id = id_components[1]
            repo_id = id_components[2]
            arch = id_components[3]
            return self.envs(env_conf_id, repo_id, arch, list_all, output_change)

        raise ValueError("That seems to be an invalid ID!")

    @cache
    def workload_pkgs(self, workload_conf_id, env_conf_id, repo_id, arch, output_change=None):
        """Return packages belonging to the matching workloads.

        By default returns a flat, sorted list of package dicts (one entry per
        ``repo_id × arch × pkg_id`` combination).  Each dict contains the standard
        RPM fields plus the following extra keys populated from workload membership:

        - ``q_in``          — ``set`` of workload IDs that include this package.
        - ``q_required_in`` — ``set`` of workload IDs where this package is explicitly
          required (top-level, listed in the workload config or arch-specific packages).
        - ``q_env_in``      — ``set`` of workload IDs where this package comes from
          the environment (not directly from the workload).
        - ``q_arch``        — Architecture string for the resolved package.

        Warning:
            Mixing multiple repos or arches (by passing ``None``) works but can
            produce confusing output when packages from different repos overlap.

        Args:
            workload_conf_id: Workload configuration ID filter, or ``None`` for all.
            env_conf_id: Environment configuration ID filter, or ``None`` for all.
            repo_id: Repository ID filter, or ``None`` for all.
            arch: Architecture filter, or ``None`` for all allowed arches.
            output_change: If set, return a sorted list of a specific field instead of
                full package dicts.  Must be one of ``"ids"``, ``"binary_names"``,
                ``"source_nvr"``, or ``"source_names"``.

        Returns:
            A sorted list of package dicts, or a sorted list of strings when
            ``output_change`` is specified.

        Raises:
            ValueError: If ``output_change`` is not a recognised value.
        """
        if output_change:
            if output_change not in ["ids", "binary_names", "source_nvr", "source_names"]:
                raise ValueError('output_change must be one of: "ids", "binary_names", "source_nvr", "source_names"')

        # Step 1: get all the matching workloads!
        workload_ids = self.workloads(workload_conf_id, env_conf_id, repo_id, arch, list_all=True)

        # I'll need repo_ids and arches to access the packages
        repo_ids = self.workloads(workload_conf_id, env_conf_id, repo_id, arch, output_change="repo_ids")
        arches = self.workloads(workload_conf_id, env_conf_id, repo_id, arch, output_change="arches")

        # Replicating the same structure as in data["pkgs"]
        # That is: [repo_id][arch][pkg_id]
        pkgs = {}
        for repo_id in repo_ids:
            pkgs[repo_id] = {}
            for arch in arches:
                pkgs[repo_id][arch] = {}

        # Workloads are already paired with envs, repos, and arches
        # (there is one for each combination)
        for workload_id in workload_ids:
            workload = self.data["workloads"][workload_id]
            workload_arch = workload["arch"]
            workload_repo_id = workload["repo_id"]
            workload_conf_id = workload["workload_conf_id"]
            workload_conf = self.configs["workloads"][workload_conf_id]

            # First, get all pkgs in the env
            for pkg_id in workload["pkg_env_ids"]:
                # Add it to the list if it's not there already.
                # Create a copy since it's gonna be modified, and include only what's needed
                pkg = self.data["pkgs"][workload_repo_id][workload_arch][pkg_id]
                if pkg_id not in pkgs[workload_repo_id][workload_arch]:
                    pkgs[workload_repo_id][workload_arch][pkg_id] = {
                        "id": pkg_id,
                        "name": pkg["name"],
                        "evr": pkg["evr"],
                        "arch": pkg["arch"],
                        "installsize": pkg["installsize"],
                        "description": pkg["description"],
                        "summary": pkg["summary"],
                        "source_name": pkg["source_name"],
                        "q_arch": workload_arch,
                        "q_in": set(),
                        "q_required_in": set(),
                        "q_env_in": set(),
                    }

                # It's here, so add it
                pkgs[workload_repo_id][workload_arch][pkg_id]["q_in"].add(workload_id)
                # Browsing env packages, so add it
                pkgs[workload_repo_id][workload_arch][pkg_id]["q_env_in"].add(workload_id)
                # Is it required?
                if (
                    pkg["name"] in self.configs["workloads"][workload_conf_id]["packages"]
                    or pkg["name"] in self.configs["workloads"][workload_conf_id]["arch_packages"][workload_arch]
                ):
                    pkgs[workload_repo_id][workload_arch][pkg_id]["q_required_in"].add(workload_id)

            # Second, add all the other packages
            for pkg_id in workload["pkg_added_ids"]:
                # Add it to the list if it's not there already
                # and initialize extra fields
                pkg = self.data["pkgs"][workload_repo_id][workload_arch][pkg_id]
                if pkg_id not in pkgs[workload_repo_id][workload_arch]:
                    pkgs[workload_repo_id][workload_arch][pkg_id] = {
                        "id": pkg_id,
                        "name": pkg["name"],
                        "evr": pkg["evr"],
                        "arch": pkg["arch"],
                        "installsize": pkg["installsize"],
                        "description": pkg["description"],
                        "summary": pkg["summary"],
                        "source_name": pkg["source_name"],
                        "q_arch": workload_arch,
                        "q_in": set(),
                        "q_required_in": set(),
                        "q_env_in": set(),
                    }

                # It's here, so add it
                pkgs[workload_repo_id][workload_arch][pkg_id]["q_in"].add(workload_id)
                # Not adding it to q_env_in
                # Is it required?
                if (
                    pkg["name"] in self.configs["workloads"][workload_conf_id]["packages"]
                    or pkg["name"] in self.configs["workloads"][workload_conf_id]["arch_packages"][workload_arch]
                ):
                    pkgs[workload_repo_id][workload_arch][pkg_id]["q_required_in"].add(workload_id)

            # Third, add package placeholders if any
            for placeholder_id in workload["pkg_placeholder_ids"]:
                placeholder = workload_conf["package_placeholders"]["pkgs"][pkg_id_to_name(placeholder_id)]
                if placeholder_id not in pkgs[workload_repo_id][workload_arch]:
                    pkgs[workload_repo_id][workload_arch][placeholder_id] = {
                        "id": placeholder_id,
                        "name": placeholder["name"],
                        "evr": "000-placeholder",
                        "arch": "placeholder",
                        "installsize": 0,
                        "description": placeholder["description"],
                        "summary": placeholder["description"],
                        "source_name": placeholder["srpm"],
                        "q_arch": workload_arch,
                        "q_in": set(),
                        "q_required_in": set(),
                        "q_env_in": set(),
                    }

                # It's here, so add it
                pkgs[workload_repo_id][workload_arch][placeholder_id]["q_in"].add(workload_id)
                # All placeholders are required
                pkgs[workload_repo_id][workload_arch][placeholder_id]["q_required_in"].add(workload_id)

        # Is it supposed to only output ids?
        if output_change:
            pkg_names = set()
            for repo_id in repo_ids:
                for arch in arches:
                    for pkg in pkgs[repo_id][arch].values():
                        output_map = {
                            "ids": pkg["id"],
                            "binary_names": pkg["name"],
                            "source_nvr": pkg["sourcerpm"],
                            "source_names": pkg["source_name"],
                        }
                        pkg_names.add(output_map.get(output_change))

            return sorted(pkg_names)

        # And now I just need to flatten that dict and return all packages as a list
        final_pkg_list = []
        for repo_id in repo_ids:
            for arch in arches:
                for pkg_id, pkg in pkgs[repo_id][arch].items():
                    final_pkg_list.append(pkg)

        # And sort them by nevr which is their ID
        return sorted(final_pkg_list, key=lambda k: k["id"])

    @cache
    def workload_pkgs_id(self, pkg_id, output_change=None):
        """Return workload packages using a pre-formed env or workload ID string.

        Parses ``id`` and delegates to :meth:`workload_pkgs`.

        Args:
            pkg_id: Colon-separated 3-component env ID or 4-component workload ID.
            output_change: Forwarded to :meth:`workload_pkgs`.

        Returns:
            Same as :meth:`workload_pkgs`.

        Raises:
            ValueError: If ``id`` does not have 3 or 4 components.
        """
        id_components = pkg_id.split(":")

        # It's an env!
        if len(id_components) == 3:
            env_conf_id = id_components[0]
            repo_id = id_components[1]
            arch = id_components[2]
            return self.workload_pkgs(None, env_conf_id, repo_id, arch, output_change)

        # It's a workload!
        if len(id_components) == 4:
            workload_conf_id = id_components[0]
            env_conf_id = id_components[1]
            repo_id = id_components[2]
            arch = id_components[3]
            return self.workload_pkgs(workload_conf_id, env_conf_id, repo_id, arch, output_change)

        raise ValueError("That seems to be an invalid ID!")

    @cache
    def env_pkgs(self, env_conf_id, repo_id, arch):
        """Return packages belonging to the matching environments.

        Returns a flat, sorted list of package dicts.  Each dict contains the
        standard RPM fields plus:

        - ``q_in``          — ``set`` of env IDs that include this package.
        - ``q_required_in`` — ``set`` of env IDs where this package is explicitly
          required (listed in the env config or its arch-specific packages).
        - ``q_arch``        — Architecture string for the resolved package.

        Warning:
            Mixing multiple repos or arches (by passing ``None``) works but can
            produce confusing output when packages from different repos overlap.

        Args:
            env_conf_id: Environment configuration ID filter, or ``None`` for all.
            repo_id: Repository ID filter, or ``None`` for all.
            arch: Architecture filter, or ``None`` for all allowed arches.

        Returns:
            A sorted list of package dicts, keyed by package NEVRA.
        """
        # Step 1: get all the matching envs!
        env_ids = self.envs(env_conf_id, repo_id, arch, list_all=True)

        # I'll need repo_ids and arches to access the packages
        repo_ids = self.envs(env_conf_id, repo_id, arch, output_change="repo_ids")
        arches = self.envs(env_conf_id, repo_id, arch, output_change="arches")

        # Replicating the same structure as in data["pkgs"]
        # That is: [repo_id][arch][pkg_id]
        pkgs = {repo_id: {arch: {} for arch in arches} for repo_id in repo_ids}

        # envs are already paired with repos, and arches
        # (there is one for each combination)
        for env_id in env_ids:
            env = self.data["envs"][env_id]
            env_arch = env["arch"]
            env_repo_id = env["repo_id"]
            env_conf_id = env["env_conf_id"]

            for pkg_id in env["pkg_ids"]:
                # Add it to the list if it's not there already.
                # Create a copy since it's gonna be modified, and include only what's needed
                pkg = self.data["pkgs"][env_repo_id][env_arch][pkg_id]
                if pkg_id not in pkgs[env_repo_id][env_arch]:
                    pkgs[env_repo_id][env_arch][pkg_id] = {
                        "id": pkg_id,
                        "name": pkg["name"],
                        "evr": pkg["evr"],
                        "arch": pkg["arch"],
                        "installsize": pkg["installsize"],
                        "description": pkg["description"],
                        "summary": pkg["summary"],
                        "source_name": pkg["source_name"],
                        "sourcerpm": pkg["sourcerpm"],
                        "q_arch": env_arch,
                        "q_in": set(),
                        "q_required_in": set(),
                    }

                # It's here, so add it
                pkgs[env_repo_id][env_arch][pkg_id]["q_in"].add(env_id)
                # Is it required?
                if pkg["name"] in self.configs["envs"][env_conf_id]["packages"]:
                    pkgs[env_repo_id][env_arch][pkg_id]["q_required_in"].add(env_id)
                if pkg["name"] in self.configs["envs"][env_conf_id]["arch_packages"][env_arch]:
                    pkgs[env_repo_id][env_arch][pkg_id]["q_required_in"].add(env_id)

        # And now I just need to flatten that dict and return all packages as a list
        final_pkg_list = []
        for repo_id in repo_ids:
            for arch in arches:
                for pkg_id, pkg in pkgs[repo_id][arch].items():
                    final_pkg_list.append(pkg)

        # And sort them by nevr which is their ID
        final_pkg_list_sorted = sorted(final_pkg_list, key=lambda k: k["id"])

        return final_pkg_list_sorted

    @cache
    def env_pkgs_id(self, pkg_id):
        """Return environment packages using a pre-formed env or workload ID string.

        Parses ``id`` and delegates to :meth:`env_pkgs`.

        Args:
            pkg_id: Colon-separated 3-component env ID or 4-component workload ID.
                When a workload ID is given only the env components are used.

        Returns:
            Same as :meth:`env_pkgs`.

        Raises:
            ValueError: If ``id`` does not have 3 or 4 components.
        """
        id_components = pkg_id.split(":")

        # It's an env!
        if len(id_components) == 3:
            env_conf_id = id_components[0]
            repo_id = id_components[1]
            arch = id_components[2]
            return self.env_pkgs(env_conf_id, repo_id, arch)

        # It's a workload!
        if len(id_components) == 4:
            env_conf_id = id_components[1]
            repo_id = id_components[2]
            arch = id_components[3]
            return self.env_pkgs(env_conf_id, repo_id, arch)

        raise ValueError("That seems to be an invalid ID!")

    @cache
    def workload_size(self, workload_conf_id, env_conf_id, repo_id, arch):
        """Return the total installed size of all packages in the matching workloads.

        Sums the ``installsize`` field across every package returned by
        :meth:`workload_pkgs` for the same filter arguments.

        Args:
            workload_conf_id: Workload configuration ID filter, or ``None`` for all.
            env_conf_id: Environment configuration ID filter, or ``None`` for all.
            repo_id: Repository ID filter, or ``None`` for all.
            arch: Architecture filter, or ``None`` for all allowed arches.

        Returns:
            Total installed size in bytes (``int``).
        """
        pkgs = self.workload_pkgs(workload_conf_id, env_conf_id, repo_id, arch)
        return sum(pkg["installsize"] for pkg in pkgs)

    @cache
    def env_size(self, env_conf_id, repo_id, arch):
        """Return the total installed size of all packages in the matching environments.

        Args:
            env_conf_id: Environment configuration ID filter, or ``None`` for all.
            repo_id: Repository ID filter, or ``None`` for all.
            arch: Architecture filter, or ``None`` for all allowed arches.

        Returns:
            Total installed size in bytes (``int``).
        """
        pkgs = self.env_pkgs(env_conf_id, repo_id, arch)
        return sum(pkg["installsize"] for pkg in pkgs)

    @cache
    def workload_size_id(self, workload_id):
        """Return the total workload size using a pre-formed env or workload ID string.

        Args:
            workload_id: Colon-separated 3-component env ID or 4-component workload ID.

        Returns:
            Total installed size in bytes (``int``).

        Raises:
            ValueError: If ``id`` does not have 3 or 4 components.
        """
        id_components = workload_id.split(":")

        # It's an env!
        if len(id_components) == 3:
            env_conf_id = id_components[0]
            repo_id = id_components[1]
            arch = id_components[2]
            return self.workload_size(None, env_conf_id, repo_id, arch)

        # It's a workload!
        if len(id_components) == 4:
            workload_conf_id = id_components[0]
            env_conf_id = id_components[1]
            repo_id = id_components[2]
            arch = id_components[3]
            return self.workload_size(workload_conf_id, env_conf_id, repo_id, arch)

        raise ValueError("That seems to be an invalid ID!")

    @cache
    def env_size_id(self, env_id):
        """Return the total environment size using a pre-formed env or workload ID string.

        Args:
            env_id: Colon-separated 3-component env ID or 4-component workload ID.

        Returns:
            Total installed size in bytes (``int``).

        Raises:
            ValueError: If ``id`` does not have 3 or 4 components.
        """
        id_components = env_id.split(":")

        # It's an env!
        if len(id_components) == 3:
            env_conf_id = id_components[0]
            repo_id = id_components[1]
            arch = id_components[2]
            return self.env_size(env_conf_id, repo_id, arch)

        # It's a workload!
        if len(id_components) == 4:
            env_conf_id = id_components[1]
            repo_id = id_components[2]
            arch = id_components[3]
            return self.env_size(env_conf_id, repo_id, arch)

        raise ValueError("That seems to be an invalid ID!")

    # TODO: these functions have similar output — create a re-usable helper function

    def workload_url_slug(self, workload_conf_id, env_conf_id, repo_id, arch):
        """Return a URL-safe slug for a workload, using ``--`` as the separator.

        Args:
            workload_conf_id: Workload configuration ID.
            env_conf_id: Environment configuration ID.
            repo_id: Repository ID.
            arch: Architecture string.

        Returns:
            Slug string e.g. ``"my-workload--my-env--fedora-eln--x86_64"``.
        """
        return f"{workload_conf_id}--{env_conf_id}--{repo_id}--{arch}"

    def env_url_slug(self, env_conf_id, repo_id, arch):
        """Return a URL-safe slug for an environment, using ``--`` as the separator.

        Args:
            env_conf_id: Environment configuration ID.
            repo_id: Repository ID.
            arch: Architecture string.

        Returns:
            Slug string e.g. ``"my-env--fedora-eln--x86_64"``.
        """
        return f"{env_conf_id}--{repo_id}--{arch}"

    def workload_id_string(self, workload_conf_id, env_conf_id, repo_id, arch):
        """Return the canonical colon-separated ID string for a workload.

        Args:
            workload_conf_id: Workload configuration ID.
            env_conf_id: Environment configuration ID.
            repo_id: Repository ID.
            arch: Architecture string.

        Returns:
            ID string e.g. ``"my-workload:my-env:fedora-eln:x86_64"``.
        """
        return f"{workload_conf_id}:{env_conf_id}:{repo_id}:{arch}"

    def env_id_string(self, env_conf_id, repo_id, arch):
        """Return the canonical colon-separated ID string for an environment.

        Args:
            env_conf_id: Environment configuration ID.
            repo_id: Repository ID.
            arch: Architecture string.

        Returns:
            ID string e.g. ``"my-env:fedora-eln:x86_64"``.
        """
        return f"{env_conf_id}:{repo_id}:{arch}"

    def url_slug_id(self, any_id):
        """Convert any colon-separated ID string to its URL-safe ``--`` slug form.

        Args:
            any_id: An env or workload ID string using ``:`` as the separator.

        Returns:
            The same string with every ``:`` replaced by ``--``.
        """
        return any_id.replace(":", "--")

    @cache
    def workloads_in_view(self, view_conf_id, arch, maintainer=None):
        """Return a sorted list of workload IDs that belong to a view.

        Filters workloads by the view's associated repository and labels, then
        optionally narrows further by maintainer.

        Args:
            view_conf_id: View configuration ID.
            arch: Architecture to filter by.  Must be a valid allowed arch or
                one that the view explicitly declares; ``None`` is not accepted.
            maintainer: If provided, only workloads owned by this maintainer are
                included.

        Returns:
            Sorted list of workload ID strings.

        Raises:
            ValueError: If ``arch`` is not in the global allowed arches list.
        """
        view_conf = self.configs["views"][view_conf_id]
        repo_id = view_conf["repository"]
        labels = view_conf["labels"]

        if arch and arch not in self.settings["allowed_arches"]:
            raise ValueError(f"Unsupported arch: {arch}")

        if arch and arch not in self.arches_in_view(view_conf_id):
            return []

        # First, get a set of workloads matching the repo and the arch
        too_many_workload_ids = set()
        workload_ids = self.workloads(None, None, repo_id, arch, list_all=True)
        too_many_workload_ids.update(workload_ids)

        # Second, limit that set further by matching the label
        final_workload_ids = set()
        for workload_id in too_many_workload_ids:
            workload = self.data["workloads"][workload_id]
            workload_conf_id = workload["workload_conf_id"]
            workload_conf = self.configs["workloads"][workload_conf_id]

            if maintainer:
                workload_maintainer = workload_conf["maintainer"]
                if workload_maintainer != maintainer:
                    continue

            workload_labels = workload["labels"]
            for workload_label in workload_labels:
                if workload_label in labels:
                    final_workload_ids.add(workload_id)

        return sorted(final_workload_ids)

    @cache
    def arches_in_view(self, view_conf_id, maintainer=None):
        """Return the list of architectures active for a view.

        If the view configuration declares an explicit ``architectures`` list,
        that list is returned.  Otherwise the global ``allowed_arches`` setting
        is used.

        Args:
            view_conf_id: View configuration ID.
            maintainer: Currently unused; reserved for future filtering.

        Returns:
            Sorted list of architecture strings.
        """
        if len(self.configs["views"][view_conf_id]["architectures"]):
            arches = self.configs["views"][view_conf_id]["architectures"]
            return sorted(arches)

        return self.settings["allowed_arches"]

    @cache
    def pkgs_in_view(self, view_conf_id, arch, output_change=None, maintainer=None):
        """Return all packages visible in a view for a given architecture.

        Aggregates packages from every workload that belongs to the view.  For
        addon views, packages already present in the base view are removed.
        Each package dict includes the standard RPM fields plus:

        - ``q_in``          — ``set`` of workload IDs that include this package.
        - ``q_required_in`` — ``set`` of workload IDs where the package is explicitly
          required (listed in the workload config or its arch-specific packages).
        - ``q_dep_in``      — ``set`` of workload IDs where the package is an indirect
          dependency (pulled in transitively, not listed explicitly).
        - ``q_env_in``      — ``set`` of workload IDs where the package originates from
          the environment.
        - ``q_maintainers`` — ``set`` of maintainer handles associated with this package.

        Args:
            view_conf_id: View configuration ID.
            arch: Architecture to resolve packages for.
            output_change: If set, return a sorted list of a specific field instead of
                full package dicts.  Must be one of ``"ids"``, ``"nevrs"``,
                ``"binary_names"``, ``"source_nvr"``, or ``"source_names"``.
            maintainer: If provided, only packages owned by this maintainer are returned.
                The ``q_*`` fields still reflect the full view context.

        Returns:
            A sorted list of package dicts, or a sorted list of strings when
            ``output_change`` is specified.

        Raises:
            ValueError: If ``output_change`` is not a recognised value.
        """
        if output_change:
            if output_change not in ["ids", "nevrs", "binary_names", "source_nvr", "source_names"]:
                raise ValueError(
                    'output_change must be one of: "ids", "nevrs", "binary_names", "source_nvr", "source_names"'
                )

        # -----
        # Step 1: get all packages from all workloads in this view
        # -----

        workload_ids = self.workloads_in_view(view_conf_id, arch)
        repo_id = self.configs["views"][view_conf_id]["repository"]

        # This has just one repo and one arch, so a flat list of IDs is enough
        pkgs = {}

        for workload_id in workload_ids:
            workload = self.data["workloads"][workload_id]
            workload_conf_id = workload["workload_conf_id"]
            workload_conf = self.configs["workloads"][workload_conf_id]

            # First, get all pkgs in the env
            for pkg_id in workload["pkg_env_ids"]:
                # Add it to the list if it's not there already.
                # Create a copy since it's gonna be modified, and include only what's needed
                pkg = self.data["pkgs"][repo_id][arch][pkg_id]
                if pkg_id not in pkgs:
                    pkgs[pkg_id] = {
                        "id": pkg_id,
                        "name": pkg["name"],
                        "evr": pkg["evr"],
                        "arch": pkg["arch"],
                        "installsize": pkg["installsize"],
                        "description": pkg["description"],
                        "summary": pkg["summary"],
                        "source_name": pkg["source_name"],
                        "sourcerpm": pkg["sourcerpm"],
                        "q_arch": arch,
                        "q_in": set(),
                        "q_required_in": set(),
                        "q_dep_in": set(),
                        "q_env_in": set(),
                        "q_maintainers": set(),
                    }

                # It's here, so add it
                pkgs[pkg_id]["q_in"].add(workload_id)
                # Browsing env packages, so add it
                pkgs[pkg_id]["q_env_in"].add(workload_id)
                # Is it required?
                if pkg["name"] in self.configs["workloads"][workload_conf_id]["packages"]:
                    pkgs[pkg_id]["q_required_in"].add(workload_id)
                if pkg["name"] in self.configs["workloads"][workload_conf_id]["arch_packages"][arch]:
                    pkgs[pkg_id]["q_required_in"].add(workload_id)

            # Second, add all the other packages
            for pkg_id in workload["pkg_added_ids"]:
                # Add it to the list if it's not there already
                # and initialize extra fields
                pkg = self.data["pkgs"][repo_id][arch][pkg_id]
                if pkg_id not in pkgs:
                    pkgs[pkg_id] = {
                        "id": pkg_id,
                        "name": pkg["name"],
                        "evr": pkg["evr"],
                        "arch": pkg["arch"],
                        "installsize": pkg["installsize"],
                        "description": pkg["description"],
                        "summary": pkg["summary"],
                        "source_name": pkg["source_name"],
                        "sourcerpm": pkg["sourcerpm"],
                        "q_arch": arch,
                        "q_in": set(),
                        "q_required_in": set(),
                        "q_dep_in": set(),
                        "q_env_in": set(),
                        "q_maintainers": set(),
                    }

                # It's here, so add it
                pkgs[pkg_id]["q_in"].add(workload_id)
                # Not adding it to q_env_in
                # Is it required?
                if pkg["name"] in self.configs["workloads"][workload_conf_id]["packages"]:
                    pkgs[pkg_id]["q_required_in"].add(workload_id)
                elif pkg["name"] in self.configs["workloads"][workload_conf_id]["arch_packages"][arch]:
                    pkgs[pkg_id]["q_required_in"].add(workload_id)
                else:
                    pkgs[pkg_id]["q_dep_in"].add(workload_id)
                # Maintainer
                pkgs[pkg_id]["q_maintainers"].add(workload_conf["maintainer"])

            # Third, add package placeholders if any
            for placeholder_id in workload["pkg_placeholder_ids"]:
                placeholder = workload_conf["package_placeholders"]["pkgs"][pkg_id_to_name(placeholder_id)]
                if placeholder_id not in pkgs:
                    pkgs[placeholder_id] = {
                        "id": placeholder_id,
                        "name": placeholder["name"],
                        "evr": "000-placeholder",
                        "arch": "placeholder",
                        "installsize": 0,
                        "description": placeholder["description"],
                        "summary": placeholder["description"],
                        "source_name": placeholder["srpm"],
                        "sourcerpm": f"{placeholder['srpm']}-000-placeholder",
                        "q_arch": arch,
                        "q_in": set(),
                        "q_required_in": set(),
                        "q_dep_in": set(),
                        "q_env_in": set(),
                        "q_maintainers": set(),
                    }

                # It's here, so add it
                pkgs[placeholder_id]["q_in"].add(workload_id)
                # All placeholders are required
                pkgs[placeholder_id]["q_required_in"].add(workload_id)
                # Maintainer
                pkgs[placeholder_id]["q_maintainers"].add(workload_conf["maintainer"])

        # -----
        # Step 2: narrow the package list down based on various criteria
        # -----

        # Is this an addon view?
        # Then I need to remove all packages that are already
        # in the base view
        view_conf = self.configs["views"][view_conf_id]
        if view_conf["type"] == "addon":
            base_view_id = view_conf["base_view_id"]

            # I always need to get all package IDs
            base_pkg_ids = self.pkgs_in_view(base_view_id, arch, output_change="ids")
            pkgs = {k: v for k, v in pkgs.items() if k not in base_pkg_ids}

        # Filtering by a maintainer?
        # Filter out packages not belonging to the maintainer
        # It's filtered out at this stage to keep the context of fields like
        # "q_required_in" etc. to be the whole view
        if maintainer:
            pkgs = {pkg_id: pkg for pkg_id, pkg in pkgs.items() if maintainer in pkg["q_maintainers"]}

        # -----
        # Step 3: Make the output to be the right format
        # -----

        # Is it supposed to only output ids?
        if output_change:
            pkg_names = set()
            for pkg in pkgs.values():
                output_map = {
                    "ids": pkg["id"],
                    "nevrs": f"{pkg['name']}-{pkg['evr']}",
                    "binary_names": pkg["name"],
                    "source_nvr": pkg["sourcerpm"],
                    "source_names": pkg["source_name"],
                }
                pkg_names.add(output_map.get(output_change))

            return sorted(pkg_names)

        # And now I just need to flatten that dict and return all packages as a list
        # And sort them by nevr which is their ID
        return sorted(pkgs.values(), key=lambda k: k["id"])

    @cache
    def view_buildroot_pkgs(self, view_conf_id, arch, output_change=None, maintainer=None):
        """Return the buildroot packages required to build sources in a view.

        Combines the base buildroot (packages always present in the build root) with
        per-SRPM build requirements declared in the buildroot configuration.  Where
        available, SRPM names resolved from ``buildroot_pkg_relations`` are attached.

        Args:
            view_conf_id: View configuration ID.
            arch: Architecture for which buildroot data is required.
            output_change: If set to ``"source_names"``, return a sorted list of
                unique SRPM names instead of the full package dict.
            maintainer: Currently unused; reserved for future filtering.

        Returns:
            A dict of ``{pkg_name: {required_by, base_buildroot, srpm_name}}``
            by default, or a sorted list of SRPM name strings when
            ``output_change="source_names"``.  Returns an empty dict / list if no
            buildroot configuration is found for the view.

        Raises:
            ValueError: If ``output_change`` is not ``"source_names"``.
        """
        if output_change:
            if output_change not in ["source_names"]:
                raise ValueError('output_change must be one of: "source_names"')

        pkgs = {}

        buildroot_conf_id = None
        for conf_id, conf in self.configs["buildroots"].items():
            if conf["view_id"] == view_conf_id:
                buildroot_conf_id = conf_id

        if not buildroot_conf_id:
            if output_change == "source_names":
                return []
            return {}

        # Populate pkgs

        base_buildroot = self.configs["buildroots"][buildroot_conf_id]["base_buildroot"][arch]
        source_pkgs = self.configs["buildroots"][buildroot_conf_id]["source_packages"][arch]

        for pkg_name in base_buildroot:
            if pkg_name not in pkgs:
                pkgs[pkg_name] = {
                    "required_by": set(),
                    "base_buildroot": True,
                    "srpm_name": None,
                }

        for srpm_name, srpm_data in source_pkgs.items():
            for pkg_name in srpm_data["requires"]:
                if pkg_name not in pkgs:
                    pkgs[pkg_name] = {
                        "required_by": set(),
                        "base_buildroot": False,
                        "srpm_name": None,
                    }
                pkgs[pkg_name]["required_by"].add(srpm_name)

        for buildroot_pkg_relations_conf in self.configs["buildroot_pkg_relations"].values():
            if view_conf_id != buildroot_pkg_relations_conf["view_id"]:
                continue

            if arch != buildroot_pkg_relations_conf["arch"]:
                continue

            buildroot_pkg_relations = buildroot_pkg_relations_conf["pkg_relations"]

            for this_pkg_id in buildroot_pkg_relations:
                this_pkg_name = pkg_id_to_name(this_pkg_id)

                if this_pkg_name in pkgs:
                    if this_pkg_id in buildroot_pkg_relations and not pkgs[this_pkg_name]["srpm_name"]:
                        pkgs[this_pkg_name]["srpm_name"] = buildroot_pkg_relations[this_pkg_id]["source_name"]

        if output_change == "source_names":
            srpms = set()

            for pkg in pkgs.values():
                if pkg["srpm_name"]:
                    srpms.add(pkg["srpm_name"])

            return sorted(srpms)

        return pkgs

    @cache
    def workload_succeeded(self, workload_conf_id, env_conf_id, repo_id, arch):
        """Return ``True`` if all matching workloads resolved successfully.

        Args:
            workload_conf_id: Workload configuration ID filter, or ``None`` for all.
            env_conf_id: Environment configuration ID filter, or ``None`` for all.
            repo_id: Repository ID filter, or ``None`` for all.
            arch: Architecture filter, or ``None`` for all allowed arches.

        Returns:
            ``True`` if every matching workload has ``succeeded=True``, otherwise
            ``False``.
        """
        workload_ids = self.workloads(workload_conf_id, env_conf_id, repo_id, arch, list_all=True)

        for workload_id in workload_ids:
            workload = self.data["workloads"][workload_id]
            if not workload["succeeded"]:
                return False
        return True

    @cache
    def workload_warnings(self, workload_conf_id, env_conf_id, repo_id, arch):
        """Return ``True`` if any matching workload has a warning message.

        Args:
            workload_conf_id: Workload configuration ID filter, or ``None`` for all.
            env_conf_id: Environment configuration ID filter, or ``None`` for all.
            repo_id: Repository ID filter, or ``None`` for all.
            arch: Architecture filter, or ``None`` for all allowed arches.

        Returns:
            ``True`` as soon as a workload with a non-empty warning message is
            found, ``False`` if none have warnings.
        """
        workload_ids = self.workloads(workload_conf_id, env_conf_id, repo_id, arch, list_all=True)

        for workload_id in workload_ids:
            workload = self.data["workloads"][workload_id]
            if workload["warnings"]["message"]:
                return True
        return False

    @cache
    def env_succeeded(self, env_conf_id, repo_id, arch):
        """Return ``True`` if all matching environments resolved successfully.

        Args:
            env_conf_id: Environment configuration ID filter, or ``None`` for all.
            repo_id: Repository ID filter, or ``None`` for all.
            arch: Architecture filter, or ``None`` for all allowed arches.

        Returns:
            ``True`` if every matching environment has ``succeeded=True``, otherwise
            ``False``.
        """
        env_ids = self.envs(env_conf_id, repo_id, arch, list_all=True)

        for env_id in env_ids:
            env = self.data["envs"][env_id]
            if not env["succeeded"]:
                return False
        return True

    @cache
    def view_succeeded(self, view_conf_id, arch, maintainer=None):
        """Return ``True`` if all workloads in a view resolved successfully.

        Args:
            view_conf_id: View configuration ID.
            arch: Architecture to check.
            maintainer: If provided, only workloads owned by this maintainer are
                considered.

        Returns:
            ``True`` if every relevant workload has ``succeeded=True``, otherwise
            ``False``.
        """
        workload_ids = self.workloads_in_view(view_conf_id, arch)

        for workload_id in workload_ids:
            workload = self.data["workloads"][workload_id]
            workload_conf_id = workload["workload_conf_id"]
            workload_conf = self.configs["workloads"][workload_conf_id]

            if maintainer:
                workload_maintainer = workload_conf["maintainer"]
                if workload_maintainer != maintainer:
                    continue

            if not workload["succeeded"]:
                return False
        return True

    def _srpm_name_to_rpm_names(self, srpm_name, repo_id):
        """Return the set of binary RPM names produced by a given SRPM in a repo.

        Searches across all architectures in the repository.

        Args:
            srpm_name: The ``source_name`` (SRPM base name) to look up.
            repo_id: Repository ID to search within.

        Returns:
            A ``set`` of binary package name strings.
        """
        all_pkgs_by_arch = self.data["pkgs"][repo_id]

        return {
            pkg["name"]
            for pkgs in all_pkgs_by_arch.values()
            for pkg in pkgs.values()
            if pkg["source_name"] == srpm_name
        }

    @cache
    def view_unwanted_pkgs(self, view_conf_id, arch, output_change=None, maintainer=None):
        """Return packages that are unwanted in a view.

        Combines two sources of unwanted packages:

        1. **Confirmed** (``unwanted_confirmed``) — packages listed directly in the
           view configuration's ``unwanted_packages``, ``unwanted_arch_packages``, and
           ``unwanted_source_packages`` fields.
        2. **Proposed** (``unwanted_proposals``) — packages referenced from separate
           unwanted-list configuration objects whose labels intersect with the view's
           labels.

        Each entry in the returned dict has the shape::

            {
                "name": str,
                "unwanted_in_view": bool,   # True if confirmed at view level
                "unwanted_list_ids": list,  # IDs of proposal lists that include it
            }

        Args:
            view_conf_id: View configuration ID.
            arch: Architecture to filter arch-specific unwanted packages, or
                ``None`` to include all architectures.
            output_change: If set, restrict which category of unwanted packages is
                included.  Must be one of ``"unwanted_proposals"`` or
                ``"unwanted_confirmed"``.  When ``None`` both categories are included.
            maintainer: If provided, only unwanted lists owned by this maintainer
                are considered for proposals.

        Returns:
            A dict of ``{pkg_name: pkg_dict}`` containing all unwanted packages.

        Raises:
            ValueError: If ``output_change`` is not a recognised value.
        """
        output_lists = ["unwanted_proposals", "unwanted_confirmed"]
        if output_change:
            if output_change not in output_lists:
                raise ValueError('output_change must be one of: "source_names"')

            output_lists = output_change

        view_conf = self.configs["views"][view_conf_id]
        repo_id = view_conf["repository"]

        # Find exclusion lists mathing this view's label(s)
        unwanted_ids = set()
        for view_label in view_conf["labels"]:
            for unwanted_id, unwanted in self.configs["unwanteds"].items():
                if maintainer:
                    unwanted_maintainer = unwanted["maintainer"]
                    if unwanted_maintainer != maintainer:
                        continue
                for unwanted_label in unwanted["labels"]:
                    if view_label == unwanted_label:
                        unwanted_ids.add(unwanted_id)

        # This will be the package list
        unwanted_pkg_names = {}

        arches = self.settings["allowed_arches"]
        if arch:
            arches = [arch]

        ### Step 1: Get packages from this view's config (unwanted confirmed)
        if "unwanted_confirmed" in output_lists:
            if not maintainer:
                for pkg_name in view_conf["unwanted_packages"]:
                    pkg = {
                        "name": pkg_name,
                        "unwanted_in_view": True,
                        "unwanted_list_ids": [],
                    }

                    unwanted_pkg_names[pkg_name] = pkg

                for arch in arches:
                    for pkg_name in view_conf["unwanted_arch_packages"][arch]:
                        if pkg_name in unwanted_pkg_names:
                            continue

                        pkg = {
                            "name": pkg_name,
                            "unwanted_in_view": True,
                            "unwanted_list_ids": [],
                        }

                        unwanted_pkg_names[pkg_name] = pkg

                for pkg_source_name in view_conf["unwanted_source_packages"]:
                    for pkg_name in self._srpm_name_to_rpm_names(pkg_source_name, repo_id):
                        if pkg_name in unwanted_pkg_names:
                            continue

                        pkg = {
                            "name": pkg_name,
                            "unwanted_in_view": True,
                            "unwanted_list_ids": [],
                        }

                        unwanted_pkg_names[pkg_name] = pkg

        ### Step 2: Get packages from the various exclusion lists (unwanted proposal)
        if "unwanted_proposals" in output_lists:
            for unwanted_id in unwanted_ids:
                unwanted_conf = self.configs["unwanteds"][unwanted_id]

                for pkg_name in unwanted_conf["unwanted_packages"]:
                    if pkg_name in unwanted_pkg_names:
                        unwanted_pkg_names[pkg_name]["unwanted_list_ids"].append(unwanted_id)
                        continue

                    pkg = {
                        "name": pkg_name,
                        "unwanted_in_view": False,
                        "unwanted_list_ids": [unwanted_id],
                    }

                    unwanted_pkg_names[pkg_name] = pkg

                for arch in arches:
                    for pkg_name in unwanted_conf["unwanted_arch_packages"][arch]:
                        if pkg_name in unwanted_pkg_names:
                            unwanted_pkg_names[pkg_name]["unwanted_list_ids"].append(unwanted_id)
                            continue

                        pkg = {
                            "name": pkg_name,
                            "unwanted_in_view": True,
                            "unwanted_list_ids": [],
                        }

                        unwanted_pkg_names[pkg_name] = pkg

                for pkg_source_name in unwanted_conf["unwanted_source_packages"]:
                    for pkg_name in self._srpm_name_to_rpm_names(pkg_source_name, repo_id):
                        if pkg_name in unwanted_pkg_names:
                            unwanted_pkg_names[pkg_name]["unwanted_list_ids"].append(unwanted_id)
                            continue

                        pkg = {
                            "name": pkg_name,
                            "unwanted_in_view": False,
                            "unwanted_list_ids": [unwanted_id],
                        }

                        unwanted_pkg_names[pkg_name] = pkg

        return unwanted_pkg_names

    @cache
    def view_placeholder_srpms(self, view_conf_id, arch):
        """Return placeholder SRPM entries declared across workloads in a view.

        Placeholder SRPMs represent sources that are expected to be built but do
        not yet exist in the repository.  Each entry aggregates the build
        requirements from all workloads that declare the same placeholder.

        Args:
            view_conf_id: View configuration ID.
            arch: Architecture to resolve against.  Must be specified (not ``None``).

        Returns:
            A dict of ``{srpm_name: {"build_requires": set}}`` where
            ``build_requires`` is the union of build requirements across all
            workloads that declare the placeholder.

        Raises:
            ValueError: If ``arch`` is ``None``.
        """
        if not arch:
            raise ValueError("arch must be specified, can't be None")

        workload_ids = self.workloads_in_view(view_conf_id, arch)

        placeholder_srpms = {}

        for workload_id in workload_ids:
            workload = self.data["workloads"][workload_id]
            workload_conf_id = workload["workload_conf_id"]
            workload_conf = self.configs["workloads"][workload_conf_id]

            for _pkg_placeholder_name, pkg_placeholder in workload_conf["package_placeholders"]["srpms"].items():
                # Placeholders can be limited to specific architectures.
                # If that's the case, check if it's available on this arch, otherwise skip it.
                if pkg_placeholder["limit_arches"]:
                    if arch not in pkg_placeholder["limit_arches"]:
                        continue

                srpm_name = pkg_placeholder["name"]

                buildrequires = pkg_placeholder["buildrequires"]

                if srpm_name not in placeholder_srpms:
                    placeholder_srpms[srpm_name] = {}
                    placeholder_srpms[srpm_name]["build_requires"] = set()

                placeholder_srpms[srpm_name]["build_requires"].update(buildrequires)

        return placeholder_srpms

    @cache
    def view_maintainers(self, view_conf_id, arch):
        """Return the set of maintainer handles for all workloads in a view.

        Args:
            view_conf_id: View configuration ID.
            arch: Architecture to resolve workloads for.

        Returns:
            A ``set`` of maintainer strings (e.g. FAS usernames).
        """
        workload_ids = self.workloads_in_view(view_conf_id, arch)

        maintainers = set()

        for workload_id in workload_ids:
            workload = self.data["workloads"][workload_id]
            workload_conf_id = workload["workload_conf_id"]
            workload_conf = self.configs["workloads"][workload_conf_id]
            maintainers.add(workload_conf["maintainer"])

        return maintainers

    @cache
    def maintainers(self):
        """Return a summary dict of all maintainers across workloads and environments.

        Each maintainer entry has the shape::

            {
                "name": str,
                "all_succeeded": bool,  # False if any workload/env they own failed
            }

        Returns:
            A dict of ``{maintainer_name: maintainer_dict}``.
        """
        maintainers = {}

        for workload_id in self.workloads(None, None, None, None, list_all=True):
            workload = self.data["workloads"][workload_id]
            workload_conf_id = workload["workload_conf_id"]
            workload_conf = self.configs["workloads"][workload_conf_id]
            maintainer = workload_conf["maintainer"]

            if maintainer not in maintainers:
                maintainers[maintainer] = {}
                maintainers[maintainer]["name"] = maintainer
                maintainers[maintainer]["all_succeeded"] = True

            if not workload["succeeded"]:
                maintainers[maintainer]["all_succeeded"] = False

        for env_id in self.envs(None, None, None, list_all=True):
            env = self.data["envs"][env_id]
            env_conf_id = env["env_conf_id"]
            env_conf = self.configs["envs"][env_conf_id]
            maintainer = env_conf["maintainer"]

            if maintainer not in maintainers:
                maintainers[maintainer] = {}
                maintainers[maintainer]["name"] = maintainer
                maintainers[maintainer]["all_succeeded"] = True

            if not env["succeeded"]:
                maintainers[maintainer]["all_succeeded"] = False

        return maintainers

    @cache
    def view_pkg_name_details(self, pkg_name, view_conf_id):
        """Return detailed information about a binary package across all arches in a view.

        Note:
            Not yet implemented.

        Args:
            pkg_name: Binary RPM name to look up.
            view_conf_id: View configuration ID.

        Raises:
            NotImplementedError: Always, until this method is implemented.
        """
        raise NotImplementedError

    @cache
    def view_srpm_name_details(self, srpm_name, view_conf_id):
        """Return detailed information about a source package across all arches in a view.

        Note:
            Not yet implemented.

        Args:
            srpm_name: Source RPM (SRPM) base name to look up.
            view_conf_id: View configuration ID.

        Raises:
            NotImplementedError: Always, until this method is implemented.
        """
        raise NotImplementedError
