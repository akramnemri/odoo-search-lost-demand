#!/usr/bin/env bash
# One-shot Elasticsearch setup, run by the `es-setup` service on every `docker compose up`
# (docs/ai/01_ARCHITECTURE.md §5.2, ADR-004). Every request creates or updates, so re-running is safe,
# and passwords always follow .env. Exits non-zero on any failure: Kibana and Odoo then do not start.
set -euo pipefail

: "${ES_URL:?}" "${ELASTIC_PASSWORD:?}" "${KIBANA_SYSTEM_PASSWORD:?}" "${ODOO_APP_ES_PASSWORD:?}"
: "${SHOP_TOOLS_ES_PASSWORD:?}" "${KIBANA_PERSONAL_USER:?}" "${KIBANA_PERSONAL_PASSWORD:?}"

shopt -s inherit_errexit

# es METHOD PATH [JSON_BODY]: prints the response body; on an HTTP error prints it to stderr and fails.
# Credentials go through curl's config on stdin so they never appear in the process list.
es() {
  local method=$1 path=$2 body=${3:-} response
  local args=(--silent --show-error --fail-with-body --max-time 30 --config - -X "$method" "${ES_URL}${path}")
  if [[ -n $body ]]; then
    args+=(-H "Content-Type: application/json" --data-binary "$body")
  fi
  if ! response=$(curl "${args[@]}" <<< "user = \"elastic:${ELASTIC_PASSWORD}\""); then
    echo "es-setup: ${method} ${path} failed: ${response}" >&2
    return 1
  fi
  printf '%s\n' "$response"
}

echo "es-setup: waiting for Elasticsearch at ${ES_URL}"
for attempt in $(seq 1 30); do
  if es GET "/_cluster/health?wait_for_status=yellow&timeout=5s" > /dev/null 2>&1; then
    break
  fi
  if [[ $attempt -eq 30 ]]; then
    echo "es-setup: Elasticsearch not healthy after 30 attempts" >&2
    exit 1
  fi
  sleep 2
done

echo "es-setup: checking the license (must be basic, never a trial)"
# On a brand-new cluster the self-generated license appears a few seconds after the cluster is healthy
# (GET _license answers 404 until then).
for attempt in $(seq 1 30); do
  if license=$(es GET "/_license?filter_path=license.type" 2> /dev/null); then
    break
  fi
  if [[ $attempt -eq 30 ]]; then
    es GET "/_license?filter_path=license.type" > /dev/null
  fi
  sleep 2
done
license=${license//[[:space:]]/}
if [[ $license != *'"type":"basic"'* ]]; then
  echo "es-setup: license is ${license}, expected basic - see ADR-004" >&2
  exit 1
fi

echo "es-setup: setting the kibana_system password"
es POST /_security/user/kibana_system/_password "{\"password\": \"${KIBANA_SYSTEM_PASSWORD}\"}" > /dev/null

echo "es-setup: role odoo_app (the Odoo module)"
# monitor: settings-page status (version, license, health). manage_search_synonyms: synonym sets (Task 3.6).
# manage on shop-products*: versioned indices and the alias swap (Task 3.1).
es PUT /_security/role/odoo_app '{
  "cluster": ["monitor", "manage_search_synonyms"],
  "indices": [
    {"names": ["shop-products*"], "privileges": ["create_index", "read", "write", "manage", "view_index_metadata"]},
    {"names": ["shop-events*"], "privileges": ["auto_configure", "create_doc", "read", "view_index_metadata"]}
  ]
}' > /dev/null

echo "es-setup: role shop_tools (host tools: replay, evaluation, probes)"
es PUT /_security/role/shop_tools '{
  "cluster": ["monitor"],
  "indices": [
    {"names": ["shop-*"], "privileges": ["read", "view_index_metadata"]},
    {"names": ["shop-events*"], "privileges": ["auto_configure", "create_doc"]}
  ]
}' > /dev/null

echo "es-setup: users odoo_app, shop_tools and ${KIBANA_PERSONAL_USER}"
es PUT /_security/user/odoo_app \
  "{\"password\": \"${ODOO_APP_ES_PASSWORD}\", \"roles\": [\"odoo_app\"], \"full_name\": \"Odoo module\"}" > /dev/null
es PUT /_security/user/shop_tools \
  "{\"password\": \"${SHOP_TOOLS_ES_PASSWORD}\", \"roles\": [\"shop_tools\"], \"full_name\": \"Host tools\"}" > /dev/null
# Built-in `editor`: full Kibana features, read-only on data indices. The dashboards are built in the
# Kibana UI (Task 4.5), so a viewer-only role would not be enough.
es PUT "/_security/user/${KIBANA_PERSONAL_USER}" \
  "{\"password\": \"${KIBANA_PERSONAL_PASSWORD}\", \"roles\": [\"editor\"], \"full_name\": \"Personal Kibana login\"}" > /dev/null

# Index templates, ingest pipelines and ILM policies from /elastic arrive with Tasks 3.1 (products)
# and 4.1 (events); this step applies them once they exist.
echo "es-setup: no Elasticsearch templates to apply yet (Tasks 3.1 and 4.1)"

echo "es-setup: done"
