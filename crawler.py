import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple


class KStartupOngoingCrawler:
    """
    K-Startup (창업지원포털) '모집중' 공고 데이터 로더
    (robots.txt 정책 준수를 위해 로컬 mock_data.json 데이터셋을 로드합니다.)
    """

    def __init__(self, json_filename: str = "mock_data.json"):
        self.data_path = Path(__file__).resolve().parent / json_filename

    def fetch_ongoing_announcements(self) -> Tuple[List[Dict[str, Any]], str]:
        if not self.data_path.exists():
            return [], f"ERROR (데이터 파일을 찾을 수 없음: {self.data_path.name})"

        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                raw_data: List[Dict[str, Any]] = json.load(f)

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            announcements: List[Dict[str, Any]] = []
            for item in raw_data:
                record = dict(item)
                record.setdefault("crawled_at", now_str)
                announcements.append(record)

            return (
                announcements,
                f"MOCK_DATASET_LOADED ({self.data_path.name}에서 모집중 공고 {len(announcements)}건 로드 완료)",
            )
        except Exception as e:
            return (
                [],
                f"ERROR ({self.data_path.name} 로드 중 예외 발생 [{type(e).__name__}])",
            )