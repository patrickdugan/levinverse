from __future__ import annotations

import argparse
import json
from pathlib import Path

from .discover import discover
from .ingest import ingest
from .report import generate_report
from .transcribe import transcribe_media


def main() -> None:
    parser = argparse.ArgumentParser(prog="levinverse")
    parser.add_argument("command", choices=("discover", "ingest", "transcribe", "report"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--video-id", action="append", help="restrict ingestion to these video IDs")
    parser.add_argument("--captions", action="store_true")
    parser.add_argument("--metadata", action="store_true", help="enrich entries through yt-dlp metadata extraction")
    parser.add_argument("--store-captions", action="store_true", help="store captions only for entries marked caption_storage_authorized")
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--permission-file", type=Path)
    parser.add_argument("--model")
    args = parser.parse_args()
    if args.command == "discover":
        seen, added = discover(args.root, args.source, args.limit, args.metadata)
        print(f"Source records: {seen}; new video records: {added}")
    elif args.command == "ingest":
        print(ingest(args.root, args.captions, args.limit, args.delay, args.store_captions, set(args.video_id) if args.video_id else None))
    elif args.command == "transcribe":
        if not args.media or not args.permission_file:
            parser.error("transcribe requires --media under media/permitted/ and --permission-file")
        permission = json.loads(args.permission_file.read_text(encoding="utf-8"))
        print(transcribe_media(args.media, args.root, permission, args.model))
    else:
        print(generate_report(args.root))


if __name__ == "__main__":
    main()
