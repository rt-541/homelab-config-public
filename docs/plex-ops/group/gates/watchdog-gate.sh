# plex-ops service-watchdog gate. NanoClaw runs it INSIDE the agent container
# (bash, 30s cap; node available, no jq/python) before every scheduled fire;
# the agent wakes only when something needs it. Creds come from the
# container env (RUNNER_URL/RUNNER_TOKEN), with the host file as fallback so
# the deploy script can self-test it on the host.
# Last stdout line must be: {"wakeAgent": <bool>, "data": {...}}
set -u
if [ -z "${RUNNER_TOKEN:-}" ] && [ -f "$HOME/.config/plex-ops/runner.env" ]; then . "$HOME/.config/plex-ops/runner.env"; fi
if [ -z "${RUNNER_TOKEN:-}" ] || [ -z "${RUNNER_URL:-}" ]; then
  echo '{"wakeAgent": true, "data": {"error": "RUNNER_URL/RUNNER_TOKEN missing in the gate environment"}}'; exit 0
fi
STATE="${GATE_STATE_DIR:-/workspace/agent/gate-state}"; mkdir -p "$STATE" 2>/dev/null || STATE=/tmp
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
curl -sS -m 25 -H "Authorization: Bearer $RUNNER_TOKEN" -o "$TMP" "$RUNNER_URL/probe/service-health" 2>/dev/null || true
STATE="$STATE" RESP_FILE="$TMP" node -e '
const fs = require("fs"), path = require("path");
const out = (wakeAgent, data) => console.log(JSON.stringify({ wakeAgent, data }));
let raw = ""; try { raw = fs.readFileSync(process.env.RESP_FILE, "utf8"); } catch (e) {}
let r = null; try { r = JSON.parse(raw || ""); } catch (e) {}
const down = path.join(process.env.STATE, "runner-down");
if (!r || r.ok !== true) {
  // Runner down or unhealthy: wake once per 6h, not every 30 min.
  const now = Date.now() / 1000; let last = 0;
  try { last = Number(fs.readFileSync(down, "utf8")) || 0; } catch (e) {}
  let wake = false;
  if (now - last > 21600) { try { fs.writeFileSync(down, String(now)); } catch (e) {} wake = true; }
  out(wake, { runner_unreachable: true, response: (raw || "null").slice(0, 300) });
} else {
  try { fs.unlinkSync(down); } catch (e) {}
  const c = r.containers || {};
  const bad = Object.keys(c).filter(k => (c[k] || {}).state !== "running" || (c[k] || {}).health === "unhealthy");
  const stragglers = (r.stragglers || []).map(s => s.name);
  const cpu = (r.prowlarr || {}).cpu_percent;
  const data = { prowlarr_ping_ok: (r.prowlarr || {}).ping_ok, prowlarr_cpu: cpu,
                 bad_containers: bad, stragglers, vpn_egress_ok: (r.vpn || {}).egress_ok };
  out(data.prowlarr_ping_ok !== true || bad.length > 0 || stragglers.length > 0
      || data.vpn_egress_ok !== true || (cpu != null && cpu > 150), data);
}'
