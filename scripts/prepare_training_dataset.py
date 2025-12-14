"""
根据标注 JSON 与对应视频生成训练数据集切片.
输出目录结构示例
当你在默认目录下运行 python scripts/set_training_data.py，针对示例文件 2025年中国羽毛球大师赛-安洗莹vs韩悦.mp4.json，会生成如下层级（每个事件 30 帧）：

/home/gang/gang_study/Data/Badminton_data/InHome/BWF/TrainingData
└── 2025年中国羽毛球大师赛-安洗莹vs韩悦
    └── set01
        ├── rally01
        │   ├── RALLY_START
        │   │   ├── frames
        │   │   │   ├── 17178.jpg
        │   │   │   ├── ...
        │   │   │   └── 17221.jpg
        │   │   ├── details.json
        │   │   └── meta.json
        │   ├── SHOT01
        │   │   ├── frames/...
        │   │   ├── details.json
        │   │   └── meta.json
        │   └── SHOT02
        │       └── ...
        └── rally02
            └── ...

frames/：以原始帧号命名的 JPG（frame-14 到 frame+15）。
details.json：该事件 details 字段的原样落盘（发球人、动作、手型等）：
{
  "player": "韩悦",
  "hand": "适用",
  "major": "勾球",
  "minor": "反手勾球"
}
meta.json：脚本自动补充的元信息，便于追踪来源：
{
  "event_id": "evt_5bf43e",
  "type": "SHOT",
  "frame": 17274,
  "video_filename": "2025年中国羽毛球大师赛-安洗莹vs韩悦.mp4",
  "frames_captured": [
    17260,
    17261,
    17262,
    17263,
    17264,
    17265,
    17266,
    17267,
    17268,
    17269,
    17270,
    17271,
    17272,
    17273,
    17274,
    17275,
    17276,
    17277,
    17278,
    17279,
    17280,
    17281,
    17282,
    17283,
    17284,
    17285,
    17286,
    17287,
    17288,
    17289
  ]
}
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from tqdm.auto import tqdm

import cv2


DEFAULT_SRC_DIR = Path(
    "/home/gang/gang_study/Data/Badminton_data/InHome/BWF/女单"
)
DEFAULT_DST_DIR = Path(
    "/home/gang/gang_study/Data/Badminton_data/InHome/BWF/TrainingData"
)
FRAMES_BEFORE = 14
FRAMES_AFTER = 15


@dataclass
class ExtractionStats:
    videos: int = 0
    events: int = 0
    skipped_events: int = 0
    errors: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="根据标注文件抽取帧窗口并组织成训练数据集"
    )
    parser.add_argument(
        "--src-dir",
        type=Path,
        default=DEFAULT_SRC_DIR,
        help="标注 JSON 所在目录（默认：%(default)s）",
    )
    parser.add_argument(
        "--dst-dir",
        type=Path,
        default=DEFAULT_DST_DIR,
        help="输出训练数据根目录（默认：%(default)s）",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="递归遍历 src-dir（默认只扫描一级）",
    )
    parser.add_argument(
        "--frames-before",
        type=int,
        default=FRAMES_BEFORE,
        help="事件帧前向采样数量（默认：%(default)s）",
    )
    parser.add_argument(
        "--frames-after",
        type=int,
        default=FRAMES_AFTER,
        help="事件帧后向采样数量（默认：%(default)s）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅处理前 N 个标注文件（调试用）",
    )
    return parser.parse_args()


def iter_annotation_files(src_dir: Path, recursive: bool) -> Iterable[Path]:
    if recursive:
        yield from sorted(src_dir.rglob("*.json"))
    else:
        yield from sorted(src_dir.glob("*.json"))


def resolve_video_path(annotation_path: Path, video_info: Dict) -> Path:
    candidates: List[Path] = []
    raw_path = video_info.get("path")
    filename = video_info.get("filename")

    if raw_path:
        candidates.append(Path(raw_path))
    if filename:
        candidates.append(annotation_path.with_name(filename))
        candidates.append(annotation_path.parent / filename)

    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"无法找到视频文件，尝试路径：{[str(p) for p in candidates if p]}"
    )


def ensure_capture(video_path: Path) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{video_path}")
    return cap


def dump_json(path: Path, payload: Dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def capture_window(
    cap: cv2.VideoCapture,
    target_frame: int,
    before: int,
    after: int,
    total_frames: Optional[int],
) -> List[Tuple[int, "cv2.typing.MatLike"]]:
    head = max(target_frame - before, 0)
    tail = target_frame + after
    if total_frames is not None:
        tail = min(tail, max(total_frames - 1, 0))

    frames: List[Tuple[int, "cv2.typing.MatLike"]] = []
    cap.set(cv2.CAP_PROP_POS_FRAMES, head)
    for frame_idx in range(head, tail + 1):
        ok, frame = cap.read()
        if not ok:
            logging.warning("读取帧失败：%s", frame_idx)
            break
        frames.append((frame_idx, frame))
    return frames


def save_event_bundle(
    cap: cv2.VideoCapture,
    event: Dict,
    dst_dir: Path,
    before: int,
    after: int,
    total_frames: Optional[int],
    video_filename: str,
) -> bool:
    dst_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = dst_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    window = capture_window(
        cap=cap,
        target_frame=int(event.get("frame", 0)),
        before=before,
        after=after,
        total_frames=total_frames,
    )
    if not window:
        return False

    for frame_idx, frame in window:
        frame_path = frames_dir / f"{frame_idx:06d}.jpg"
        if not cv2.imwrite(str(frame_path), frame):
            logging.warning("保存帧失败：%s", frame_path)

    dump_json(dst_dir / "details.json", event.get("details", {}))
    dump_json(
        dst_dir / "meta.json",
        {
            "event_id": event.get("event_id"),
            "type": event.get("type"),
            "frame": event.get("frame"),
            "video_filename": video_filename,
            "frames_captured": [idx for idx, _ in window],
        },
    )
    return True


def sanitize_index(name: str, idx: int) -> str:
    return f"{name}{idx:02d}"


def process_annotation(
    annotation_path: Path,
    dst_root: Path,
    before: int,
    after: int,
    stats: ExtractionStats,
) -> None:
    logging.info("处理标注：%s", annotation_path.name)
    data = json.loads(annotation_path.read_text(encoding="utf-8"))
    video_info = data.get("video_info", {})
    video_path = resolve_video_path(annotation_path, video_info)

    cap = ensure_capture(video_path)
    total_frames = (
        int(video_info["total_frames"]) if "total_frames" in video_info else None
    )
    if total_frames is None:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        total_frames = frame_count if frame_count > 0 else None

    video_dir = dst_root / video_path.stem
    current_set = 0
    current_rally = 0
    shot_idx = 0

    for event in data.get("events", []):
        event_type = event.get("type")
        if event_type == "SET_START":
            current_set += 1
            current_rally = 0
            continue

        if current_set == 0:
            current_set = 1

        if event_type == "RALLY_START":
            current_rally += 1
            shot_idx = 0
            event_name = "RALLY_START"
        elif event_type == "SHOT":
            if current_rally == 0:
                logging.warning(
                    "检测到孤立 SHOT，跳过：%s (%s)",
                    event.get("event_id"),
                    annotation_path.name,
                )
                stats.skipped_events += 1
                continue
            shot_idx += 1
            event_name = sanitize_index("SHOT", shot_idx)
        else:
            continue

        rally_dir = (
            video_dir
            / sanitize_index("set", current_set)
            / sanitize_index("rally", current_rally)
        )
        if save_event_bundle(
            cap=cap,
            event=event,
            dst_dir=rally_dir / event_name,
            before=before,
            after=after,
            total_frames=total_frames,
            video_filename=video_path.name,
        ):
            stats.events += 1
        else:
            stats.skipped_events += 1

    cap.release()
    stats.videos += 1


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
    )

    if not args.src_dir.exists():
        logging.error("源目录不存在：%s", args.src_dir)
        sys.exit(1)
    args.dst_dir.mkdir(parents=True, exist_ok=True)

    stats = ExtractionStats()
    annotation_files = list(iter_annotation_files(args.src_dir, args.recursive))
    if args.limit is not None:
        annotation_files = annotation_files[: args.limit]

    iterator: Iterable[Path]
    if tqdm is not None and annotation_files:
        iterator = tqdm(annotation_files, desc="处理标注文件", unit="视频")
    else:
        iterator = annotation_files

    total = len(annotation_files) or 1
    for idx, annotation_file in enumerate(iterator, start=1):
        if tqdm is None and total:
            logging.info("进度 %s/%s：%s", idx, total, annotation_file.name)
        try:
            process_annotation(
                annotation_file,
                args.dst_dir,
                args.frames_before,
                args.frames_after,
                stats,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logging.exception("处理失败：%s", annotation_file)
            stats.errors += 1

    logging.info(
        "完成：视频 %s 个，事件成功 %s 个，事件跳过 %s 个，异常 %s 个",
        stats.videos,
        stats.events,
        stats.skipped_events,
        stats.errors,
    )


if __name__ == "__main__":
    main()

