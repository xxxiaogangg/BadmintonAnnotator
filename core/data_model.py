# file: core/data_model.py

SCHEMA_VERSION = 1


def get_new_annotation_structure(video_filename, video_path, resolution, fps, total_frames):
    """
    返回一个全新的、结构化的标注字典。
    """
    return {
      "schema_version": SCHEMA_VERSION,
      "video_info": {
        "filename": video_filename,
        "path": video_path,
        "resolution": resolution,
        "fps": fps,
        "total_frames": total_frames
      },
      "match_info": {
        "event_name": "未命名赛事",
        "event_level": "未知",
        "match_stage": "未知",
        "player_a": "球员A",
        "player_b": "球员B",
        "set_scores": [],
        "current_set_score": [0, 0]
      },
      "events": [],
      "frame_annotations": {}
    }


def normalize_annotations(data):
    """
    为历史数据补齐必要字段，确保最小可用结构。
    """
    if not isinstance(data, dict):
        return data

    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("video_info", {})
    data.setdefault("match_info", {})
    data.setdefault("events", [])
    data.setdefault("frame_annotations", {})

    match_defaults = {
        "event_name": "未命名赛事",
        "event_level": "未知",
        "match_stage": "未知",
        "player_a": "球员A",
        "player_b": "球员B",
        "set_scores": [],
        "current_set_score": [0, 0],
    }
    match_info = data.get("match_info", {})
    if not isinstance(match_info, dict):
        match_info = {}
    for key, value in match_defaults.items():
        if key not in match_info:
            match_info[key] = value
    data["match_info"] = match_info

    if not isinstance(data.get("events"), list):
        data["events"] = []
    if not isinstance(data.get("frame_annotations"), dict):
        data["frame_annotations"] = {}

    for event in data["events"]:
        if not isinstance(event, dict):
            continue
        details = event.get("details")
        if not isinstance(details, dict):
            details = {}
        event_type = event.get("type")
        if event_type in ["SHOT", "RALLY_START"]:
            details.setdefault("hand", "待定")
            details.setdefault("major", "待定")
            details.setdefault("minor", "待定")
            details.setdefault("view_desc", "视角正常")
            if event_type == "SHOT":
                details.setdefault("player", "待定")
            if event_type == "RALLY_START":
                details.setdefault("serving_player", "待定")
                details.setdefault("score_at_start", [0, 0])
        event["details"] = details

    return data
