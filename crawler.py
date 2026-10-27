import json
import re
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional


class KStartupOngoingCrawler:
    """
    K-Startup (창업지원포털) '모집중' 공고 데이터 로더
    - robots.txt 준수를 위해 로컬 mock_data.json을 로드합니다.
    - 로드 시점에 검색용 통합 텍스트(_search_text)와 마감일(_parsed_deadline)을 사전 연산합니다.
    """

    def __init__(self, json_filename: str = "mock_data.json"):
        self.data_path = Path(__file__).resolve().parent / json_filename

    @staticmethod
    def parse_deadline_to_iso(deadline_str: str) -> Optional[str]:
        if not deadline_str:
            return None
        text = str(deadline_str)

        full_match = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", text)
        if full_match:
            try:
                return date(
                    int(full_match.group(1)),
                    int(full_match.group(2)),
                    int(full_match.group(3)),
                ).isoformat()
            except ValueError:
                return None

        short_match = re.search(r"(\d{1,2})[-./](\d{1,2})", text)
        if short_match:
            try:
                return date(
                    datetime.now().year,
                    int(short_match.group(1)),
                    int(short_match.group(2)),
                ).isoformat()
            except ValueError:
                return None

        return None

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
                record["_parsed_deadline"] = self.parse_deadline_to_iso(
                    record.get("deadline", "")
                )
                record["_search_text"] = (
                    f"{record.get('title', '')} {record.get('category', '')} "
                    f"{record.get('organization', '')} {record.get('target_stage', '')} "
                    f"{record.get('region', '')} {record.get('summary', '')}"
                ).lower()
                announcements.append(record)

            return (
                announcements,
                f"MOCK_DATASET_LOADED ({self.data_path.name}에서 모집중 공고 {len(announcements)}건 로드 및 사전 연산 완료)",
            )
        except Exception as e:
            return (
                [],
                f"ERROR ({self.data_path.name} 로드 중 예외 발생 [{type(e).__name__}])",
            )