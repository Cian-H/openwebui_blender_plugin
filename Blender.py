"""
title: Blender Rendering Function for OpenWebUI
author: Cian Hughes
version: 0.0.2
license: MIT
requirements: pydantic, requests
environment_variables: OPENWEBUI_BASE_URL, BLENDER_SERVER_URL, STLVIEW_CDN_URL
"""

import asyncio

import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import requests
from pydantic import BaseModel, Field, field_validator


async def dummy_emitter(_: Dict[str, Any]) -> None:
    pass


class FileData(BaseModel):
    id: str
    filename: str
    meta: Dict[str, Any]
    path: str


class Action:
    """
    An action for generating and displaying a 3d model from a blender `bpy` python script.
    """

    class Valves(BaseModel):
        """
        Pydantic model for storing the server url.
        """

        OPENWEBUI_BASE_URL: str = Field(
            default="",
            description="Base URL for the OpenWebUI",
            validate_default=True,
        )
        BLENDER_SERVER_URL: str = Field(
            default="",
            description="URL for your Blender render server",
            validate_default=True,
        )
        STLVIEW_CDN_URL: str = Field(
            default="https://cdn.jsdelivr.net/gh/omrips/viewstl@v1.13/build/",
            description="URL for your STLView CDN",
            validate_default=True,
        )

        @field_validator("OPENWEBUI_BASE_URL", "BLENDER_SERVER_URL", "STLVIEW_CDN_URL")
        @staticmethod
        def ensure_trailing_slash(s: str) -> str:
            return f"{s}/" if s and (s[-1] != "/") else s

    def __init__(self):
        """
        Initialize the Pipe class with default values and environment variables.
        Also, ensure the STLView library is present in the `./stlview` directory.
        """
        self.id = "BLENDER"
        self.name = "Blender: "
        self.valves = self.Valves(
            BLENDER_SERVER_URL=os.getenv("BLENDER_SERVER_URL", ""),
            STLVIEW_CDN_URL=os.getenv(
                "STLVIEW_CDN_URL",
                "https://cdn.jsdelivr.net/gh/omrips/viewstl@v1.13/build/",
            ),
            OPENWEBUI_BASE_URL=os.getenv("OPENWEBUI_BASE_URL", ""),
        )
        self.cache = "cache/blender_render/"
        self.download_stlview()

    def download_stlview(self):
        """Download all stlview files if they don't exist locally"""
        files = [
            "stl_viewer.min.js",
            "three.min.js",
            "webgl_detector.js",
            "Projector.js",
            "CanvasRenderer.js",
            "OrbitControls.js",
            "load_stl.min.js",
            "parser.min.js",
        ]

        print("OpenWebUI/BLENDER - Caching stlview JS files")
        js_cache = Path("data") / self.cache
        js_cache.mkdir(parents=True, exist_ok=True)
        for file in files:
            filepath = js_cache / file
            if not filepath.exists():
                print(f"OpenWebUI/BLENDER/download_stlview - Downloading {file}")
                try:
                    response = requests.get(f"{self.valves.STLVIEW_CDN_URL}{file}")
                    if response.status_code == 200:
                        with open(filepath, "wb") as f:
                            f.write(response.content)
                except Exception as e:
                    raise requests.RequestException(f"Error downloading {file}: {e}")
            else:
                print(
                    f"OpenWebUI/BLENDER/download_stlview - Skipping {file} (already exists)"
                )

    async def action(
        self,
        body: Dict,
        __user__: Optional[str] = None,
        __event_emitter__: Callable[[Dict[str, Any]], Any] = dummy_emitter,
        __event_call__: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Optional[Dict]:
        """
        An action that renders and displays stl models from generated python code
        using the `bpy` library. Model code to be rendered must be given in the form
        of a python function with the type signature `model() -> bpy.types.Object`.
        """
        print("OpenWebUI/BLENDER/action - Starting action...")

        msg_id = body["id"]
        chat_id = body["chat_id"]
        msg = await self.get_msg(body, msg_id)

        if __event_call__ is None:
            raise TypeError("__event_call__ must not be `None`")

        print("OpenWebUI/BLENDER/action - Writing 3d model code...")
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Writing 3d model code...", "done": False},
            }
        )
        model_code = await self.get_model_code(msg["content"])
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Writing 3d model code...", "done": True},
            }
        )

        if model_code == "":
            print("OpenWebUI/BLENDER/action - No model code found!")
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "No model code found!", "done": True},
                }
            )
            return

        print("OpenWebUI/BLENDER/action - Rendering model to HTML...")
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Rendering 3d model...", "done": False},
            }
        )
        model_filename, model_html = await self.render_model_to_html(
            model_code, chat_id, msg_id
        )
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Rendering 3d model...", "done": True},
            }
        )
        print("OpenWebUI/BLENDER/action - Displaying 3d model as artifact...")
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Displaying 3d model...", "done": False},
            }
        )
        await __event_emitter__(
            {
                "type": "message",
                "data": {
                    "description": "A 3d model rendered based on the blender code provided.",
                    "content": f"\n\n```html\n{model_html}\n```\n\n[Download model]({self.valves.OPENWEBUI_BASE_URL}{self.cache}models/{model_filename})\n",
                },
            }
        )
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Displaying 3d model...", "done": True},
            }
        )
        print("OpenWebUI/BLENDER/action - Action complete!")

    @staticmethod
    async def get_msg(body: Dict, msg_id: str) -> Dict:
        print("OpenWebUI/BLENDER/get_msg - Getting message...")
        messages = body["messages"]
        msg = {}
        for msg in messages:
            if msg["id"] == msg_id:
                break
        else:
            raise ValueError(f"message {msg_id} not found!")
        print("OpenWebUI/BLENDER/get_msg - Message found!")
        return msg

    async def get_model_code(
        self,
        content: str,
    ) -> str:
        """
        Extract Blender model code from the given message content.

        This implementation assumes the model code is provided in the body
        as a python code block containing a definition for a function called
        `model`. If not found, it raises a ValueError.
        """
        if content == "":
            print("OpenWebUI/BLENDER/get_model_code - Empty content received")
            return ""
        print("OpenWebUI/BLENDER/get_model_code - Searching for model code block")
        lines = content.split("\n")
        try:
            code_start, code_end = lines.index("```python"), lines.index("```")
        except ValueError:
            raise ValueError(
                "No code block containing `model()` function found in message"
            )
        print("OpenWebUI/BLENDER/get_model_code - Python code block found!")
        if code_start < code_end:
            code_block = "\n".join(lines[code_start + 1 : code_end])
            if "def model(" in code_block:
                print(
                    "OpenWebUI/BLENDER/get_model_code - Valid model code block found!"
                )
                return code_block
        else:
            code_end = code_start
        print("OpenWebUI/BLENDER/get_model_code - Model code block invalid!")
        return await self.get_model_code("\n".join(lines[code_end + 1 :]))

    async def render_model_to_html(
        self,
        model_code: str,
        chat_id: str,
        msg_id: str,
    ) -> Tuple[str, str]:
        print("OpenWebUI/BLENDER/render_model_to_html - Rendering model to HTML...")
        model = await self.render_model(
            model_code,
        )
        model_filename, model_html = await self.generate_model_html(
            model, chat_id, msg_id
        )
        if not model_html:
            raise requests.RequestException("Request to blender server failed")
        print("OpenWebUI/BLENDER/render_model_to_html - Model HTML rendered!")
        return model_filename, model_html

    async def render_model(
        self,
        model_code: str,
    ) -> bytes:
        payload = {"model_code": model_code}
        print(
            "OpenWebUI/BLENDER/render_model - Requesting STL from blender render server..."
        )
        response = requests.post(
            f"{self.valves.BLENDER_SERVER_URL}create_model",
            json=payload,
        )
        response.raise_for_status()
        print("OpenWebUI/BLENDER/render_model - Response received!")
        return response.content

    async def generate_model_html(
        self, model: bytes, chat_id: str, msg_id: str
    ) -> Tuple[str, str]:
        print("OpenWebUI/BLENDER/generate_model_html - Generating model HTML...")
        model_cache = Path("data") / self.cache / "models"
        existing_models = len([*model_cache.glob(f"{chat_id}-model-{msg_id}*.stl")])
        stl_filename = f"{chat_id}-model-{msg_id}-{existing_models}.stl"
        stl_filepath = (
            (model_cache / stl_filename).resolve().relative_to(Path().resolve())
        )
        model_cache.mkdir(parents=True, exist_ok=True)
        t1 = asyncio.create_task(self.write_model_to_cache(model, stl_filepath))
        stl_html = await self.template_html(stl_filename)
        print("OpenWebUI/BLENDER/generate_model_html - HTML templated!")
        await t1
        print("OpenWebUI/BLENDER/generate_model_html - Model HTML generated!")
        return stl_filename, stl_html

    async def write_model_to_cache(self, model: bytes, stl_filepath: Path):
        print("OpenWebUI/BLENDER/write_model_to_cache - Writing model data to cache...")
        with stl_filepath.open("wb") as stl_file:
            stl_file.write(model)
        print("OpenWebUI/BLENDER/write_model_to_cache - Model data cached!")

    async def template_html(self, stl_filename: str) -> str:
        print("OpenWebUI/BLENDER/template_html - Templating HTML...")
        return f"""<script src="{self.valves.OPENWEBUI_BASE_URL}{self.cache}/js/stl_viewer.min.js"></script>
<script>
    var stl_viewer = new StlViewer(
        document.getElementById("stl_cont"),
        {{
            models: [
                {{
                    filename: "{self.valves.OPENWEBUI_BASE_URL}{self.cache}models/{stl_filename}",
                    rotation: {{x: 0, y: 0, z: 0}},
                    position: {{x: 0, y: 0, z: 0}},
                    scale: 1.0
                }}
            ],
            background: {{color: "#FFFFFF"}},
        }}
    );
</script>
<div id="stl_cont" style="width: 500px; height: 500px;"></div>"""
