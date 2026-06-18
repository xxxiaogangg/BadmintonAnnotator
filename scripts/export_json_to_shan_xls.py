#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


HEADERS = [
    "唯一序号",
    "赛事名称",
    "本场胜方",
    "本场比分",
    "年份",
    "赛事名",
    "性别",
    "轮次",
    "运动员A",
    "运动员B",
    "技术回溯",
    "局数",
    "上/下半场",
    "回合数",
    "A选手得分",
    "B选手得分",
    "是否为关键分",
    "拍数",
    "拍数倒序",
    "拍数阶段",
    "选手",
    "区域",
    "正反手",
    "技术动作",
    "英文",
    "得分方",
    "失分方",
    "最后一拍得失分",
    "得失分类型",
    " 路径名称",
    "最后一拍",
    "击球时间",
    "回合用时(格式化)",
    "回合用时(毫秒)",
    "回合休息用时(格式化)",
    "回合休息用时(毫秒)",
    "本局比赛用时(格式化)",
    "本局比赛用时(毫秒)",
    "本局休息总用时(格式化)",
    "本局休息总用时(毫秒)",
    "半局比赛时间(格式化)",
    "半局比赛时间(毫秒)",
    "半局休息时间(格式化)",
    "半局休息时间(毫秒)",
    "本场比赛用时(格式化)",
    "本场比赛用时(毫秒)",
    "本局胜方",
    "本局负方",
    "本场负方",
    "红方",
    "蓝方",
    "红方是发球方",
    "蓝方是发球方",
    "红方第二局是关键局",
    "蓝方第二局是关键局",
]

RALLY_START_RE = re.compile(r"evt_s(?P<set>\d+)_r(?P<rally>\d+)_start$")
SHOT_RE = re.compile(r"evt_s(?P<set>\d+)_r(?P<rally>\d+)_shot(?P<shot>\d+)$")
RALLY_END_RE = re.compile(r"evt_s(?P<set>\d+)_r(?P<rally>\d+)_end$")
SET_RE = re.compile(r"evt_s(?P<set>\d+)_(?P<kind>start|end)$")

SERVE_ACTION_EXPORT = {
    "发网前": "网前",
    "发平高": "平高",
    "发高远": "高远",
}

BASE_ACTION_EXPORT = {
    "高": "高",
    "高远": "高",
    "平高": "平高",
    "吊": "吊",
    "劈吊": "劈吊",
    "杀": "杀",
    "搓放网": "搓/放",
    "放网": "搓/放",
    "勾球": "勾",
    "勾": "勾",
    "推": "推",
    "挑": "挑",
    "推挑": "推挑",
    "扑": "扑",
    "抽": "抽",
    "挡": "挡",
    "拦挡": "拦挡",
    "封网": "封网",
}

ENGLISH_ACTIONS = {
    "网前": "Low serve",
    "高远": "high service",
    "平高": "high service",
    "高": "clear",
    "杀": "smash",
    "劈吊": "cut",
    "吊": "drop",
    "挑": "lob",
    "推挑": "lob",
    "推": "push",
    "搓/放": "net",
    "勾": "cross",
    "挡": "block",
    "拦挡": "block",
    "抽": "drive",
    "扑": "kill",
    "封网": "net block",
    "接杀挡": "defense block",
    "接杀挑": "defense lob",
    "接杀勾": "defense cross",
    "接吊球放网": "net",
    "接吊球挑": "lob",
    "接吊球勾": "cross",
    "接劈吊放网": "net",
    "接劈吊挑": "lob",
    "接劈吊勾": "cross",
}


@dataclass
class Hit:
    set_no: int
    rally_no: int
    shot_no: int
    frame: int
    details: dict[str, Any]
    event_type: str


@dataclass
class Rally:
    set_no: int
    rally_no: int
    hits: list[Hit]
    end_event: dict[str, Any] | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export BadmintonAnnotator JSON to Shan-style .xls CSV."
    )
    parser.add_argument("json_path", type=Path, help="BadmintonAnnotator .json file")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output .xls path")
    parser.add_argument("--gender", default="女子", help="Value for 性别 column")
    parser.add_argument("--year", default=None, help="Value for 年份 column; defaults to year inferred from JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = json.loads(args.json_path.read_text(encoding="utf-8"))
    output = args.output or default_output_path(args.json_path)
    row_count = write_xls(data, output, gender=args.gender, year=args.year)
    print(json.dumps({"output": str(output), "rows": row_count}, ensure_ascii=False))
    return 0


def default_output_path(json_path: Path) -> Path:
    name = json_path.name
    if name.endswith(".mp4.json"):
        stem = name[: -len(".mp4.json")]
    elif name.endswith(".json"):
        stem = name[: -len(".json")]
    else:
        stem = json_path.stem
    return json_path.with_name(f"{stem}-json-export.xls")


def write_xls(data: dict[str, Any], output_path: Path, *, gender: str = "女子", year: Optional[str] = None) -> int:
    """Write an Excel-compatible CSV using .xls extension and return exported row count."""
    export_year = year or infer_year(data)
    rows = export_rows(data, gender=gender, year=export_year)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def infer_year(data: dict[str, Any]) -> str:
    match_info = data.get("match_info") if isinstance(data.get("match_info"), dict) else {}
    video_info = data.get("video_info") if isinstance(data.get("video_info"), dict) else {}
    candidates = [
        match_info.get("event_name"),
        video_info.get("filename"),
        video_info.get("path"),
    ]
    for candidate in candidates:
        match = re.search(r"(20\d{2})", str(candidate or ""))
        if match:
            return f"{match.group(1)}年"
    return f"{datetime.now().year}年"


def strip_leading_year_for_title(event_name: str, year: str) -> str:
    year_match = re.search(r"(20\d{2})", str(year or ""))
    if not year_match:
        return event_name
    year_digits = year_match.group(1)
    if not event_name.startswith(year_digits):
        return event_name
    stripped = event_name[len(year_digits):].lstrip("年 -_")
    return stripped or event_name


def export_rows(data: dict[str, Any], *, gender: str, year: str) -> list[dict[str, Any]]:
    fps = float(data.get("video_info", {}).get("fps") or 30.0)
    match_info = data.get("match_info") if isinstance(data.get("match_info"), dict) else {}
    player_a = str(match_info.get("player_a") or "A")
    player_b = str(match_info.get("player_b") or "B")
    event_name = str(match_info.get("event_name") or data.get("video_info", {}).get("filename") or "未命名赛事")
    title_event_name = strip_leading_year_for_title(event_name, year)
    match_stage = str(match_info.get("match_stage") or "")
    set_scores = normalized_set_scores(match_info.get("set_scores"))

    events = sorted(
        [event for event in data.get("events", []) if isinstance(event, dict)],
        key=lambda event: (int(event.get("frame") or 0), str(event.get("event_id") or "")),
    )
    rallies = build_rallies(events)
    set_frames = build_set_frames(events, rallies)
    timing = build_timing_summary(rallies, set_frames, fps)
    set_scores = set_scores or derive_set_scores(rallies, player_a, player_b)

    match_winner, match_loser, match_score = match_result(player_a, player_b, set_scores)
    red_player = player_a
    blue_player = player_b
    rows: list[dict[str, Any]] = []

    sequence = 1
    for rally in rallies:
        if not rally.hits:
            continue
        start_details = rally.hits[0].details
        score_at_start = coerce_score(start_details.get("score_at_start"))
        end_details = rally.end_event.get("details", {}) if rally.end_event else {}
        winner = str(end_details.get("winner") or "")
        loser = other_player(winner, player_a, player_b)
        score_after = add_score(score_at_start, winner, player_a, player_b)
        reason = normalize_end_reason(str(end_details.get("minor") or "制胜分"))
        last_result, result_type = result_text(winner, loser, reason)
        set_winner, set_loser = set_result_for(rally.set_no, player_a, player_b, set_scores)
        rally_timing = timing["rallies"].get((rally.set_no, rally.rally_no), {})
        set_timing = timing["sets"].get(rally.set_no, {})
        half = "上半场" if max(score_at_start) < 11 else "下半场"
        serving_player = str(start_details.get("serving_player") or "")
        previous_minor = ""
        total_hits = len(rally.hits)

        for shot_index, hit in enumerate(rally.hits, start=1):
            details = hit.details
            is_serve = hit.event_type == "RALLY_START"
            player = str(details.get("serving_player") if is_serve else details.get("player") or "")
            minor = str(details.get("minor") or "")
            action = export_action(minor, previous_minor=previous_minor, is_serve=is_serve)
            row = {
                "唯一序号": sequence,
                "赛事名称": f"{year}{title_event_name}{gender}{match_stage}{player_a}VS{player_b}",
                "本场胜方": match_winner,
                "本场比分": match_score,
                "年份": year,
                "赛事名": event_name,
                "性别": gender,
                "轮次": match_stage,
                "运动员A": player_a,
                "运动员B": player_b,
                "技术回溯": "",
                "局数": rally.set_no,
                "上/下半场": half,
                "回合数": rally.rally_no,
                "A选手得分": score_after[0],
                "B选手得分": score_after[1],
                "是否为关键分": "",
                "拍数": shot_index,
                "拍数倒序": total_hits - shot_index + 1,
                "拍数阶段": shot_stage(shot_index),
                "选手": player,
                "区域": export_court_position(str(details.get("court_position") or "")),
                "正反手": str(details.get("technique_hand") or ""),
                "技术动作": action,
                "英文": ENGLISH_ACTIONS.get(action, ""),
                "得分方": winner,
                "失分方": loser,
                "最后一拍得失分": last_result,
                "得失分类型": result_type,
                " 路径名称": export_path_name(details, is_serve=is_serve),
                "最后一拍": "是" if shot_index == total_hits else "",
                "击球时间": format_ms(frame_to_ms(hit.frame, fps)),
                "回合用时(格式化)": format_ms(int(rally_timing.get("play_ms", 0))),
                "回合用时(毫秒)": int(rally_timing.get("play_ms", 0)),
                "回合休息用时(格式化)": format_ms(int(rally_timing.get("rest_ms", 0))),
                "回合休息用时(毫秒)": int(rally_timing.get("rest_ms", 0)),
                "本局比赛用时(格式化)": format_ms(int(set_timing.get("play_ms", 0))),
                "本局比赛用时(毫秒)": int(set_timing.get("play_ms", 0)),
                "本局休息总用时(格式化)": format_ms(int(set_timing.get("rest_ms", 0))),
                "本局休息总用时(毫秒)": int(set_timing.get("rest_ms", 0)),
                "半局比赛时间(格式化)": format_ms(int(set_timing.get(f"{half}_play_ms", 0))),
                "半局比赛时间(毫秒)": int(set_timing.get(f"{half}_play_ms", 0)),
                "半局休息时间(格式化)": format_ms(int(set_timing.get(f"{half}_rest_ms", 0))),
                "半局休息时间(毫秒)": int(set_timing.get(f"{half}_rest_ms", 0)),
                "本场比赛用时(格式化)": format_ms(int(timing.get("match_play_ms", 0))),
                "本场比赛用时(毫秒)": int(timing.get("match_play_ms", 0)),
                "本局胜方": set_winner,
                "本局负方": set_loser,
                "本场负方": match_loser,
                "红方": red_player,
                "蓝方": blue_player,
                "红方是发球方": "是" if serving_player == red_player else "否",
                "蓝方是发球方": "是" if serving_player == blue_player else "否",
                "红方第二局是关键局": "否",
                "蓝方第二局是关键局": "否",
            }
            rows.append(row)
            sequence += 1
            previous_minor = minor
    return rows


def build_rallies(events: list[dict[str, Any]]) -> list[Rally]:
    groups: dict[tuple[int, int], dict[str, Any]] = {}
    for event in events:
        event_id = str(event.get("event_id") or "")
        event_type = str(event.get("type") or "")
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        frame = int(event.get("frame") or 0)
        start_match = RALLY_START_RE.match(event_id)
        shot_match = SHOT_RE.match(event_id)
        end_match = RALLY_END_RE.match(event_id)
        if start_match:
            set_no = int(start_match.group("set"))
            rally_no = int(start_match.group("rally"))
            group = groups.setdefault((set_no, rally_no), {"hits": {}, "end": None})
            group["hits"][1] = Hit(set_no, rally_no, 1, frame, details, event_type)
        elif shot_match:
            set_no = int(shot_match.group("set"))
            rally_no = int(shot_match.group("rally"))
            shot_no = int(shot_match.group("shot"))
            group = groups.setdefault((set_no, rally_no), {"hits": {}, "end": None})
            group["hits"][shot_no] = Hit(set_no, rally_no, shot_no, frame, details, event_type)
        elif end_match:
            set_no = int(end_match.group("set"))
            rally_no = int(end_match.group("rally"))
            group = groups.setdefault((set_no, rally_no), {"hits": {}, "end": None})
            group["end"] = event
    rallies = []
    for (set_no, rally_no), group in sorted(groups.items()):
        hits = [group["hits"][shot_no] for shot_no in sorted(group["hits"])]
        rallies.append(Rally(set_no=set_no, rally_no=rally_no, hits=hits, end_event=group["end"]))
    return rallies


def build_set_frames(events: list[dict[str, Any]], rallies: list[Rally]) -> dict[int, dict[str, int]]:
    frames: dict[int, dict[str, int]] = {}
    for event in events:
        match = SET_RE.match(str(event.get("event_id") or ""))
        if not match:
            continue
        set_no = int(match.group("set"))
        key = "start" if match.group("kind") == "start" else "end"
        frames.setdefault(set_no, {})[key] = int(event.get("frame") or 0)
    for rally in rallies:
        if not rally.hits:
            continue
        item = frames.setdefault(rally.set_no, {})
        item.setdefault("start", rally.hits[0].frame)
        end_frame = int(rally.end_event.get("frame") or 0) if rally.end_event else rally.hits[-1].frame
        item["end"] = max(item.get("end", end_frame), end_frame)
    return frames


def build_timing_summary(rallies: list[Rally], set_frames: dict[int, dict[str, int]], fps: float) -> dict[str, Any]:
    rally_timing: dict[tuple[int, int], dict[str, int]] = {}
    set_timing: dict[int, dict[str, int]] = {}
    match_start = None
    match_end = None
    rallies_by_set: dict[int, list[Rally]] = {}
    for rally in rallies:
        rallies_by_set.setdefault(rally.set_no, []).append(rally)

    for set_no, set_rallies in rallies_by_set.items():
        set_rallies.sort(key=lambda row: row.rally_no)
        set_start = set_frames.get(set_no, {}).get("start", set_rallies[0].hits[0].frame)
        set_end = set_frames.get(set_no, {}).get("end", set_rallies[-1].hits[-1].frame)
        match_start = set_start if match_start is None else min(match_start, set_start)
        match_end = set_end if match_end is None else max(match_end, set_end)
        upper_play = lower_play = upper_rest = lower_rest = 0
        rest_total = 0

        for index, rally in enumerate(set_rallies):
            start_frame = rally.hits[0].frame
            end_frame = int(rally.end_event.get("frame") or 0) if rally.end_event else rally.hits[-1].frame
            next_start = set_rallies[index + 1].hits[0].frame if index + 1 < len(set_rallies) else end_frame
            play_ms = frames_to_ms(max(0, end_frame - start_frame), fps)
            rest_ms = frames_to_ms(max(0, next_start - end_frame), fps)
            rally_timing[(rally.set_no, rally.rally_no)] = {"play_ms": play_ms, "rest_ms": rest_ms}
            rest_total += rest_ms
            score = coerce_score(rally.hits[0].details.get("score_at_start"))
            if max(score) < 11:
                upper_play += play_ms
                upper_rest += rest_ms
            else:
                lower_play += play_ms
                lower_rest += rest_ms

        set_timing[set_no] = {
            "play_ms": frames_to_ms(max(0, set_end - set_start), fps),
            "rest_ms": rest_total,
            "上半场_play_ms": upper_play,
            "上半场_rest_ms": upper_rest,
            "下半场_play_ms": lower_play,
            "下半场_rest_ms": lower_rest,
        }

    return {
        "rallies": rally_timing,
        "sets": set_timing,
        "match_play_ms": frames_to_ms(max(0, (match_end or 0) - (match_start or 0)), fps),
    }


def normalized_set_scores(value: Any) -> list[list[int]]:
    result: list[list[int]] = []
    if not isinstance(value, list):
        return result
    for score in value:
        parsed = coerce_score(score)
        if parsed != [0, 0]:
            result.append(parsed)
    return result


def derive_set_scores(rallies: list[Rally], player_a: str, player_b: str) -> list[list[int]]:
    scores: list[list[int]] = []
    current_set = None
    score = [0, 0]
    for rally in rallies:
        if current_set != rally.set_no:
            if current_set is not None:
                scores.append(score)
            current_set = rally.set_no
            score = [0, 0]
        winner = str((rally.end_event or {}).get("details", {}).get("winner") or "")
        score = add_score(score, winner, player_a, player_b)
    if current_set is not None:
        scores.append(score)
    return scores


def match_result(player_a: str, player_b: str, set_scores: list[list[int]]) -> tuple[str, str, str]:
    a_sets = sum(1 for score in set_scores if score[0] > score[1])
    b_sets = sum(1 for score in set_scores if score[1] > score[0])
    winner = player_a if a_sets >= b_sets else player_b
    loser = player_b if winner == player_a else player_a
    return winner, loser, f"{a_sets}' ： {b_sets}'"


def set_result_for(set_no: int, player_a: str, player_b: str, set_scores: list[list[int]]) -> tuple[str, str]:
    if 1 <= set_no <= len(set_scores):
        score = set_scores[set_no - 1]
        if score[0] > score[1]:
            return player_a, player_b
        if score[1] > score[0]:
            return player_b, player_a
    return "", ""


def coerce_score(value: Any) -> list[int]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return [int(value[0]), int(value[1])]
        except (TypeError, ValueError):
            pass
    return [0, 0]


def add_score(score: list[int], winner: str, player_a: str, player_b: str) -> list[int]:
    result = [int(score[0]), int(score[1])]
    if winner == player_a:
        result[0] += 1
    elif winner == player_b:
        result[1] += 1
    return result


def other_player(player: str, player_a: str, player_b: str) -> str:
    if player == player_a:
        return player_b
    if player == player_b:
        return player_a
    return ""


def normalize_end_reason(reason: str) -> str:
    if "非受迫性失误" in reason:
        return "非受迫性失误"
    if "受迫性失误" in reason:
        return "受迫性失误"
    return "制胜分"


def result_text(winner: str, loser: str, reason: str) -> tuple[str, str]:
    if reason == "制胜分":
        return f"{winner}制胜分", f"{winner}制胜分"
    return f"{loser}{reason}", f"{winner}导致对方{reason}"


def export_action(minor: str, *, previous_minor: str, is_serve: bool) -> str:
    if is_serve:
        return SERVE_ACTION_EXPORT.get(minor, minor.removeprefix("发") if minor.startswith("发") else minor)
    current = canonical_action(minor)
    previous = canonical_action(previous_minor)
    if previous == "杀":
        if current == "挡":
            return "接杀挡"
        if current in {"挑", "推挑"}:
            return "接杀挑"
        if current == "勾":
            return "接杀勾"
    if previous == "吊":
        if current == "放网":
            return "接吊球放网"
        if current in {"挑", "推挑"}:
            return "接吊球挑"
        if current == "勾":
            return "接吊球勾"
    if previous == "劈吊":
        if current == "放网":
            return "接劈吊放网"
        if current in {"挑", "推挑"}:
            return "接劈吊挑"
        if current == "勾":
            return "接劈吊勾"
    return BASE_ACTION_EXPORT.get(minor, minor)


def canonical_action(minor: str) -> str:
    if minor in {"高远", "高"}:
        return "高"
    if minor in {"搓放网", "放网", "搓/放"}:
        return "放网"
    if minor in {"勾球", "勾"}:
        return "勾"
    return minor


def export_court_position(value: str) -> str:
    if len(value) >= 2 and value[0] in "前中后" and value[1] in "左中右":
        return f"{value[1]}{value[0]}场"
    return value if value and value != "待定" else ""


def export_path_name(details: dict[str, Any], *, is_serve: bool) -> str:
    if is_serve:
        landing = str(details.get("serve_landing") or "")
        match = re.search(r"[1-6]", landing)
        return f"{match.group(0)}号位" if match else ""
    route = str(details.get("shot_route") or "")
    return route if route in {"直线", "斜线", "中路"} else ""


def shot_stage(shot_no: int) -> str:
    if shot_no <= 5:
        return "1-5拍"
    if shot_no <= 8:
        return "6-8拍"
    if shot_no <= 16:
        return "9-16拍"
    return "17-1000拍"


def frame_to_ms(frame: int, fps: float) -> int:
    if fps <= 0:
        return 0
    return int(round((frame / fps) * 1000))


def frames_to_ms(frames: int, fps: float) -> int:
    if fps <= 0:
        return 0
    return int(round((frames / fps) * 1000))


def format_ms(ms: int) -> str:
    ms = max(0, int(ms))
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{minutes:02d}′{seconds:02d}″{millis:03d}"


if __name__ == "__main__":
    raise SystemExit(main())
