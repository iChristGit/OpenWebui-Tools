"""
title: Reddit Explorer 🔴
author: ichrist
description: Explore Reddit directly in your chat! Browse hot/new/top posts, search subreddits, read comments, view images and videos, all without any API key. The LLM intelligently picks the best subreddit for your query.
version: 1.0.0
license: MIT
requirements: requests
"""

import json
import re
import urllib.parse
from typing import Any, Callable, Optional
import requests

# ─── Subreddit suggestion map ─────────────────────────────────────────────────
TOPIC_SUBREDDIT_MAP = {
    "news": ["worldnews", "news", "UpliftingNews", "nottheonion"],
    "technology": ["technology", "tech", "gadgets", "hardware", "software"],
    "programming": [
        "programming",
        "learnprogramming",
        "webdev",
        "Python",
        "javascript",
    ],
    "ai": ["artificial", "MachineLearning", "ChatGPT", "LocalLLaMA", "singularity"],
    "gaming": ["gaming", "pcgaming", "PS5", "xbox", "NintendoSwitch"],
    "science": ["science", "physics", "biology", "chemistry", "space"],
    "finance": [
        "personalfinance",
        "investing",
        "stocks",
        "CryptoCurrency",
        "wallstreetbets",
    ],
    "health": ["health", "fitness", "nutrition", "loseit", "running"],
    "movies": ["movies", "MovieSuggestions", "criterion", "horror", "scifi"],
    "music": [
        "Music",
        "listentothis",
        "hiphopheads",
        "indieheads",
        "WeAreTheMusicMakers",
    ],
    "sports": ["sports", "nba", "nfl", "soccer", "formula1"],
    "politics": ["politics", "worldpolitics", "europe", "geopolitics"],
    "food": ["food", "Cooking", "recipes", "MealPrepSunday", "AskCulinary"],
    "travel": ["travel", "solotravel", "backpacking", "digitalnomad"],
    "funny": ["funny", "memes", "dankmemes", "me_irl", "ProgrammerHumor"],
    "ask": ["AskReddit", "NoStupidQuestions", "explainlikeimfive", "answers"],
    "photography": ["photocritique", "itookapicture", "analog", "mobilephotography"],
    "crypto": ["CryptoCurrency", "Bitcoin", "ethereum", "defi", "NFT"],
    "cars": ["cars", "Autos", "electricvehicles", "teslamotors", "formula1"],
    "fashion": [
        "malefashionadvice",
        "femalefashionadvice",
        "streetwear",
        "frugalmalefashion",
    ],
    "books": ["books", "literature", "suggestmeabook", "fantasy", "scifibooks"],
    "diy": ["DIY", "woodworking", "crafts", "3Dprinting", "electronics"],
    "nature": ["nature", "EarthPorn", "NaturePorn", "hiking", "camping"],
    "default": ["all", "popular", "worldnews", "AskReddit", "todayilearned"],
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

HEADERS = {"User-Agent": "OpenWebUI-RedditExplorer/1.0 (educational tool)"}


def _get(url: str, params: dict = None) -> Optional[dict]:
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _format_number(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


def _media_block(post: dict) -> str:
    """Return a markdown block for any media attached to a post."""
    lines = []
    hint = post.get("post_hint", "")
    url = post.get("url", "")
    preview = post.get("preview", {})
    media = post.get("media", {})
    secure_media = post.get("secure_media", {})
    gallery = post.get("is_gallery", False)
    gallery_data = post.get("gallery_data", {})
    media_metadata = post.get("media_metadata", {})

    # Image
    if hint == "image" or (
        url and re.search(r"\.(jpg|jpeg|png|gif|webp)(\?.*)?$", url, re.I)
    ):
        lines.append(f"\n> 🖼️ **Image**\n\n![post image]({url})\n")

    # Reddit-hosted video
    elif hint == "hosted:video":
        video_url = (
            (secure_media or {}).get("reddit_video", {}).get("fallback_url")
            or (media or {}).get("reddit_video", {}).get("fallback_url")
            or url
        )
        lines.append(f"\n> 🎬 **Video** — [▶ Watch on Reddit]({video_url})\n")

    # Embedded video (YouTube, Twitch, etc.)
    elif hint == "rich:video":
        embed_url = (
            (secure_media or {}).get("oembed", {}).get("url")
            or (media or {}).get("oembed", {}).get("url")
            or url
        )
        thumb = (secure_media or {}).get("oembed", {}).get("thumbnail_url") or (
            media or {}
        ).get("oembed", {}).get("thumbnail_url", "")
        provider = (
            (secure_media or {}).get("oembed", {}).get("provider_name", "External")
        )
        lines.append(f"\n> 🎥 **{provider} Video** — [▶ Open Video]({embed_url})\n")
        if thumb:
            lines.append(f"![thumbnail]({thumb})\n")

    # Gallery
    elif gallery and gallery_data:
        items = gallery_data.get("items", [])[:4]
        lines.append(
            f"\n> 🖼️ **Gallery** ({len(gallery_data.get('items',[]))} images)\n"
        )
        for item in items:
            mid = item.get("media_id", "")
            meta = media_metadata.get(mid, {})
            src = meta.get("s", {})
            img_url = src.get("u", "").replace("&amp;", "&")
            if img_url:
                lines.append(f"![gallery image]({img_url})\n")

    # Preview image (fallback for link posts)
    elif preview:
        imgs = preview.get("images", [])
        if imgs:
            src = imgs[0].get("source", {})
            img_url = src.get("url", "").replace("&amp;", "&")
            if img_url:
                lines.append(f"\n> 🔗 **Preview**\n\n![preview]({img_url})\n")

    return "\n".join(lines)


def _format_post(post: dict, index: int = None, show_media: bool = True) -> str:
    d = post.get("data", post)
    title = d.get("title", "No title")
    author = d.get("author", "[deleted]")
    subreddit = d.get("subreddit", "")
    score = _format_number(d.get("score", 0))
    num_comments = _format_number(d.get("num_comments", 0))
    upvote_ratio = int(d.get("upvote_ratio", 0) * 100)
    flair = d.get("link_flair_text", "")
    is_nsfw = d.get("over_18", False)
    is_spoiler = d.get("spoiler", False)
    post_id = d.get("id", "")
    permalink = f"https://reddit.com{d.get('permalink', '')}"
    selftext = d.get("selftext", "")
    url = d.get("url", "")
    post_hint = d.get("post_hint", "")
    created = d.get("created_utc", 0)

    prefix = f"**{index}.** " if index is not None else ""
    nsfw_tag = " 🔞`NSFW`" if is_nsfw else ""
    spoiler_tag = " 🙈`SPOILER`" if is_spoiler else ""
    flair_tag = f" `{flair}`" if flair else ""

    lines = [
        f"---",
        f"{prefix}### {title}{nsfw_tag}{spoiler_tag}{flair_tag}",
        f"👤 **u/{author}** · 📌 **r/{subreddit}** · ⬆️ **{score}** ({upvote_ratio}%) · 💬 **{num_comments} comments**",
    ]

    # Body text (truncated)
    if selftext and selftext != "[removed]" and selftext != "[deleted]":
        preview_text = selftext[:400].strip()
        if len(selftext) > 400:
            preview_text += "…"
        lines.append(f"\n> {preview_text.replace(chr(10), chr(10) + '> ')}")

    # Media
    if show_media:
        media_block = _media_block(d)
        if media_block:
            lines.append(media_block)

    # Link (external)
    if post_hint == "link" and url and "reddit.com" not in url:
        lines.append(f"\n🔗 [External link]({url})")

    lines.append(f"\n[💬 View full post & comments]({permalink})")
    return "\n".join(lines)


def _format_comment(comment: dict, depth: int = 0) -> str:
    d = comment.get("data", {})
    if not d or d.get("kind") == "more":
        return ""
    author = d.get("author", "[deleted]")
    body = d.get("body", "")
    score = _format_number(d.get("score", 0))
    if not body or body in ("[removed]", "[deleted]"):
        return ""
    indent = "  " * depth
    lines = [f"{indent}---", f"{indent}**u/{author}** · ⬆️ {score}"]
    for line in body[:500].split("\n"):
        lines.append(f"{indent}> {line}")
    if len(body) > 500:
        lines.append(f"{indent}> *(comment truncated)*")
    return "\n".join(lines)


# ─── Tool Class ───────────────────────────────────────────────────────────────


class Tools:
    def __init__(self):
        pass

    async def get_hot_posts(
        self,
        subreddit: str,
        limit: int = 10,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Fetch the current HOT posts from a subreddit. Use this when the user asks
        what's trending, popular, or hot on Reddit, or in a specific community.
        Automatically picks a good subreddit if none is specified.
        Includes post text, images, video links, score, and comment count.

        :param subreddit: The subreddit name (without r/), e.g. 'worldnews', 'gaming', 'AskReddit'. Use 'all' for front page.
        :param limit: Number of posts to return (1-25, default 10).
        :return: Formatted markdown with post titles, scores, media, and links.
        """
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"🔴 Fetching hot posts from r/{subreddit}…",
                        "done": False,
                    },
                }
            )

        limit = max(1, min(25, limit))
        data = _get(
            f"https://www.reddit.com/r/{subreddit}/hot.json",
            {"limit": limit, "raw_json": 1},
        )

        if "error" in data:
            return f"❌ Could not fetch r/{subreddit}: {data['error']}"

        posts = data.get("data", {}).get("children", [])
        if not posts:
            return f"No hot posts found in r/{subreddit}."

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"✅ Got {len(posts)} posts from r/{subreddit}",
                        "done": True,
                    },
                }
            )

        lines = [f"# 🔥 Hot Posts — r/{subreddit}\n"]
        for i, post in enumerate(posts, 1):
            lines.append(_format_post(post["data"], index=i))
        lines.append(
            f"\n\n---\n*Showing {len(posts)} hot posts from [r/{subreddit}](https://reddit.com/r/{subreddit})*"
        )
        return "\n".join(lines)

    async def get_new_posts(
        self,
        subreddit: str,
        limit: int = 10,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Fetch the NEWEST / most recent posts from a subreddit. Use when the user
        wants the latest, freshest, or most recent content from a community.

        :param subreddit: The subreddit name (without r/), e.g. 'technology', 'news'.
        :param limit: Number of posts to return (1-25, default 10).
        :return: Formatted markdown list of the newest posts.
        """
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"🆕 Fetching new posts from r/{subreddit}…",
                        "done": False,
                    },
                }
            )

        limit = max(1, min(25, limit))
        data = _get(
            f"https://www.reddit.com/r/{subreddit}/new.json",
            {"limit": limit, "raw_json": 1},
        )

        if "error" in data:
            return f"❌ Could not fetch r/{subreddit}: {data['error']}"

        posts = data.get("data", {}).get("children", [])
        if not posts:
            return f"No new posts found in r/{subreddit}."

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"✅ Loaded {len(posts)} new posts",
                        "done": True,
                    },
                }
            )

        lines = [f"# 🆕 New Posts — r/{subreddit}\n"]
        for i, post in enumerate(posts, 1):
            lines.append(_format_post(post["data"], index=i))
        lines.append(
            f"\n\n---\n*Showing {len(posts)} newest posts from [r/{subreddit}](https://reddit.com/r/{subreddit})*"
        )
        return "\n".join(lines)

    async def get_top_posts(
        self,
        subreddit: str,
        time_filter: str = "day",
        limit: int = 10,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Fetch the TOP-rated posts from a subreddit over a time period.
        Use this for 'best of', 'top posts this week/month/year', or 'most popular ever'.

        :param subreddit: The subreddit name (without r/), e.g. 'science', 'funny'.
        :param time_filter: Time range — one of: 'hour', 'day', 'week', 'month', 'year', 'all'. Default 'day'.
        :param limit: Number of posts (1-25, default 10).
        :return: Formatted markdown list of top posts.
        """
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"🏆 Fetching top posts from r/{subreddit} ({time_filter})…",
                        "done": False,
                    },
                }
            )

        valid = ["hour", "day", "week", "month", "year", "all"]
        if time_filter not in valid:
            time_filter = "day"
        limit = max(1, min(25, limit))
        data = _get(
            f"https://www.reddit.com/r/{subreddit}/top.json",
            {"t": time_filter, "limit": limit, "raw_json": 1},
        )

        if "error" in data:
            return f"❌ Could not fetch r/{subreddit}: {data['error']}"

        posts = data.get("data", {}).get("children", [])
        if not posts:
            return f"No top posts found in r/{subreddit}."

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"✅ Loaded {len(posts)} top posts",
                        "done": True,
                    },
                }
            )

        time_labels = {
            "hour": "Past Hour",
            "day": "Today",
            "week": "This Week",
            "month": "This Month",
            "year": "This Year",
            "all": "All Time",
        }
        label = time_labels.get(time_filter, time_filter)
        lines = [f"# 🏆 Top Posts — r/{subreddit} · {label}\n"]
        for i, post in enumerate(posts, 1):
            lines.append(_format_post(post["data"], index=i))
        lines.append(
            f"\n\n---\n*Top posts from [r/{subreddit}](https://reddit.com/r/{subreddit}) — {label}*"
        )
        return "\n".join(lines)

    async def search_subreddit(
        self,
        subreddit: str,
        query: str,
        sort: str = "relevance",
        time_filter: str = "all",
        limit: int = 10,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Search for posts matching a query within a specific subreddit (or all of Reddit).
        Use this when the user asks about a specific topic, event, or keyword within a community.
        Use subreddit='all' to search all of Reddit.

        :param subreddit: The subreddit name (without r/). Use 'all' to search everywhere.
        :param query: The search query/keywords.
        :param sort: Sort order — 'relevance', 'hot', 'top', 'new', 'comments'. Default 'relevance'.
        :param time_filter: Time range — 'hour', 'day', 'week', 'month', 'year', 'all'. Default 'all'.
        :param limit: Number of results (1-25, default 10).
        :return: Formatted markdown with matching posts.
        """
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"🔍 Searching r/{subreddit} for '{query}'…",
                        "done": False,
                    },
                }
            )

        limit = max(1, min(25, limit))
        params = {
            "q": query,
            "sort": sort,
            "t": time_filter,
            "limit": limit,
            "raw_json": 1,
        }
        if subreddit.lower() != "all":
            params["restrict_sr"] = "1"

        data = _get(f"https://www.reddit.com/r/{subreddit}/search.json", params)

        if "error" in data:
            return f"❌ Search failed: {data['error']}"

        posts = data.get("data", {}).get("children", [])
        if not posts:
            return f"🔍 No results found for **'{query}'** in r/{subreddit}."

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"✅ Found {len(posts)} results",
                        "done": True,
                    },
                }
            )

        scope = f"r/{subreddit}" if subreddit.lower() != "all" else "all of Reddit"
        lines = [f'# 🔍 Search: "{query}" in {scope}\n']
        for i, post in enumerate(posts, 1):
            lines.append(_format_post(post["data"], index=i))
        lines.append(f"\n\n---\n*{len(posts)} results for '{query}' in {scope}*")
        return "\n".join(lines)

    async def get_post_comments(
        self,
        post_id: str,
        subreddit: str,
        limit: int = 15,
        sort: str = "top",
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Fetch comments for a specific Reddit post. Use this when the user wants to
        read the discussion, reactions, or replies to a specific post.
        You need the post_id (the short alphanumeric ID from the post URL, e.g. '1abc23').

        :param post_id: The Reddit post ID (e.g. '1abc23' from the URL reddit.com/r/sub/comments/1abc23/...).
        :param subreddit: The subreddit where the post lives.
        :param limit: Number of top-level comments to return (1-50, default 15).
        :param sort: Comment sort — 'top', 'best', 'new', 'controversial', 'old'. Default 'top'.
        :return: Formatted markdown with the post and its top comments.
        """
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"💬 Loading comments for post {post_id}…",
                        "done": False,
                    },
                }
            )

        limit = max(1, min(50, limit))
        data = _get(
            f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json",
            {"limit": limit, "sort": sort, "raw_json": 1, "depth": 3},
        )

        if isinstance(data, dict) and "error" in data:
            return f"❌ Could not load comments: {data['error']}"

        if not isinstance(data, list) or len(data) < 2:
            return "❌ Unexpected response format from Reddit."

        # Post data
        post_listing = data[0].get("data", {}).get("children", [])
        if not post_listing:
            return "❌ Could not find post data."
        post = post_listing[0].get("data", {})

        # Comments
        comment_listing = data[1].get("data", {}).get("children", [])

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"✅ Loaded {len(comment_listing)} comments",
                        "done": True,
                    },
                }
            )

        lines = [
            _format_post(post, show_media=True),
            f"\n\n---\n## 💬 Top Comments ({sort})\n",
        ]
        count = 0
        for child in comment_listing:
            if child.get("kind") == "t1":
                comment_str = _format_comment(child, depth=0)
                if comment_str:
                    lines.append(comment_str)
                    count += 1
                    # Include first-level replies (1 level deep)
                    replies = child.get("data", {}).get("replies", {})
                    if isinstance(replies, dict):
                        for reply in replies.get("data", {}).get("children", [])[:3]:
                            if reply.get("kind") == "t1":
                                reply_str = _format_comment(reply, depth=1)
                                if reply_str:
                                    lines.append(reply_str)
        if count == 0:
            lines.append("*No comments yet.*")

        return "\n".join(lines)

    async def get_subreddit_info(
        self,
        subreddit: str,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Get detailed information about a subreddit: description, subscriber count,
        active users, creation date, rules, and related communities.
        Use this when the user asks 'what is r/...', 'tell me about r/...', or before
        browsing an unfamiliar community.

        :param subreddit: The subreddit name (without r/).
        :return: Formatted markdown with subreddit details and stats.
        """
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"ℹ️ Loading info for r/{subreddit}…",
                        "done": False,
                    },
                }
            )

        data = _get(f"https://www.reddit.com/r/{subreddit}/about.json", {"raw_json": 1})

        if "error" in data:
            return f"❌ Could not load info for r/{subreddit}: {data['error']}"

        d = data.get("data", {})
        if not d:
            return f"❌ Subreddit r/{subreddit} not found or is private."

        name = d.get("display_name_prefixed", f"r/{subreddit}")
        title = d.get("title", "")
        desc = d.get("public_description", "") or d.get("description", "")[:500]
        subscribers = _format_number(d.get("subscribers", 0))
        active = _format_number(d.get("active_user_count", 0))
        nsfw = "🔞 NSFW" if d.get("over18") else "✅ SFW"
        created = d.get("created_utc", 0)
        community_icon = (
            d.get("community_icon", "").split("?")[0] if d.get("community_icon") else ""
        )
        banner = (
            d.get("banner_background_image", "").split("?")[0]
            if d.get("banner_background_image")
            else ""
        )
        header = d.get("header_img", "")
        lang = d.get("lang", "en")
        url = f"https://reddit.com/r/{d.get('display_name', subreddit)}"

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "✅ Info loaded", "done": True},
                }
            )

        lines = [f"# 🏠 {name}"]
        if community_icon:
            lines.append(f"![icon]({community_icon})")
        if banner:
            lines.append(f"![banner]({banner})")
        lines += [
            f"### {title}" if title else "",
            f"\n{desc[:600]}" if desc else "",
            f"\n| Stat | Value |",
            f"|------|-------|",
            f"| 👥 Members | **{subscribers}** |",
            f"| 🟢 Online now | **{active}** |",
            f"| 🌍 Language | `{lang}` |",
            f"| 🔒 Content | {nsfw} |",
            f"| 🔗 Link | [{name}]({url}) |",
        ]

        # Fetch rules
        rules_data = _get(f"https://www.reddit.com/r/{subreddit}/about/rules.json")
        if rules_data and "rules" in rules_data:
            rules = rules_data["rules"][:5]
            if rules:
                lines.append("\n### 📜 Rules")
                for i, rule in enumerate(rules, 1):
                    lines.append(
                        f"{i}. **{rule.get('short_name', '')}** — {rule.get('description', '')[:150]}"
                    )

        return "\n".join(filter(lambda x: x is not None, lines))

    async def suggest_subreddits(
        self,
        topic: str,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Suggest the best subreddits for a given topic or interest.
        Use this when the user isn't sure which subreddit to browse, or asks
        'where on Reddit can I find X' or 'what subreddit is good for Y'.
        Also verifies each suggestion is real by checking subscriber counts.

        :param topic: The topic, interest, or theme to find subreddits for (e.g. 'cooking', 'AI news', 'workout motivation').
        :return: A curated list of relevant subreddits with descriptions and stats.
        """
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"🗺️ Finding subreddits for '{topic}'…",
                        "done": False,
                    },
                }
            )

        # Search Reddit itself for relevant subreddits
        data = _get(
            "https://www.reddit.com/subreddits/search.json",
            {"q": topic, "limit": 8, "raw_json": 1},
        )

        results = []
        if data and "data" in data:
            for child in data["data"].get("children", []):
                d = child.get("data", {})
                name = d.get("display_name", "")
                title = d.get("title", "")
                desc = (d.get("public_description") or "")[:150]
                subs = _format_number(d.get("subscribers", 0))
                active = _format_number(d.get("active_user_count", 0))
                nsfw = "🔞" if d.get("over18") else ""
                if name:
                    results.append((name, title, desc, subs, active, nsfw))

        # Also add from the local topic map
        topic_lower = topic.lower()
        local_suggestions = []
        for key, subs in TOPIC_SUBREDDIT_MAP.items():
            if key in topic_lower or topic_lower in key:
                local_suggestions = subs[:3]
                break

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"✅ Found {len(results)} subreddits",
                        "done": True,
                    },
                }
            )

        lines = [f"# 🗺️ Subreddits for: **{topic}**\n"]

        if results:
            lines.append("## 🔍 Search Results\n")
            for name, title, desc, subs, active, nsfw in results[:6]:
                lines.append(f"### r/{name} {nsfw}")
                if title:
                    lines.append(f"*{title}*")
                lines.append(f"👥 **{subs} members** · 🟢 **{active} online**")
                if desc:
                    lines.append(f"> {desc}")
                lines.append(f"🔗 [Visit r/{name}](https://reddit.com/r/{name})\n")

        if local_suggestions:
            lines.append("\n## 💡 Also Try\n")
            for sub in local_suggestions:
                lines.append(f"- [r/{sub}](https://reddit.com/r/{sub})")

        if not results and not local_suggestions:
            lines.append(
                f"I couldn't find specific subreddits for '{topic}', but try searching [r/all](https://reddit.com/r/all) or ask me to search Reddit directly!"
            )

        return "\n".join(lines)

    async def get_reddit_frontpage(
        self,
        feed: str = "popular",
        limit: int = 10,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Get the Reddit front page / global feeds. Use this when the user asks
        'what's happening on Reddit', 'show me Reddit', 'what's popular on Reddit',
        or doesn't specify a particular subreddit.

        :param feed: Which feed to show — 'popular' (most upvoted across Reddit), 'all' (literally everything), 'best' (personalized hot). Default 'popular'.
        :param limit: Number of posts to return (1-25, default 10).
        :return: Formatted markdown front page.
        """
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"🌐 Loading Reddit {feed} feed…",
                        "done": False,
                    },
                }
            )

        valid_feeds = ["popular", "all", "best"]
        if feed not in valid_feeds:
            feed = "popular"
        limit = max(1, min(25, limit))
        data = _get(
            f"https://www.reddit.com/r/{feed}.json", {"limit": limit, "raw_json": 1}
        )

        if "error" in data:
            return f"❌ Could not load Reddit feed: {data['error']}"

        posts = data.get("data", {}).get("children", [])
        if not posts:
            return "No posts found on the front page."

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"✅ Loaded {len(posts)} front page posts",
                        "done": True,
                    },
                }
            )

        feed_emoji = {"popular": "🌟", "all": "🌐", "best": "✨"}
        emoji = feed_emoji.get(feed, "📋")
        lines = [f"# {emoji} Reddit Front Page — r/{feed}\n"]
        for i, post in enumerate(posts, 1):
            lines.append(_format_post(post["data"], index=i))
        lines.append(f"\n\n---\n*Reddit r/{feed} · {len(posts)} posts*")
        return "\n".join(lines)

    async def get_user_profile(
        self,
        username: str,
        limit: int = 8,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Look up a Reddit user's profile: their karma, bio, recent posts and comments.
        Use when the user asks about a specific Redditor or wants to see someone's post history.

        :param username: The Reddit username (without u/).
        :param limit: Number of recent posts/comments to show (1-20, default 8).
        :return: Formatted markdown with user stats and recent activity.
        """
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": f"👤 Loading profile for u/{username}…",
                        "done": False,
                    },
                }
            )

        about = _get(
            f"https://www.reddit.com/user/{username}/about.json", {"raw_json": 1}
        )
        posts = _get(
            f"https://www.reddit.com/user/{username}/submitted.json",
            {"limit": limit, "raw_json": 1},
        )

        if "error" in about:
            return f"❌ Could not find user u/{username}: {about['error']}"

        d = about.get("data", {})
        link_karma = _format_number(d.get("link_karma", 0))
        comment_karma = _format_number(d.get("comment_karma", 0))
        total_karma = _format_number(
            d.get("total_karma", d.get("link_karma", 0) + d.get("comment_karma", 0))
        )
        description = d.get("subreddit", {}).get("public_description", "")
        icon_img = d.get("icon_img", "").split("?")[0] if d.get("icon_img") else ""
        is_mod = "🛡️ Moderator" if d.get("is_mod") else ""
        is_gold = "🥇 Reddit Gold" if d.get("is_gold") else ""
        verified = "✅ Verified" if d.get("verified") else ""
        created = d.get("created_utc", 0)

        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": "✅ Profile loaded", "done": True},
                }
            )

        lines = [f"# 👤 u/{username}"]
        if icon_img:
            lines.append(f"![avatar]({icon_img})")
        badges = " · ".join(filter(None, [is_mod, is_gold, verified]))
        if badges:
            lines.append(badges)
        if description:
            lines.append(f"\n> {description[:300]}")
        lines += [
            f"\n| Stat | Value |",
            f"|------|-------|",
            f"| 🔗 Post Karma | **{link_karma}** |",
            f"| 💬 Comment Karma | **{comment_karma}** |",
            f"| ⭐ Total Karma | **{total_karma}** |",
            f"| 🔗 Profile | [u/{username}](https://reddit.com/u/{username}) |",
        ]

        # Recent posts
        post_children = (
            posts.get("data", {}).get("children", []) if isinstance(posts, dict) else []
        )
        if post_children:
            lines.append(f"\n### 📝 Recent Posts\n")
            for post in post_children[:limit]:
                pd = post.get("data", {})
                title = pd.get("title", "")
                sub = pd.get("subreddit_name_prefixed", "")
                score = _format_number(pd.get("score", 0))
                permalink = f"https://reddit.com{pd.get('permalink', '')}"
                lines.append(f"- **[{title}]({permalink})** · {sub} · ⬆️ {score}")

        return "\n".join(lines)
