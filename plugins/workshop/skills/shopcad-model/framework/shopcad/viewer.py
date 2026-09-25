"""Writes the self-contained three.js viewer page that sits next to the GLBs.

Interactive: orbit controls, one button per state, a checkbox per component,
camera presets. Render mode (?shot=1&view=iso&state=open&hide=A,B) fixes the
canvas size, hides the UI and sets document.title to "rendered" when the
frame is drawn, which is what the headless screenshot waits on.
"""

import json

TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__NAME__ model</title>
<style>
:root{--bg:#ece8df;--ink:#1B2430;--muted:#5B6B7A;--paper:#fff;--rule:#C9D2DA;--acc:#2F6F9F}
html,body{margin:0;height:100%;background:var(--bg);font-family:"IBM Plex Sans",system-ui,sans-serif;color:var(--ink);overflow:hidden}
canvas{display:block}
#ui{position:fixed;top:10px;left:10px;display:grid;gap:8px;max-width:min(320px,calc(100vw - 20px));font-size:13px}
.card{background:rgba(255,255,255,.92);border:1px solid var(--rule);padding:8px 10px;display:grid;gap:6px}
.card>summary{list-style:none;display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:14px;font-weight:600;cursor:pointer;user-select:none}
.card>summary::-webkit-details-marker{display:none}
.card>summary::after{content:"hide";font-size:11px;font-weight:400;color:var(--muted)}
/* folded: no title, just a small square toggle in the corner */
.card:not([open]){padding:0;width:30px;height:30px;justify-items:center;align-content:center}
.card:not([open])>summary{justify-content:center;width:100%;height:100%}
.card:not([open])>summary>span{display:none}
.card:not([open])>summary::after{content:"\2261";font-size:20px;line-height:1;color:var(--ink)}
.row{display:flex;flex-wrap:wrap;gap:6px}
button{font:inherit;font-size:12px;padding:4px 8px;border:1px solid var(--rule);background:var(--paper);color:var(--ink);cursor:pointer}
button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
label{display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer}
details summary{cursor:pointer;font-size:12px;color:var(--muted)}
#status{font-size:11px;color:var(--muted)}
.shot #ui{display:none}
</style>
<script type="importmap">
{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
"three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}
</script>
</head><body>
<div id="ui">
  <details class="card" id="panel" open>
    <summary><span>__NAME__</span></summary>
    <div class="row" id="states"></div>
    <div class="row" id="views"></div>
    <details><summary>components</summary><div id="comps" style="display:grid;gap:3px;margin-top:6px"></div></details>
    <div id="status">loading</div>
  </details>
</div>
<script id="manifest" type="application/json">__MANIFEST__</script>
<script id="embed" type="application/json">__EMBED__</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const M = JSON.parse(document.getElementById('manifest').textContent);
const EMBED = JSON.parse(document.getElementById('embed').textContent || '{}');
const q = new URLSearchParams(location.search);
const shot = q.get('shot') === '1';
if (shot) document.body.classList.add('shot');
const W = shot ? parseInt(q.get('w') || '1600') : innerWidth;
const H = shot ? parseInt(q.get('h') || '1100') : innerHeight;
const norm = s => String(s).replace(/\s/g, '_').replace(/[^\w-]/g, '');
const compByNorm = {}; for (const c of M.components) compByNorm[norm(c)] = c;
const hidden = new Set((q.get('hide') || '').split(',').filter(Boolean));

const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setSize(W, H); renderer.setPixelRatio(shot ? 1 : Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 0.95;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xece8df);
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.55;
scene.add(new THREE.HemisphereLight(0xffffff, 0xb9b1a4, 0.7));
const sun = new THREE.DirectionalLight(0xfff4e6, 1.8);
sun.castShadow = true; sun.shadow.mapSize.set(4096, 4096); sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.05;
scene.add(sun); scene.add(sun.target);

let camera = new THREE.PerspectiveCamera(32, W / H, 1, 5000);
let controls = null;
let model = null, bbox = null;
const loader = new GLTFLoader();
const status = document.getElementById('status');
const compState = {};

function applyVisibility() {
  if (!model) return;
  model.traverse(o => { if (o.userData.comp) o.visible = !hidden.has(o.userData.comp) && compState[o.userData.comp] !== false; });
}

function frame(view) {
  const focus = (q.get('focus') || '').split(',').filter(Boolean);
  if (focus.length && model) {
    // frame one or more components from a corner: dir = se|sw|ne|nw (default sw)
    const fb = new THREE.Box3();
    model.traverse(o => { if (o.isMesh && focus.includes(o.userData.comp)) fb.expandByObject(o); });
    if (!fb.isEmpty()) {
      const fc = fb.getCenter(new THREE.Vector3()), fs = fb.getSize(new THREE.Vector3());
      const fd = Math.max(fs.x, fs.y, fs.z) * 1.7;
      // dir: any of n, s, e, w or a diagonal (sw, ne, ...); a single letter is a straight-on view.
      // elev: camera height as a fraction of the focus size (default 0.55; 0.15 is eye level, 1.6 is near plan).
      const dir = q.get('dir') || 'sw';
      let sx = dir.includes('e') ? 1 : (dir.includes('w') ? -1 : 0), sz = dir.includes('n') ? -1 : (dir.includes('s') ? 1 : 0);
      if (!sx && !sz) { sx = -1; sz = 1; }
      const elev = parseFloat(q.get('elev') || '0.55');
      // zoom: scales the stand-off distance (default 1; 0.6 fills the frame with a long, flat object)
      const zoom = parseFloat(q.get('zoom') || '1');
      const horiz = ((sx && sz) ? 0.8 : 1.7) * zoom;   // a straight-on view sees the object's full width, so stand further back
      camera = new THREE.PerspectiveCamera(30, W / H, 1, 5000);
      camera.position.set(fc.x + sx * fd * horiz, fc.y + fd * elev, fc.z + sz * fd * horiz);
      camera.up.set(0, 1, 0); camera.lookAt(fc); camera.updateProjectionMatrix();
      if (controls) controls.dispose();
      if (!shot) { controls = new OrbitControls(camera, renderer.domElement); controls.target.copy(fc); controls.update(); }
      // light from the camera side, pushed sideways for straight-on views so the facing plane still shades
      const sideOff = new THREE.Vector3(sz ? 280 : 60, 300, sx ? 220 : 0);
      sun.position.copy(camera.position).sub(fc).normalize().multiplyScalar(600).add(fc).add(sideOff); sun.target.position.copy(fc);
      const s2 = fd * 1.2;
      sun.shadow.camera.left = -s2; sun.shadow.camera.right = s2; sun.shadow.camera.top = s2; sun.shadow.camera.bottom = -s2;
      sun.shadow.camera.near = 20; sun.shadow.camera.far = 2500;
      return;
    }
  }
  const c = bbox.getCenter(new THREE.Vector3());
  const size = bbox.getSize(new THREE.Vector3());
  const d = Math.max(size.x, size.z, size.y * 0.9) * 1.05;
  const ortho = (view === 'plan' || view === 'north' || view === 'east' || view === 'west' || view === 'south');
  if (ortho) {
    const across = view === 'plan' ? Math.max(size.x, size.z) : (view === 'north' || view === 'south' ? size.x : size.z);
    const tall = view === 'plan' ? Math.max(size.x, size.z) : size.y;
    const hw = Math.max(across * 0.55, tall * 0.55 * W / H);
    const hh = hw * H / W;
    camera = new THREE.OrthographicCamera(-hw, hw, hh, -hh, 1, 5000);
  } else {
    camera = new THREE.PerspectiveCamera(32, W / H, 1, 5000);
  }
  if (view === 'plan') { camera.position.set(c.x, c.y + 1500, c.z + 0.01); camera.up.set(0, 0, -1); }
  else if (view === 'north') { camera.position.set(c.x, size.y / 2, c.z + 1500); }
  else if (view === 'south') { camera.position.set(c.x, size.y / 2, c.z - 1500); }
  else if (view === 'east') { camera.position.set(c.x - 1500, size.y / 2, c.z); }
  else if (view === 'west') { camera.position.set(c.x + 1500, size.y / 2, c.z); }
  else if (view === 'iso-nw') { camera.position.set(c.x - d * 1.3, c.y + d * 1.0, c.z - d * 1.3); }
  else if (view === 'iso-ne') { camera.position.set(c.x + d * 1.3, c.y + d * 1.0, c.z - d * 1.3); }
  else if (view === 'iso-sw') { camera.position.set(c.x - d * 1.3, c.y + d * 1.0, c.z + d * 1.3); }
  else if (view === 'shop') { camera.position.set(c.x - d * 0.35, c.y + d * 0.55, c.z + d * 1.15); }
  else if (view === 'garden') { camera.position.set(c.x + d * 0.45, c.y + d * 0.55, c.z + d * 1.15); }
  else { camera.position.set(c.x + d * 1.25, c.y + d * 1.05, c.z + d * 1.35); }
  if (view !== 'plan') camera.up.set(0, 1, 0);
  let target = new THREE.Vector3(c.x, bbox.min.y + size.y * 0.42, c.z);
  if (view === 'plan') target = new THREE.Vector3(c.x, 0, c.z);
  if (view === 'shop') target = new THREE.Vector3(bbox.max.x - 40, 36, c.z + 10);
  if (view === 'garden') target = new THREE.Vector3(bbox.min.x + 40, 36, c.z + 10);
  camera.lookAt(target);
  camera.updateProjectionMatrix();
  if (controls) controls.dispose();
  if (!shot) { controls = new OrbitControls(camera, renderer.domElement); controls.target.copy(target); controls.update(); }
  // light from the camera's side so faces toward the viewer are lit
  sun.position.copy(camera.position).sub(c).normalize().multiplyScalar(900).add(c).add(new THREE.Vector3(ortho ? -350 : 120, 500, 0)); sun.target.position.copy(c);
  sun.intensity = ortho ? 1.5 : 1.8;
  const s = Math.max(size.x, size.y, size.z) * 0.8;
  sun.shadow.camera.left = -s; sun.shadow.camera.right = s; sun.shadow.camera.top = s; sun.shadow.camera.bottom = -s;
  sun.shadow.camera.near = 50; sun.shadow.camera.far = 3000;
}

function load(stateName, view) {
  const st = M.states[stateName];
  status.textContent = 'loading ' + st.label;
  loader.load(EMBED[st.file] || st.file, gltf => {
    if (model) scene.remove(model);
    model = gltf.scene;
    model.traverse(o => {
      if (o.isMesh) {
        o.castShadow = o.material.transparent ? false : true; o.receiveShadow = true;
        let p = o.parent, comp = null;
        while (p) { const nm = compByNorm[norm(p.userData.name || p.name)]; if (nm) { comp = nm; break; } p = p.parent; }
        o.userData.comp = comp || norm(o.userData.name || o.name).split('_')[0];
        if (o.material.transparent) o.material.depthWrite = false;
      }
    });
    scene.add(model);
    bbox = new THREE.Box3().setFromObject(model);
    applyVisibility();
    frame(view);
    for (const b of document.querySelectorAll('#states button')) b.classList.toggle('on', b.dataset.s === stateName);
    status.textContent = st.label + (st.description ? ': ' + st.description : '');
    renderer.render(scene, camera);
    if (shot) document.title = 'rendered';
  }, undefined, err => { status.textContent = 'error ' + err; if (shot) document.title = 'error'; });
}

const statesEl = document.getElementById('states');
for (const [k, st] of Object.entries(M.states)) {
  const b = document.createElement('button'); b.textContent = st.label; b.dataset.s = k;
  b.onclick = () => load(k, currentView); statesEl.appendChild(b);
}
const viewsEl = document.getElementById('views');
let currentView = q.get('view') || 'iso';
for (const v of ['iso', 'iso-sw', 'iso-ne', 'iso-nw', 'plan', 'north', 'east', 'west']) {
  const b = document.createElement('button'); b.textContent = v; b.onclick = () => { currentView = v; frame(v); }; viewsEl.appendChild(b);
}
const compsEl = document.getElementById('comps');
for (const c of M.components) {
  const l = document.createElement('label'); const i = document.createElement('input'); i.type = 'checkbox'; i.checked = !hidden.has(c);
  i.onchange = () => { compState[c] = i.checked; applyVisibility(); };
  l.appendChild(i); l.appendChild(document.createTextNode(c)); compsEl.appendChild(l);
}

// the whole panel folds to a corner button so nothing covers the model; it starts folded on a phone and
// when the viewer is embedded in another page (the drawing set's iframe); ?panel=1|0 overrides both
const embedded = window.self !== window.top;
document.getElementById('panel').open = q.has('panel') ? q.get('panel') !== '0' : !(embedded || innerWidth < 600);

load(q.get('state') || M.default_state, currentView);
if (!shot) {
  addEventListener('resize', () => { renderer.setSize(innerWidth, innerHeight); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); });
  renderer.setAnimationLoop(() => { if (controls) controls.update(); renderer.render(scene, camera); });
}
</script>
</body></html>
'''


def write(path, manifest, embed=None):
    """embed: {glb filename: bytes} to inline as data URLs for headless rendering."""
    em = {}
    if embed:
        import base64
        for fn, data in embed.items():
            em[fn] = "data:model/gltf-binary;base64," + base64.b64encode(data).decode("ascii")
    html = (TEMPLATE.replace("__NAME__", manifest["name"]).replace("__MANIFEST__", json.dumps(manifest))
            .replace("__EMBED__", json.dumps(em)))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", path, len(html), "bytes")
