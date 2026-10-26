import json
import re
import time
from datetime import datetime
from typing import List, Dict, Any, Tuple
import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class KStartupOngoingCrawler:
    """
    K-Startup (창업지원포털) '모집중' 공고 전용 크롤러
    Target URL: https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do
    """

    BASE_URL = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.k-startup.go.kr/",
    }

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def fetch_ongoing_announcements(
        self, max_pages: int = 2, force_mock: bool = False
    ) -> Tuple[List[Dict[str, Any]], str]:
        if force_mock:
            return self._get_fallback_mock_data(), "MOCK_MODE (사용자 선택에 의해 Mock 데이터 로드됨)"

        collected: List[Dict[str, Any]] = []
        try:
            for page in range(1, max_pages + 1):
                params = {"schM": "list", "page": str(page)}
                response = self.session.get(
                    self.BASE_URL, params=params, timeout=self.timeout, verify=False
                )
                response.raise_for_status()

                page_items = self._parse_html(response.text)
                if page_items:
                    collected.extend(page_items)
                time.sleep(0.3)

            if len(collected) > 0:
                return (
                    collected,
                    f"LIVE_SUCCESS (K-Startup '모집중' 세션에서 실시간 {len(collected)}건 수집 완료)",
                )
            return (
                self._get_fallback_mock_data(),
                "FALLBACK_MODE (실시간 DOM 요소 0건 감지 -> 내장된 K-Startup 모집중 데이터셋으로 자동 전환)",
            )
        except Exception as e:
            return (
                self._get_fallback_mock_data(),
                f"FALLBACK_MODE (네트워크/방화벽 예외 발생 [{type(e).__name__}] -> 내장 데이터셋으로 자동 전환)",
            )

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        results = []

        items = soup.select(".board_list-wrap ul > li")
        if not items:
            items = soup.select("ul.list > li")
        if not items:
            items = [
                a.find_parent("li")
                for a in soup.select('a[href*="go_view"], a[href*="pbancSn"]')
                if a.find_parent("li")
            ]

        for idx, item in enumerate(items):
            try:
                a_tag = item.select_one('a[href*="go_view"], a[href*="pbancSn"], .middle a, a')
                href = a_tag.get("href", "") if a_tag else ""
                sn_match = re.search(r"(\d{5,7})", href)
                pbanc_sn = sn_match.group(1) if sn_match else f"LIVE-{idx+1000}"

                title_el = item.select_one("p.tit, .tit_wrap .tit, .title, strong")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title and a_tag:
                    title = a_tag.get_text(strip=True)
                if not title:
                    continue

                category_el = item.select_one(".top span.flag, span.flag, .category")
                category = category_el.get_text(strip=True) if category_el else "사업화"

                dday_el = item.select_one(".top span.day, span.day, .dday")
                d_day = dday_el.get_text(strip=True) if dday_el else "모집중"

                bottom_spans = [
                    s.get_text(strip=True)
                    for s in item.select(".bottom span.list, .bottom span, .info span")
                ]
                organization = (
                    bottom_spans[1]
                    if len(bottom_spans) > 1
                    else (bottom_spans[0] if bottom_spans else "창업진흥원")
                )

                deadline = "상시모집"
                for text in bottom_spans:
                    if "마감일" in text or "202" in text or "~" in text:
                        deadline = text.replace("마감일자", "").replace("마감일", "").strip()

                detail_url = f"{self.BASE_URL}?schM=view&pbancSn={pbanc_sn}"

                results.append(
                    {
                        "pbanc_sn": pbanc_sn,
                        "status": "모집중",
                        "category": category,
                        "title": title,
                        "organization": organization,
                        "d_day": d_day,
                        "deadline": deadline,
                        "target_stage": self._infer_stage_from_title(title),
                        "region": self._infer_region_from_title(title),
                        "summary": f"[{category}] {organization} 주관 모집중 공고: {title}. 마감: {deadline} ({d_day})",
                        "detail_url": detail_url,
                        "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
            except Exception:
                continue

        return results

    @staticmethod
    def _infer_stage_from_title(title: str) -> str:
        if any(k in title for k in ["예비창업", "예비", "아이디어", "학생", "청년"]):
            return "예비창업자 / 초기"
        if any(k in title for k in ["도약", "스케일업", "글로벌", "투자", "TIPS", "팁스"]):
            return "도약기 (3~7년) / 스케일업"
        if any(k in title for k in ["초기창업", "창업패키지", "보육", "입주"]):
            return "초기창업자 (3년 이내)"
        return "전체 창업자 (예비~7년 이내)"

    @staticmethod
    def _infer_region_from_title(title: str) -> str:
        regions = ["서울", "경기", "인천", "부산", "대구", "대전", "광주", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
        for r in regions:
            if r in title:
                return r
        return "전국"

    @staticmethod
    def _get_fallback_mock_data() -> List[Dict[str, Any]]:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return [
            {
                "pbanc_sn": "179101",
                "status": "모집중",
                "category": "사업화",
                "title": "[모집중] 혁신분야 예비창업패키지 (AI·빅데이터·딥테크 특화) 참여자 모집공고",
                "organization": "창업진흥원",
                "d_day": "D-12",
                "deadline": "마감일 ~ 11-15 18:00",
                "target_stage": "예비창업자",
                "region": "전국",
                "summary": "혁신 기술(AI, 빅데이터, 바이오, 친환경 등)을 보유한 예비창업자에게 시제품 제작비 평균 5,000만원(최대 1억원) 및 전담 멘토링, BM 고도화 교육을 패키지 지원합니다.",
                "detail_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179101",
                "crawled_at": now_str,
            },
            {
                "pbanc_sn": "179102",
                "status": "모집중",
                "category": "사업화",
                "title": "[모집중] 초기창업패키지 (창업 3년 이내 기업 사업화 자금 및 실증 지원)",
                "organization": "창업진흥원 / 서울창조경제혁신센터",
                "d_day": "D-9",
                "deadline": "마감일 ~ 11-12 16:00",
                "target_stage": "초기창업자 (3년 이내)",
                "region": "전국 (서울 주관)",
                "summary": "유망 창업아이템 및 고급기술을 보유한 창업 3년 이내 초기창업기업을 대상으로 시장진입, 초기 판로개척, 시제품 고도화 자금(최대 1억원) 및 투자유치 IR을 지원합니다.",
                "detail_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179102",
                "crawled_at": now_str,
            },
            {
                "pbanc_sn": "179103",
                "status": "모집중",
                "category": "기술개발(R&D)",
                "title": "[모집중] 창업성장기술개발사업 디딤돌 과제 (첫걸음 R&D) 참여기업 모집",
                "organization": "중소기업기술정보진흥원(TIPA)",
                "d_day": "D-18",
                "deadline": "마감일 ~ 11-21 18:00",
                "target_stage": "창업 7년 이내 (매출 20억 미만)",
                "region": "전국",
                "summary": "중소벤처기업부 R&D에 처음 참여하는 창업기업(7년 이하)을 대상으로 1년간 최대 1.2억원의 기술개발(R&D) 자금을 지원하여 기술경쟁력 확보 및 사업화를 촉진합니다.",
                "detail_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179103",
                "crawled_at": now_str,
            },
            {
                "pbanc_sn": "179104",
                "status": "모집중",
                "category": "시설ㆍ공간ㆍ보육",
                "title": "[모집중] 서울 AI 허브 및 청년창업사관학교 신규 입주기업(보육공간) 모집",
                "organization": "중소벤처기업진흥공단",
                "d_day": "D-5",
                "deadline": "마감일 ~ 11-08 17:00",
                "target_stage": "예비창업자 및 3년 이내 초기기업",
                "region": "서울",
                "summary": "만 39세 이하 청년 창업가 및 AI·SW 스타트업을 대상으로 무상/저렴한 독립형 사무공간(1년 입주, 연장 가능), 클라우드 GPU 서버 크레딧, 법률·회계 컨설팅을 지원합니다.",
                "detail_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179104",
                "crawled_at": now_str,
            },
            {
                "pbanc_sn": "179105",
                "status": "모집중",
                "category": "멘토링ㆍ컨설팅ㆍ교육",
                "title": "[모집중] K-스타트업 투자유치(IR) 역량강화 및 VC 1:1 네트워킹 프로그램",
                "organization": "한국벤처투자인큐베이팅센터",
                "d_day": "D-14",
                "deadline": "마감일 ~ 11-17 18:00",
                "target_stage": "예비~도약기 (시드~Pre-A 투자 희망)",
                "region": "서울/경기",
                "summary": "시드(Seed) 및 Pre-A 라운드 투자 유치를 준비하는 스타트업을 위해 IR 덱(Deck) 스토리라인 첨삭, 피칭 코칭, 현직 VC 심사역 1:1 밋업 및 데모데이 참가 기회를 제공합니다.",
                "detail_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179105",
                "crawled_at": now_str,
            },
            {
                "pbanc_sn": "179106",
                "status": "모집중",
                "category": "판로ㆍ해외진출",
                "title": "[모집중] 글로벌 액셀러레이팅(GAPS) 지원사업 (북미·유럽·동남아 시장 진출)",
                "organization": "창업진흥원 / 글로벌디지털혁신네트워크",
                "d_day": "D-21",
                "deadline": "마감일 ~ 11-24 18:00",
                "target_stage": "창업 7년 이내 (글로벌 진출 희망)",
                "region": "전국",
                "summary": "해외 시장 진출을 희망하는 유망 스타트업에게 글로벌 액셀러레이터의 현지 보육 프로그램, 해외 법인 설립, 글로벌 마케팅 자금(최대 6,000만원)을 지원합니다.",
                "detail_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179106",
                "crawled_at": now_str,
            },
            {
                "pbanc_sn": "179107",
                "status": "모집중",
                "category": "사업화",
                "title": "[모집중] 로컬크리에이터(지역가치 창업가) 활성화 지원사업 모집공고",
                "organization": "소상공인시장진흥공단",
                "d_day": "D-7",
                "deadline": "마감일 ~ 11-10 18:00",
                "target_stage": "예비창업자 및 소상공인/초기창업자",
                "region": "전국 (비수도권 우대)",
                "summary": "지역의 자연환경, 문화적 자산을 결합해 사업적 가치를 창출하는 로컬크리에이터(F&B, 공간기획, 로컬콘텐츠, 관광 등)에게 사업화 자금 최대 4,000만원을 지원합니다.",
                "detail_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179107",
                "crawled_at": now_str,
            },
            {
                "pbanc_sn": "179108",
                "status": "모집중",
                "category": "사업화",
                "title": "[모집중] 창업도약패키지 (대기업 협업형 오픈이노베이션 트랙) 참여기업 모집",
                "organization": "창업진흥원 / 경기창조경제혁신센터",
                "d_day": "D-15",
                "deadline": "마감일 ~ 11-18 18:00",
                "target_stage": "도약기 (창업 3년 초과 ~ 7년 이내)",
                "region": "전국 (경기 주관)",
                "summary": "죽음의 계곡(Death Valley) 극복과 스케일업을 원하는 창업 3~7년 기업에게 대기업 인프라를 활용한 PoC(기술검증) 기회 및 최대 2억원의 사업화 자금을 지원합니다.",
                "detail_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179108",
                "crawled_at": now_str,
            },
        ]