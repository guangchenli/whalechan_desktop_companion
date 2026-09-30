"""Expose the running desktop companion as an MCP terminal bell over stdio."""
import asyncio
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from PyQt6.QtCore import QCoreApplication
from pydantic import Field

from pet_ipc import send_request
from contracts import (ActionList, ActionResult, BellResult, PetStatus,
                       MAX_MESSAGE, MAX_TITLE, validate_action, validate_notification)


mcp = FastMCP(
    "Desktop Pet Bell",
    instructions="Use desktop_pet_bell like a terminal bell to notify the user when work finishes, "
                 "needs their attention, or reaches a meaningful milestone. Send a few concise "
                 "sentences in the user's language. Notifications appear beside their desktop pet. "
                 "Avoid frequent progress messages. Use desktop_pet_list_actions to discover animations "
                 "and desktop_pet_play_action to play one. The desktop pet must already be running.",
)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
async def desktop_pet_bell(
    message: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE)],
    title: Annotated[str, Field(min_length=1, max_length=MAX_TITLE, pattern=r"^[^\r\n]+$")] = "Agent",
    duration_seconds: Annotated[float, Field(ge=3, le=120)] = 12,
    sound: bool = False,
) -> BellResult:
    """Notify the user with a manga speech bubble beside their desktop pet.

    message: Plain text, 1–2000 characters; supports Chinese and multiple lines.
    title: Short sender or task label, 1–60 characters on one line.
    duration_seconds: Legacy compatibility field, 3–120 seconds; does not dismiss the bubble.
    The bubble stays visible until the user closes it. A red badge counts waiting messages.
    sound: Also request the system bell (desktop settings may silence it).
    Returns displayed/queued and a notification id, confirming acceptance, not that it was read.
    Messages queue in arrival order; a full queue returns an error. Does not take keyboard focus.
    """
    options = validate_notification(message, title, duration_seconds, sound)
    return await asyncio.to_thread(send_request, dict(command="bell", **options))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def desktop_pet_status() -> PetStatus:
    """Check pet readiness, notification queue, current animation and whether animation is paused."""
    return await asyncio.to_thread(send_request, {"command": "status"})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def desktop_pet_list_actions() -> ActionList:
    """List this pet's available animation names, Chinese labels, loop flags and cycle durations.

    Use the returned action names with desktop_pet_play_action; available actions depend on the pet.
    Includes the current animation and whether it is paused. Requires a running desktop pet.
    """
    return await asyncio.to_thread(send_request, {"command": "list_actions"})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
async def desktop_pet_play_action(
    action: Annotated[str, Field(min_length=1, max_length=64)],
    once: bool = True,
) -> ActionResult:
    """Immediately play a specific animation on the desktop pet, resuming paused animation.

    action: An exact name returned by desktop_pet_list_actions, e.g. waving, jumping, running, idle.
    once: True by default; play one complete cycle then return to idle. False follows the track's
    original loop/fallback behavior, so non-looping tracks still end. Use idle with once false
    to return to normal idle animation. Replaces the current action without queuing or moving
    the window. Returns acceptance immediately; unknown actions return an error without changes.
    """
    options = validate_action(action, once)
    return await asyncio.to_thread(send_request, dict(command="play_action", **options))


if __name__ == "__main__":
    # Local sockets use blocking I/O in worker threads; no GUI or Qt event loop is needed here.
    qt_app = QCoreApplication([])
    mcp.run(transport="stdio")
