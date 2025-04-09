"""
title: Blender Rendering Function for OpenWebUI
author: Cian Hughes
version: 0.0.2
license: MIT
requirements: pydantic, requests
environment_variables: OPENWEBUI_URL, BLENDER_SERVER_URL, STLVIEW_CDN_URL
"""

import asyncio

import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests
from pydantic import BaseModel, Field


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

        OPENWEBUI_URL: str = Field(default="", description="URL for the OpenWebUI")
        BLENDER_SERVER_URL: str = Field(
            default="", description="URL for your Blender render server"
        )
        STLVIEW_CDN_URL: str = Field(
            default="https://cdn.jsdelivr.net/gh/omrips/viewstl@v1.13/build/",
            description="URL for your STLView CDN",
        )

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
            OPENWEBUI_URL=os.getenv("OPENWEBUI_URL", ""),
        )
        self.cache = "cache/blender_render"
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

        js_cache = Path("data") / self.cache
        js_cache.mkdir(parents=True, exist_ok=True)
        for file in files:
            filepath = js_cache / file
            if not filepath.exists():
                try:
                    response = requests.get(f"{self.valves.STLVIEW_CDN_URL}{file}")
                    if response.status_code == 200:
                        with open(filepath, "wb") as f:
                            f.write(response.content)
                except Exception as e:
                    raise requests.RequestException(f"Error downloading {file}: {e}")

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
        msg_id = body["id"]
        chat_id = body["chat_id"]
        msg = await self.get_msg(body, msg_id)

        if __event_call__ is None:
            raise TypeError("__event_call__ must not be `None`")

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
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Rendering 3d model...", "done": False},
            }
        )
        model_html = await self.render_model_to_html(model_code, chat_id, msg_id)
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Rendering 3d model...", "done": True},
            }
        )
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
                    "content": f"\n\n```html\n{model_html}\n```\n",
                },
            }
        )
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Displaying 3d model...", "done": True},
            }
        )

    @staticmethod
    async def get_msg(body: Dict, msg_id: str) -> Dict:
        messages = body["messages"]
        msg = {}
        for msg in messages:
            if msg["id"] == msg_id:
                break
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
        lines = content.split("\n")
        try:
            code_start, code_end = lines.index("```python"), lines.index("```")
        except ValueError:
            raise ValueError(
                "No code block containing `model()` function found in message"
            )
        if code_start < code_end:
            code_block = "\n".join(lines[code_start + 1 : code_end])
            if "def model(" in code_block:
                return code_block
        else:
            code_end = code_start
        return await self.get_model_code("\n".join(lines[code_end + 1 :]))

    async def render_model_to_html(
        self,
        model_code: str,
        chat_id: str,
        msg_id: str,
    ) -> str:
        model = await self.render_model(
            model_code,
        )
        model_html = await self.generate_model_html(model, chat_id, msg_id)
        if not model_html:
            raise requests.RequestException("Request to blender server failed")
        return model_html

    async def render_model(
        self,
        model_code: str,
    ) -> bytes:
        payload = {"model_code": model_code}
        response = requests.post(
            f"{self.valves.BLENDER_SERVER_URL}/create_model",
            json=payload,
        )
        response.raise_for_status()
        return response.content

    async def generate_model_html(self, model: bytes, chat_id: str, msg_id: str) -> str:
        model_cache = Path("data") / self.cache / "models"
        stl_filename = f"{chat_id}-model-{msg_id}.stl"
        stl_filepath = (
            Path(f"{model_cache}/{stl_filename}")
            .resolve()
            .relative_to(Path().resolve())
        )
        model_cache.mkdir(parents=True, exist_ok=True)
        t1 = asyncio.create_task(self.write_model_to_cache(model, stl_filepath))
        stl_html = await self.template_html(stl_filename)
        await t1
        return stl_html

    async def write_model_to_cache(self, model: bytes, stl_filepath: Path):
        with stl_filepath.open("wb") as stl_file:
            stl_file.write(model)

    async def template_html(self, stl_filename: str) -> str:
        return f"""<!DOCTYPE html>
<html>
<head>
    <title>3d visualisation of model</title>
    <script src="{self.valves.OPENWEBUI_URL}/{self.cache}/js/stl_viewer.min.js"></script>
    <script>
        document.addEventListener('DOMContentLoaded', function () {{
            try {{
                if (typeof StlViewer === 'undefined') {{
                    throw new Error('StlViewer library not loaded');
                }}
                var stl_viewer = new StlViewer(
                    document.getElementById("stl_cont"),
                    {{
                        models: [
                            {{
                                filename: "{self.valves.OPENWEBUI_URL}/{self.cache}/models/{stl_filename}",
                                rotation: {{x: 0, y: 0, z: 0}},
                                position: {{x: 0, y: 0, z: 0}},
                                scale: 1.0
                            }}
                        ],
                        background: {{color: "#FFFFFF"}},
                    }}
                );
                stl_viewer.onError = function (error) {{
                    console.error('STL Viewer error:', error);
                }};
                console.log('STL Viewer initialized successfully');
            }} catch (error) {{
                console.error('Error initializing STL Viewer:', error);
            }}
        }});
    </script>
</head>
<body>
    <div id="stl_cont" style="width: 500px; height: 500px;"></div>
</body>
</html>"""
