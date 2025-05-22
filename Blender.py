"""
title: Blender Rendering Function for OpenWebUI
author: Cian Hughes
author_url: https://github.com/Cian-H
version: 0.3.1
license: MIT
requirements: httpx, pydantic, trimesh
environment_variables: BLENDER_SERVER_URL
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import httpx
from pydantic import BaseModel, Field, field_validator
import trimesh


async def dummy_emitter(_: Dict[str, Any]) -> None:
    """A dummy emitter to satisfy type checks in the `Action.action` method."""
    pass


class BlenderRenderError(Exception):
    """
    Exception raised when the Blender render server returns an error.

    Attributes:
        message (str): The error message
        details (str): Additional details about the error
        blender_log (str): The Blender output log containing Python errors
    """

    def __init__(self, message: str, details: str, blender_log: str):
        self.message = message
        self.details = details
        self.blender_log = blender_log
        super().__init__(self.message)


class Action:
    """
    An action for generating and displaying a 3d model from a blender `bpy` python script.

    Attributes:
        id (str): The id tag for this action.
        name (str): The logging name for the action.
        valves (self.Valves): A pydantic model for storing WebUI accessible settings.
        cache (str): The path to the action's cache in openwebui's storage.
    """

    class Valves(BaseModel):
        """
        Pydantic model for storing the server url.

        Attributes:
            BLENDER_SERVER_URL (str): The URL for the Blender render server.
        """

        BLENDER_SERVER_URL: str = Field(
            default="",
            description="The URL for your Blender render server.",
            validate_default=True,
        )

        @field_validator("BLENDER_SERVER_URL")
        @staticmethod
        def ensure_trailing_slash(s: str) -> str:
            """
            Ensures that the given string ends in a trailing forward slash ("/").

            Args:
                s (str): The string being validated.

            Returns:
                str: The validated string.
            """
            return f"{s}/" if s and (s[-1] != "/") else s

    def __init__(self):
        """
        Initialize the Action class with default values and environment variables.
        """
        self.id = "BLENDER"
        self.name = "Blender: "
        self.valves = self.Valves(
            BLENDER_SERVER_URL=os.getenv("BLENDER_SERVER_URL", ""),
        )
        self.cache = "cache/blender_render/"

    async def action(
        self,
        body: Dict,
        __user__: Optional[str] = None,
        __event_emitter__: Callable[[Dict[str, Any]], Any] = dummy_emitter,
        __event_call__: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        """
        An action that renders and displays glb models from generated python code
        using the `bpy` library. Model code to be rendered must be given in the form
        of a python function with the type signature `model() -> bpy.types.Object`.

        Args:
            body (Dict): The body of the conversation for which the action was called.
            __user__ (Optional[str]): The user calling the action.
            __event_emitter__ (Callable[[Dict[str, Any]], Any]): The event emitter for the calling context.
            __event_call__ (Optional[Callable[[Dict[str, Any]], Any]]): The event call context.
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

        try:
            model_filename, model_html = await self.render_model_to_html(
                model_code, chat_id, msg_id
            )
            model_conversion_task = asyncio.create_task(
                self.convert_glb_to_obj(
                    (Path("data") / self.cache / "models" / model_filename)
                    .resolve()
                    .relative_to(Path().resolve())
                )
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
                        "content": f"\n\n```html\n{model_html}\n```\n",
                    },
                }
            )
            print("OpenWebUI/BLENDER/action - Awaiting conversion from GLB to STL...")
            obj_path = await model_conversion_task
            obj_endpoint = str(obj_path.relative_to(Path("data")))
            await __event_emitter__(
                {
                    "type": "message",
                    "data": {
                        "description": "A 3d model rendered based on the blender code provided.",
                        "content": f"\n[Download model](/{obj_endpoint})\n",
                    },
                }
            )
        except BlenderRenderError as error:
            error_message = f"""
## Error Rendering Blender Model

The Blender render server reported the following error:

```
{error.message}

```

### Details
{error.details}

### Blender Log
```
{error.blender_log}
```

Would you like me to correct this error?
"""
            await __event_emitter__(
                {
                    "type": "message",
                    "data": {
                        "description": "Error rendering 3d model",
                        "content": error_message,
                        "role": "assistant",
                    },
                }
            )

        finally:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "Displaying 3d model...", "done": True},
                }
            )
            print("OpenWebUI/BLENDER/action - Action complete!")

    @staticmethod
    async def get_msg(body: Dict, msg_id: str) -> Dict:
        """
        Finds a specific message in the body of the conversation based on the message id.

        Args:
            body (Dict): The body of the conversation.
            msg_id (str): The ID of the message to be retrieved.

        Returns:
            Dict: The message with the given ID.

        Raises:
            ValueError: If no message matching ID is found.
        """
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

        Args:
            content (str): The content of the message in which to search for a valid code block.

        Returns:
            str: The valid code block, if one is found.

        Raises:
            ValueError: If no valid code block is found in the message content.
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
        """
        Renders the model code given into html components for display.

        Args:
            model_code (str): The code for the model to be rendered.
            chat_id (str): The id of the chat for which the model is being generated
            msg_id (str): The id of the message for which the model is being generated

        Returns:
            Tuple[str, str]: The filename of the glb model produced (to allow for downloading)
                and the html code for displaying the model.

        Raises:
            httpx.RequestError: If an error response is received from the blender render server.
        """
        print("OpenWebUI/BLENDER/render_model_to_html - Rendering model to HTML...")
        model = await self.render_model(model_code)
        model_filename, model_html = await self.generate_model_html(
            model, chat_id, msg_id
        )
        if not model_html:
            raise httpx.RequestError("Request to blender server failed")
        print("OpenWebUI/BLENDER/render_model_to_html - Model HTML rendered!")
        return model_filename, model_html

    async def render_model(
        self,
        model_code: str,
    ) -> bytes:
        """
        Makes a request for the blender render server to render a model from the given code.

        Args:
            model_code (str): The code for the model to be rendered.

        Returns:
            bytes: The raw bytes of the glb file rendered by the server.

        Raises:
            httpx.RequestError: If an error response is received from the blender render server.
        """
        payload = {"model_code": model_code}
        print(
            "OpenWebUI/BLENDER/render_model - Requesting GLB from blender render server..."
        )
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.valves.BLENDER_SERVER_URL}create_model",
                    json=payload,
                )

                # Check if the response is an error (HTTP 4xx or 5xx status)
                if 400 <= response.status_code < 600:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("error", "Unknown error")
                        details = error_data.get("details", "")
                        blender_log = error_data.get("blender_log", "")
                        raise BlenderRenderError(error_msg, details, blender_log)
                    except json.JSONDecodeError:
                        raise BlenderRenderError(
                            f"HTTP {response.status_code}", response.text, ""
                        )

                response.raise_for_status()
                print("OpenWebUI/BLENDER/render_model - Response received!")
                return response.content

            except httpx.RequestError as e:
                raise BlenderRenderError(
                    f"Network error: {str(e)}",
                    "Could not connect to the Blender render server. Please check that it's running.",
                    "",
                )

    async def generate_model_html(
        self, model: bytes, chat_id: str, msg_id: str
    ) -> Tuple[str, str]:
        """
        Makes a request for the blender render server to render a model from the given code.

        Args:
            model (bytes): The raw bytes of the glb file rendered by the server.
            chat_id (str): The id of the chat for which the model is being generated
            msg_id (str): The id of the message for which the model is being generated

        Returns:
            Tuple[str, str]: The filename of the glb model produced (to allow for downloading)
                and the html code for displaying the model.
        """
        print("OpenWebUI/BLENDER/generate_model_html - Generating model HTML...")
        model_cache = Path("data") / self.cache / "models"
        existing_models = len([*model_cache.glob(f"{chat_id}-model-{msg_id}*.glb")])
        glb_filename = f"{chat_id}-model-{msg_id}-{existing_models}.glb"
        glb_filepath = (
            (model_cache / glb_filename).resolve().relative_to(Path().resolve())
        )
        model_cache.mkdir(parents=True, exist_ok=True)
        write_model_task = asyncio.create_task(
            self.write_model_to_cache(model, glb_filepath)
        )
        template_html_task = asyncio.create_task(self.template_html(glb_filename))
        await write_model_task
        print("OpenWebUI/BLENDER/generate_model_html - Model GLB generated!")
        return glb_filename, await template_html_task

    async def write_model_to_cache(self, model: bytes, glb_filepath: Path):
        """
        Writes model bytes to a file in the cache.

        Args:
            model (bytes): The raw bytes of the glb file rendered by the server.
            glb_filepath (Path): The path to write the glb file to.
        """
        print("OpenWebUI/BLENDER/write_model_to_cache - Writing model data to cache...")
        with glb_filepath.open("wb") as glb_file:
            glb_file.write(model)
        print("OpenWebUI/BLENDER/write_model_to_cache - Model data cached!")

    async def template_html(self, glb_filename: str) -> str:
        """
        Generates HTML using Google's model-viewer web component.
        """
        print("OpenWebUI/BLENDER/template_html - Creating model-viewer template...")

        model_path = f"/{self.cache}models/{glb_filename}"

        return f"""<script type="module" src="https://ajax.googleapis.com/ajax/libs/model-viewer/4.0.0/model-viewer.min.js"></script>
<script type="module">
  const modelViewer = document.getElementById("mv");
  modelViewer.addEventListener("load", () => {{
    modelViewer.model.materials[0].pbrMetallicRoughness.setBaseColorFactor("#b3b3b3");
  }});
</script>
<model-viewer
    src="{model_path}"
    id="mv" camera-controls auto-rotate shadow-intensity="1" shadow-softness="0.5"
    style="width: 100vw; height: 100vh;">
</model-viewer>"""

    async def convert_glb_to_obj(self, glb_path: Path) -> Path:
        assert glb_path.exists()
        obj_path = glb_path.with_suffix(".obj")
        trimesh.load(glb_path).export(obj_path)
        return obj_path
