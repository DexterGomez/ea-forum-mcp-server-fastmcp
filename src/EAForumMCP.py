from fastmcp import FastMCP
from typing import Annotated, Literal, Any
from pydantic import Field
import mcp.types as types

from src.utils.cache import get_cache
from src.config.settings import settings
from src.clients.algolia_client import AlgoliaClient
from src.clients.graphql_client import GraphQLClient
from src.utils.retry import retry_with_backoff

class EAForumMCP:
    def __init__(self):
        self.mcp = FastMCP("EA Forum")
        self.cache = get_cache(settings.CACHE_TTL_SECONDS, settings.CACHE_MAX_SIZE)
        self.algolia_client = AlgoliaClient(settings.EA_FORUM_API_BASE_URL, settings.REQUEST_TIMEOUT_SECONDS)
        self.graphql_client = GraphQLClient(settings.EA_FORUM_GRAPHQL_ENDPOINT, settings.REQUEST_TIMEOUT_SECONDS)

        # initializes tools
        self._register_tools()

    def _register_tools(self) -> None:
        self.mcp.tool(self.search_posts)
        self.mcp.tool(self.get_post)
        self.mcp.tool(self.search_by_tag)

    def run(self, transport: Literal['stdio', 'streamable-http', 'sse'] | None = None, **transport_kwargs: Any) -> None:
        """Equivalent to fastmcp.FastMCP.run"""
        self.mcp.run(transport, **transport_kwargs)

    @retry_with_backoff(max_retries=settings.MAX_RETRIES, initial_delay=settings.RETRY_DELAY_SECONDS)
    async def search_posts(self,
        query: Annotated[str, Field(description="Search query string")],
        date_range: Annotated[Literal["day","week","month","year"], Field(description="Date filer")],
        limit : Annotated[int, Field(description="Number of results to return", ge=1, le=100)] = 10,
        page : Annotated[int, Field(description="Page number", ge=0)] = 0, 
        curated_only: Annotated[bool, Field(description="Only return curated posts")] = False,
        exclude_events: Annotated[bool, Field(description="Exclude event posts")] = True
    ) -> list[types.TextContent]:
        """Serach EA Forum posts using full-text search"""

        cache_key = self.cache.get_search_key(
            query=query,
            date_range=date_range,
            limit=limit,
            page=page,
            curated_only=curated_only,
            exclude_events=exclude_events
        )
        
        cached_result = self.cache.get(cache_key)

        if cached_result:
            return [types.TextContent(type="text", text=cached_result)]
        
        results = self.algolia_client.search_posts(
            search_query=query,
            date_range=date_range,
            limit=limit,
            page=page,
            curated_only=curated_only,
            exclude_events=exclude_events
        )

        if not results or not results[0]["hits"]:
            response = "No posts found matching your search criteria."
        else:
            posts = results[0]["hits"]
            total_hits = results[0]["nbHits"]
            
            response_parts = [f"Found {total_hits} posts. Showing {len(posts)} results:\n"]
            
            for i, post in enumerate(posts, 1):
                tags = ", ".join(tag["name"] for tag in post.get("tags", []))
                response_parts.append(
                    f"\n{i}. **{post['title']}**\n"
                    f"   - ID: {post['objectID']}\n"
                    f"   - Author: {post['authorDisplayName']}\n"
                    f"   - Score: {post['baseScore']}\n"
                    f"   - Posted: {post['postedAt']}\n"
                    f"   - Tags: {tags}\n"
                    f"   - Preview: {post['body'][:200]}...\n"
                )
            
            response = "\n".join(response_parts)

        # Cache the result
        self.cache.set(cache_key, response)
        
        return [types.TextContent(type="text", text=response)]

    @retry_with_backoff(max_retries=settings.MAX_RETRIES, initial_delay=settings.RETRY_DELAY_SECONDS)
    async def get_post(self,
        post_id: Annotated[str, Field(description="The post ID to retrive")]
    ) -> list[types.TextContent]:
        """Get full content of a specific EA Forum post by ID"""

        # Check cache
        cache_key = self.cache.get_post_key(post_id)
        cached_result = self.cache.get(cache_key)
        if cached_result:
            return [types.TextContent(type="text", text=cached_result)]

        # Get post content
        post = self.graphql_client.get_post_by_id(post_id)

        if not post:
            response = f"Post with ID '{post_id}' not found."
        else:
            tags = ", ".join(tag["name"] for tag in post.get("tags", []))
            
            response = (
                f"# {post['title']}\n\n"
                f"**Author:** {post['user']['displayName']} (Karma: {post['user']['karma']})\n"
                f"**Posted:** {post['postedAt']}\n"
                f"**Score:** {post['baseScore']} (Votes: {post['voteCount']})\n"
                f"**Comments:** {post['commentCount']}\n"
                f"**Tags:** {tags}\n"
                f"**Word Count:** {post['contents']['wordCount']}\n\n"
                f"## Content\n\n"
                f"{post['contents']['plaintextDescription']}\n\n"
                f"---\n"
                f"*Full HTML content available in post['contents']['html']*"
            )

        # Cache the result
        self.cache.set(cache_key, response)
        
        return [types.TextContent(type="text", text=response)]

    async def search_by_tag(self,
        tag: Annotated[Literal[*tuple(settings.KNOWN_TAGS.keys())], Field(description="Tag name to search for")], # "*tuple" unpacks tags # type: ignore
        limit: Annotated[int, Field(description="Number of results to return", ge=1, le=100)] = 30
    ) -> list[types.TextContent]:
        """Search posts by a specific tag"""
        tag_key = tag
        if tag_key not in settings.KNOWN_TAGS:
            return [types.TextContent(type="text", text=f"Unknown tag: {tag_key}")]

        tag_info = settings.KNOWN_TAGS[tag_key]
        
        # Search using the tag name
        results = self.algolia_client.search_by_tag(
            tag_id=tag_info["id"],
            tag_name=tag_info["name"],
            limit=limit,
        )

        if not results or not results[0]["hits"]:
            response = f"No posts found for tag '{tag_info['name']}'."
        else:
            posts = results[0]["hits"]
            
            response_parts = [
                f"Found {len(posts)} posts tagged with '{tag_info['name']}':\n"
            ]
            
            for i, post in enumerate(posts, 1):
                response_parts.append(
                    f"\n{i}. **{post['title']}**\n"
                    f"   - ID: {post['objectID']}\n"
                    f"   - Author: {post['authorDisplayName']}\n"
                    f"   - Score: {post['baseScore']}\n"
                    f"   - Posted: {post['postedAt']}\n"
                )
            
            response = "\n".join(response_parts)
        
        return [types.TextContent(type="text", text=response)]