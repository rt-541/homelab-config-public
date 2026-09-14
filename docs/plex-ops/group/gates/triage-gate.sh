# plex-ops queue-triage gate. NanoClaw runs it INSIDE the agent container
# (bash, 30s cap; node available, no jq/python) before every scheduled fire;
# the agent wakes only when the queues hold something actionable (any class
# other than "unknown") or an arr is unreachable. Creds come from the
# container env (RUNNER_URL/RUNNER_TOKEN), host file as fallback.
# Last stdout line must be: {"wakeAgent": <bool>, "data": {...}}
set -u
if [ -z "${RUNNER_TOKEN:-}" ] && [ -f "$HOME/.config/plex-ops/runner.env" ]; then . "$HOME/.config/plex-ops/runner.env"; fi
if [ -z "${RUNNER_TOKEN:-}" ] || [ -z "${RUNNER_URL:-}" ]; then
  echo '{"wakeAgent": true, "data": {"error": "RUNNER_URL/RUNNER_TOKEN missing in the gate environment"}}'; exit 0
fi
# The full queue payload can exceed the env/argv size limit: pass it by file.
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
curl -sS -m 25 -H "Authorization: Bearer $RUNNER_TOKEN" -o "$TMP" "$RUNNER_URL/probe/queue-health" 2>/dev/null || true
RESP_FILE="$TMP" node -e '
const fs = require("fs");
const out = (wakeAgent, data) => console.log(JSON.stringify({ wakeAgent, data }));
let raw = ""; try { raw = fs.readFileSync(process.env.RESP_FILE, "utf8"); } catch (e) {}
let r = null; try { r = JSON.parse(raw || ""); } catch (e) {}
if (!r || r.ok !== true) {
  out(true, { runner_unreachable: true, response: (raw || "null").slice(0, 300) });
} else {
  const data = {}; let wake = false;
  for (const [app, v] of Object.entries(r.apps || {})) {
    if (v && v.error) { data[app] = { error: v.error }; wake = true; continue; }
    const c = (v && v.counts) || {};
    const actionable = (c["malware-ext"] || 0) + (c["not-upgrade"] || 0)
                     + (c["mapping-mismatch"] || 0) + (c["sample-stall"] || 0);
    data[app] = { total: (v || {}).total, actionable, counts: c };
    if (actionable > 0) wake = true;
  }
  out(wake, data);
}'
