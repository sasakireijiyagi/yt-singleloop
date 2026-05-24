import re
from typing import Any

import streamlit as st
import streamlit.components.v1 as components


st.set_page_config(
    page_title="YouTube Loop Trainer",
    page_icon="🔁",
    layout="wide",
)


import json
import os
import urllib.parse
import urllib.request

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    YOUTUBE_API_KEY: str = st.secrets["YOUTUBE_API_KEY"]
except Exception:
    YOUTUBE_API_KEY = ""


def extract_video_id(url: str) -> str:
    """
    Extract a YouTube video ID from common URL formats.

    Supported examples:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    - VIDEO_ID only
    """
    if not url:
        return ""

    url = url.strip()

    patterns = [
        r"(?:youtube\.com/watch\?v=)([^&\s]+)",
        r"(?:youtu\.be/)([^?\s&]+)",
        r"(?:youtube\.com/embed/)([^?\s&]+)",
        r"(?:youtube\.com/shorts/)([^?\s&]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url

    return ""


def format_duration(seconds: Any) -> str:
    if seconds is None:
        return "--:--"

    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return str(seconds)

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"


def format_loop_time(total_seconds: float) -> str:
    total_seconds = max(0.0, float(total_seconds))
    hours = int(total_seconds // 3600)
    remainder = total_seconds - hours * 3600
    minutes = int(remainder // 60)
    seconds = remainder - minutes * 60

    if hours:
        return f"{hours}:{minutes:02d}:{seconds:04.1f}"

    return f"{minutes}:{seconds:04.1f}"


def split_minutes_seconds(total_seconds: float) -> tuple[int, float]:
    total_seconds = max(0.0, float(total_seconds))
    minutes = int(total_seconds // 60)
    seconds = round(total_seconds - minutes * 60, 1)
    return minutes, seconds


def combine_minutes_seconds(minutes: int | float, seconds: int | float) -> float:
    return float(minutes) * 60.0 + float(seconds)


def set_loop_inputs_from_seconds(start_sec: float, end_sec: float) -> None:
    start_min, start_second = split_minutes_seconds(start_sec)
    end_min, end_second = split_minutes_seconds(end_sec)

    st.session_state.loop_start_min_input = start_min
    st.session_state.loop_start_sec_input = start_second
    st.session_state.loop_end_min_input = end_min
    st.session_state.loop_end_sec_input = end_second


def get_initial_loop_seconds() -> tuple[float, float]:
    start_sec = combine_minutes_seconds(
        st.session_state.get("loop_start_min_input", 0),
        st.session_state.get("loop_start_sec_input", 0.0),
    )
    end_sec = combine_minutes_seconds(
        st.session_state.get("loop_end_min_input", 0),
        st.session_state.get("loop_end_sec_input", 10.0),
    )
    return float(start_sec), float(end_sec)


def clean_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback

    text = str(value).strip()
    return text if text else fallback


def youtube_thumbnail_url(video_id: str, candidate: Any = None) -> str:
    candidate_text = clean_text(candidate)

    if candidate_text:
        return candidate_text

    if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"

    return ""


def _parse_iso8601_duration(duration: str) -> int:
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


@st.cache_data(show_spinner=False, ttl=3600)
def search_youtube_api(query: str, max_results: int, api_key: str) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []

    search_url = (
        "https://www.googleapis.com/youtube/v3/search?"
        + urllib.parse.urlencode({
            "part": "snippet",
            "q": query,
            "maxResults": max_results,
            "type": "video",
            "key": api_key,
        })
    )
    with urllib.request.urlopen(search_url) as resp:
        search_data = json.loads(resp.read())

    video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]
    if not video_ids:
        return []

    details_url = (
        "https://www.googleapis.com/youtube/v3/videos?"
        + urllib.parse.urlencode({
            "part": "snippet,contentDetails",
            "id": ",".join(video_ids),
            "key": api_key,
        })
    )
    with urllib.request.urlopen(details_url) as resp:
        details_data = json.loads(resp.read())

    results: list[dict[str, Any]] = []
    for item in details_data.get("items", []):
        video_id = item["id"]
        snippet = item["snippet"]
        duration_sec = _parse_iso8601_duration(item["contentDetails"]["duration"])
        thumbnail = (
            snippet.get("thumbnails", {}).get("medium", {}).get("url")
            or youtube_thumbnail_url(video_id)
        )
        results.append({
            "video_id": video_id,
            "title": snippet.get("title", "Untitled"),
            "channel": snippet.get("channelTitle", ""),
            "duration": duration_sec,
            "duration_text": format_duration(duration_sec),
            "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail": thumbnail,
        })
    return results


@st.cache_data(show_spinner=False, ttl=3600)
def search_youtube(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed.")

    query = query.strip()
    if not query:
        return []

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "noplaylist": True,
    }

    search_url = f"ytsearch{max_results}:{query}"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_url, download=False)

    entries = info.get("entries", []) if isinstance(info, dict) else []
    results: list[dict[str, Any]] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        raw_id = clean_text(entry.get("id") or entry.get("url"))
        video_id = extract_video_id(raw_id) or raw_id

        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            webpage_url = clean_text(entry.get("webpage_url") or entry.get("url"))
            video_id = extract_video_id(webpage_url)

        if not video_id:
            continue

        title = clean_text(entry.get("title"), "Untitled")
        channel = clean_text(
            entry.get("channel") or entry.get("uploader") or entry.get("creator"),
            "Unknown channel",
        )
        duration = entry.get("duration")
        duration_text = clean_text(entry.get("duration_string")) or format_duration(duration)
        webpage_url = clean_text(
            entry.get("webpage_url"),
            f"https://www.youtube.com/watch?v={video_id}",
        )
        thumbnail = youtube_thumbnail_url(video_id, entry.get("thumbnail"))

        results.append(
            {
                "video_id": video_id,
                "title": title,
                "channel": channel,
                "duration": duration,
                "duration_text": duration_text,
                "webpage_url": webpage_url,
                "thumbnail": thumbnail,
            }
        )

    return results




def result_label(item: dict[str, Any]) -> str:
    title = item.get("title", "Untitled")
    channel = item.get("channel", "Unknown channel")
    duration = item.get("duration_text", "--:--")
    return f"{title} / {channel} / {duration}"


def render_player(
    video_id: str,
    start_sec: float,
    end_sec: float,
    player_width: int,
    end_at_video_end: bool = False,
) -> None:
    player_height = int(player_width * 9 / 16)
    end_at_video_end_js = "true" if end_at_video_end else "false"

    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: transparent;
      color: #222;
    }}

    .wrapper {{
      width: 100%;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 12px;
    }}

    #player {{
      border-radius: 12px;
      overflow: hidden;
      background: #000;
    }}

    .panel {{
      width: min({player_width}px, 100%);
      box-sizing: border-box;
      padding: 12px;
      border: 1px solid #e5e5e5;
      border-radius: 14px;
      background: #fafafa;
    }}

    .time-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 18px;
      font-size: 14px;
      margin-bottom: 10px;
      color: #333;
    }}

    .time-row strong {{
      font-variant-numeric: tabular-nums;
    }}

    .controls {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }}

    button {{
      font-size: 15px;
      line-height: 1;
      padding: 10px 14px;
      border: none;
      border-radius: 999px;
      cursor: pointer;
      background: #111;
      color: white;
    }}

    button:hover {{
      opacity: 0.84;
    }}

    button.secondary {{
      background: #666;
    }}

    button.marker {{
      background: #444;
    }}

    button.adjust {{
      background: #555;
      font-size: 13px;
      padding: 7px 10px;
    }}

    .adjust-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      margin-top: 8px;
      font-size: 13px;
      color: #444;
    }}

    .adjust-label {{
      min-width: 2em;
      font-weight: bold;
    }}

    @media (max-width: 600px) {{
      button {{
        font-size: 13px;
        padding: 8px 10px;
      }}
      button.adjust {{
        font-size: 12px;
        padding: 6px 8px;
      }}
      .adjust-row {{
        gap: 4px 6px;
      }}
    }}

    .status {{
      font-size: 14px;
      color: #555;
      min-height: 1.4em;
      margin-top: 10px;
    }}

    .hint {{
      font-size: 12px;
      color: #777;
      margin-top: 8px;
      line-height: 1.5;
    }}
  </style>
</head>

<body>
  <div class="wrapper">
    <div id="player"></div>

    <div class="panel">
      <div class="time-row">
        <span>現在位置: <strong id="currentTimeLabel">0:00.0</strong></span>
        <span>ループ範囲: <strong id="loopRangeLabel">0:00.0 → 0:10.0</strong></span>
      </div>

      <div class="controls">
        <button onclick="startLoop()">ループ開始</button>
        <button class="secondary" onclick="pauseVideo()">一時停止</button>
        <button class="secondary" onclick="stopLoop()">ループ停止</button>
        <button class="secondary" onclick="jumpToStart()">開始位置へ</button>
      </div>

      <div class="controls" style="margin-top: 8px;">
        <button class="marker" onclick="setStartHere()">ここを開始にする</button>
        <button class="marker" onclick="setEndHere()">ここを終了にする</button>
      </div>

      <div class="adjust-row">
        <span class="adjust-label">開始</span>
        <button class="adjust" onclick="adjustStart(-5)">−5</button>
        <button class="adjust" onclick="adjustStart(-1)">−1</button>
        <button class="adjust" onclick="adjustStart(-0.5)">−0.5</button>
        <button class="adjust" onclick="adjustStart(-0.1)">−0.1</button>
        <button class="adjust" onclick="adjustStart(+0.1)">+0.1</button>
        <button class="adjust" onclick="adjustStart(+0.5)">+0.5</button>
        <button class="adjust" onclick="adjustStart(+1)">+1</button>
        <button class="adjust" onclick="adjustStart(+5)">+5</button>
      </div>

      <div class="adjust-row">
        <span class="adjust-label">終了</span>
        <button class="adjust" onclick="adjustEnd(-5)">−5</button>
        <button class="adjust" onclick="adjustEnd(-1)">−1</button>
        <button class="adjust" onclick="adjustEnd(-0.5)">−0.5</button>
        <button class="adjust" onclick="adjustEnd(-0.1)">−0.1</button>
        <button class="adjust" onclick="adjustEnd(+0.1)">+0.1</button>
        <button class="adjust" onclick="adjustEnd(+0.5)">+0.5</button>
        <button class="adjust" onclick="adjustEnd(+1)">+1</button>
        <button class="adjust" onclick="adjustEnd(+5)">+5</button>
      </div>

      <div id="status" class="status">Player loaded. Press ループ開始.</div>
      <div class="hint">
        左サイドバーは初期値です。動画を見ながらの調整は、このプレイヤー内の「ここを開始にする」「ここを終了にする」で行えます。
      </div>
    </div>
  </div>

  <script>
    const videoId = "{video_id}";
    const endAtVideoEnd = {end_at_video_end_js};
    let localStartSec = {float(start_sec)};
    let localEndSec = {float(end_sec)};

    let player = null;
    let playerReady = false;
    let loopActive = false;
    let monitorTimer = null;
    let lastKnownTime = null;

    function formatTime(totalSeconds) {{
      totalSeconds = Math.max(0, Number(totalSeconds) || 0);
      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;

      if (hours > 0) {{
        return hours + ":" + String(minutes).padStart(2, "0") + ":" + seconds.toFixed(1).padStart(4, "0");
      }}

      return minutes + ":" + seconds.toFixed(1).padStart(4, "0");
    }}

    function setStatus(message) {{
      const status = document.getElementById("status");
      if (status) {{
        status.textContent = message;
      }}
    }}

    function updateLabels() {{
      const currentLabel = document.getElementById("currentTimeLabel");
      const rangeLabel = document.getElementById("loopRangeLabel");

      if (currentLabel && playerReady && player && player.getCurrentTime) {{
        currentLabel.textContent = formatTime(player.getCurrentTime());
      }}

      if (rangeLabel) {{
        rangeLabel.textContent = formatTime(localStartSec) + " → " + formatTime(localEndSec);
      }}
    }}

    function getVideoEndSec() {{
      if (playerReady && player && player.getDuration) {{
        const duration = Number(player.getDuration());
        if (Number.isFinite(duration) && duration > 0) {{
          return Number(duration.toFixed(1));
        }}
      }}

      return Math.max(localEndSec, localStartSec + 5.0);
    }}

    function ensureValidRangeAfterStartChange() {{
      localEndSec = getVideoEndSec();

      if (localEndSec <= localStartSec + 0.1) {{
        localEndSec = localStartSec + 5.0;
      }}
    }}

    function ensureValidRangeAfterEndChange() {{
      if (localEndSec <= localStartSec + 0.1) {{
        const videoEnd = getVideoEndSec();
        localEndSec = Math.min(videoEnd, localStartSec + 5.0);

        if (localEndSec <= localStartSec + 0.1) {{
          localEndSec = localStartSec + 0.5;
        }}
      }}
    }}

    function monitorPlayback() {{
      if (!playerReady || !player || !player.getCurrentTime) {{
        return;
      }}

      const current = player.getCurrentTime();

      const jumpedForwardBeyondEnd =
        lastKnownTime !== null &&
        current > localEndSec &&
        current - lastKnownTime > 1.0;

      if (jumpedForwardBeyondEnd) {{
        localEndSec = getVideoEndSec();
        updateLabels();
        setStatus("Moved beyond current end. End reset to video end: " + formatTime(localEndSec));
        lastKnownTime = current;
        return;
      }}

      updateLabels();

      if (loopActive && current >= localEndSec) {{
        player.seekTo(localStartSec, true);
        player.playVideo();
        lastKnownTime = localStartSec;
        return;
      }}

      lastKnownTime = current;
    }}

    function destroyPlayerForUnload() {{
      loopActive = false;

      if (monitorTimer) {{
        clearInterval(monitorTimer);
        monitorTimer = null;
      }}

      if (player && player.stopVideo) {{
        try {{
          player.stopVideo();
        }} catch (error) {{}}
      }}

      if (player && player.destroy) {{
        try {{
          player.destroy();
        }} catch (error) {{}}
      }}

      playerReady = false;
      player = null;
    }}

    window.addEventListener("pagehide", destroyPlayerForUnload);
    window.addEventListener("beforeunload", destroyPlayerForUnload);
    window.addEventListener("unload", destroyPlayerForUnload);

    const tag = document.createElement("script");
    tag.src = "https://www.youtube.com/iframe_api";
    const firstScriptTag = document.getElementsByTagName("script")[0];
    firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);

    function onYouTubeIframeAPIReady() {{
      player = new YT.Player("player", {{
        width: "{player_width}",
        height: "{player_height}",
        videoId: videoId,
        playerVars: {{
          playsinline: 1,
          rel: 0,
          modestbranding: 1,
          autoplay: 0,
          start: Math.floor(localStartSec)
        }},
        events: {{
          onReady: onPlayerReady,
          onStateChange: onPlayerStateChange
        }}
      }});
    }}

    function onPlayerReady() {{
      playerReady = true;

      const videoEnd = getVideoEndSec();
      if (endAtVideoEnd && videoEnd > localStartSec + 0.1) {{
        localEndSec = videoEnd;
      }}

      player.cueVideoById({{
        videoId: videoId,
        startSeconds: localStartSec
      }});
      updateLabels();

      if (endAtVideoEnd) {{
        setStatus("Ready. End is set to video end: " + formatTime(localEndSec));
      }} else {{
        setStatus("Ready. Press ループ開始.");
      }}

      if (monitorTimer) {{
        clearInterval(monitorTimer);
      }}
      monitorTimer = setInterval(monitorPlayback, 200);
    }}

    function onPlayerStateChange(event) {{
      if (event.data === YT.PlayerState.PLAYING) {{
        if (loopActive) {{
          setStatus("Looping: " + formatTime(localStartSec) + " → " + formatTime(localEndSec));
        }} else {{
          setStatus("Playing. Set start/end while watching.");
        }}
      }}

      if (event.data === YT.PlayerState.PAUSED) {{
        setStatus("Paused.");
      }}

      if (event.data === YT.PlayerState.CUED) {{
        setStatus("Ready. Press ループ開始.");
      }}

      if (event.data === YT.PlayerState.ENDED) {{
        if (loopActive) {{
          player.seekTo(localStartSec, true);
          player.playVideo();
          lastKnownTime = localStartSec;
        }}
      }}
    }}

    function startLoop() {{
      if (!playerReady || !player) {{
        setStatus("Player is not ready yet.");
        return;
      }}

      loopActive = true;
      lastKnownTime = localStartSec;
      player.seekTo(localStartSec, true);
      player.playVideo();
      updateLabels();
      setStatus("Looping: " + formatTime(localStartSec) + " → " + formatTime(localEndSec));
    }}

    function pauseVideo() {{
      if (!playerReady || !player) {{
        return;
      }}

      player.pauseVideo();
    }}

    function stopLoop() {{
      loopActive = false;

      if (playerReady && player) {{
        player.pauseVideo();
        player.seekTo(localStartSec, true);
        lastKnownTime = localStartSec;
      }}

      updateLabels();
      setStatus("Loop stopped.");
    }}

    function jumpToStart() {{
      if (!playerReady || !player) {{
        return;
      }}

      lastKnownTime = localStartSec;
      player.seekTo(localStartSec, true);
      updateLabels();
      setStatus("Jumped to start: " + formatTime(localStartSec));
    }}

    function setStartHere() {{
      if (!playerReady || !player || !player.getCurrentTime) {{
        return;
      }}

      localStartSec = Number(player.getCurrentTime().toFixed(1));
      ensureValidRangeAfterStartChange();
      lastKnownTime = localStartSec;
      updateLabels();

      setStatus(
        "Start set to " + formatTime(localStartSec) +
        ". End reset to video end: " + formatTime(localEndSec) + "."
      );
    }}

    function setEndHere() {{
      if (!playerReady || !player || !player.getCurrentTime) {{
        return;
      }}

      const requestedEndSec = Number(player.getCurrentTime().toFixed(1));
      localEndSec = requestedEndSec;
      ensureValidRangeAfterEndChange();
      lastKnownTime = requestedEndSec;
      updateLabels();

      if (requestedEndSec <= localStartSec + 0.1) {{
        setStatus(
          "End must be after start. Start kept at " +
          formatTime(localStartSec) +
          ". End adjusted to " +
          formatTime(localEndSec) +
          "."
        );
      }} else {{
        setStatus("End set to " + formatTime(localEndSec) + ". Start stays " + formatTime(localStartSec) + ".");
      }}
    }}

    function adjustStart(delta) {{
      localStartSec = Math.max(0, Number((localStartSec + delta).toFixed(1)));
      if (localStartSec >= localEndSec - 0.1) {{
        localStartSec = Math.max(0, localEndSec - 0.1);
      }}
      updateLabels();
      setStatus("開始: " + formatTime(localStartSec) + " → 終了: " + formatTime(localEndSec));
    }}

    function adjustEnd(delta) {{
      localEndSec = Math.max(localStartSec + 0.1, Number((localEndSec + delta).toFixed(1)));
      updateLabels();
      setStatus("開始: " + formatTime(localStartSec) + " → 終了: " + formatTime(localEndSec));
    }}

    updateLabels();
  </script>
</body>
</html>
"""

    components.html(html, height=player_height + 220)


def set_active_video(item: dict[str, Any], start_sec: float, end_sec: float, end_at_video_end: bool) -> None:
    video_id = item.get("video_id", "")

    st.session_state.active_video = {
        "video_id": video_id,
        "title": item.get("title", ""),
        "channel": item.get("channel", ""),
        "duration": item.get("duration"),
        "duration_text": item.get("duration_text", ""),
        "webpage_url": item.get("webpage_url", ""),
        "thumbnail": youtube_thumbnail_url(video_id, item.get("thumbnail", "")),
        "end_at_video_end": bool(end_at_video_end),
    }

    st.session_state.applied_start_sec = float(start_sec)
    st.session_state.applied_end_sec = float(end_sec)


def initialise_session_state() -> None:
    defaults = {
        "search_results": [],
        "active_video": None,
        "applied_start_sec": 0.0,
        "applied_end_sec": 10.0,
        "loop_start_min_input": 0,
        "loop_start_sec_input": 0.0,
        "loop_end_min_input": 0,
        "loop_end_sec_input": 10.0,
        "initial_end_to_video_end": True,
        "preview_video_id_for_initial": "",
        "just_saved": False,
        "pending_save_loop": None,
        "saved_loops": [],
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def sync_initial_end_to_video_if_needed(selected_item: dict[str, Any] | None) -> None:
    """
    If the user wants the initial end point to be the end of the video,
    keep the sidebar minute/second inputs aligned with the selected video's duration.

    This is called before rendering the number inputs, which avoids Streamlit's
    'cannot modify session_state after widget creation' error.
    """
    if not selected_item:
        return

    video_id = selected_item.get("video_id", "")

    if video_id and video_id != st.session_state.preview_video_id_for_initial:
        st.session_state.preview_video_id_for_initial = video_id

    if not st.session_state.get("initial_end_to_video_end", True):
        return

    try:
        duration_sec = float(selected_item.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration_sec = 0.0

    if duration_sec <= 0:
        return

    start_sec, _ = get_initial_loop_seconds()
    if start_sec >= duration_sec:
        start_sec = 0.0

    set_loop_inputs_from_seconds(start_sec, duration_sec)


st.markdown("""
<style>
@media screen and (max-width: 768px) {
    .main .block-container {
        max-width: 100% !important;
        padding-left: 0.75rem !important;
        padding-right: 0.75rem !important;
    }
    section[data-testid="stSidebar"] > div {
        width: 80vw !important;
    }
}
</style>
""", unsafe_allow_html=True)

st.title("YouTube Loop Trainer")
st.caption("YouTubeの一部分をくり返し再生して、英語発表やシャドーイングや音楽ループに使う簡易アプリです。")

initialise_session_state()

selected_for_preview: dict[str, Any] | None = None

with st.sidebar:
    st.header("動画")

    search_available = bool(YOUTUBE_API_KEY) or (yt_dlp is not None)
    if search_available:
        source_mode = st.radio(
            "動画の選び方",
            ["YouTube検索", "URLを直接貼る"],
            horizontal=False,
        )
    else:
        source_mode = "URLを直接貼る"

    if source_mode == "YouTube検索":
        with st.form("youtube_search_form", clear_on_submit=False):
            query = st.text_input(
                "検索語",
                placeholder="psychotherapy presentation practice",
                key="youtube_search_query",
            )

            max_results = st.slider(
                "検索件数",
                min_value=3,
                max_value=15,
                value=8,
                step=1,
                key="youtube_search_max_results",
            )

            search_submitted = st.form_submit_button(
                "検索",
                type="primary",
                use_container_width=True,
            )

        if search_submitted:
            with st.spinner("YouTubeを検索しています..."):
                try:
                    if YOUTUBE_API_KEY:
                        st.session_state.search_results = search_youtube_api(query, max_results, YOUTUBE_API_KEY)
                    else:
                        st.session_state.search_results = search_youtube(query, max_results)
                    st.session_state.active_video = None
                    st.session_state.preview_video_id_for_initial = ""
                except Exception as exc:
                    st.session_state.search_results = []
                    st.session_state.active_video = None
                    st.session_state.preview_video_id_for_initial = ""
                    st.error(f"検索に失敗しました: {exc}")

        results = st.session_state.search_results

        if results:
            labels = [result_label(item) for item in results]
            selected_index = st.selectbox(
                "動画を選択",
                options=range(len(results)),
                format_func=lambda i: labels[i],
            )

            selected_for_preview = results[selected_index]
        else:
            st.caption("検索すると、ここに動画候補が出ます。")

    else:
        youtube_url = st.text_input(
            "YouTube URL",
            placeholder="https://www.youtube.com/watch?v=...",
        )
        url_video_id = extract_video_id(youtube_url)

        if url_video_id:
            selected_for_preview = {
                "video_id": url_video_id,
                "title": "URL直接指定",
                "channel": "",
                "duration": None,
                "duration_text": "",
                "webpage_url": youtube_url,
                "thumbnail": youtube_thumbnail_url(url_video_id),
            }

    # 初期終了を動画末尾にする場合、ここで先に同期する。
    # 重要: number_input を描画する前に session_state を更新する。
    sync_initial_end_to_video_if_needed(selected_for_preview)

    if selected_for_preview:
        st.caption("選択しただけでは再生しません。下のボタンでプレイヤーに読み込みます。")

        if selected_for_preview.get("thumbnail"):
            _thumb_url = selected_for_preview["thumbnail"]
            components.html(f"""
            <div onclick="selectVideo()" style="cursor:pointer;position:relative;line-height:0;">
              <img src="{_thumb_url}" style="width:100%;border-radius:8px;display:block;">
              <div style="position:absolute;bottom:0;left:0;right:0;background:linear-gradient(transparent,rgba(0,0,0,0.55));padding:8px;border-radius:0 0 8px 8px;color:white;font-size:12px;text-align:center;">タップして選択</div>
            </div>
            <script>
            function selectVideo() {{
              var buttons = window.parent.document.querySelectorAll('button');
              for (var i = 0; i < buttons.length; i++) {{
                if (buttons[i].innerText.trim() === '動画を選択') {{
                  buttons[i].click();
                  return;
                }}
              }}
            }}
            </script>
            """, height=180)

        st.markdown(f"**{selected_for_preview.get('title', 'Untitled')}**")
        meta_parts = []
        if selected_for_preview.get("channel"):
            meta_parts.append(selected_for_preview["channel"])
        if selected_for_preview.get("duration_text"):
            meta_parts.append(selected_for_preview["duration_text"])
        if meta_parts:
            st.caption(" / ".join(meta_parts))

        # ここに置く。サムネ・タイトルの直下。
        # 初期ループ設定は session_state から読むので、下の入力欄で変更済みの値も反映される。
        if st.button("動画を選択", use_container_width=True, type="primary", key="select_video_button_near_thumbnail"):
            initial_start_sec, initial_end_sec = get_initial_loop_seconds()
            end_to_video_end = bool(st.session_state.get("initial_end_to_video_end", True))

            if end_to_video_end:
                try:
                    duration_sec = float(selected_for_preview.get("duration") or 0.0)
                except (TypeError, ValueError):
                    duration_sec = 0.0

                if duration_sec > 0:
                    initial_end_sec = duration_sec

            if not end_to_video_end and initial_end_sec <= initial_start_sec:
                st.error("初期終了時間は初期開始時間より後にしてください。")
            else:
                set_active_video(
                    selected_for_preview,
                    start_sec=initial_start_sec,
                    end_sec=initial_end_sec,
                    end_at_video_end=end_to_video_end,
                )
                st.rerun()

    st.divider()
    st.header("初期ループ設定")

    st.caption(
        "ここで決めた値は、次に **動画を選択** したときの初期値になります。"
        "その後の微調整は右側プレイヤー内で行います。"
    )

    end_to_video_end = st.checkbox(
        "終了を動画末尾にする",
        key="initial_end_to_video_end",
    )

    if end_to_video_end:
        sync_initial_end_to_video_if_needed(selected_for_preview)

    st.caption("初期開始")
    start_col1, start_col2 = st.columns(2)
    with start_col1:
        st.number_input(
            "分",
            min_value=0,
            step=1,
            key="loop_start_min_input",
        )
    with start_col2:
        st.number_input(
            "秒",
            min_value=0.0,
            max_value=59.5,
            step=0.5,
            format="%.1f",
            key="loop_start_sec_input",
        )
    st.caption("初期終了")
    end_col1, end_col2 = st.columns(2)
    with end_col1:
        st.number_input(
            "分 ",
            min_value=0,
            step=1,
            key="loop_end_min_input",
            disabled=end_to_video_end,
        )
    with end_col2:
        st.number_input(
            "秒 ",
            min_value=0.0,
            max_value=59.5,
            step=0.5,
            format="%.1f",
            key="loop_end_sec_input",
            disabled=end_to_video_end,
        )

    initial_start_sec, initial_end_sec = get_initial_loop_seconds()

    if end_to_video_end:
        if selected_for_preview and selected_for_preview.get("duration"):
            st.caption(f"初期範囲: {format_loop_time(initial_start_sec)} 〜 動画末尾")
        else:
            st.caption("初期範囲: 開始位置 〜 動画末尾（読み込み後に確定）")
    else:
        st.caption(
            f"初期範囲: {format_loop_time(initial_start_sec)} 〜 {format_loop_time(initial_end_sec)}"
        )

    if not selected_for_preview:
        st.caption("動画を検索またはURL入力すると、サムネ下に **動画を選択** ボタンが出ます。")

    st.caption("※現在のループ範囲は、右側プレイヤー内のボタンで調整します。")

    player_width = st.slider(
        "動画の大きさ",
        min_value=480,
        max_value=1200,
        value=800,
        step=40,
    )



active_video = st.session_state.active_video

if active_video is None:
    st.info("左のサイドバーにYouTube URLを入力して、動画を選択してください。")
    st.stop()

selected_video_id = active_video.get("video_id", "")

if not selected_video_id:
    st.info("左のサイドバーにYouTube URLを入力して、動画を選択してください。")
    st.stop()

start_sec = float(st.session_state.applied_start_sec)
end_sec = float(st.session_state.applied_end_sec)
end_at_video_end = bool(active_video.get("end_at_video_end", False))

if not end_at_video_end and end_sec <= start_sec:
    st.error("終了時間は開始時間より後にしてください。")
    st.stop()

selected_video_title = active_video.get("title", "")
selected_video_channel = active_video.get("channel", "")
selected_video_duration = active_video.get("duration_text", "")
selected_video_url = active_video.get("webpage_url", "")
selected_thumbnail = active_video.get("thumbnail", "")

# メインエリアを左（プレイヤー）・右（保存済みループ）に分割
col_player, col_saved = st.columns([3, 1])

with col_player:
    st.subheader("練習プレイヤー")

    if selected_video_title:
        st.markdown(f"**{selected_video_title}**")

    meta_parts = []
    if selected_video_channel:
        meta_parts.append(selected_video_channel)
    if selected_video_duration:
        meta_parts.append(selected_video_duration)
    if meta_parts:
        st.caption(" / ".join(meta_parts))

    if selected_video_url:
        st.markdown(f"[YouTubeで開く]({selected_video_url})")

    if selected_thumbnail:
        st.image(selected_thumbnail, width=320)

    if end_at_video_end:
        st.write(f"初期再生区間: **{format_loop_time(start_sec)}** 〜 **動画末尾**")
    else:
        st.write(f"初期再生区間: **{format_loop_time(start_sec)}** 〜 **{format_loop_time(end_sec)}**")

    st.caption("プレイヤー内の「ここを開始にする」を押すと、終了位置は動画末尾へ自動で広がります。「ここを終了にする」では開始位置は動きません。")

    render_player(
        video_id=selected_video_id,
        start_sec=start_sec,
        end_sec=end_sec,
        player_width=int(player_width),
        end_at_video_end=end_at_video_end,
    )

    st.divider()
    st.subheader("ループを保存")

    # 動画が切り替わったときだけ保存用の時間入力を初期値にリセットする
    if st.session_state.get("_save_input_for_video") != selected_video_id:
        _sm0, _ss0 = split_minutes_seconds(start_sec)
        _em0, _es0 = split_minutes_seconds(end_sec if not end_at_video_end else start_sec + 10.0)
        st.session_state["save_time_start_min"] = _sm0
        st.session_state["save_time_start_sec"] = _ss0
        st.session_state["save_time_end_min"] = _em0
        st.session_state["save_time_end_sec"] = _es0
        st.session_state["_save_input_for_video"] = selected_video_id

    st.caption(
        "プレイヤー内で「ここを開始にする」「ここを終了にする」で確定した時刻を、"
        "下の欄に入力してから保存してください。"
    )
    _sv_c1, _sv_c2 = st.columns(2)
    with _sv_c1:
        st.caption("開始")
        _svm1, _svm2 = st.columns(2)
        with _svm1:
            _save_sm = st.number_input("分", min_value=0, step=1, key="save_time_start_min", label_visibility="collapsed")
        with _svm2:
            _save_ss = st.number_input("秒", min_value=0.0, max_value=59.9, step=0.1, format="%.1f", key="save_time_start_sec", label_visibility="collapsed")
    with _sv_c2:
        st.caption("終了")
        _sem1, _sem2 = st.columns(2)
        with _sem1:
            _save_em = st.number_input("分 ", min_value=0, step=1, key="save_time_end_min", label_visibility="collapsed")
        with _sem2:
            _save_es = st.number_input("秒 ", min_value=0.0, max_value=59.9, step=0.1, format="%.1f", key="save_time_end_sec", label_visibility="collapsed")

    _save_start_sec = combine_minutes_seconds(_save_sm, _save_ss)
    _save_end_sec = combine_minutes_seconds(_save_em, _save_es)

    save_label = st.text_input(
        "メモ（省略可）",
        placeholder="例：イントロ、サビ、むずかしいとこ",
        key="save_loop_label",
    )
    if st.button("このループを保存", type="primary"):
        if _save_end_sec <= _save_start_sec:
            st.error("終了は開始より後の時刻にしてください。")
        else:
            _save_label_str = (
                save_label if save_label
                else f"{format_loop_time(_save_start_sec)} 〜 {format_loop_time(_save_end_sec)}"
            )
            _new_loop = {
                "title": active_video.get("title", "Untitled"),
                "channel": active_video.get("channel", ""),
                "video_id": selected_video_id,
                "url": selected_video_url,
                "start_sec": _save_start_sec,
                "end_sec": _save_end_sec,
                "end_at_video_end": False,
                "label": _save_label_str,
            }
            _existing = st.session_state.get("saved_loops", [])
            _is_dup = any(
                l["video_id"] == _new_loop["video_id"]
                and abs(l["start_sec"] - _new_loop["start_sec"]) < 0.05
                and abs(l["end_sec"] - _new_loop["end_sec"]) < 0.05
                for l in _existing
            )
            if _is_dup:
                st.info("同じループはすでに保存されています。")
            else:
                st.session_state.setdefault("saved_loops", []).append(_new_loop)
                st.success("保存しました！")
                st.rerun()

with col_saved:
    st.subheader("保存済みループ")
    _saved_loops = st.session_state.get("saved_loops", [])
    if not _saved_loops:
        st.caption("まだ保存されたループはありません。")
    for _i, _lp in enumerate(_saved_loops):
        with st.container(border=True):
            st.caption(f"**{_lp.get('title', 'Untitled')}**")
            st.caption(_lp.get('label', ''))
            _lc, _ld_col = st.columns(2)
            if _lc.button("読み込む", key=f"load_lp_{_i}", use_container_width=True):
                _it = {
                    "video_id": _lp["video_id"],
                    "title": _lp.get("title", ""),
                    "channel": _lp.get("channel", ""),
                    "duration": None,
                    "duration_text": "",
                    "webpage_url": _lp.get("url", ""),
                    "thumbnail": youtube_thumbnail_url(_lp["video_id"]),
                }
                set_active_video(
                    _it,
                    _lp["start_sec"],
                    _lp["end_sec"],
                    _lp.get("end_at_video_end", False),
                )
                # 保存用時間入力もリセットさせる
                st.session_state.pop("_save_input_for_video", None)
                st.rerun()
            if _ld_col.button("削除", key=f"del_lp_{_i}", use_container_width=True):
                st.session_state["saved_loops"].pop(_i)
                st.rerun()

with st.expander("使い方"):
    st.markdown(
        """
        1. 左のサイドバーにYouTube URLを貼る
        2. 左サイドバーの **初期ループ設定** を必要に応じて指定する
        3. **動画を選択** を押してプレイヤーに読み込む
        4. 動画を再生しながら、プレイヤー内の **ここを開始にする** / **ここを終了にする** で微調整する
        5. **ループ開始** を押す

        左サイドバーは、動画を読み込むときの初期値です。
        現在のループ範囲は、右側プレイヤー内で調整します。

        **ここを開始にする** を押すと、終了位置は動画末尾へ自動で広がります。
        **ここを終了にする** を押した場合、開始位置は変更されません。

        動画ファイルはダウンロードしません。YouTubeの埋め込みプレイヤーで再生します。

        プレイヤー内で決めた開始・終了位置は、その場のループ再生にはすぐ反映されます。
        ただし、Streamlitの通常HTML埋め込みの制約上、プレイヤー内で決めた値はサイドバーの分秒入力欄には自動反映されません。
        """
    )
