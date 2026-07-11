# backend/publishing/mcp_server.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json

try:
    from mcp.server import Server
    from mcp.server.models import InitializationOptions
    from mcp.server.stdio import stdio_server
    from mcp import types as mcp_types
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    print("❌ MCP not installed. Run: uv pip install mcp")

if MCP_AVAILABLE:
    app = Server("ai-content-studio")

    @app.list_tools()
    async def list_tools() -> list:
        """
        Dynamically generate tool list from registry.
        Every registered platform becomes an MCP tool automatically.
        """
        from publishing.registry import get_available_platforms, PLATFORM_REGISTRY

        tools = []

        # One publish tool per registered platform
        for p in get_available_platforms():
            pid = p["id"]
            is_thread = pid == "twitter"
            tools.append(mcp_types.Tool(
                name=f"publish_{pid}",
                description=(
                    f"Publish content to {p['display']} {p['emoji']}. "
                    f"{'Auto-posting restricted — returns copy instructions.' if p.get('auto_post_restricted') else 'Supports auto-posting.'} "
                    f"Supports images: {p['supports_images']}."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "content": {
                            "type": "array" if is_thread else "string",
                            "description": "Tweet list" if is_thread else "Post text",
                            **({"items": {"type": "string"}} if is_thread else {}),
                        },
                        "image_path": {"type": "string",
                                       "description": "Optional local image path"},
                    },
                    "required": ["topic", "content"],
                },
            ))

        # Platform-agnostic tools
        tools.extend([
            mcp_types.Tool(
                name="generate_image",
                description=(
                    "Generate AI image using Gemini prompt + Pollinations.ai. "
                    "Free, no API key required for generation."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "platform": {
                            "type": "string",
                            "enum": ["twitter", "linkedin", "blog", "facebook"],
                        },
                        "content_summary": {"type": "string"},
                    },
                    "required": ["topic", "platform"],
                },
            ),
            mcp_types.Tool(
                name="check_content_safety",
                description=(
                    "Check if a topic is safe to generate content about. "
                    "Returns SAFE, BORDERLINE, or BLOCKED with reason."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"topic": {"type": "string"}},
                    "required": ["topic"],
                },
            ),
            mcp_types.Tool(
                name="publish_all_approved",
                description=(
                    "Publish approved session content to all configured platforms. "
                    "Generates images, runs safety checks, publishes concurrently."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "blog_post": {"type": "string"},
                        "linkedin_post": {"type": "string"},
                        "twitter_thread": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "platforms": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "generate_images": {"type": "boolean", "default": True},
                    },
                    "required": ["topic"],
                },
            ),
            mcp_types.Tool(
                name="list_platform_status",
                description="List all platforms and whether their credentials are configured.",
                inputSchema={"type": "object", "properties": {}},
            ),
            mcp_types.Tool(
                name="get_copy_instructions",
                description="Get copy-paste instructions for platforms that restrict auto-posting.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["platform", "content"],
                },
            ),
        ])

        return tools

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list:
        from publishing.registry import (
            get_publisher, get_available_platforms,
            get_platform_status, PLATFORM_REGISTRY,
            AUTO_POST_RESTRICTED, COPY_INSTRUCTIONS,
        )
        from publishing.base import PlatformContent
        from publishing.image_generator import generate_image
        from publishing.guardrails import check_topic_safety
        from publishing.publisher import publish_approved_content

        result = {}

        # ── Dynamic platform tools ────────────────────────────────────────────
        for platform_id in PLATFORM_REGISTRY.keys():
            if name == f"publish_{platform_id}":
                # Check if restricted
                if platform_id in AUTO_POST_RESTRICTED:
                    content_raw = arguments.get("content", "")
                    _, display, copy_url = COPY_INSTRUCTIONS.get(
                        platform_id, ("", platform_id, ""))
                    result = {
                        "success": False,
                        "restricted": True,
                        "reason": AUTO_POST_RESTRICTED[platform_id],
                        "copy_url": copy_url,
                        "copy_instructions": (
                            f"Copy your content and paste at {copy_url}\n\n"
                            f"Content to copy:\n{content_raw}"
                        ),
                    }
                else:
                    publisher = get_publisher(platform_id)
                    content_raw = arguments.get("content", "")
                    content = PlatformContent(
                        topic=arguments.get("topic", ""),
                        tone="professional",
                        blog_post=content_raw if platform_id in ["blog"] else "",
                        linkedin_post=content_raw if platform_id == "linkedin" else "",
                        twitter_thread=content_raw if platform_id == "twitter" else [],
                        image_path=arguments.get("image_path"),
                    )
                    pub_result = await publisher.run(content)
                    result = pub_result.to_dict()
                break

        # ── Static tools ──────────────────────────────────────────────────────
        if name == "generate_image":
            path = await generate_image(
                topic=arguments["topic"],
                platform=arguments.get("platform", "blog"),
                content_summary=arguments.get("content_summary", ""),
            )
            result = {"success": bool(path), "image_path": path or ""}

        elif name == "check_content_safety":
            safety = await check_topic_safety(arguments["topic"])
            result = {
                "level": safety.level.value,
                "is_allowed": safety.is_allowed,
                "reason": safety.reason,
                "warning": safety.warning_message,
            }

        elif name == "publish_all_approved":
            session_data = {
                "topic": arguments.get("topic", ""),
                "tone": "professional",
                "blog_post": arguments.get("blog_post", ""),
                "linkedin_post": arguments.get("linkedin_post", ""),
                "twitter_thread": arguments.get("twitter_thread", []),
            }
            result = await publish_approved_content(
                session_data=session_data,
                platforms=arguments.get("platforms", list(PLATFORM_REGISTRY.keys())),
                generate_images=arguments.get("generate_images", True),
            )

        elif name == "list_platform_status":
            statuses = await get_platform_status()
            result = {"platforms": statuses}

        elif name == "get_copy_instructions":
            platform = arguments.get("platform", "")
            content = arguments.get("content", "")
            _, display, copy_url = COPY_INSTRUCTIONS.get(
                platform, ("", platform, ""))
            result = {
                "platform": display,
                "copy_url": copy_url,
                "instructions": f"1. Copy the content below\n2. Open {copy_url}\n3. Paste and publish\n\nContent:\n{content}",
                "restricted": platform in AUTO_POST_RESTRICTED,
                "restriction_reason": AUTO_POST_RESTRICTED.get(platform, ""),
            }

        return [mcp_types.TextContent(type="text", text=json.dumps(result, indent=2))]

    async def main():
        from publishing.registry import get_available_platforms
        platforms = get_available_platforms()
        print("🚀 AI Content Studio MCP Server")
        print(f"   Platforms: {[p['id'] for p in platforms]}")
        print(f"   Total tools: {len(platforms) + 5}")
        print("   Waiting for MCP client...")
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream, write_stream,
                InitializationOptions(
                    server_name="ai-content-studio",
                    server_version="1.0.0",
                    capabilities=app.get_capabilities(
                        notification_options=None,
                        experimental_capabilities={},
                    ),
                ),
            )

if __name__ == "__main__":
    if not MCP_AVAILABLE:
        sys.exit(1)
    asyncio.run(main())