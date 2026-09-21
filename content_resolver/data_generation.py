"""Data-file generation for the content-resolver output.

Generates JSON and plain-text artefacts that are consumed by the frontend and
by external tooling.  All public functions accept a fully-populated
:class:`~content_resolver.query.Query` object and write their output to the
directory specified in ``query.settings["output"]``.

The main entry point is :func:`generate_data_files`, which orchestrates all
individual generators.
"""

import os

from content_resolver.utils import dump_data, log


def _generate_json_file(data, page_name, settings):
    """Serialise *data* to a JSON file in the configured output directory.

    The file name is derived from *page_name* by replacing colons with ``--``
    and appending ``.json``.

    Args:
        data: Python object to serialise (sets are handled by
            :class:`~content_resolver.utils.SetEncoder`).
        page_name: Logical name of the page/dataset, used to construct the
            output filename.
        settings: Global settings dict; must contain an ``"output"`` key with
            the output directory path.
    """
    log(f"Generating the '{page_name}' JSON file...")

    output = settings["output"]

    filename = f"{page_name.replace(':', '--')}.json"
    log(f"  Writing file...  ({filename})")
    dump_data(os.path.join(output, filename), data)

    log("  Done!")
    log("")


def _generate_txt_file(data_list, file_name, settings):
    """Write a plain-text file with one list item per line.

    The file name is derived from *file_name* by replacing colons with ``--``
    and appending ``.txt``.

    Args:
        data_list: Iterable of strings to write, one per line.
        file_name: Logical name used to construct the output filename.
        settings: Global settings dict; must contain an ``"output"`` key.
    """
    file_contents = "\n".join(data_list)

    filename = f"{file_name.replace(':', '--')}.txt"

    output = settings["output"]

    log(f"  Writing file...  ({filename})")
    with open(os.path.join(output, filename), "w") as file:
        file.write(file_contents)


def _generate_view_lists(query):
    """Generate per-arch and all-arch plain-text package lists for every view.

    For each view configuration and architecture combination the following list
    types are produced:

    - ``view-all-binary-package-list`` — all RPM NEVRAs in the view
    - ``view-all-binary-package-nevr-list`` — all RPM NEVRs
    - ``view-all-binary-package-name-list`` — all RPM names
    - ``view-all-source-package-list`` — all SRPM NEVRs
    - ``view-all-source-package-name-list`` — all SRPM names
    - ``view-binary-package-list`` — runtime RPM NEVRAs
    - ``view-binary-package-nevr-list`` — runtime RPM NEVRs
    - ``view-binary-package-name-list`` — runtime RPM names
    - ``view-source-package-list`` — runtime SRPM NEVRs
    - ``view-source-package-name-list`` — runtime SRPM names
    - ``view-buildroot-package-list`` — build-root RPM NEVRAs
    - ``view-buildroot-package-nevr-list`` — build-root RPM NEVRs
    - ``view-buildroot-package-name-list`` — build-root RPM names
    - ``view-buildroot-source-package-list`` — build-root SRPM NEVRs
    - ``view-buildroot-source-package-name-list`` — build-root SRPM names

    Each list is written both as an arch-specific file (``<list>--<view>--<arch>.txt``)
    and as a combined all-arch file (``<list>--<view>.txt``).

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance.
    """
    log("Generating view lists...")

    for view_conf_id, view_conf in query.configs["views"].items():
        all_arches_lists = {}

        for arch in view_conf["architectures"]:
            view_id = f"{view_conf_id}:{arch}"
            view = query.data["views"][view_id]

            lists = {
                # all      RPM    NEVRAs      view-all-binary-package-list
                # all      RPM    NEVRs       view-all-binary-package-nevr-list
                # all      RPM    Names       view-all-binary-package-name-list
                "view-all-binary-package-list": set(),
                "view-all-binary-package-nevr-list": set(),
                "view-all-binary-package-name-list": set(),
                # all      SRPM   NEVRs       view-all-source-package-list
                # all      SRPM   Names       view-all-source-package-name-list
                "view-all-source-package-list": set(),
                "view-all-source-package-name-list": set(),
                # runtime  RPM    NEVRAs      view-binary-package-list
                # runtime  RPM    NEVRs       view-binary-package-nevr-list
                # runtime  RPM    Names       view-binary-package-name-list
                "view-binary-package-list": set(),
                "view-binary-package-nevr-list": set(),
                "view-binary-package-name-list": set(),
                # runtime  SRPM   NEVRs       view-source-package-list
                # runtime  SRPM   Names       view-source-package-name-list
                "view-source-package-list": set(),
                "view-source-package-name-list": set(),
                # build    RPM    NEVRAs      view-buildroot-package-list
                # build    RPM    NEVRs       view-buildroot-package-nevr-list
                # build    RPM    Names       view-buildroot-package-name-list
                "view-buildroot-package-list": set(),
                "view-buildroot-package-nevr-list": set(),
                "view-buildroot-package-name-list": set(),
                # build    SRPM   NEVRs       view-buildroot-source-package-list
                # build    SRPM   Names       view-buildroot-source-package-name-list
                "view-buildroot-source-package-list": set(),
                "view-buildroot-source-package-name-list": set(),
            }

            for pkg_id, pkg in view["pkgs"].items():
                lists["view-all-binary-package-list"].add(pkg_id)
                lists["view-all-binary-package-nevr-list"].add(pkg["nevr"])
                lists["view-all-binary-package-name-list"].add(pkg["name"])

                srpm_id = pkg["sourcerpm"].rsplit(".src.rpm")[0]

                lists["view-all-source-package-list"].add(srpm_id)
                lists["view-all-source-package-name-list"].add(pkg["source_name"])

                if pkg["in_workload_ids_all"]:
                    lists["view-binary-package-list"].add(pkg_id)
                    lists["view-binary-package-nevr-list"].add(pkg["nevr"])
                    lists["view-binary-package-name-list"].add(pkg["name"])

                    lists["view-source-package-list"].add(srpm_id)
                    lists["view-source-package-name-list"].add(pkg["source_name"])

                else:
                    lists["view-buildroot-package-list"].add(pkg_id)
                    lists["view-buildroot-package-nevr-list"].add(pkg["nevr"])
                    lists["view-buildroot-package-name-list"].add(pkg["name"])

                    lists["view-buildroot-source-package-list"].add(srpm_id)
                    lists["view-buildroot-source-package-name-list"].add(pkg["source_name"])

            for list_name, list_content in lists.items():
                # Generate the arch-specific lists
                file_name = f"{list_name}--{view_conf_id}--{arch}"
                _generate_txt_file(sorted(list(list_content)), file_name, query.settings)

                # Populate the all-arch lists
                if list_name not in all_arches_lists:
                    all_arches_lists[list_name] = set()
                all_arches_lists[list_name].update(list_content)

        for list_name, list_content in all_arches_lists.items():
            # Generate the all-arch lists
            file_name = f"{list_name}--{view_conf_id}"
            _generate_txt_file(sorted(list(list_content)), file_name, query.settings)

    log("Done!")
    log("")


def _generate_env_json_files(query):
    """Generate JSON data files for every environment configuration and result.

    For each environment configuration, writes:

    - A config JSON file (``env-conf--<env_conf_id>.json``) containing the raw
      configuration dict.
    - A result JSON file (``env--<env_id>.json``) for every resolved
      ``env_id``, containing the resolved data and the package query results.

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance.
    """
    log("Generating JSON files for environments...")

    # == envs
    log("")
    log("Envs:")
    for env_conf_id in query.configs["envs"].keys():
        # === Config

        log("")
        log(f"  Config for: {env_conf_id}")

        # Where to save
        data_name = f"env-conf--{query.url_slug_id(env_conf_id)}"

        # What to save
        output_data = {
            "id": env_conf_id,
            "type": "env_conf",
            "data": query.configs["envs"][env_conf_id],
        }

        # And save it
        _generate_json_file(output_data, data_name, query.settings)

        # === Results

        for env_id in query.envs(env_conf_id, None, None, list_all=True):
            log(f"  Results: {env_id}")

            # Where to save
            data_name = f"env--{query.url_slug_id(env_id)}"

            # What to save
            output_data = {
                "id": env_id,
                "type": "env",
                "data": query.data["envs"][env_id],
                "pkg_query": query.env_pkgs_id(env_id),
            }

            # And save it
            _generate_json_file(output_data, data_name, query.settings)

    log("  Done!")
    log("")


def _generate_workload_json_files(query):
    """Generate JSON data files for every workload configuration and result.

    For each workload configuration, writes:

    - A config JSON file (``workload-conf--<workload_conf_id>.json``).
    - A result JSON file (``workload--<workload_id>.json``) for every resolved
      ``workload_id``, including the package query results.

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance.
    """
    log("Generating JSON files for workloads...")

    # == Workloads
    log("")
    log("Workloads:")
    for workload_conf_id in query.configs["workloads"].keys():
        # === Config

        log("")
        log(f"  Config for: {workload_conf_id}")

        # Where to save
        data_name = f"workload-conf--{query.url_slug_id(workload_conf_id)}"

        # What to save
        output_data = {
            "id": workload_conf_id,
            "type": "workload_conf",
            "data": query.configs["workloads"][workload_conf_id],
        }

        # And save it
        _generate_json_file(output_data, data_name, query.settings)

        # === Results

        for workload_id in query.workloads(workload_conf_id, None, None, None, list_all=True):
            log(f"  Results: {workload_id}")

            # Where to save
            data_name = f"workload--{query.url_slug_id(workload_id)}"

            # What to save
            output_data = {
                "id": workload_id,
                "type": "workload",
                "data": query.data["workloads"][workload_id],
                "pkg_query": query.workload_pkgs_id(workload_id),
            }

            # And save it
            _generate_json_file(output_data, data_name, query.settings)

    log("  Done!")
    log("")


def _generate_view_json_files(query):
    """Generate JSON data files for every view configuration.

    For each view, writes three JSON files:

    - ``view-packages--<view_conf_id>.json`` — a subset of binary package
      fields (name, source name, arches, workload membership, level, etc.).
    - ``view-sources--<view_conf_id>.json`` — a subset of source package
      (SRPM) fields (name, arches, best maintainers, buildroot relationships,
      etc.).
    - ``view-workloads--<view_conf_id>.json`` — the aggregated workload data
      for the view across all architectures.

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance.
    """
    log("Generating JSON files for views...")
    for view_conf_id in query.configs["views"].keys():
        view_all_arches = query.data["views_all_arches"][view_conf_id]

        # =================================================================
        # view-packages
        # =============

        # Where to save
        data_name = f"view-packages--{query.url_slug_id(view_conf_id)}"

        log(f"  {data_name}")

        # What to save
        output_data = {
            "id": view_conf_id,
            "pkgs": {},
        }

        keys_to_save = [
            "name",
            "source_name",
            "arches_arches",
            "placeholder",
            "hard_dependency_of_pkg_nevrs",
            "weak_dependency_of_pkg_nevrs",
            "in_workload_conf_ids_req",
            "level_number",
        ]

        for pkg_id, pkg in view_all_arches["pkgs_by_nevr"].items():
            output_data["pkgs"][pkg_id] = {}

            for key in keys_to_save:
                output_data["pkgs"][pkg_id][key] = pkg[key]

        # And save it
        _generate_json_file(output_data, data_name, query.settings)

        # =================================================================
        # view-srpms (components, including ownership recommendations)
        # =============

        # Where to save
        data_name = f"view-sources--{query.url_slug_id(view_conf_id)}"

        log(f"  {data_name}")

        # What to save
        output_data = {
            "id": view_conf_id,
            "srpms": {},
        }

        keys_to_save = [
            "name",
            "arches",
            "best_maintainers",
            "level_number",
            "in_workload_conf_ids_env",
            "in_workload_conf_ids_req",
            "in_workload_conf_ids_dep",
            "in_buildroot_of_srpm_name_req",
            "in_buildroot_of_srpm_name_dep",
            "level_number",
        ]

        for srpm_name, srpm in view_all_arches["source_pkgs_by_name"].items():
            output_data["srpms"][srpm_name] = {}

            for key in keys_to_save:
                output_data["srpms"][srpm_name][key] = srpm[key]

        # And save it
        _generate_json_file(output_data, data_name, query.settings)

        # =================================================================
        # view-workloads
        # =============

        # Where to save
        data_name = f"view-workloads--{query.url_slug_id(view_conf_id)}"

        log(f"  {data_name}")

        # What to save
        output_data = {
            "id": view_conf_id,
            "workloads": view_all_arches["workloads"],
        }
        # And save it
        _generate_json_file(output_data, data_name, query.settings)

    log("  Done!")
    log("")


def _generate_maintainers_json_file(query):
    """Generate a single JSON file summarising all maintainers.

    Writes ``maintainers.json`` to the output directory using the data
    returned by :meth:`~content_resolver.query.Query.maintainers`.

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance.
    """
    log("Generating the maintainers json file...")

    maintainer_data = query.maintainers()
    _generate_json_file(maintainer_data, "maintainers", query.settings)

    log("  Done!")
    log("")


def generate_data_files(query):
    """Orchestrate generation of all data files for the current run.

    Calls each individual data-file generator in order:

    1. Plain-text view package lists (:func:`_generate_view_lists`)
    2. Environment JSON files (:func:`_generate_env_json_files`)
    3. Workload JSON files (:func:`_generate_workload_json_files`)
    4. View JSON files (:func:`_generate_view_json_files`)
    5. Maintainers JSON file (:func:`_generate_maintainers_json_file`)

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance with
            resolved data, configurations, and settings.
    """
    log("")
    log("###############################################################################")
    log("### Generating data files! ####################################################")
    log("###############################################################################")
    log("")

    # Generate the package lists for views
    _generate_view_lists(query)

    # Generate the JSON files for envs
    _generate_env_json_files(query)

    # Generate the JSON files for workloads
    _generate_workload_json_files(query)

    # Generate the JSON files for views
    _generate_view_json_files(query)

    # Generate data for the top-level results pages
    _generate_maintainers_json_file(query)
