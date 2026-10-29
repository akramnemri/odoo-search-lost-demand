# Our Odoo image: the pinned official image + the pinned Elasticsearch client (ADR-002, docs/setup/VERSIONS.md).
FROM odoo:19.0-20261015

USER root

# Ubuntu marks the system Python as externally managed (PEP 668) and pip cannot uninstall Debian packages.
# The pinned set goes to /usr/local beside the image's packages (--ignore-installed), so Odoo's own
# interpreter finds it. `pip check` already reports a conflict between Debian packages of the base image
# (maxminddb / setuptools), so the build fails only on a problem that involves a package we add.
# Supply chain: prebuilt wheels only (no package setup script runs during the build) and every file checked
# against its SHA-256 in requirements.txt.
COPY requirements.txt /tmp/lost-demand-requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages --no-deps --ignore-installed \
        --only-binary :all: --require-hashes \
        -r /tmp/lost-demand-requirements.txt \
    && { pip3 check > /tmp/pip-check.txt 2>&1 || true; } \
    && ! grep -iE 'elasticsearch|elastic.transport|anyio|sniffio|typing.extensions' /tmp/pip-check.txt \
    && python3 -c "import elasticsearch" \
    && rm /tmp/lost-demand-requirements.txt /tmp/pip-check.txt

COPY odoo.conf /etc/odoo/odoo.conf.template
COPY --chmod=755 entrypoint.sh /usr/local/bin/lost-demand-entrypoint.sh

USER odoo

ENTRYPOINT ["/usr/local/bin/lost-demand-entrypoint.sh"]
CMD ["odoo"]
