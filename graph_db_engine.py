import json
import math
import os
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None


class StartupTaxonomyGraphEngine:
    """
    창업 도메인 택사노미(3대 페르소나 - 핵심 성장 과제 - 지원분야 - 모집공고 - 주관기관)를
    Property Graph 구조로 모델링하고, 3단계 통계 스케일링(20점 단위 지수 도약 -> IQR 이상치 보정 ->
    Z-Score 로지스틱 분포 변환) 및 고정형 고대비 그래프를 생성하는 엔진
    """

    PERSONA_TAXONOMY: Dict[str, Dict[str, Any]] = {
        "예비창업자": {
            "id": "PERSONA_PRE",
            "label": "예비창업자",
            "career_range": "사업자등록 이전 (예비 창업팀)",
            "description": "아이디어 구체화, 비즈니스 모델(BM) 수립, 시제품(MVP) 제작 자금 및 초기 입주공간이 필요한 단계",
            "criteria_summary": "공고일 기준 개인·법인 사업자등록 미보유 (폐업 이력 시 동종업종 여부 확인) 및 MVP·입주·BM 멘토링 과제 부합",
            "eligibility_criteria": [
                "공고일 기준 신청자 명의의 개인사업자 또는 법인사업자 등록 사실이 없을 것 (폐업 이력이 있는 경우 동종업종 폐업 후 경과 기간 요건 확인 필요)",
                "시제품(MVP) 제작, 초기 보육공간 입주, 아이디어·BM 구체화 멘토링 등 예비창업 단계 핵심 성장 과제와 부합할 것",
            ],
            "core_needs": [
                {
                    "id": "NEED_PRE_1",
                    "name": "시제품(MVP) 제작 및 초기 사업화 자금",
                    "weight": 1.0,
                    "categories": ["사업화"],
                    "keywords": ["예비창업", "시제품", "사업화", "아이템", "로컬", "바우처", "청년", "MVP"],
                },
                {
                    "id": "NEED_PRE_2",
                    "name": "초기 창업 보육공간 입주 및 인프라",
                    "weight": 0.92,
                    "categories": ["시설ㆍ공간ㆍ보육"],
                    "keywords": ["입주", "공간", "보육", "허브", "사관학교", "사무공간", "공유오피스", "캠퍼스"],
                },
                {
                    "id": "NEED_PRE_3",
                    "name": "아이디어 검증 및 BM 멘토링",
                    "weight": 0.85,
                    "categories": ["멘토링ㆍ컨설팅ㆍ교육", "사업화"],
                    "keywords": ["멘토링", "교육", "컨설팅", "역량강화", "피칭", "네트워킹", "부트캠프", "BM", "특허"],
                },
            ],
        },
        "창업 초기(3년 내외) 팀": {
            "id": "PERSONA_EARLY",
            "label": "창업 초기(3년 내외) 팀",
            "career_range": "창업 후 3년 이내 (초기 스타트업)",
            "description": "제품 시장 적합성(PMF) 검증, 초기 판로 개척, 첫걸음 기술개발(R&D), 시드/Pre-A 투자유치가 필요한 단계",
            "criteria_summary": "사업자등록증 개업연월일(법인설립등기일) 기준 업력 3년(36개월) 이내 충족 및 초기 사업화·첫걸음 R&D·시드 투자유치 과제 부합",
            "eligibility_criteria": [
                "공고일 기준 사업자등록증상 개업연월일(법인의 경우 법인등기부등본상 회사성립연월일)로부터 업력 3년(36개월) 이내일 것",
                "초기 판로 개척·실증, 첫걸음 기술개발(R&D), 시드·Pre-A 투자유치, 초기 보육공간 확보 등 초기 성장 과제와 부합할 것",
            ],
            "core_needs": [
                {
                    "id": "NEED_EARLY_1",
                    "name": "초기 판로개척 및 아이템 고도화 자금",
                    "weight": 1.0,
                    "categories": ["사업화", "판로ㆍ해외진출"],
                    "keywords": ["초기창업", "판로", "시장진입", "사업화", "실증", "고도화", "바우처", "마케팅", "크라우드펀딩"],
                },
                {
                    "id": "NEED_EARLY_2",
                    "name": "첫걸음 기술개발(R&D) 출연금 확보",
                    "weight": 0.94,
                    "categories": ["기술개발(R&D)"],
                    "keywords": ["R&D", "기술개발", "디딤돌", "첫걸음", "연구소", "기술경쟁력", "팁스", "TIPS", "SaaS"],
                },
                {
                    "id": "NEED_EARLY_3",
                    "name": "시드 및 Pre-A 투자유치(IR) 연계",
                    "weight": 0.88,
                    "categories": ["멘토링ㆍ컨설팅ㆍ교육", "사업화"],
                    "keywords": ["투자", "IR", "VC", "데모데이", "시드", "Pre-A", "액셀러레이팅"],
                },
                {
                    "id": "NEED_EARLY_4",
                    "name": "성장기 독립 사무공간 및 기술 인프라",
                    "weight": 0.82,
                    "categories": ["시설ㆍ공간ㆍ보육"],
                    "keywords": ["입주", "보육", "공간", "클라우드", "GPU", "허브", "창업존", "테스트베드"],
                },
            ],
        },
        "그 이상 베테랑 팀": {
            "id": "PERSONA_VETERAN",
            "label": "그 이상 베테랑 팀",
            "career_range": "창업 3년 초과 ~ 7년 이상 (도약·스케일업 팀)",
            "description": "죽음의 계곡 극복, 대기업 오픈이노베이션(PoC), 대규모 스케일업 자금, 글로벌 시장 진출이 필요한 단계",
            "criteria_summary": "업력 3년 초과 ~ 7년(84개월) 이내 도약기 요건(신산업 10년 이내·매출·선투자 조건 포함) 충족 및 오픈이노베이션·글로벌·상용화 R&D 과제 부합",
            "eligibility_criteria": [
                "공고일 기준 업력 3년 초과 ~ 7년(84개월) 이내 도약기 요건(또는 벤처·신산업 10년 이내, 매출액·민간 선투자 연계 요건)을 충족할 것",
                "대기업 오픈이노베이션(PoC), 글로벌 시장 진출·수출, 대규모 상용화 기술개발(R&D) 및 후속 스케일업 투자유치 과제와 부합할 것",
            ],
            "core_needs": [
                {
                    "id": "NEED_VET_1",
                    "name": "대기업 협업 오픈이노베이션 및 스케일업",
                    "weight": 1.0,
                    "categories": ["사업화"],
                    "keywords": ["도약", "스케일업", "대기업", "협업", "오픈이노베이션", "PoC", "죽음의 계곡", "초격차"],
                },
                {
                    "id": "NEED_VET_2",
                    "name": "글로벌 시장 진출 및 해외 액셀러레이팅",
                    "weight": 0.94,
                    "categories": ["판로ㆍ해외진출"],
                    "keywords": ["글로벌", "해외", "수출", "액셀러레이팅", "GAPS", "북미", "유럽", "현지", "전시회", "CES", "유니콘"],
                },
                {
                    "id": "NEED_VET_3",
                    "name": "상용화 기술개발(R&D) 및 후속 투자유치",
                    "weight": 0.88,
                    "categories": ["기술개발(R&D)", "멘토링ㆍ컨설팅ㆍ교육", "시설ㆍ공간ㆍ보육"],
                    "keywords": ["R&D", "기술개발", "전략형", "상용화", "시리즈A", "시리즈B", "M&A", "POST-TIPS", "스케일업 팁스"],
                },
            ],
        },
    }

    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []
        self.announcements: List[Dict[str, Any]] = []

        self.neo4j_uri = os.getenv("NEO4J_URI", "").strip()
        self.neo4j_user = os.getenv("NEO4J_USER", "").strip()
        self.neo4j_password = os.getenv("NEO4J_PASSWORD", "").strip()
        self.neo4j_synced = False

    @staticmethod
    def map_stage_to_persona(user_stage: str) -> str:
        """사용자의 창업 단계 입력값을 GraphDB의 3대 페르소나 키로 매핑합니다."""
        if "예비" in user_stage:
            return "예비창업자"
        if "초기" in user_stage or "3년 이내" in user_stage:
            return "창업 초기(3년 내외) 팀"
        return "그 이상 베테랑 팀"

    @classmethod
    def get_persona_criteria_info(cls, persona_name: str) -> Dict[str, Any]:
        p_data = cls.PERSONA_TAXONOMY.get(
            persona_name, cls.PERSONA_TAXONOMY["예비창업자"]
        )
        return {
            "persona": p_data["label"],
            "career_range": p_data["career_range"],
            "criteria_summary": p_data["criteria_summary"],
            "eligibility_criteria": p_data["eligibility_criteria"],
        }

    @classmethod
    def evaluate_stage_and_region(
        cls, persona_label: str, user_region: str, ann: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        [공통 적격 판정 엔진]
        페르소나별 적격 판단 기준에 따라 공고의 지원대상(target_stage) 및 지역(region) 적합도를
        정량 점수(업력 최대 0.35, 지역 최대 0.15)와 판정 근거 문구로 일관되게 산출합니다.
        """
        target = ann.get("target_stage", "")
        doc_region = ann.get("region", "전국")
        p_meta = cls.PERSONA_TAXONOMY.get(
            persona_label, cls.PERSONA_TAXONOMY["예비창업자"]
        )
        criteria_summary = p_meta["criteria_summary"]

        stage_score = 0.10
        stage_fit = "조건부 확인 필요"
        stage_verdict = f"조건부 확인 ({target} / 페르소나 기준 대조 필요)"

        if persona_label == "예비창업자":
            if "예비" in target and "초기" not in target and "도약" not in target and "3년" not in target:
                stage_score = 0.35
                stage_fit = "핵심 적격 (예비창업 전용)"
                stage_verdict = "적합 (사업자 미등록 예비창업자 전용 공고로 적격 기준 부합)"
            elif "예비" in target:
                stage_score = 0.28
                stage_fit = "적격 (예비창업 포함)"
                stage_verdict = "적합 (예비창업자 지원 가능 공고로 적격 기준 부합)"
            elif "전체" in target or "예비~도약" in target:
                stage_score = 0.20
                stage_fit = "지원 가능 (전체 창업자)"
                stage_verdict = "적합 (전체 창업 단계 대상 공고)"
            elif "3~7년" in target or "3년 초과" in target or "도약" in target:
                stage_score = 0.0
                stage_fit = "대상 외 (기창업 도약기 전용)"
                stage_verdict = "부적합 가능성 높음 (업력 3~7년 도약기 전용 공고로 예비창업자 기준 불일치)"
            elif "3년 이내" in target or "7년 이내" in target:
                stage_score = 0.04
                stage_fit = "조건부 주의 (기창업자 중심)"
                stage_verdict = "조건부 주의 (사업자등록 완료 기업 대상 공고 — 접수 마감 전 사업자등록 조건 허용 여부 확인 필요)"

        elif persona_label == "창업 초기(3년 내외) 팀":
            if "초기" in target and "예비" not in target and "도약" not in target:
                stage_score = 0.35
                stage_fit = "핵심 적격 (초기 3년 이내 전용)"
                stage_verdict = "적합 (개업일 기준 업력 3년 이내 초기창업 전용 적격 기준 부합)"
            elif "3년 이내" in target or "초기" in target:
                stage_score = 0.29
                stage_fit = "적격 (창업 3년 이내 포함)"
                stage_verdict = "적합 (업력 3년 이내 초기기업 지원 가능)"
            elif "7년 이내" in target and "3년 초과" not in target:
                stage_score = 0.23
                stage_fit = "적격 (창업 7년 이내 포함)"
                stage_verdict = "적합 (창업 7년 이하 대상 공고로 초기 3년 이내 팀 포함)"
            elif "예비~도약" in target or "전체" in target:
                stage_score = 0.19
                stage_fit = "지원 가능 (전체 창업자)"
                stage_verdict = "적합 (전체 창업자 대상 공고)"
            elif target == "예비창업자" or ("예비" in target and "초기" not in target and "3년" not in target):
                stage_score = 0.0
                stage_fit = "대상 외 (미등록 예비창업 전용)"
                stage_verdict = "부적합 가능성 높음 (사업자 미등록 예비창업자 전용 공고로 기창업 초기팀 기준 불일치)"
            elif "3~7년" in target or "3년 초과" in target:
                stage_score = 0.08
                stage_fit = "조건부 주의 (업력 3년 초과 확인)"
                stage_verdict = "조건부 주의 (업력 3년 초과 도약기 공고 — 개업연월일 기준 만 3년 경과 여부 확인 필요)"

        elif persona_label == "그 이상 베테랑 팀":
            if ("도약" in target or "3~7년" in target or "3년 초과" in target) and "예비" not in target and "초기" not in target:
                stage_score = 0.35
                stage_fit = "핵심 적격 (창업 3~7년 도약기 전용)"
                stage_verdict = "적합 (업력 3년 초과~7년 이내 도약·스케일업 전용 적격 기준 부합)"
            elif "도약" in target or "3~7년" in target or "7년 이내" in target:
                stage_score = 0.27
                stage_fit = "적격 (창업 7년 이내 포함)"
                stage_verdict = "적합 (업력 7년 이내 대상 공고로 베테랑 팀 지원 가능)"
            elif "예비~도약" in target or "전체" in target:
                stage_score = 0.19
                stage_fit = "지원 가능 (전체 창업자)"
                stage_verdict = "적합 (전체 창업자 대상 공고)"
            elif "예비" in target or "3년 이내" in target:
                stage_score = 0.0
                stage_fit = "대상 외 (예비·3년 이내 전용)"
                stage_verdict = "부적합 가능성 높음 (예비 또는 업력 3년 이내 전용 공고로 3년 초과 베테랑 팀 기준 불일치)"

        # 지역 판정 (최대 0.15)
        if not user_region or user_region == "전국 무관":
            region_score = 0.12
            region_verdict = f"적합 (공고 지역: {doc_region})"
        elif user_region in doc_region:
            region_score = 0.15
            region_verdict = f"적합 (사용자 지역 '{user_region}'과 공고 지역 '{doc_region}' 일치)"
        elif "전국" in doc_region:
            region_score = 0.12
            region_verdict = f"적합 (전국 단위 모집 공고: {doc_region})"
        elif "비수도권" in user_region and any(k in doc_region for k in ["비수도권", "부산", "대전", "대구", "광주", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]):
            region_score = 0.14
            region_verdict = f"적합 (비수도권/로컬 우대 및 지역 부합: {doc_region})"
        else:
            region_score = 0.03
            region_verdict = f"주의 (공고 주관/제한 지역 '{doc_region}' 소재지 요건 또는 협약 내 이전 조건 확인 필요)"

        return {
            "stage_score": stage_score,
            "stage_fit": stage_fit,
            "stage_verdict": stage_verdict,
            "region_score": region_score,
            "region_verdict": region_verdict,
            "criteria_basis": criteria_summary,
        }

    @staticmethod
    def _percentile(sorted_vals: List[float], q: float) -> float:
        if not sorted_vals:
            return 0.0
        pos = (len(sorted_vals) - 1) * q
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return sorted_vals[lo]
        return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)

    @classmethod
    def scale_scores_distribution(
        cls,
        raw_scores_100: List[float],
        top_target_count: int = 4,
    ) -> List[float]:
        """
        [3단계 통계 스케일링 파이프라인]
        1. 20점 단위 지수 도약: X = 2^(R / 20) - 1 (20점 상승 시마다 증가폭 2배 가속)
        2. IQR 이상치 보정(Winsorizing): [Q1 - 1.5*IQR, Q3 + 1.5*IQR] 바깥 극단값 압축 보정
        3. Z-Score + 로지스틱(Sigmoid) 분포 스케일링:
           - 그룹 내 상위 3~4개(top_target_count)만 최상위 구간(0.80 ~ 0.94)에 배치
           - 대다수 중위권 공고는 0.35 ~ 0.78 구간에 고르게 분포, 극단적 저득점(<0.30)도 소수로 억제
        """
        valid_indices = [i for i, r in enumerate(raw_scores_100) if r > 12.0]
        if not valid_indices:
            return [0.0 for _ in raw_scores_100]

        # 1단계: 20점 단위 비선형 지수 도약
        step_up_vals = [
            math.pow(2.0, min(max(raw_scores_100[i], 0.0), 100.0) / 20.0) - 1.0
            for i in valid_indices
        ]

        if len(step_up_vals) <= 2:
            return [
                round(min(max(raw_scores_100[i] / 100.0, 0.20), 0.92), 2)
                if raw_scores_100[i] > 12.0
                else 0.0
                for i in range(len(raw_scores_100))
            ]

        # 2단계: IQR 사분위수 기반 이상치 보정 (Winsorizing)
        sorted_step = sorted(step_up_vals)
        q1 = cls._percentile(sorted_step, 0.25)
        q3 = cls._percentile(sorted_step, 0.75)
        iqr = max(q3 - q1, 0.20)
        low_fence = q1 - 1.5 * iqr
        high_fence = q3 + 1.5 * iqr

        winsorized = []
        for v in step_up_vals:
            if v > high_fence:
                # 이상치의 폭주는 95% 억제하되 미세한 순위 차이는 보존
                winsorized.append(high_fence + (v - high_fence) * 0.05)
            elif v < low_fence:
                winsorized.append(low_fence - (low_fence - v) * 0.05)
            else:
                winsorized.append(v)

        # 3단계: Z-Score 표준화 및 로지스틱(Sigmoid) 스케일링
        mean_w = sum(winsorized) / len(winsorized)
        var_w = sum((w - mean_w) ** 2 for w in winsorized) / len(winsorized)
        std_w = max(math.sqrt(var_w), 1e-4)

        z_scores = [(w - mean_w) / std_w for w in winsorized]
        sorted_z_desc = sorted(z_scores, reverse=True)
        n_valid = len(sorted_z_desc)

        z_med = cls._percentile(sorted(z_scores), 0.50)

        # 상위 top_target_count(기본 4개, 즉 3~4개)가 >= 0.80에 안착하도록 경계 Z값 산출
        if n_valid > top_target_count:
            z_top_border = sorted_z_desc[top_target_count - 1]
            z_next = sorted_z_desc[top_target_count]
            if z_top_border > z_next:
                z_cut = (z_top_border + z_next) / 2.0
            else:
                z_cut = z_top_border + 0.02
        else:
            z_cut = sorted_z_desc[0] + 0.20

        # 로지스틱 곡선(0.20 ~ 0.94)에서 0.80에 도달하는 로짓(Log-odds) 값:
        # (0.80 - 0.20) / (0.94 - 0.20) = 0.60 / 0.74 = 0.8108 -> ln(0.8108 / 0.1892) = 1.4553
        u_target_080 = 1.46
        upper_span = max(z_cut - z_med, 0.25)
        alpha_upper = u_target_080 / upper_span
        alpha_lower = 1.15  # 하위권 완만한 감쇠로 극단적 저득점(<0.30) 비율 최소화

        scaled_map: Dict[int, float] = {}
        for idx_in_valid, orig_idx in enumerate(valid_indices):
            z = z_scores[idx_in_valid]
            if z >= z_med:
                u = alpha_upper * (z - z_med)
            else:
                u = alpha_lower * (z - z_med)

            u_clamped = min(max(u, -4.0), 4.0)
            logistic_val = 1.0 / (1.0 + math.exp(-u_clamped))
            final_val = 0.20 + logistic_val * 0.74  # 범위: 0.20 ~ 0.94
            scaled_map[orig_idx] = round(final_val, 2)

        return [scaled_map.get(i, 0.0) for i in range(len(raw_scores_100))]

    @classmethod
    def stretch_score_contrast(cls, raw_score: float) -> float:
        """단일 점수 호환용 보조 메서드 (배치 스케일링은 scale_scores_distribution 사용)"""
        if raw_score <= 0.12:
            return 0.0
        scaled_list = cls.scale_scores_distribution([raw_score * 100.0], top_target_count=1)
        return scaled_list[0]

    def build_knowledge_graph(self, announcements: List[Dict[str, Any]]) -> Dict[str, int]:
        self.nodes.clear()
        self.edges.clear()
        self.announcements = announcements

        categories = set(
            ["사업화", "기술개발(R&D)", "시설ㆍ공간ㆍ보육", "멘토링ㆍ컨설팅ㆍ교육", "판로ㆍ해외진출"]
            + [a.get("category", "사업화") for a in announcements]
        )
        for cat in sorted(categories):
            cat_id = f"CAT_{cat}"
            self.nodes[cat_id] = {
                "id": cat_id,
                "label": cat,
                "type": "SupportCategory",
                "properties": {"name": cat, "role": "K-Startup 지원사업 분류"},
            }

        for p_name, p_data in self.PERSONA_TAXONOMY.items():
            p_id = p_data["id"]
            self.nodes[p_id] = {
                "id": p_id,
                "label": p_name,
                "type": "Persona",
                "properties": {
                    "name": p_name,
                    "career_range": p_data["career_range"],
                    "description": p_data["description"],
                    "criteria_summary": p_data["criteria_summary"],
                },
            }

            for need in p_data["core_needs"]:
                n_id = need["id"]
                self.nodes[n_id] = {
                    "id": n_id,
                    "label": need["name"],
                    "type": "CoreNeed",
                    "properties": {
                        "name": need["name"],
                        "persona": p_name,
                        "priority_weight": need["weight"],
                    },
                }
                self.edges.append(
                    {
                        "source": p_id,
                        "target": n_id,
                        "relation": "HAS_NEED",
                        "label": f"핵심과제 ({int(need['weight']*100)}%)",
                        "weight": need["weight"],
                    }
                )

                for mapped_cat in need["categories"]:
                    cat_id = f"CAT_{mapped_cat}"
                    if cat_id in self.nodes:
                        self.edges.append(
                            {
                                "source": n_id,
                                "target": cat_id,
                                "relation": "MAPPED_TO_CATEGORY",
                                "label": "지원분야 매핑",
                                "weight": 0.6,
                            }
                        )

        for ann in announcements:
            sn = str(ann.get("pbanc_sn", ""))
            ann_id = f"ANN_{sn}"
            title = ann.get("title", "")
            cat = ann.get("category", "사업화")
            org = ann.get("organization", "창업진흥원")
            target_stage = ann.get("target_stage", "")

            self.nodes[ann_id] = {
                "id": ann_id,
                "label": self._shorten_title(title),
                "full_title": title,
                "type": "Announcement",
                "properties": {
                    "pbanc_sn": sn,
                    "title": title,
                    "category": cat,
                    "organization": org,
                    "target_stage": target_stage,
                    "region": ann.get("region", "전국"),
                    "d_day": ann.get("d_day", "모집중"),
                    "deadline": ann.get("deadline", "상시"),
                    "summary": ann.get("summary", ""),
                    "detail_url": ann.get("detail_url", ""),
                },
            }

            cat_id = f"CAT_{cat}"
            if cat_id in self.nodes:
                self.edges.append(
                    {
                        "source": ann_id,
                        "target": cat_id,
                        "relation": "BELONGS_TO",
                        "label": "소속 분야",
                        "weight": 0.5,
                    }
                )

            org_id = f"ORG_{org}"
            if org_id not in self.nodes:
                self.nodes[org_id] = {
                    "id": org_id,
                    "label": org,
                    "type": "Organization",
                    "properties": {"name": org, "role": "공고 주관/수행기관"},
                }
            self.edges.append(
                {
                    "source": ann_id,
                    "target": org_id,
                    "relation": "HOSTED_BY",
                    "label": "주관기관",
                    "weight": 0.4,
                }
            )

        # [방식 1 적용] 페르소나별 독립 스케일링 (페르소나당 상위 3~4개만 >= 0.80 배정)
        for p_name, p_data in self.PERSONA_TAXONOMY.items():
            raw_assoc_list: List[Dict[str, Any]] = []
            raw_scores_100: List[float] = []

            for ann in announcements:
                assoc_info = self._calculate_persona_announcement_association(p_data, ann)
                raw_assoc_list.append((ann, assoc_info))
                raw_scores_100.append(assoc_info["raw_score_100"])

            scaled_scores = self.scale_scores_distribution(
                raw_scores_100=raw_scores_100,
                top_target_count=4,
            )

            for (ann, assoc_info), final_score in zip(raw_assoc_list, scaled_scores):
                if final_score >= 0.18 and assoc_info["best_need_id"]:
                    sn = str(ann.get("pbanc_sn", ""))
                    ann_id = f"ANN_{sn}"
                    self.edges.append(
                        {
                            "source": assoc_info["best_need_id"],
                            "target": ann_id,
                            "relation": "RESOLVED_BY",
                            "label": f"연관도 {final_score:.2f}",
                            "weight": final_score,
                            "persona": p_name,
                            "best_need_name": assoc_info["best_need_name"],
                            "matched_keywords": assoc_info["matched_keywords"],
                            "stage_fit": assoc_info["stage_fit"],
                            "stage_verdict": assoc_info["stage_verdict"],
                            "criteria_basis": assoc_info["criteria_basis"],
                            "reason": assoc_info["reason"],
                        }
                    )

        if self.neo4j_uri and GraphDatabase is not None:
            self._sync_to_neo4j()

        return {"nodes_count": len(self.nodes), "edges_count": len(self.edges)}

    def _calculate_persona_announcement_association(
        self, p_data: Dict[str, Any], ann: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        100점 만점 정밀 원점수(raw_score_100) 산출:
        - 업력 적격 점수 (최대 35점)
        - 주력 핵심과제 분야 및 제목/요약 키워드 정합성 (최대 55점)
        - 부가 핵심과제 복합 시너지 및 전국/특화 가산점 (최대 10점)
        """
        p_label = p_data["label"]
        eval_res = self.evaluate_stage_and_region(p_label, "전국 무관", ann)
        stage_score_100 = eval_res["stage_score"] * 100.0  # 최대 35.0점

        if stage_score_100 <= 5.0:
            return {
                "raw_score_100": 0.0,
                "best_need_id": None,
                "best_need_name": "",
                "matched_keywords": [],
                "stage_fit": eval_res["stage_fit"],
                "stage_verdict": eval_res["stage_verdict"],
                "criteria_basis": eval_res["criteria_basis"],
                "reason": eval_res["stage_verdict"],
            }

        cat = ann.get("category", "")
        title_lower = ann.get("title", "").lower()
        summary_lower = ann.get("summary", "").lower()
        full_text = ann.get("_search_text") or f"{title_lower} {summary_lower} {cat.lower()}"

        need_evals = []
        for need in p_data["core_needs"]:
            # 지원분야 일치 기본점수 완화로 단순 카테고리 일치만으로 고득점이 되는 현상 방지
            cat_pts = 16.0 if cat in need["categories"] else 3.0

            matched_kw = []
            kw_pts = 0.0
            for kw in need["keywords"]:
                kw_l = kw.lower()
                if kw_l in title_lower:
                    matched_kw.append(kw)
                    kw_pts += 9.5  # 공고 제목에 핵심 키워드 직접 명시 시 높은 가중치
                elif kw_l in full_text:
                    matched_kw.append(kw)
                    kw_pts += 5.5  # 요약문 등에 포함 시 일반 가중치

            kw_pts = min(kw_pts, 39.0)
            weighted_need_pts = (cat_pts + kw_pts) * need["weight"]
            need_evals.append(
                {
                    "need_id": need["id"],
                    "need_name": need["name"],
                    "score": weighted_need_pts,
                    "keywords": matched_kw,
                }
            )

        need_evals.sort(key=lambda x: x["score"], reverse=True)
        best = need_evals[0]
        secondary_synergy = sum(item["score"] for item in need_evals[1:]) * 0.12
        secondary_synergy = min(secondary_synergy, 10.0)

        raw_score_100 = min(stage_score_100 + best["score"] + secondary_synergy, 100.0)

        reason = (
            f"[{eval_res['stage_fit']}] '{best['need_name']}' 과제 연결 | "
            f"적격근거({eval_res['criteria_basis']}) | "
            f"일치 키워드({', '.join(best['keywords']) if best['keywords'] else '문맥 매칭'})"
        )

        return {
            "raw_score_100": raw_score_100,
            "best_need_id": best["need_id"],
            "best_need_name": best["need_name"],
            "matched_keywords": best["keywords"],
            "stage_fit": eval_res["stage_fit"],
            "stage_verdict": eval_res["stage_verdict"],
            "criteria_basis": eval_res["criteria_basis"],
            "reason": reason,
        }

    def query_persona_subgraph(
        self,
        persona_name: str,
        selected_need_name: str = "전체",
        min_score: float = 0.25,
        include_org_nodes: bool = True,
    ) -> Dict[str, Any]:
        target_personas = (
            list(self.PERSONA_TAXONOMY.keys())
            if persona_name == "전체 페르소나 비교"
            else [persona_name]
        )
        persona_ids = {
            self.PERSONA_TAXONOMY[p]["id"]
            for p in target_personas
            if p in self.PERSONA_TAXONOMY
        }

        active_node_ids = set(persona_ids)
        vis_edges: List[Dict[str, Any]] = []
        ranked_announcements: List[Dict[str, Any]] = []

        allowed_need_ids = set()
        for edge in self.edges:
            if edge["relation"] == "HAS_NEED" and edge["source"] in persona_ids:
                need_node = self.nodes.get(edge["target"], {})
                if selected_need_name != "전체" and need_node.get("label") != selected_need_name:
                    continue
                allowed_need_ids.add(edge["target"])
                active_node_ids.add(edge["target"])
                vis_edges.append(edge)

        matched_ann_ids = set()
        ann_max_score: Dict[str, float] = {}

        for edge in self.edges:
            if (
                edge["relation"] == "RESOLVED_BY"
                and edge["source"] in allowed_need_ids
                and edge["weight"] >= min_score
            ):
                ann_id = edge["target"]
                matched_ann_ids.add(ann_id)
                active_node_ids.add(ann_id)
                vis_edges.append(edge)

                if edge["weight"] > ann_max_score.get(ann_id, 0.0):
                    ann_max_score[ann_id] = edge["weight"]

                ann_props = self.nodes.get(ann_id, {}).get("properties", {})
                ranked_announcements.append(
                    {
                        "persona": edge.get("persona", ""),
                        "core_need": edge.get("best_need_name", ""),
                        "pbanc_sn": ann_props.get("pbanc_sn", ""),
                        "title": ann_props.get("title", ""),
                        "category": ann_props.get("category", ""),
                        "organization": ann_props.get("organization", ""),
                        "target_stage": ann_props.get("target_stage", ""),
                        "stage_fit": edge.get("stage_fit", ""),
                        "stage_verdict": edge.get("stage_verdict", ""),
                        "criteria_basis": edge.get("criteria_basis", ""),
                        "d_day": ann_props.get("d_day", ""),
                        "deadline": ann_props.get("deadline", ""),
                        "association_score": edge["weight"],
                        "matched_keywords": ", ".join(edge.get("matched_keywords", [])) or "분야 매칭",
                        "reason": edge.get("reason", ""),
                        "detail_url": ann_props.get("detail_url", ""),
                    }
                )

        active_cat_ids = set()
        for edge in self.edges:
            if edge["relation"] == "BELONGS_TO" and edge["source"] in matched_ann_ids:
                active_cat_ids.add(edge["target"])
                active_node_ids.add(edge["target"])
                vis_edges.append(edge)

        for edge in self.edges:
            if (
                edge["relation"] == "MAPPED_TO_CATEGORY"
                and edge["source"] in allowed_need_ids
                and edge["target"] in active_cat_ids
            ):
                vis_edges.append(edge)

        if include_org_nodes:
            for edge in self.edges:
                if edge["relation"] == "HOSTED_BY" and edge["source"] in matched_ann_ids:
                    active_node_ids.add(edge["target"])
                    vis_edges.append(edge)

        vis_nodes = []
        for nid in active_node_ids:
            if nid in self.nodes:
                node_copy = dict(self.nodes[nid])
                if node_copy["type"] == "Announcement":
                    node_copy["max_score"] = ann_max_score.get(nid, 0.5)
                vis_nodes.append(node_copy)

        ranked_announcements.sort(key=lambda x: x["association_score"], reverse=True)

        return {
            "nodes": vis_nodes,
            "edges": vis_edges,
            "ranked_announcements": ranked_announcements,
            "cypher_query": self.generate_cypher_query(persona_name, min_score),
        }

    def generate_cypher_query(self, persona_name: str, min_score: float) -> str:
        p_filter = "" if persona_name == "전체 페르소나 비교" else f"{{name: '{persona_name}'}}"
        return (
            f"// Neo4j Cypher: 페르소나 기반 다중 홉(Multi-Hop) 공고 연관도 탐색 쿼리\n"
            f"MATCH (p:Persona {p_filter})-[r1:HAS_NEED]->(n:CoreNeed)-[r2:RESOLVED_BY]->(a:Announcement)\n"
            f"WHERE r2.weight >= {min_score}\n"
            f"OPTIONAL MATCH (a)-[:BELONGS_TO]->(c:SupportCategory)\n"
            f"OPTIONAL MATCH (a)-[:HOSTED_BY]->(o:Organization)\n"
            f"RETURN p.name AS persona, n.name AS core_need, c.name AS category,\n"
            f"       a.pbanc_sn AS pbanc_sn, a.title AS title, r2.weight AS association_score,\n"
            f"       o.name AS organization, a.d_day AS d_day\n"
            f"ORDER BY association_score DESC;"
        )

    def _sync_to_neo4j(self) -> None:
        try:
            driver = GraphDatabase.driver(
                self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password)
            )
            with driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")
                for node in self.nodes.values():
                    label = node["type"]
                    props = dict(node.get("properties", {}))
                    props["id"] = node["id"]
                    props["label"] = node["label"]
                    session.run(
                        f"MERGE (n:{label} {{id: $id}}) SET n += $props",
                        id=node["id"],
                        props=props,
                    )
                for edge in self.edges:
                    rel = edge["relation"]
                    session.run(
                        f"MATCH (a {{id: $src}}), (b {{id: $dst}}) "
                        f"MERGE (a)-[r:{rel}]->(b) SET r.weight = $w, r.label = $lbl",
                        src=edge["source"],
                        dst=edge["target"],
                        w=edge.get("weight", 0.5),
                        lbl=edge.get("label", ""),
                    )
            driver.close()
            self.neo4j_synced = True
        except Exception:
            self.neo4j_synced = False

    @staticmethod
    def _shorten_title(title: str, max_len: int = 22) -> str:
        clean = title.replace("[모집중]", "").strip()
        return clean if len(clean) <= max_len else clean[:max_len] + "..."

    @staticmethod
    def render_interactive_graph_html(
        nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]
    ) -> str:
        color_palette = {
            "Persona": {
                "bg": "#DC2626",
                "border": "#7F1D1D",
                "font": "#FFFFFF",
                "shape": "box",
                "col_x": -520,
            },
            "CoreNeed": {
                "bg": "#F59E0B",
                "border": "#92400E",
                "font": "#111827",
                "shape": "box",
                "col_x": -190,
            },
            "Announcement": {
                "bg": "#059669",
                "border": "#064E3B",
                "font": "#FFFFFF",
                "shape": "box",
                "col_x": 190,
            },
            "SupportCategory": {
                "bg": "#7C3AED",
                "border": "#4C1D95",
                "font": "#FFFFFF",
                "shape": "ellipse",
                "col_x": 540,
            },
            "Organization": {
                "bg": "#334155",
                "border": "#0F172A",
                "font": "#FFFFFF",
                "shape": "box",
                "col_x": 540,
            },
        }

        grouped_nodes: Dict[str, List[Dict[str, Any]]] = {
            "Persona": [],
            "CoreNeed": [],
            "Announcement": [],
            "RightColumn": [],
        }

        for n in nodes:
            ntype = n.get("type", "Announcement")
            if ntype in ("SupportCategory", "Organization"):
                grouped_nodes["RightColumn"].append(n)
            elif ntype in grouped_nodes:
                grouped_nodes[ntype].append(n)
            else:
                grouped_nodes["Announcement"].append(n)

        grouped_nodes["Announcement"].sort(
            key=lambda x: x.get("max_score", 0.0), reverse=True
        )

        vis_nodes = []
        for group_key, group_list in grouped_nodes.items():
            count = len(group_list)
            spacing_y = 105 if group_key != "RightColumn" else 80
            start_y = -((count - 1) * spacing_y) / 2.0

            for idx, n in enumerate(group_list):
                ntype = n.get("type", "Announcement")
                style = color_palette.get(ntype, color_palette["Announcement"])
                props = n.get("properties", {})
                pos_x = style["col_x"]
                pos_y = start_y + idx * spacing_y

                max_score = float(n.get("max_score", 0.5))
                if ntype == "Announcement":
                    font_size = 15 if max_score >= 0.80 else (13 if max_score >= 0.50 else 11)
                    margin_val = 14 if max_score >= 0.80 else (10 if max_score >= 0.50 else 7)
                    border_width = 3 if max_score >= 0.80 else 2
                    display_label = f"[{max_score:.2f}] {n['label']}"
                elif ntype == "Persona":
                    font_size = 16
                    margin_val = 14
                    border_width = 3
                    display_label = n["label"]
                else:
                    font_size = 13
                    margin_val = 10
                    border_width = 2
                    display_label = n["label"]

                vis_nodes.append(
                    {
                        "id": n["id"],
                        "label": display_label,
                        "x": pos_x,
                        "y": pos_y,
                        "fixed": {"x": False, "y": False},
                        "shape": style["shape"],
                        "color": {
                            "background": style["bg"],
                            "border": style["border"],
                            "highlight": {"background": "#111827", "border": "#F59E0B"},
                        },
                        "font": {
                            "color": style["font"],
                            "size": font_size,
                            "face": "Pretendard, -apple-system, BlinkMacSystemFont, sans-serif",
                            "bold": True,
                        },
                        "margin": margin_val,
                        "borderWidth": border_width,
                        "shadow": {"enabled": True, "size": 5, "x": 2, "y": 2},
                        "raw_properties": props,
                        "node_type": ntype,
                    }
                )

        vis_edges = []
        for idx, e in enumerate(edges):
            rel = e.get("relation", "")
            if rel == "MAPPED_TO_CATEGORY":
                continue

            weight = float(e.get("weight", 0.5))
            dashes = False

            if rel == "HAS_NEED":
                edge_color = "#D97706"
                width = 3.0
                font_color = "#92400E"
            elif rel == "RESOLVED_BY":
                if weight >= 0.80:
                    edge_color = "#DC2626"
                    width = 5.5
                    font_color = "#991B1B"
                elif weight >= 0.50:
                    edge_color = "#2563EB"
                    width = 3.0
                    font_color = "#1E40AF"
                else:
                    edge_color = "#94A3B8"
                    width = 1.5
                    dashes = True
                    font_color = "#64748B"
            elif rel == "BELONGS_TO":
                edge_color = "#8B5CF6"
                dashes = True
                width = 1.8
                font_color = "#5B21B6"
            else:
                edge_color = "#64748B"
                dashes = True
                width = 1.5
                font_color = "#334155"

            vis_edges.append(
                {
                    "id": f"e_{idx}",
                    "from": e["source"],
                    "to": e["target"],
                    "label": e.get("label", rel),
                    "width": width,
                    "dashes": dashes,
                    "arrows": {"to": {"enabled": True, "scaleFactor": 0.8}},
                    "color": {"color": edge_color, "highlight": "#111827"},
                    "font": {
                        "size": 11,
                        "color": font_color,
                        "align": "horizontal",
                        "background": "rgba(255,255,255,0.9)",
                    },
                    "smooth": {"type": "cubicBezier", "forceDirection": "horizontal", "roundness": 0.35},
                }
            )

        nodes_json = json.dumps(vis_nodes, ensure_ascii=False)
        edges_json = json.dumps(vis_edges, ensure_ascii=False)

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8" />
            <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    background: #F8FAFC;
                }}
                #graph-wrapper {{
                    position: relative;
                    width: 100%;
                    height: 620px;
                    border: 2px solid #CBD5E1;
                    border-radius: 8px;
                    background: #FFFFFF;
                    overflow: hidden;
                }}
                #network-canvas {{
                    width: 100%;
                    height: 100%;
                }}
                .legend-box {{
                    position: absolute;
                    top: 12px;
                    left: 12px;
                    background: rgba(255, 255, 255, 0.96);
                    border: 1px solid #94A3B8;
                    border-radius: 6px;
                    padding: 10px 14px;
                    font-size: 12px;
                    color: #0F172A;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
                }}
                .legend-title {{
                    font-weight: 700;
                    margin-bottom: 6px;
                    font-size: 12px;
                    color: #0F172A;
                    border-bottom: 1px solid #E2E8F0;
                    padding-bottom: 4px;
                }}
                .legend-item {{
                    display: flex;
                    align-items: center;
                    margin-bottom: 5px;
                    font-weight: 600;
                }}
                .dot {{
                    width: 14px;
                    height: 14px;
                    border-radius: 3px;
                    margin-right: 8px;
                    display: inline-block;
                }}
                .line-sample {{
                    width: 22px;
                    margin-right: 8px;
                    display: inline-block;
                }}
                #node-inspector {{
                    position: absolute;
                    bottom: 12px;
                    right: 12px;
                    width: 350px;
                    max-height: 220px;
                    overflow-y: auto;
                    background: rgba(255, 255, 255, 0.98);
                    border: 2px solid #64748B;
                    border-radius: 6px;
                    padding: 12px;
                    font-size: 12px;
                    color: #0F172A;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.12);
                }}
                .inspector-header {{
                    font-weight: 700;
                    font-size: 13px;
                    color: #0F172A;
                    border-bottom: 1px solid #CBD5E1;
                    padding-bottom: 6px;
                    margin-bottom: 8px;
                }}
                .prop-row {{
                    margin-bottom: 4px;
                    line-height: 1.45;
                }}
                .prop-key {{
                    font-weight: 700;
                    color: #334155;
                }}
            </style>
        </head>
        <body>
            <div id="graph-wrapper">
                <div id="network-canvas"></div>
                <div class="legend-box">
                    <div class="legend-title">노드 구분 (고대비 색상)</div>
                    <div class="legend-item"><span class="dot" style="background:#DC2626; border:1px solid #7F1D1D;"></span>1단계: 페르소나 (창업 단계)</div>
                    <div class="legend-item"><span class="dot" style="background:#F59E0B; border:1px solid #92400E;"></span>2단계: 핵심 성장 과제 (Core Need)</div>
                    <div class="legend-item"><span class="dot" style="background:#059669; border:1px solid #064E3B;"></span>3단계: 모집중 공고 ([점수] 공고명)</div>
                    <div class="legend-item"><span class="dot" style="background:#7C3AED; border:1px solid #4C1D95; border-radius:50%;"></span>4단계: 지원분야 (사업유형)</div>
                    <div class="legend-item"><span class="dot" style="background:#334155; border:1px solid #0F172A;"></span>4단계: 주관기관</div>
                    <div class="legend-title" style="margin-top:8px;">연관도 점수 구간별 연결선</div>
                    <div class="legend-item"><span class="line-sample" style="border-top:5px solid #DC2626;"></span>최상위 연관 (0.80 이상 · 상위 3~4건)</div>
                    <div class="legend-item"><span class="line-sample" style="border-top:3px solid #2563EB;"></span>중상위 연관 (0.50 ~ 0.79)</div>
                    <div class="legend-item"><span class="line-sample" style="border-top:2px dashed #94A3B8;"></span>낮은 연관 (0.50 미만)</div>
                </div>
                <div id="node-inspector">
                    <div class="inspector-header">노드 상세 정보 (클릭 시 고정 조회)</div>
                    <div id="inspector-content">그래프는 움직이지 않도록 고정되어 있습니다. 노드를 클릭하면 상세 속성이 표시됩니다.</div>
                </div>
            </div>
            <script>
                const nodes = new vis.DataSet({nodes_json});
                const edges = new vis.DataSet({edges_json});
                const container = document.getElementById('network-canvas');
                const data = {{ nodes: nodes, edges: edges }};
                const options = {{
                    physics: {{
                        enabled: false
                    }},
                    interaction: {{
                        hover: true,
                        dragNodes: true,
                        dragView: true,
                        zoomView: true,
                        navigationButtons: true
                    }}
                }};
                const network = new vis.Network(container, data, options);
                network.fit({{ animation: false }});

                network.on("click", function(params) {{
                    const inspector = document.getElementById("inspector-content");
                    if (params.nodes.length > 0) {{
                        const nodeId = params.nodes[0];
                        const nodeData = nodes.get(nodeId);
                        const props = nodeData.raw_properties || {{}};
                        let html = `<div class="prop-row"><span class="prop-key">구분:</span> ${{nodeData.node_type}}</div>`;
                        for (const [k, v] of Object.entries(props)) {{
                            if (k === "detail_url" && v) {{
                                html += `<div class="prop-row"><span class="prop-key">원문링크:</span> <a href="${{v}}" target="_blank">공고 상세페이지 이동</a></div>`;
                            }} else if (v) {{
                                html += `<div class="prop-row"><span class="prop-key">${{k}}:</span> ${{v}}</div>`;
                            }}
                        }}
                        inspector.innerHTML = html;
                    }}
                }});
            </script>
        </body>
        </html>
        """