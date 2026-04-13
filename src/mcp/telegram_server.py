"""MCP server exposing Telegram-specific tools to Claude.

Runs as a stdio transport server. The ``send_image_to_user`` tool validates
file existence and extension, then returns a success string. Actual Telegram
delivery is handled by the bot's stream callback which intercepts the tool
call.
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}

mcp = FastMCP("telegram")


@mcp.tool()
async def send_image_to_user(file_path: str, caption: str = "") -> str:
    """Send an image file to the Telegram user.

    Args:
        file_path: Absolute path to the image file.
        caption: Optional caption to display with the image.

    Returns:
        Confirmation string when the image is queued for delivery.
    """
    path = Path(file_path)

    if not path.is_absolute():
        return f"Error: path must be absolute, got '{file_path}'"

    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return (
            f"Error: unsupported image extension '{path.suffix}'. "
            f"Supported: {', '.join(sorted(IMAGE_EXTENSIONS))}"
        )

    if not path.is_file():
        return f"Error: file not found: {file_path}"

    return f"Image queued for delivery: {path.name}"


@mcp.tool()
async def send_voice_reply(text: str) -> str:
    """Send a voice note to the Telegram user using text-to-speech synthesis.

    Use this tool when the user explicitly asks for an audio / voice reply,
    or when a short conversational response would feel natural as spoken audio.
    Do NOT use it for code blocks, long technical explanations, or when the
    user has said they do not want voice replies.

    When called, the bot will synthesize *text* as an OGG voice note and send
    it instead of the plain text response.  Write *text* as natural spoken
    language — avoid markdown formatting, code fences, and bullet points.

    Args:
        text: The spoken text to synthesize. Keep it conversational.

    Returns:
        Confirmation string when the voice note is queued for delivery.
    """
    if not text or not text.strip():
        return "Error: text must not be empty."
    return f"Voice note queued for delivery ({len(text.split())} words)."


if __name__ == "__main__":
    mcp.run(transport="stdio")
