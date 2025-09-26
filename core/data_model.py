# file: core/data_model.py

def get_new_annotation_structure(video_filename, video_path, resolution, fps, total_frames):
    """
    返回一个全新的、结构化的标注字典。
    """
    return {
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