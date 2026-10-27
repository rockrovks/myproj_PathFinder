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

    _FULL_DATE_PATTERN = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")
    _SHORT_DATE_PATTERN = re.compile(r"(\d{1,2})[-./](\d{1,2})")
    _SEARCH_TEXT_FIELDS: Tuple[str, ...] = (
        "title",
        "category",
        "organization",
        "target_stage",
        "region",
        "summary",
    )

    def __init__(self, json_filename: str = "mock_data.json"):
        self.data_path = Path(__file__).resolve().parent / json_filename

    @classmethod
    def build_search_text(cls, record: Dict[str, Any]) -> str:
        return " ".join(
            str(record.get(field, "")) for field in cls._SEARCH_TEXT_FIELDS
        ).lower()

    @classmethod
    def parse_deadline_to_iso(
        cls, deadline_str: str, default_year: Optional[int] = None
    ) -> Optional[str]:
        if not deadline_str:
            return None
        text = str(deadline_str)

        full_match = cls._FULL_DATE_PATTERN.search(text)
        if full_match:
            try:
                return date(
                    int(full_match.group(1)),
                    int(full_match.group(2)),
                    int(full_match.group(3)),
                ).isoformat()
            except ValueError:
                return None

        short_match = cls._SHORT_DATE_PATTERN.search(text)
        if short_match:
            try:
                year = default_year if default_year is not None else datetime.now().year
                return date(
                    year,
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
                announcements: List[Dict[str, Any]] = json.load(f)

            now = datetime.now()
            now_str = now.strftime("%Y-%m-%d %H:%M:%S")
            current_year = now.year

            for record in announcements:
                record.setdefault("crawled_at", now_str)
                record["_parsed_deadline"] = self.parse_deadline_to_iso(
                    record.get("deadline", ""), default_year=current_year
                )
                record["_search_text"] = self.build_search_text(record)

            return (
                announcements,
                f"MOCK_DATASET_LOADED ({self.data_path.name}에서 모집중 공고 {len(announcements)}건 로드 및 사전 연산 완료)",
            )
        except Exception as e:
            return (
                [],
                f"ERROR ({self.data_path.name} 로드 중 예외 발생 [{type(e).__name__}])",
            )
