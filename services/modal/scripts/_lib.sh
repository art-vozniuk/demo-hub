# Shared helpers for deploy/preload/destroy scripts.
# Source this AFTER `cd`-ing into services/modal/ so relative paths resolve.

# run_deploy <app-py-path> <endpoint-file> <env-var-name>
#
# Deploys a Modal app, extracts the resolved web endpoint URL from the
# CLI output, writes it to <endpoint-file> next to services/modal/ and
# prints the env var assignment the dispatch worker needs.
run_deploy() {
    local app_path="$1"
    local endpoint_file="$2"
    local env_var="$3"

    local out
    out="$(mktemp -t modal-deploy.XXXXXX.out)"
    trap 'rm -f "${out}"' RETURN

    echo "Deploying ${app_path}..."
    modal deploy "${app_path}" | tee "${out}"

    local url
    url="$(grep -Eo 'https://[^[:space:]]+\.modal\.run' "${out}" | head -n1 || true)"
    if [ -z "${url}" ]; then
        echo "Failed to extract endpoint URL from modal output." >&2
        return 1
    fi

    echo "${url}" > "${endpoint_file}"
    echo
    echo "Deployed."
    echo "  Endpoint:  ${url}"
    echo "  Stored at: $(pwd)/${endpoint_file}"
    echo
    echo "Set on the dispatch worker:"
    echo "  ${env_var}=${url}"
}

# run_preload <app-py-path>
run_preload() {
    modal run "${1}::preload_weights"
    echo "Volume populated successfully."
}

# run_destroy <app-name> <volume-name>
run_destroy() {
    modal app stop "${1}" || true
    echo "Stopped ${1}. Volume '${2}' and secrets are preserved."
}
