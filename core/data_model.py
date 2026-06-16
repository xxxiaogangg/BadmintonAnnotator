# file: core/data_model.py

SCHEMA_VERSION = 1

COURT_CALIBRATION_VERSION = 1
COURT_SIDE_ASSIGNMENT_VERSION = 1
COURT_POINT_ORDER = [
    "singles_far_left",
    "singles_far_right",
    "singles_near_right",
    "singles_near_left",
    "net_left_top",
    "net_right_top",
    "net_right_bottom",
    "net_left_bottom",
]
COURT_POINT_LABELS = {
    "singles_far_left": "单打远左",
    "singles_far_right": "单打远右",
    "singles_near_right": "单打近右",
    "singles_near_left": "单打近左",
    "net_left_top": "网左上",
    "net_right_top": "网右上",
    "net_right_bottom": "网右下",
    "net_left_bottom": "网左下",
}
TECHNIQUE_MAJOR_ALIASES = {
    "后场上手": "后场技术",
    "网前三技术": "网前技术",
}
LEGACY_MID_FRONT_MAJOR = "中前场/防守反应"
FRONT_COURT_ACTIONS = {"推", "挑", "推挑", "扑", "封网", "搓放网", "勾球"}
MID_COURT_ACTIONS = {"抽", "挡"}
RALLY_END_REASON_ALIASES = {
    "受迫性失误": "对方受迫性失误",
    "非受迫性失误": "对方非受迫性失误",
}


def _coerce_resolution(resolution):
    if isinstance(resolution, (list, tuple)) and len(resolution) >= 2:
        try:
            width = int(resolution[0])
            height = int(resolution[1])
            if width > 0 and height > 0:
                return width, height
        except (TypeError, ValueError):
            pass
    return 1280, 720


def get_default_court_calibration(resolution):
    """
    创建一个默认的单打场地 8 点标定：单打四角 + 球网四角。
    坐标使用视频原始坐标，后续 UI 显示时再映射到 QLabel 坐标。
    """
    width, height = _coerce_resolution(resolution)
    point_ratios = {
        "singles_far_left": (0.38, 0.18),
        "singles_far_right": (0.62, 0.18),
        "singles_near_right": (0.82, 0.88),
        "singles_near_left": (0.18, 0.88),
        "net_left_top": (0.30, 0.47),
        "net_right_top": (0.70, 0.47),
        "net_right_bottom": (0.71, 0.52),
        "net_left_bottom": (0.29, 0.52),
    }
    points = {
        point_id: {
            "label": COURT_POINT_LABELS[point_id],
            "x": int(width * x_ratio),
            "y": int(height * y_ratio),
        }
        for point_id, (x_ratio, y_ratio) in point_ratios.items()
    }
    return {
        "version": COURT_CALIBRATION_VERSION,
        "court_type": "singles",
        "locked": True,
        "visible": True,
        "points": points,
    }


def normalize_court_calibration(court_calibration, resolution):
    default = get_default_court_calibration(resolution)
    if not isinstance(court_calibration, dict):
        return default

    normalized = {
        "version": court_calibration.get("version", COURT_CALIBRATION_VERSION),
        "court_type": court_calibration.get("court_type", "singles"),
        "locked": bool(court_calibration.get("locked", True)),
        "visible": bool(court_calibration.get("visible", True)),
        "points": {},
    }

    raw_points = court_calibration.get("points")
    if isinstance(raw_points, list):
        raw_points = {
            point.get("id"): point
            for point in raw_points
            if isinstance(point, dict) and point.get("id")
        }
    if not isinstance(raw_points, dict):
        raw_points = {}

    for point_id in COURT_POINT_ORDER:
        default_point = default["points"][point_id]
        raw_point = raw_points.get(point_id, {})
        if not isinstance(raw_point, dict):
            raw_point = {}
        try:
            x = int(raw_point.get("x", default_point["x"]))
            y = int(raw_point.get("y", default_point["y"]))
        except (TypeError, ValueError):
            x = default_point["x"]
            y = default_point["y"]
        normalized["points"][point_id] = {
            "label": raw_point.get("label") or COURT_POINT_LABELS[point_id],
            "x": x,
            "y": y,
        }

    return normalized


def normalize_court_side_assignment(court_side_assignment, match_info):
    if not isinstance(court_side_assignment, dict):
        return None

    player_a = match_info.get("player_a")
    player_b = match_info.get("player_b")
    valid_players = {player_a, player_b}
    top_player = court_side_assignment.get("initial_top_player")
    bottom_player = court_side_assignment.get("initial_bottom_player")
    if not top_player or not bottom_player:
        return None
    if top_player == bottom_player:
        return None
    if player_a and player_b and {top_player, bottom_player} != valid_players:
        return None

    return {
        "version": court_side_assignment.get("version", COURT_SIDE_ASSIGNMENT_VERSION),
        "initial_top_player": top_player,
        "initial_bottom_player": bottom_player,
        "source": court_side_assignment.get("source", "manual"),
    }


def normalize_technique_major(major, minor=None):
    if major in TECHNIQUE_MAJOR_ALIASES:
        return TECHNIQUE_MAJOR_ALIASES[major]
    if major == LEGACY_MID_FRONT_MAJOR:
        if minor in FRONT_COURT_ACTIONS:
            return "网前技术"
        if minor in MID_COURT_ACTIONS:
            return "中场技术"
    return major


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
      "frame_annotations": {},
      "court_calibration": get_default_court_calibration(resolution),
      "court_side_assignment": None
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
    data["court_calibration"] = normalize_court_calibration(
        data.get("court_calibration"),
        data.get("video_info", {}).get("resolution"),
    )

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
    data["court_side_assignment"] = normalize_court_side_assignment(
        data.get("court_side_assignment"),
        match_info,
    )

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
            details.setdefault("technique_hand", "待定")
            details.setdefault("minor", "待定")
            details.setdefault("view_desc", "视角正常")
            if event_type == "SHOT":
                details["major"] = normalize_technique_major(
                    details.get("major"),
                    details.get("minor"),
                )
                details.setdefault("player", "待定")
                details.setdefault("shot_route", "待定")
                details.setdefault("court_position", "待定")
            if event_type == "RALLY_START":
                details.setdefault("serving_player", "待定")
                details.setdefault("serving_player_source", "")
                details.setdefault("score_at_start", [0, 0])
                details.setdefault("serve_landing", "待定")
                details.setdefault("court_position", "待定")
        elif event_type == "RALLY_END":
            details.setdefault("hand", "适用")
            details.setdefault("major", "制胜分原因")
            details.setdefault("technique_hand", "")
            details.setdefault("minor", "待定")
            details["minor"] = RALLY_END_REASON_ALIASES.get(
                details.get("minor"),
                details.get("minor"),
            )
        event["details"] = details

    return data
