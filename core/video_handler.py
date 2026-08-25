"""
Video translation, subtitle extraction, Edge TTS dubbing, and audio-video muxing.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import edge_tts
from youtube_transcript_api import YouTubeTranscriptApi

from translation_app.config import config
from translation_app.core.translator import TranslationService
from translation_app.utils.error_handler import handle_translation_error
from translation_app.utils.logger import logger


@dataclass
class SubtitleSnippet:
    """Represents a single timestamped subtitle / speech snippet."""
    index: int
    start: float  # seconds
    duration: float  # seconds
    original_text: str
    translated_text: str = ""
    audio_path: Optional[str] = None
    audio_duration: float = 0.0

    @property
    def end(self) -> float:
        return self.start + self.duration


def format_timestamp_srt(seconds: float) -> str:
    """Convert float seconds to SRT timestamp format: HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0.0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis = 0
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def extract_youtube_video_id(url_or_id: str) -> Optional[str]:
    """Extract YouTube 11-character video ID from varied URL forms."""
    if not url_or_id:
        return None
    raw = url_or_id.strip()
    if len(raw) == 11 and re.match(r"^[A-Za-z0-9_-]{11}$", raw):
        return raw

    patterns = [
        r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/|\/live\/|\/watch\?v=)([^#&?\s]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return match.group(1)
    return None


def get_ffmpeg_path() -> str:
    """Find ffmpeg executable path on Windows or POSIX."""
    # 1. Check system PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    # 2. Common Windows paths
    possible_paths = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "ffmpeg", "bin", "ffmpeg.exe"),
    ]
    for p in possible_paths:
        if os.path.exists(p):
            return p

    return "ffmpeg"


def get_ffprobe_path() -> str:
    """Find ffprobe executable path on Windows or POSIX."""
    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        return system_ffprobe

    possible_paths = [
        r"C:\ffmpeg\bin\ffprobe.exe",
        r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "ffmpeg", "bin", "ffprobe.exe"),
    ]
    for p in possible_paths:
        if os.path.exists(p):
            return p

    return "ffprobe"


class VideoHandler:
    """Comprehensive handler for video subtitle extraction, translation, and AI dubbing."""

    AVAILABLE_VIETNAMESE_VOICES = {
        "vi-VN-HoaiMyNeural": "Hoài My (Nữ - Truyền cảm)",
        "vi-VN-NamMinhNeural": "Nam Minh (Nam - Rõ ràng)",
    }

    def __init__(self, translation_service: Optional[TranslationService] = None):
        self.translation_service = translation_service or TranslationService()
        self.ffmpeg_path = get_ffmpeg_path()
        self.ffprobe_path = get_ffprobe_path()

    def fetch_youtube_subtitles(self, url_or_id: str, preferred_langs: Optional[List[str]] = None) -> List[SubtitleSnippet]:
        """
        Fetch transcript snippets from a YouTube video URL or ID.

        Args:
            url_or_id: YouTube URL or 11-char video ID
            preferred_langs: List of language codes to prioritize (e.g. ['en', 'ja', 'vi'])

        Returns:
            List of SubtitleSnippet objects with timestamp boundaries.
        """
        video_id = extract_youtube_video_id(url_or_id)
        if not video_id:
            raise ValueError(f"Không thể nhận diện Video ID từ đường dẫn: {url_or_id}")

        logger.info(f"Fetching YouTube transcript for video ID: {video_id}")
        raw_items = []

        try:
            ytt = YouTubeTranscriptApi()
            transcript_list = ytt.list(video_id)
            
            # Find matching transcript
            transcript = None
            if preferred_langs:
                try:
                    transcript = transcript_list.find_transcript(preferred_langs)
                except Exception:
                    pass

            if not transcript:
                # Get the first available transcript (manual or auto-generated)
                for t in transcript_list:
                    transcript = t
                    break

            if transcript:
                raw_items = transcript.fetch()
                logger.info(f"Fetched {len(raw_items)} transcript segments in '{transcript.language}' ({transcript.language_code})")
        except Exception as e:
            logger.warning(f"YouTubeTranscriptApi primary list/fetch failed ({e}), attempting direct fetch fallback...")
            try:
                raw_items = YouTubeTranscriptApi().fetch(video_id)
            except Exception as e2:
                logger.error(f"Failed to fetch transcript via YouTubeTranscriptApi: {e2}")
                # Try fallback using yt-dlp to download auto-subtitles
                raw_items = self._fetch_subtitles_via_ytdlp(video_id)

        if not raw_items:
            raise RuntimeError("Không tìm thấy phụ đề hoặc lời thoại tự động cho video YouTube này.")

        snippets: List[SubtitleSnippet] = []
        for idx, item in enumerate(raw_items, start=1):
            if hasattr(item, 'text'):
                text = str(item.text).strip()
                start = float(item.start)
                duration = float(item.duration)
            elif isinstance(item, dict):
                text = str(item.get('text', '')).strip()
                start = float(item.get('start', 0.0))
                duration = float(item.get('duration', 0.0))
            else:
                continue

            if not text:
                continue

            # Clean newlines inside single snippet
            clean_text = " ".join(text.split())
            snippet = SubtitleSnippet(
                index=idx,
                start=round(start, 3),
                duration=round(max(0.2, duration), 3),
                original_text=clean_text,
                translated_text="",
            )
            snippets.append(snippet)

        logger.info(f"Loaded {len(snippets)} valid subtitle snippets.")
        return snippets

    def _fetch_subtitles_via_ytdlp(self, video_id: str) -> list:
        """Fallback subtitle extraction via yt-dlp."""
        import yt_dlp
        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitlesformat': 'json3/vtt/srt',
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            subtitles = info.get('subtitles') or info.get('automatic_captions') or {}
            if not subtitles:
                return []
            
            # Select first available language
            lang_key = next(iter(subtitles.keys()))
            formats = subtitles[lang_key]
            json_format = next((f for f in formats if f.get('ext') == 'json3'), None)
            if json_format and 'url' in json_format:
                import urllib.request
                import json
                req = urllib.request.Request(json_format['url'], headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    events = data.get('events', [])
                    results = []
                    for ev in events:
                        segs = ev.get('segs', [])
                        text = "".join(s.get('utf8', '') for s in segs).strip()
                        if text and text != '\n':
                            start_ms = ev.get('tStartMs', 0)
                            dur_ms = ev.get('dDurationMs', 1000)
                            results.append({
                                'text': text,
                                'start': start_ms / 1000.0,
                                'duration': dur_ms / 1000.0
                            })
                    return results
        return []

    def download_youtube_video(
        self,
        url: str,
        output_dir: str,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> str:
        """
        Download YouTube video stream to local file.

        Args:
            url: YouTube URL
            output_dir: Output directory
            progress_callback: Optional callback receiving (percent, status_str)

        Returns:
            Absolute path to downloaded video file.
        """
        import yt_dlp

        os.makedirs(output_dir, exist_ok=True)
        video_id = extract_youtube_video_id(url) or "video"
        output_template = os.path.join(output_dir, f"{video_id}_%(title).50s.%(ext)s")

        def ytdl_hook(d):
            if d['status'] == 'downloading':
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes') or 0
                if total_bytes > 0:
                    pct = min(100.0, (downloaded / total_bytes) * 100.0)
                    speed = d.get('speed', 0) or 0
                    speed_mb = speed / (1024 * 1024) if speed else 0
                    if progress_callback:
                        progress_callback(pct, f"Đang tải video YouTube ({pct:.1f}% - {speed_mb:.1f} MB/s)...")
            elif d['status'] == 'finished':
                if progress_callback:
                    progress_callback(100.0, "Đã tải xong video YouTube.")

        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_template,
            'progress_hooks': [ytdl_hook],
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
        }

        logger.info(f"Downloading YouTube video from: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith(".mp4"):
                filename = os.path.splitext(filename)[0] + ".mp4"
            if not os.path.exists(filename):
                # Look for matching file in output_dir
                for f in os.listdir(output_dir):
                    if f.startswith(video_id) and f.endswith(".mp4"):
                        filename = os.path.join(output_dir, f)
                        break

        logger.info(f"YouTube video downloaded successfully: {filename}")
        return filename

    def translate_subtitles(
        self,
        snippets: List[SubtitleSnippet],
        source_lang: str = "auto",
        target_lang: str = "vi",
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[SubtitleSnippet]:
        """
        Translate all subtitle snippets while preserving exact timestamps.

        Args:
            snippets: List of SubtitleSnippet items.
            source_lang: Source language code.
            target_lang: Target language code (default 'vi').
            progress_callback: Progress update callback.
            cancel_check: Function returning True if operation was cancelled.

        Returns:
            Updated snippets list with translated_text filled.
        """
        total = len(snippets)
        if total == 0:
            return snippets

        logger.info(f"Translating {total} subtitle snippets from {source_lang} to {target_lang}...")

        # Process snippet translation
        for idx, snippet in enumerate(snippets, start=1):
            if cancel_check and cancel_check():
                logger.info("Subtitle translation cancelled by user.")
                break

            if not snippet.original_text.strip():
                snippet.translated_text = ""
                continue

            try:
                translated = self.translation_service.translate_text(
                    snippet.original_text,
                    src_lang=source_lang,
                    dest_lang=target_lang,
                )
                snippet.translated_text = str(translated).strip()
            except Exception as e:
                logger.warning(f"Error translating snippet #{idx}: {e}")
                snippet.translated_text = snippet.original_text

            pct = (idx / total) * 100.0
            if progress_callback:
                progress_callback(pct, f"Đang dịch lời thoại ({idx}/{total} câu)...")

        logger.info("Subtitle translation completed.")
        return snippets

    def get_audio_duration(self, audio_path: str) -> float:
        """Measure precise audio file duration in seconds using ffprobe/ffmpeg."""
        try:
            cmd = [
                self.ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass

        # Fallback using ffmpeg parse
        try:
            cmd = [self.ffmpeg_path, "-i", audio_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", result.stderr)
            if match:
                hrs, mins, secs = match.groups()
                return int(hrs) * 3600 + int(mins) * 60 + float(secs)
        except Exception as e:
            logger.debug(f"Could not probe audio duration for {audio_path}: {e}")

        return 1.0

    async def _synthesize_single_snippet_async(self, text: str, voice: str, out_path: str):
        """Internal helper to synthesize single text snippet via Edge-TTS."""
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(out_path)

    def synthesize_snippet_audio(self, text: str, voice: str, output_path: str):
        """Synchronous wrapper to synthesize text to audio."""
        asyncio.run(self._synthesize_single_snippet_async(text, voice, output_path))

    def generate_dubbed_audio(
        self,
        snippets: List[SubtitleSnippet],
        voice_name: str = "vi-VN-HoaiMyNeural",
        output_audio_path: str = "dubbed_audio.mp3",
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        """
        Generate synchronized Vietnamese dubbed audio track matching video timestamps.

        Args:
            snippets: List of SubtitleSnippet with translated_text.
            voice_name: Edge TTS voice name (e.g. 'vi-VN-HoaiMyNeural').
            output_audio_path: Destination path for full assembled audio.
            progress_callback: Optional callback for UI progress.
            cancel_check: Optional cancel check callback.

        Returns:
            Path to assembled synchronized audio file.
        """
        total = len(snippets)
        if total == 0:
            raise ValueError("Danh sách lời thoại trống, không thể tạo lồng tiếng.")

        logger.info(f"Generating dubbed audio for {total} segments using voice: {voice_name}")
        temp_dir = tempfile.mkdtemp(prefix="dubbing_tts_")
        segment_files: List[Tuple[float, str]] = []  # (start_time, file_path)

        try:
            for idx, snippet in enumerate(snippets, start=1):
                if cancel_check and cancel_check():
                    logger.info("Audio synthesis cancelled by user.")
                    break

                text_to_speak = snippet.translated_text.strip() or snippet.original_text.strip()
                if not text_to_speak:
                    continue

                raw_seg_path = os.path.join(temp_dir, f"raw_seg_{idx:04d}.mp3")
                adj_seg_path = os.path.join(temp_dir, f"adj_seg_{idx:04d}.mp3")

                # Synthesize with Edge TTS
                try:
                    self.synthesize_snippet_audio(text_to_speak, voice_name, raw_seg_path)
                except Exception as e:
                    logger.warning(f"Edge-TTS failed on snippet #{idx} ({e}), retrying once...")
                    try:
                        self.synthesize_snippet_audio(text_to_speak, voice_name, raw_seg_path)
                    except Exception as e2:
                        logger.error(f"Could not synthesize snippet #{idx}: {e2}")
                        continue

                if not os.path.exists(raw_seg_path) or os.path.getsize(raw_seg_path) == 0:
                    continue

                # Measure actual duration vs available target duration
                actual_dur = self.get_audio_duration(raw_seg_path)
                target_dur = snippet.duration
                snippet.audio_duration = actual_dur

                # Time-stretching speed factor calculation
                if actual_dur > 0.1 and target_dur > 0.1:
                    speed_factor = actual_dur / target_dur
                    # Clamp speed to maintain natural human intonation (0.85x to 1.35x)
                    speed_factor = max(0.85, min(1.35, speed_factor))
                else:
                    speed_factor = 1.0

                # Apply FFmpeg atempo filter if needed
                if abs(speed_factor - 1.0) > 0.05:
                    cmd_tempo = [
                        self.ffmpeg_path,
                        "-y",
                        "-i", raw_seg_path,
                        "-filter:a", f"atempo={speed_factor:.3f}",
                        "-q:a", "2",
                        adj_seg_path
                    ]
                    sub_res = subprocess.run(cmd_tempo, capture_output=True, text=True)
                    if sub_res.returncode == 0 and os.path.exists(adj_seg_path):
                        final_seg_path = adj_seg_path
                    else:
                        final_seg_path = raw_seg_path
                else:
                    final_seg_path = raw_seg_path

                segment_files.append((snippet.start, final_seg_path))

                pct = (idx / total) * 100.0
                if progress_callback:
                    progress_callback(pct, f"Đang tạo giọng lồng tiếng ({idx}/{total} câu)...")

            if not segment_files:
                raise RuntimeError("Không thể tạo giọng đọc cho bất kỳ câu thoại nào.")

            # Assemble all segments into full audio timeline
            if progress_callback:
                progress_callback(95.0, "Đang đồng bộ và ghép nối toàn bộ luồng âm thanh...")

            self._assemble_timeline_audio(segment_files, output_audio_path)
            logger.info(f"Assembled complete dubbed audio at: {output_audio_path}")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        return output_audio_path

    def _assemble_timeline_audio(self, segment_files: List[Tuple[float, str]], output_path: str):
        """
        Merge individual timed segments into a continuous audio stream aligned with timeline.
        Uses FFmpeg adelay filter or sequential silence insertion.
        """
        if not segment_files:
            return

        # Sort segments strictly by start timestamp
        segment_files.sort(key=lambda x: x[0])

        # Generate silence and audio list using FFmpeg concat or filter_complex
        # For maximum reliability across Windows FFmpeg builds, generate a master wave/mp3 with silence padding
        concat_list_path = output_path + ".concat.txt"
        temp_dir = os.path.dirname(os.path.abspath(output_path))

        current_time = 0.0
        file_entries = []

        try:
            for idx, (start_time, seg_file) in enumerate(segment_files):
                # If there is a gap between current_time and start_time, generate a silence file
                gap = start_time - current_time
                if gap > 0.05:
                    silence_file = os.path.join(temp_dir, f"__silence_{idx:04d}.mp3")
                    cmd_silence = [
                        self.ffmpeg_path,
                        "-y",
                        "-f", "lavfi",
                        "-i", f"anullsrc=r=44100:cl=stereo",
                        "-t", f"{gap:.3f}",
                        "-q:a", "2",
                        silence_file
                    ]
                    subprocess.run(cmd_silence, capture_output=True, text=True)
                    if os.path.exists(silence_file):
                        file_entries.append(silence_file)

                file_entries.append(seg_file)
                seg_dur = self.get_audio_duration(seg_file)
                current_time = max(start_time + seg_dur, current_time + seg_dur)

            # Write concat demuxer file
            with open(concat_list_path, "w", encoding="utf-8") as f:
                for entry in file_entries:
                    escaped_path = entry.replace("\\", "/")
                    f.write(f"file '{escaped_path}'\n")

            # Concatenate all into final output audio
            cmd_concat = [
                self.ffmpeg_path,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_path,
                "-c:a", "libmp3lame",
                "-q:a", "2",
                output_path
            ]
            res = subprocess.run(cmd_concat, capture_output=True, text=True)
            if res.returncode != 0:
                logger.error(f"FFmpeg concat failed: {res.stderr}")
                raise RuntimeError(f"FFmpeg ghép âm thanh thất bại: {res.stderr}")

        finally:
            if os.path.exists(concat_list_path):
                try:
                    os.remove(concat_list_path)
                except Exception:
                    pass
            # Clean silence files
            for entry in file_entries:
                if "__silence_" in entry and os.path.exists(entry):
                    try:
                        os.remove(entry)
                    except Exception:
                        pass

    def mux_video_with_dubbed_audio(
        self,
        video_path: str,
        dubbed_audio_path: str,
        output_video_path: str,
        ducking_volume: float = 0.15,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> str:
        """
        Merge original video with dubbed Vietnamese audio using Audio Ducking or replacement.

        Args:
            video_path: Path to original video.
            dubbed_audio_path: Path to dubbed Vietnamese audio.
            output_video_path: Destination path for output video.
            ducking_volume: Volume level for original audio (0.0 = mute original, 0.15 = 15% ducking).
            progress_callback: Optional progress callback.

        Returns:
            Path to rendered video file.
        """
        logger.info(f"Muxing video with dubbed audio (Ducking: {ducking_volume * 100:.0f}%)...")
        if progress_callback:
            progress_callback(97.0, f"Đang xuất video lồng tiếng ({output_video_path})...")

        if ducking_volume <= 0.01:
            # Complete audio replacement: Video stream (copy) + Dubbed Audio (AAC)
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-i", video_path,
                "-i", dubbed_audio_path,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                output_video_path
            ]
        else:
            # Audio ducking mix: Original audio lowered to ducking_volume + Dubbed audio at 1.0
            filter_complex = (
                f"[0:a]volume={ducking_volume:.2f}[bg];"
                f"[1:a]volume=1.0[fg];"
                f"[bg][fg]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-i", video_path,
                "-i", dubbed_audio_path,
                "-filter_complex", filter_complex,
                "-map", "0:v:0",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                output_video_path
            ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg video muxing failed: {result.stderr}")
            # Fallback to pure audio replacement if amix fails (e.g. original video has no audio stream)
            cmd_fallback = [
                self.ffmpeg_path,
                "-y",
                "-i", video_path,
                "-i", dubbed_audio_path,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                output_video_path
            ]
            res_fb = subprocess.run(cmd_fallback, capture_output=True, text=True)
            if res_fb.returncode != 0:
                raise RuntimeError(f"Xuất video thất bại: {result.stderr}")

        if progress_callback:
            progress_callback(100.0, "Xuất video lồng tiếng thành công!")

        logger.info(f"Video muxed successfully: {output_video_path}")
        return output_video_path

    def export_srt(
        self,
        snippets: List[SubtitleSnippet],
        output_srt_path: str,
        use_translated: bool = True
    ) -> str:
        """Export subtitle snippets to a standard .srt subtitle file."""
        logger.info(f"Exporting subtitles to SRT: {output_srt_path}")
        with open(output_srt_path, "w", encoding="utf-8") as f:
            for idx, snippet in enumerate(snippets, start=1):
                start_str = format_timestamp_srt(snippet.start)
                end_str = format_timestamp_srt(snippet.end)
                text = snippet.translated_text if (use_translated and snippet.translated_text) else snippet.original_text

                f.write(f"{idx}\n")
                f.write(f"{start_str} --> {end_str}\n")
                f.write(f"{text}\n\n")

        return output_srt_path
