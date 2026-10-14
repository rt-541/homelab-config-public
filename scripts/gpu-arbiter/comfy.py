"""Drive a local ComfyUI to turn a render into a photograph with FLUX.1 Kontext dev.

The workflow is the stock Kontext edit graph: the render is scaled to Kontext's
preferred size, encoded, attached to the prompt as a reference latent, and
sampled from that latent, so the layout, the camera and the objects stay put
and only the surfaces, light and plants become photographic.
"""

import json
import os
import shutil
import time
import urllib.parse
import urllib.request

DEFAULT_PROMPT = ("Turn this 3D render into a real photograph taken with a full-frame camera on a sunny afternoon. "
                  "Keep the exact layout, camera angle, house, deck, patio, stone walls, trees, furniture and every "
                  "object in the same place and size. Make every surface a real material: weathered brick, asphalt "
                  "shingles, composite deck boards, natural buff flagstone, stacked wall stone, a thick mowed lawn with "
                  "real grass blades, dense living evergreen foliage. Natural light, soft shadows, subtle haze, high "
                  "detail, no text, no people.")

MODELS = dict(unet="flux1-dev-kontext_fp8_scaled.safetensors", clip_l="clip_l.safetensors",
              t5="t5xxl_fp8_e4m3fn_scaled.safetensors", vae="ae.safetensors")


def workflow(image_name, prompt=DEFAULT_PROMPT, seed=7, steps=24, guidance=2.5, models=MODELS):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": models["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": models["clip_l"], "clip_name2": models["t5"], "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": models["vae"]}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "5": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["4", 0]}},
        "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "8": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["7", 0], "latent": ["6", 0]}},
        "9": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["8", 0], "guidance": guidance}},
        "10": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["7", 0]}},
        "11": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["9", 0], "negative": ["10", 0],
                                                    "latent_image": ["6", 0], "seed": seed, "steps": steps, "cfg": 1.0,
                                                    "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": "photo"}},
    }


class Comfy:
    def __init__(self, base="http://127.0.0.1:8188", input_dir="/docker/comfyui/input", output_dir="/docker/comfyui/output"):
        self.base, self.input_dir, self.output_dir = base.rstrip("/"), input_dir, output_dir

    def _get(self, path, timeout=10):
        with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
            return json.loads(r.read())

    def ready(self):
        try:
            self._get("/system_stats", timeout=3)
            return True
        except Exception:  # noqa: BLE001
            return False

    def wait_ready(self, timeout=300):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.ready():
                return True
            time.sleep(3)
        return False

    def photo(self, src, dst, prompt=None, seed=7, steps=24, timeout=1800):
        """Run one Kontext pass on src (a PNG), write the photo to dst. Returns seconds taken."""
        t0 = time.time()
        name = "in-%d-%s" % (int(t0), os.path.basename(src))
        shutil.copyfile(src, os.path.join(self.input_dir, name))
        body = json.dumps({"prompt": workflow(name, prompt or DEFAULT_PROMPT, seed, steps)}).encode()
        req = urllib.request.Request(self.base + "/prompt", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            pid = json.loads(r.read())["prompt_id"]
        while time.time() - t0 < timeout:
            h = self._get("/history/" + urllib.parse.quote(pid))
            if pid in h:
                entry = h[pid]
                st = entry.get("status", {})
                if st.get("status_str") == "error":
                    raise RuntimeError("ComfyUI error: %s" % json.dumps(st.get("messages", []))[:800])
                for node in entry.get("outputs", {}).values():
                    for img in node.get("images", []):
                        out = os.path.join(self.output_dir, img.get("subfolder", ""), img["filename"])
                        shutil.copyfile(out, dst)
                        os.remove(out)
                        os.remove(os.path.join(self.input_dir, name))
                        return round(time.time() - t0, 1)
            time.sleep(2)
        raise TimeoutError("ComfyUI did not finish %s in %ds" % (src, timeout))
