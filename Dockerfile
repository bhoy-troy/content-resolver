FROM registry.fedoraproject.org/fedora:44


## Configure DNF to skip ldconfig in container builds
## An error is caused because DNF is trying to update the dynamic linker cache in the container.
#RUN echo "tsflags=nodocs" >> /etc/dnf/dnf.conf


TODO: use requirements.txt for Python deps with versioning
RUN dnf -y update fedora-gpg-keys && \
    dnf -y install \
        git-core \
        python3-flake8 \
        python3-jinja2 \
        python3-koji \
        python3-libdnf5 \
        python3-pytest \
        python3-yaml && \
    dnf clean all && \
    rm -rf /var/cache/dnf

WORKDIR /workspace
