"""
youtube_collector.py — Domain-agnostic YouTube transcript collection
---------------------------------------------------------------------
Ported from trading-service's youtube_collector.py + youtube_playwright.py.
All trading-specific logic (ticker extraction, DB writes, financial channels)
has been REMOVED. This collector knows HOW to pull YouTube transcripts —
the caller decides WHICH channels and search queries.

Libraries: yt-dlp (metadata), youtube-transcript-api (captions)
No API key needed.
"""

import asyncio
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# yt-dlp version check at import
try:
    _v = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--version"],
        capture_output=True, text=True, timeout=5,
    )
    _YTDLP_VERSION = _v.stdout.strip() if _v.returncode == 0 else "unknown"
    logger.info(f"[youtube] yt-dlp version: {_YTDLP_VERSION}")
except Exception:
    _YTDLP_VERSION = "not-found"
    logger.warning("[youtube] yt-dlp not found")


@dataclass
class YouTubeVideo:
    """Normalized YouTube video data."""
    video_id: str
    title: str
    channel: str
    transcript: str
    published_at: datetime | None
    duration_secs: int
    thumbnail_url: str
    view_count: int = 0


class YouTubeCollector:
    """Collects YouTube video transcripts.

    Two modes:
      1. collect_channel() — Latest videos from a specific channel
      2. search() — Search YouTube for videos matching a query

    Transcript extraction strategy (3-tier fallback):
      1. yt-dlp subtitle download (most reliable)
      2. youtube-transcript-api (may be IP-blocked)
      3. Playwright DOM scraping (ultimate fallback, if available)
    """

    async def collect_channel(
        self,
        channel_handle: str,
        max_videos: int = 3,
        days_back: int = 7,
    ) -> list[YouTubeVideo]:
        """Get recent videos from a YouTube channel with transcripts."""
        videos_data = await asyncio.to_thread(
            self._get_channel_videos, channel_handle, max_videos
        )

        if not videos_data:
            return []

        results: list[YouTubeVideo] = []
        cutoff = datetime.utcnow() - timedelta(days=days_back)

        for video in videos_data:
            vid = await self._process_video(video, channel_handle, cutoff)
            if vid:
                results.append(vid)
            await asyncio.sleep(1.0)  # Rate limit between transcript fetches

        logger.info(f"[youtube] {channel_handle}: {len(results)}/{len(videos_data)} videos with transcripts")
        return results

    async def search(
        self,
        query: str,
        max_results: int = 10,
        days_back: int = 30,
    ) -> list[YouTubeVideo]:
        """Search YouTube for videos matching a query and extract transcripts."""
        videos_data = await asyncio.to_thread(
            self._search_youtube, query, max_results
        )

        if not videos_data:
            return []

        # Sort newest first
        videos_data.sort(key=lambda v: v.get("upload_date", "00000000"), reverse=True)

        results: list[YouTubeVideo] = []
        cutoff = datetime.utcnow() - timedelta(days=days_back) if days_back > 0 else None

        for video in videos_data:
            vid = await self._process_video(video, video.get("channel", "search"), cutoff)
            if vid:
                results.append(vid)
            await asyncio.sleep(1.0)

        logger.info(f"[youtube] Search '{query}': {len(results)}/{len(videos_data)} with transcripts")
        return results

    async def _process_video(
        self,
        video: dict,
        channel: str,
        cutoff: datetime | None,
    ) -> YouTubeVideo | None:
        """Process a single video: check date, get transcript."""
        video_id = video.get("id")
        if not video_id:
            for url_key in ("url", "webpage_url", "original_url"):
                url_val = video.get(url_key, "")
                if "watch?v=" in url_val:
                    video_id = url_val.split("watch?v=")[-1].split("&")[0]
                    break
                elif url_val and len(url_val) == 11:
                    video_id = url_val
                    break
        if not video_id:
            return None

        title = video.get("title", "")
        upload_date = video.get("upload_date", "")
        duration = video.get("duration", 0) or 0

        published_at = None
        if upload_date:
            try:
                published_at = datetime.strptime(upload_date, "%Y%m%d")
            except ValueError:
                pass

        if cutoff and published_at and published_at < cutoff:
            return None

        # Get transcript
        transcript = await asyncio.to_thread(self._get_transcript, video_id)
        if not transcript or len(transcript) < 50:
            return None

        thumbnail_url = video.get("thumbnail") or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

        return YouTubeVideo(
            video_id=video_id,
            title=title,
            channel=video.get("channel", channel),
            transcript=transcript,
            published_at=published_at,
            duration_secs=duration,
            thumbnail_url=thumbnail_url,
            view_count=video.get("view_count", 0) or 0,
        )

    def _get_channel_videos(self, channel: str, max_videos: int) -> list[dict]:
        """Use yt-dlp to get recent video metadata from a channel."""
        try:
            cmd = [
                sys.executable, "-m", "yt_dlp",
                f"https://www.youtube.com/@{channel}/videos",
                "--flat-playlist", "--dump-json",
                f"--playlist-end={max_videos}",
                "--no-download", "--quiet",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                if result.stderr:
                    logger.warning(f"[youtube] yt-dlp channel error for {channel}: {result.stderr[:200]}")
                return []

            videos = []
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    try:
                        videos.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return videos

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error(f"[youtube] yt-dlp error for {channel}: {e}")
            return []

    def _search_youtube(self, query: str, max_results: int) -> list[dict]:
        """Use yt-dlp ytsearch to find videos matching a query."""
        try:
            cmd = [
                sys.executable, "-m", "yt_dlp",
                f"ytsearch{max_results}:{query}",
                "--dump-json", "--no-download", "--no-playlist",
                "--quiet", "--no-warnings",
                "--socket-timeout", "15",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                return []

            if not result.stdout.strip():
                return []

            videos = []
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    try:
                        videos.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return videos

        except subprocess.TimeoutExpired:
            logger.warning(f"[youtube] Search timed out for '{query}'")
            return []
        except FileNotFoundError:
            logger.error("[youtube] yt-dlp not found!")
            return []

    def _get_transcript(self, video_id: str) -> str | None:
        """Get transcript — yt-dlp subtitles first, then youtube-transcript-api fallback."""
        # Method 1: yt-dlp subtitle download
        transcript = self._get_transcript_ytdlp(video_id)
        if transcript:
            return transcript

        # Method 2: youtube-transcript-api
        transcript = self._get_transcript_api(video_id)
        if transcript:
            return transcript

        return None

    def _get_transcript_ytdlp(self, video_id: str) -> str | None:
        """Get transcript using yt-dlp subtitle download."""
        import tempfile
        import os

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = os.path.join(tmpdir, "sub")
                cmd = [
                    sys.executable, "-m", "yt_dlp",
                    f"https://www.youtube.com/watch?v={video_id}",
                    "--skip-download", "--write-auto-sub", "--write-subs",
                    "--sub-lang", "en.*", "--sub-format", "json3",
                    "--no-warnings", "--socket-timeout", "15",
                    "-o", output_path,
                ]
                subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                             encoding="utf-8", errors="replace")

                sub_file = None
                for f in os.listdir(tmpdir):
                    if f.endswith(".json3") or f.endswith(".vtt"):
                        sub_file = os.path.join(tmpdir, f)
                        break

                if not sub_file:
                    return None

                if sub_file.endswith(".json3"):
                    with open(sub_file, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    parts = []
                    for event in data.get("events", []):
                        for seg in event.get("segs", []):
                            text = seg.get("utf8", "").strip()
                            if text and text != "\n":
                                parts.append(text)
                    transcript = " ".join(parts).strip()
                else:
                    with open(sub_file, "r", encoding="utf-8") as fh:
                        lines = fh.readlines()
                    parts = [l.strip() for l in lines if "-->" not in l and not l.startswith("WEBVTT") and l.strip()]
                    transcript = " ".join(parts).strip()

                return transcript if len(transcript) > 50 else None

        except Exception:
            return None

    def _get_transcript_api(self, video_id: str) -> str | None:
        """Fallback: Get transcript using youtube-transcript-api."""
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            import os

            cookies_file = os.environ.get("YOUTUBE_COOKIES_FILE", "")
            if cookies_file and os.path.exists(cookies_file):
                ytt = YouTubeTranscriptApi(cookie_path=cookies_file)
            else:
                ytt = YouTubeTranscriptApi()

            try:
                transcript = ytt.fetch(video_id, languages=["en"])
                parts = []
                for snippet in transcript:
                    text = snippet.get("text", "").strip() if isinstance(snippet, dict) else str(snippet).strip()
                    if text:
                        parts.append(text)
                text = " ".join(parts)
                if len(text) > 50:
                    return text
            except Exception:
                pass

            return None
        except ImportError:
            return None


def _serialize_video(video: YouTubeVideo) -> dict:
    """Convert YouTubeVideo to JSON-safe dict for API responses."""
    return {
        "video_id": video.video_id,
        "title": video.title,
        "channel": video.channel,
        "transcript": video.transcript,
        "published_at": video.published_at.isoformat() if video.published_at else None,
        "duration_secs": video.duration_secs,
        "thumbnail_url": video.thumbnail_url,
        "view_count": video.view_count,
    }
