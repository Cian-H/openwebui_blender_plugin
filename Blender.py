"""
title: Blender Rendering Function for OpenWebUI
author: Cian Hughes
version: 0.0.1
license: MIT
requirements: pydantic, requests
environment_variables: BLENDER_SERVER_URL, STLVIEW_CDN_URL
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests
from pydantic import BaseModel, Field


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


async def dummy_emitter(_: Dict[str, Any]) -> None:
    pass


class Action:
    """
    An action for generating and displaying a 3d model from a blender `bpy` python script.
    """

    class Valves(BaseModel):
        """
        Pydantic model for storing the server url.
        """

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
        )
        self.js_cache = Path("./data/cache/blender_render/js")
        self.model_cache = Path("./data/uploads")
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

        self.js_cache.mkdir(parents=True, exist_ok=True)
        for file in files:
            filepath = self.js_cache / file
            if not filepath.exists():
                print(f"Downloading {file}...")
                try:
                    response = requests.get(f"{self.valves.STLVIEW_CDN_URL}{file}")
                    if response.status_code == 200:
                        with open(filepath, "wb") as f:
                            f.write(response.content)
                        print(f"Downloaded {file} successfully.")
                    else:
                        print(
                            f"Failed to download {file}. Status code: {response.status_code}"
                        )
                except Exception as e:
                    print(f"Error downloading {file}: {e}")
            else:
                print(f"{file} already exists, skipping download.")

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
        print(f"action:{__name__}")

        msg_id = body["id"]
        chat_id = body["chat_id"]
        msg = await self.get_msg(body, msg_id)

        print("msg found")

        if __event_call__ is None:
            raise TypeError("__event_call__ must not be `None`")

        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Writing 3d model code...", "done": False},
            }
        )
        print("creating model code")
        print(msg)
        model_code = await self.get_model_code(msg["content"])
        print("model code created")
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
        model_html = await self.render_model_to_html(
            model_code,
            body,
            chat_id,
            msg_id,
            __user__=__user__,
            __event_emitter__=__event_emitter__,
            __event_call__=__event_call__,
        )
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Rendering 3d model...", "done": True},
            }
        )
        await __event_emitter__(
            {
                "type": "message",
                "data": {
                    "description": "A 3d model rendered based on the blender code provided.",
                    "content": model_html,
                },
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
        print("method:get_model_code")
        lines = content.split("\n")
        print("lines split")
        try:
            code_start, code_end = lines.index("```python"), lines.index("```")
        except ValueError:
            raise ValueError(
                "No code block containing `model()` function found in message"
            )
        print("indeces found")
        if code_start < code_end:
            print("method:get_model_code:branch1")
            code_block = "\n".join(lines[code_start + 1 : code_end])
            if "def model(" in code_block:
                return code_block
        else:
            print("method:get_model_code:branch2")
            code_end = code_start
        print("method:get_model_code:recurse")
        return await self.get_model_code("\n".join(lines[code_end + 1 :]))

    async def render_model_to_html(
        self,
        model_code: str,
        body: Dict,
        chat_id: str,
        msg_id: str,
        __user__: Optional[str] = None,
        __event_emitter__: Callable[[Dict[str, Any]], Any] = dummy_emitter,
        __event_call__: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> str:
        print("Rendering model to html")
        model = await self.render_model(
            model_code,
            body,
            __user__=__user__,
            __event_emitter__=__event_emitter__,
            __event_call__=__event_call__,
        )
        model_html = await self.generate_model_html(model, chat_id, msg_id)
        if not model_html:
            raise requests.RequestException("Request to blender server failed")
        print("Model rendered!")
        return model_html

    async def render_model(
        self,
        model_code: str,
        body: Dict,
        __user__: Optional[str] = None,
        __event_emitter__: Callable[[Dict[str, Any]], Any] = dummy_emitter,
        __event_call__: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> bytes:
        print("Sending model_code to render server")
        payload = {"model_code": model_code}
        response = requests.post(
            f"{self.valves.BLENDER_SERVER_URL}/create_model",
            json=payload,
        )
        print("Render server response received!")
        response.raise_for_status()
        return response.content

    async def generate_model_html(self, model: bytes, chat_id: str, msg_id: str) -> str:
        print("Generating model html")
        stl_filepath = (
            Path(f"{self.model_cache}{chat_id}-model-{msg_id}.stl")
            .resolve()
            .relative_to(Path().resolve())
        )
        t1 = asyncio.create_task(self.write_model_to_cache(model, stl_filepath))
        stl_html = await self.template_html(stl_filepath)
        await t1
        print("Model html generated!")
        return stl_html

    async def write_model_to_cache(self, model: bytes, stl_filepath: Path):
        self.model_cache.mkdir(parents=True, exist_ok=True)
        print("Writing model binary to model cache")
        with stl_filepath.open("wb") as stl_file:
            stl_file.write(model)
        print("Model cached!")

    async def template_html(self, stl_filepath: Path) -> str:
        print("Generating html from template")
        main_js = self.js_cache / "stl_viewer.min.js"
        p = main_js.parent
        backtrack_path = ""
        while p != Path():
            backtrack_path += "../"
            p = p.parent
            if p == Path("/"):
                raise FileNotFoundError(
                    "Attempt to find relative path reached filesystem root! This shouldn't ever happen!"
                )

        return f"""
            <div id="stl_cont"></div>

            <script src="{main_js}"></script>
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
                                        filename: "{backtrack_path}{stl_filepath}",
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
        """
