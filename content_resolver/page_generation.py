"""HTML page generation for the content-resolver static site.

Renders Jinja2 templates into HTML files and writes them to the output
directory configured in ``query.settings["output"]``.

Each ``_generate_*`` helper is responsible for a specific section of the site
(workloads, environments, views, maintainers, config pages, etc.).  The main
entry point is :func:`generate_pages`, which calls all section generators in
order and also handles static-file copying and the Jinja2 environment setup.
"""

import os
import subprocess

import jinja2

from content_resolver.data_generation import _generate_json_file
from content_resolver.utils import dump_data, log


def _generate_html_page(template_name, template_data, page_name, settings):
    """Render a Jinja2 template and write the result as an HTML file.

    The output filename is derived from *page_name* by replacing colons with
    ``--``, taking only the basename (to prevent path-traversal), and appending
    ``.html``.

    Args:
        template_name: Name of the Jinja2 template file (without the ``.html``
            extension) to look up in the configured template environment.
        template_data: Dict of variables to pass to the template.  If ``None``
            or empty, an empty dict is used.  The key
            ``"global_refresh_time_started"`` is always injected automatically.
        page_name: Logical page identifier used to construct the output filename.
        settings: Global settings dict; must contain ``"output"`` (directory)
            and ``"jinja2_template_env"`` (a :class:`jinja2.Environment`).
    """
    log(f"Generating the '{page_name}' page...")

    output = settings["output"]

    template_env = settings["jinja2_template_env"]

    template = template_env.get_template(f"{template_name}.html")

    if not template_data:
        template_data = {}
    template_data["global_refresh_time_started"] = settings["global_refresh_time_started"]

    page = template.render(**template_data)

    # Prevent path traversal by extracting only the basename
    safe_page_name = os.path.basename(page_name.replace(":", "--"))
    filename = f"{safe_page_name}.html"

    log(f"  Writing file...  ({filename})")
    with open(os.path.join(output, filename), "w") as file:
        file.write(page)

    log("  Done!")
    log("")


def _generate_workload_pages(query):
    """Generate all HTML pages related to workloads.

    Produces the following page types for every applicable combination of
    workload configuration, environment, repository, and architecture:

    - **Workload overview** (``workload-overview--<workload>--<repo>``): a
      summary across all environments for a given workload/repo pair.
    - **Workload detail** (``workload--<workload_id>``): full package list for
      a single resolved workload.
    - **Workload dependencies** (``workload-dependencies--<workload_id>``):
      dependency breakdown for a single resolved workload.
    - **Compare arches** (``workload-cmp-arches--<workload>--<env>--<repo>``):
      side-by-side package comparison across architectures.
    - **Compare envs** (``workload-cmp-envs--<workload>--<repo>--<arch>``):
      side-by-side package comparison across environments.

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance.
    """
    log("Generating workload pages...")

    # Workload overview pages
    for workload_conf_id in query.workloads(None, None, None, None, output_change="workload_conf_ids"):
        for repo_id in query.workloads(workload_conf_id, None, None, None, output_change="repo_ids"):
            template_data = {
                "query": query,
                "workload_conf_id": workload_conf_id,
                "repo_id": repo_id,
            }

            page_name = f"workload-overview--{workload_conf_id}--{repo_id}"
            _generate_html_page("workload_overview", template_data, page_name, query.settings)

    # Workload detail pages
    for workload_id in query.workloads(None, None, None, None, list_all=True):
        workload = query.data["workloads"][workload_id]

        workload_conf_id = workload["workload_conf_id"]
        workload_conf = query.configs["workloads"][workload_conf_id]

        env_conf_id = workload["env_conf_id"]
        env_conf = query.configs["envs"][env_conf_id]

        repo_id = workload["repo_id"]
        repo = query.configs["repos"][repo_id]

        template_data = {
            "query": query,
            "workload_id": workload_id,
            "workload": workload,
            "workload_conf": workload_conf,
            "env_conf": env_conf,
            "repo": repo,
        }

        page_name = f"workload--{workload_id}"
        _generate_html_page("workload", template_data, page_name, query.settings)
        page_name = f"workload-dependencies--{workload_id}"
        _generate_html_page("workload_dependencies", template_data, page_name, query.settings)

    # Workload compare arches pages
    for workload_conf_id in query.workloads(None, None, None, None, output_change="workload_conf_ids"):
        for env_conf_id in query.workloads(workload_conf_id, None, None, None, output_change="env_conf_ids"):
            for repo_id in query.workloads(workload_conf_id, env_conf_id, None, None, output_change="repo_ids"):
                arches = query.workloads(workload_conf_id, env_conf_id, repo_id, None, output_change="arches")

                workload_conf = query.configs["workloads"][workload_conf_id]
                env_conf = query.configs["envs"][env_conf_id]
                repo = query.configs["repos"][repo_id]

                columns = {}
                rows = set()
                for arch in arches:
                    columns[arch] = {}

                    pkgs = query.workload_pkgs(workload_conf_id, env_conf_id, repo_id, arch)
                    for pkg in pkgs:
                        name = pkg["name"]
                        rows.add(name)
                        columns[arch][name] = pkg

                template_data = {
                    "query": query,
                    "workload_conf_id": workload_conf_id,
                    "workload_conf": workload_conf,
                    "env_conf_id": env_conf_id,
                    "env_conf": env_conf,
                    "repo_id": repo_id,
                    "repo": repo,
                    "columns": columns,
                    "rows": rows,
                }

                page_name = f"workload-cmp-arches--{workload_conf_id}--{env_conf_id}--{repo_id}"

                _generate_html_page("workload_cmp_arches", template_data, page_name, query.settings)

    # Workload compare envs pages
    for workload_conf_id in query.workloads(None, None, None, None, output_change="workload_conf_ids"):
        for repo_id in query.workloads(workload_conf_id, None, None, None, output_change="repo_ids"):
            for arch in query.workloads(workload_conf_id, None, repo_id, None, output_change="arches"):
                env_conf_ids = query.workloads(workload_conf_id, None, repo_id, arch, output_change="env_conf_ids")

                workload_conf = query.configs["workloads"][workload_conf_id]
                repo = query.configs["repos"][repo_id]

                columns = {}
                rows = set()
                for env_conf_id in env_conf_ids:
                    columns[env_conf_id] = {}

                    pkgs = query.workload_pkgs(workload_conf_id, env_conf_id, repo_id, arch)
                    for pkg in pkgs:
                        name = pkg["name"]
                        rows.add(name)
                        columns[env_conf_id][name] = pkg

                template_data = {
                    "query": query,
                    "workload_conf_id": workload_conf_id,
                    "workload_conf": workload_conf,
                    "repo_id": repo_id,
                    "repo": repo,
                    "arch": arch,
                    "columns": columns,
                    "rows": rows,
                }

                page_name = f"workload-cmp-envs--{workload_conf_id}--{repo_id}--{arch}"

                _generate_html_page("workload_cmp_envs", template_data, page_name, query.settings)

    log("  Done!")
    log("")


def _generate_env_pages(query):
    """Generate all HTML pages related to environments.

    Produces the following page types:

    - **Environment overview** (``env-overview--<env_conf_id>--<repo_id>``):
      summary across all arches for a given env/repo pair.
    - **Environment detail** (``env--<env_id>``): full package list for a
      single resolved environment.
    - **Environment dependencies** (``env-dependencies--<env_id>``): dependency
      breakdown for a single resolved environment.
    - **Compare arches** (``env-cmp-arches--<env_conf_id>--<repo_id>``):
      side-by-side package comparison across architectures.

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance.
    """
    log("Generating env pages...")

    for env_conf_id in query.envs(None, None, None, output_change="env_conf_ids"):
        for repo_id in query.envs(env_conf_id, None, None, output_change="repo_ids"):
            template_data = {
                "query": query,
                "env_conf_id": env_conf_id,
                "repo_id": repo_id,
            }

            page_name = f"env-overview--{env_conf_id}--{repo_id}"
            _generate_html_page("env_overview", template_data, page_name, query.settings)

    # env detail pages
    for env_id in query.envs(None, None, None, list_all=True):
        env = query.data["envs"][env_id]

        env_conf_id = env["env_conf_id"]
        env_conf = query.configs["envs"][env_conf_id]

        repo_id = env["repo_id"]
        repo = query.configs["repos"][repo_id]

        template_data = {
            "query": query,
            "env_id": env_id,
            "env": env,
            "env_conf": env_conf,
            "repo": repo,
        }

        page_name = f"env--{env_id}"
        _generate_html_page("env", template_data, page_name, query.settings)

        page_name = f"env-dependencies--{env_id}"
        _generate_html_page("env_dependencies", template_data, page_name, query.settings)

    # env compare arches pages
    for env_conf_id in query.envs(None, None, None, output_change="env_conf_ids"):
        for repo_id in query.envs(env_conf_id, None, None, output_change="repo_ids"):
            arches = query.envs(env_conf_id, repo_id, None, output_change="arches")

            env_conf = query.configs["envs"][env_conf_id]
            repo = query.configs["repos"][repo_id]

            columns = {}
            rows = set()
            for arch in arches:
                columns[arch] = {}

                pkgs = query.env_pkgs(env_conf_id, repo_id, arch)
                for pkg in pkgs:
                    name = pkg["name"]
                    rows.add(name)
                    columns[arch][name] = pkg

            template_data = {
                "query": query,
                "env_conf_id": env_conf_id,
                "env_conf": env_conf,
                "repo_id": repo_id,
                "repo": repo,
                "columns": columns,
                "rows": rows,
            }

            page_name = f"env-cmp-arches--{env_conf_id}--{repo_id}"

            _generate_html_page("env_cmp_arches", template_data, page_name, query.settings)

    log("  Done!")
    log("")


def _generate_maintainer_pages(query):
    """Generate HTML overview and workload pages for every maintainer.

    For each maintainer, produces:

    - ``maintainer--<maintainer>`` — overview page listing all their
      workloads/environments and their success status.
    - ``maintainer-workloads--<maintainer>`` — detailed workload listing for
      the maintainer.

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance.
    """
    log("Generating maintainer pages...")

    for maintainer in query.maintainers():
        template_data = {
            "query": query,
            "maintainer": maintainer,
        }

        # Overview page
        page_name = f"maintainer--{maintainer}"
        _generate_html_page("maintainer_overview", template_data, page_name, query.settings)

        # My Workloads page
        page_name = f"maintainer-workloads--{maintainer}"
        _generate_html_page("maintainer_workloads", template_data, page_name, query.settings)

    log("  Done!")
    log("")


def _generate_config_pages(query):
    """Generate HTML pages for all YAML configuration objects.

    Produces index pages for each configuration type (repos, envs, workloads,
    labels, views, unwanteds) as well as individual detail pages for each
    configuration entry.

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance.
    """
    log("Generating config pages...")

    for conf_type in ["repos", "envs", "workloads", "labels", "views", "unwanteds"]:
        template_data = {
            "query": query,
            "conf_type": conf_type,
        }
        page_name = f"configs_{conf_type}"
        _generate_html_page("configs", template_data, page_name, query.settings)

    # Config repo pages
    for repo_id, repo_conf in query.configs["repos"].items():
        template_data = {
            "query": query,
            "repo_conf": repo_conf,
        }
        page_name = f"config-repo--{repo_id}"
        _generate_html_page("config_repo", template_data, page_name, query.settings)

    # Config env pages
    for env_conf_id, env_conf in query.configs["envs"].items():
        template_data = {
            "query": query,
            "env_conf": env_conf,
        }
        page_name = f"config-env--{env_conf_id}"
        _generate_html_page("config_env", template_data, page_name, query.settings)

    # Config workload pages
    for workload_conf_id, workload_conf in query.configs["workloads"].items():
        template_data = {
            "query": query,
            "workload_conf": workload_conf,
        }
        page_name = f"config-workload--{workload_conf_id}"
        _generate_html_page("config_workload", template_data, page_name, query.settings)

    # Config label pages
    for label_conf_id, label_conf in query.configs["labels"].items():
        template_data = {"query": query, "label_conf": label_conf}
        page_name = f"config-label--{label_conf_id}"
        _generate_html_page("config_label", template_data, page_name, query.settings)

    # Config view pages
    for view_conf_id, view_conf in query.configs["views"].items():
        template_data = {"query": query, "view_conf": view_conf}
        page_name = f"config-view--{view_conf_id}"
        _generate_html_page("config_view", template_data, page_name, query.settings)

    # Config unwanted pages
    for unwanted_conf_id, unwanted_conf in query.configs["unwanteds"].items():
        template_data = {"query": query, "unwanted_conf": unwanted_conf}
        page_name = f"config-unwanted--{unwanted_conf_id}"
        _generate_html_page("config_unwanted", template_data, page_name, query.settings)

    log("  Done!")
    log("")


def _generate_repo_pages(query):
    """Generate per-arch HTML detail pages for every repository.

    Each page is named ``repo--<repo_id>--<arch>``.

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance.
    """
    log("Generating repo pages...")

    for repo_id, repo in query.configs["repos"].items():
        for arch in repo["source"]["architectures"]:
            template_data = {
                "query": query,
                "repo": repo,
                "arch": arch,
            }
            page_name = f"repo--{repo_id}--{arch}"
            _generate_html_page("repo", template_data, page_name, query.settings)

    log("  Done!")
    log("")


def _generate_view_pages(query):
    """Generate all HTML pages related to views.

    For each view configuration, produces:

    - ``view--<view_conf_id>`` — overview page.
    - ``view-packages--<view_conf_id>`` — full binary package listing.
    - ``view-sources--<view_conf_id>`` — full source package (SRPM) listing.
    - ``view-unwanted--<view_conf_id>`` — unwanted package listing.
    - ``view-workloads--<view_conf_id>`` — workload breakdown.
    - ``view-errors--<view_conf_id>`` — resolution error listing.
    - ``view-rpm--<view_conf_id>--<pkg_name>`` — per-RPM detail page and JSON.
    - ``view-srpm--<view_conf_id>--<srpm_name>`` — per-SRPM detail page and JSON.

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance.
    """
    log("Generating view pages... (the new function)")

    for view_conf_id, view_conf in query.configs["views"].items():
        # Common data
        view_all_arches = query.data["views_all_arches"][view_conf_id]
        template_data = {
            "query": query,
            "view_conf": view_conf,
            "view_all_arches": view_all_arches,
        }

        # Generate the overview page
        page_name = f"view--{view_conf_id}"
        _generate_html_page("view_overview", template_data, page_name, query.settings)

        # Generate the packages page
        page_name = f"view-packages--{view_conf_id}"
        _generate_html_page("view_packages", template_data, page_name, query.settings)

        # Generate the source packages page
        page_name = f"view-sources--{view_conf_id}"
        _generate_html_page("view_sources", template_data, page_name, query.settings)

        # Generate the unwanted packages page
        page_name = f"view-unwanted--{view_conf_id}"
        _generate_html_page("view_unwanted", template_data, page_name, query.settings)

        # Generate the workloads page
        page_name = f"view-workloads--{view_conf_id}"
        _generate_html_page("view_workloads", template_data, page_name, query.settings)

        # Generate the errors page
        page_name = f"view-errors--{view_conf_id}"
        _generate_html_page("view_errors", template_data, page_name, query.settings)

        # Generate the arch lists
        for arch in view_conf["architectures"]:
            view_id = f"{view_conf_id}:{arch}"

            view = query.data["views"][view_id]

            template_data = {
                "query": query,
                "view_conf": view_conf,
                "view": view,
                "arch": arch,
            }
            page_name = f"view--{view_conf_id}--{arch}"

        # Generate the RPM pages
        for pkg_name, pkg in view_all_arches["pkgs_by_name"].items():
            template_data = {
                "query": query,
                "view_conf": view_conf,
                "view_all_arches": view_all_arches,
                "pkg": pkg,
            }
            page_name = f"view-rpm--{view_conf_id}--{pkg_name}"
            _generate_html_page("view_rpm", template_data, page_name, query.settings)
            _generate_json_file(pkg, page_name, query.settings)

        # Generate the SRPM pages
        for srpm_name, srpm in view_all_arches["source_pkgs_by_name"].items():
            template_data = {
                "query": query,
                "view_conf": view_conf,
                "view_all_arches": view_all_arches,
                "srpm": srpm,
            }
            page_name = f"view-srpm--{view_conf_id}--{srpm_name}"
            _generate_html_page("view_srpm", template_data, page_name, query.settings)
            _generate_json_file(srpm, page_name, query.settings)


def _dump_all_data(query):
    """Serialize the full query state (data, configs, settings) to ``data.json``.

    This is a diagnostic/debugging helper.  It is currently disabled in
    :func:`generate_pages` because the output can be very large.

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance.
    """
    log("Dumping all data...")

    data = {
        "data": query.data,
        "configs": query.configs,
        "settings": query.settings,
        "computed_data": query.computed_data,
    }
    file_name = "data.json"
    file_path = os.path.join(query.settings["output"], file_name)
    dump_data(file_path, data)

    log("  Done!")
    log("")


def generate_pages(query):
    """Orchestrate generation of the complete static HTML site.

    Sets up the Jinja2 template environment, copies static assets, then calls
    each section generator in order:

    1. Jinja2 environment initialisation + static file copy
    2. Landing page (``index.html``) and results page
    3. Configuration pages (:func:`_generate_config_pages`)
    4. Top-level listing pages (repos, envs, workloads, labels, views,
       maintainers)
    5. Repository pages (:func:`_generate_repo_pages`)
    6. Maintainer pages (:func:`_generate_maintainer_pages`)
    7. Environment pages (:func:`_generate_env_pages`)
    8. Workload pages (:func:`_generate_workload_pages`)
    9. View pages (:func:`_generate_view_pages`)
    10. Errors page

    Args:
        query: Populated :class:`~content_resolver.query.Query` instance with
            resolved data, configurations, and settings (including
            ``"output"`` and ``"global_refresh_time_started"``).
    """
    log("")
    log("###############################################################################")
    log("### Generating html pages! ####################################################")
    log("###############################################################################")
    log("")

    # Create the jinja2 thingy
    template_loader = jinja2.FileSystemLoader(searchpath="./templates/")
    template_env = jinja2.Environment(
        loader=template_loader,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    query.settings["jinja2_template_env"] = template_env

    # Copy static files
    log("Copying static files...")
    src_static_dir = os.path.join("templates", "_static")
    output_static_dir = os.path.join(query.settings["output"])
    subprocess.run(["cp", "-R", src_static_dir, output_static_dir])
    log("  Done!")
    log("")

    # Generate the landing page
    _generate_html_page("homepage", None, "index", query.settings)

    # Generate the main menu page
    _generate_html_page("results", None, "results", query.settings)

    # Generate config pages
    _generate_config_pages(query)

    # Generate the top-level results pages
    template_data = {
        "query": query,
    }
    _generate_html_page("repos", template_data, "repos", query.settings)
    _generate_html_page("envs", template_data, "envs", query.settings)
    _generate_html_page("workloads", template_data, "workloads", query.settings)
    _generate_html_page("labels", template_data, "labels", query.settings)
    _generate_html_page("views", template_data, "views", query.settings)
    _generate_html_page("maintainers", template_data, "maintainers", query.settings)

    # Generate repo pages
    _generate_repo_pages(query)

    # Generate maintainer pages
    _generate_maintainer_pages(query)

    # Generate env_overview pages
    _generate_env_pages(query)

    # Generate workload_overview pages
    _generate_workload_pages(query)

    # Generate view pages
    _generate_view_pages(query)

    # Dump all data
    # The data is now pretty huge and not really needed anyway
    # if not query.settings["use_cache"]:
    #    _dump_all_data(query)

    # Generate the errors page
    template_data = {
        "query": query,
    }
    _generate_html_page("errors", template_data, "errors", query.settings)
