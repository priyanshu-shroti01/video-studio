"""Project-local MCP server (stdio) for social publishing: `uv run video-pipeline-mcp` (docs/SOCIAL_PUBLISHING.md).

Tools (annotations are hints for the client; the real rules are enforced in pipeline/publishing.gate()):
  list_publishable        read-only                     productions with a rendered package, grouped by brand
  plan_platforms          read-only                     routing from the real video files (ffprobe)
  publication_status      read-only                     approvals, publications, open review flags
  draft_metadata          writes local files            local LLM / template; refused after approval
  keyword_research        read-only, OPEN WORLD         sends only generic seed phrases; shows the queries
  publish_youtube         DESTRUCTIVE, OPEN WORLD       publishing.publish(confirm=True) through gate()
  publish_instagram_reel  DESTRUCTIVE, OPEN WORLD       publishing.publish(confirm=True) through gate()

An AI assistant must call a publish tool ONLY when the user explicitly asked to publish that production to that
platform, and publish tools must never be added to a permissions allowlist.

stdout is the MCP protocol: nothing else is printed there. Logs go to stderr. Secrets and tokens are never
returned or logged (adapters keep them in headers; results carry ids, metadata and hashes only)."""
from __future__ import annotations

import logging
import re
import sys

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from ..errors import PipelineError

log = logging.getLogger("video-pipeline-mcp")
SECRETISH = re.compile(r"(access_token|refresh_token|client_secret|api_key|Authorization|Bearer|OAuth)\S*", re.I)

INSTRUCTIONS = (
    "Social publishing for this local video studio. Read-only tools are safe. draft_metadata writes "
    "publishing/metadata.json BEFORE approval only. publish_youtube and publish_instagram_reel upload to the "
    "brand's real accounts: call them only when the user explicitly asked to publish that production to that "
    "platform, pass the user's own name as actor, and never on your own initiative. Approval, review flags and "
    "credentials are human decisions and are not available as tools.")

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
LOCAL_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
NETWORK_READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
PUBLISH = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)


def _safe(fn, *a, **kw) -> dict:
    """Run a service call; turn pipeline errors into a structured refusal (no stack traces, no secrets)."""
    try:
        return {"ok": True, **fn(*a, **kw)}
    except PipelineError as e:
        log.info("refused: %s", e.code)
        return {"ok": False, "error": {"code": e.code, "message": SECRETISH.sub("[redacted]", e.message)}}


def build_server() -> MCPServer:
    from . import service
    srv = MCPServer("video-pipeline-social", instructions=INSTRUCTIONS)

    @srv.tool(annotations=READ_ONLY, title="List publishable productions")
    def list_publishable(brand_id: str | None = None) -> dict:
        """Productions with a rendered approval package, grouped by brand, with formats, metadata status,
        approval state, existing publications and whether each brand's accounts are configured. Offline."""
        return _safe(service.list_publishable, brand_id)

    @srv.tool(annotations=READ_ONLY, title="Plan platforms")
    def plan_platforms(production_id: str) -> dict:
        """Which platforms each rendered video can go to, with reasons, from ffprobe of the real file.
        9:16 <= 180 s: YouTube Shorts + Instagram Reels; 16:9: YouTube with chapters, never Instagram."""
        return _safe(service.plan_platforms, production_id)

    @srv.tool(annotations=READ_ONLY, title="Publication status")
    def publication_status(production_id: str) -> dict:
        """State, approvals (valid or invalidated), publications and open review flags of a production."""
        return _safe(service.publication_status, production_id)

    @srv.tool(annotations=LOCAL_WRITE, title="Draft social metadata")
    def draft_metadata(production_id: str, brand_id: str | None = None, provider: str = "ollama",
                       keyword: str | None = None, publish_at: str | None = None, set_thumbnail: bool = False) -> dict:
        """Write publishing/metadata.json (+ title/description/hashtags) with the LOCAL LLM (provider 'ollama')
        or the deterministic template ('template'); falls back to the template automatically. Only allowed
        before approval (QA_COMPLETE / AWAITING_APPROVAL): metadata is part of the approved package. Nothing is
        published. publish_at: optional ISO 8601 YouTube schedule (privacy becomes private)."""
        if provider not in ("ollama", "template"):
            return {"ok": False, "error": {"code": "INVALID", "message": "provider must be 'ollama' or 'template'"}}
        return _safe(service.draft_metadata, production_id, brand_id=brand_id, provider=provider, keyword=keyword,
                     publish_at=publish_at, set_thumbnail=set_thumbnail)

    @srv.tool(annotations=NETWORK_READ, title="Keyword research (network)")
    def keyword_research(production_id: str | None = None, brand_id: str | None = None,
                         extra_seeds: list[str] | None = None, use_youtube_api: bool = False) -> dict:
        """Search-demand research on YouTube autocomplete (and optionally the YouTube Data API). Sends ONLY the
        brand profile's generic seed phrases (plus extra seeds that are plain lowercase words). The exact
        outgoing URLs are returned in `queries`. Cached 24 h. Not a ranking guarantee; Instagram has no trends API."""
        return _safe(service.keyword_research, production_id=production_id, brand_id=brand_id,
                     extra_seeds=extra_seeds, use_youtube_api=use_youtube_api)

    @srv.tool(annotations=PUBLISH, title="Publish to YouTube")
    def publish_youtube(production_id: str, format: str, actor: str, brand_id: str | None = None) -> dict:  # noqa: A002
        """UPLOADS the approved video to the brand's YouTube channel. Only when the user explicitly asked to
        publish THIS production to YouTube. actor = the user's own name. Refused unless APPROVED, the approval
        is still valid, QA passed, the file hashes match, and the credentials belong to the brand's channel.
        Returns what was sent (metadata, hash, remote id)."""
        return _safe(service.publish, production_id, "youtube", format, actor, brand_id=brand_id)

    @srv.tool(annotations=PUBLISH, title="Publish an Instagram Reel")
    def publish_instagram_reel(production_id: str, actor: str, format: str = "short", brand_id: str | None = None) -> dict:  # noqa: A002
        """UPLOADS the approved 9:16 video as a Reel to the brand's Instagram account. Only when the user
        explicitly asked to publish THIS production to Instagram. actor = the user's own name. Landscape or
        non-9:16 video is refused. Same gate as YouTube plus the account's publishing rate limit."""
        return _safe(service.publish, production_id, "instagram", format, actor, brand_id=brand_id)

    return srv


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from ..paths import ensure_dirs
    ensure_dirs()
    log.info("starting stdio server")
    build_server().run("stdio")


if __name__ == "__main__":
    main()
