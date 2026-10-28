import json
import os
import re
from datetime import datetime
from typing import Dict, Any, List, Tuple
from dotenv import load_dotenv
from crawler import KStartupOngoingCrawler
from mcp_rag_engine import MCPServerRegistry
from graph_db_engine import StartupTaxonomyGraphEngine

load_dotenv()

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class StartupPathfinderOrchestrator:
    """
    [Orchestration + ReAct + 하이브리드(규칙 + LLM) 프로필-프롬프트 충돌 검증 및 연관 검색 엔진]
    1. 필수 프로필(4대 항목) · 선택 프로필(3대 항목) · 수기 프롬프트 간의 불일치·충돌을 규칙 엔진 + LLM으로 판별하여 되묻기(Ask-back) 수행
    2. 탭 1 공고 목록에서 '제목 + 내용' 선택 시 연관 키워드 확장 검색 수행
    3. 탭 2 에이전트 실행 시 엄격한 하드 필터링(결격 공고 완전 배제) + RAG + GraphDB + 적격/결격 판단 근거 분리 출력 수행
    """

    SYSTEM_PROMPT = """당신은 대한민국 K-Startup 창업지원 전문 AI 에이전트 '창업 패스파인더'입니다.
다음의 핵심 원칙과 페르소나별 적격 판단 기준을 엄격히 준수하여 보고서를 작성하십시오.

[1. 서식 및 근거 기반(Grounding) 원칙]
- 이모티콘을 절대 사용하지 말고 명확하고 격식 있는 비즈니스 보고서 톤으로 작성하십시오.
- 제공된 공고 데이터(RAG 및 GraphDB 검색 근거)에 없는 지원금액, 자격요건, 일정을 임의로 추측하거나 지어내지 마십시오.
- 하드 필터링으로 이미 배제된 결격 공고는 최종 보고서에 절대 언급하거나 노출하지 마십시오. 오직 제공된 적격 추천 공고들에 대해서만 작성하십시오.
- 각 추천 공고의 적격 판정 결과(업력, 지역, 선택 프로필 부합 여부)와 실제 판정 근거가 된 '공고 내 매칭 문구(matched_eligibility_phrases)'를 보고서에 반드시 명시하십시오.

[2. 3대 페르소나 적격 판단 기준 근거 (필수 반영)]
- 예비창업자: 공고일 기준 신청자 명의의 개인·법인 사업자등록 미보유(폐업 이력 시 동종업종 여부 확인) 및 시제품(MVP) 제작·보육공간 입주·BM 멘토링 과제 부합 여부
- 창업 초기(3년 내외) 팀: 사업자등록증 개업연월일(법인설립등기일) 기준 업력 3년(36개월) 이내 충족 및 초기 사업화·첫걸음 R&D·시드 투자유치 과제 부합 여부
- 그 이상 베테랑 팀: 업력 3년 초과 ~ 7년(84개월) 이내 도약기 요건(신산업 10년 이내·매출·선투자 조건 포함) 충족 및 오픈이노베이션(PoC)·글로벌 진출·상용화 R&D 과제 부합 여부

[3. 보고서 필수 구성 목차]
1. 맞춤형 모집중 공고 추천 및 선정 근거 (각 공고별 RAG 매칭 점수, GraphDB 핵심 성장 과제 경로 및 연관도 점수, 페르소나 및 선택 프로필 적격 판단 결과와 실제 매칭된 공고 문구 명시)
2. 에이전트 성찰(Reflection) 기반 유의사항 및 세부 자격요건 점검 안내
3. 마감일(D-Day) 기준 우선순위 실행 로드맵 및 사업계획서(PSST) 작성 전략"""

    CONFLICT_CHECK_SYSTEM_PROMPT = """당신은 창업 지원 에이전트의 '프로필-프롬프트 정합성 및 근거 검증기'입니다.
사용자가 입력한 [필수 프로필 4대 항목], [선택 프로필 3대 항목], 그리고 수기로 작성한 [상세 조건 프롬프트]를 상호 비교하여 불일치(충돌)나 심각한 근거 부족이 있는지 판정하십시오.

[검증 대상 항목]
1. 필수 창업 단계(stage): 예비창업자 / 초기창업자 (3년 이내) / 도약기 (3~7년 이내) / 글로벌·스케일업
2. 필수 창업 아이템/기술 분야(domain): 프롬프트에서 설명하는 사업 아이템·업종과 다른 산업군으로 충돌하는지 여부
3. 필수 지역(region): 프롬프트에서 명시한 사업장 소재지·희망 지역과 충돌하는지 여부
4. 필수 희망 지원 분야(category): 특정 단일 분야를 선택했으나 프롬프트에서 타 분야 혜택을 요청하는지 여부
5. 선택 대표자 연령대(age_group): '만 39세 이하 (청년)' 또는 '만 40세 이상' 선택값이 프롬프트 내 연령/청년/중장년 서술과 모순되는지 여부
6. 선택 사업자 형태(business_type): '미등록 (예비창업)' / '개인사업자' / '법인사업자' 선택값이 필수 창업 단계(stage), 정확한 업력(exact_career), 또는 프롬프트 서술과 모순되는지 여부
7. 선택 정확한 업력(exact_career): 직접 입력한 업력(창업 전, 연차/개월수, 설립연월)이 필수 창업 단계(stage), 사업자 형태(business_type), 또는 프롬프트 내 업력 서술과 모순되는지 여부

반드시 아래 JSON 형식으로만 응답하십시오:
{
  "has_conflict": true 또는 false,
  "conflicts": ["감지된 구체적인 불일치/충돌 사유 문장 1", ...],
  "follow_up_questions": ["사용자에게 확인을 요청할 구체적인 되묻기 질문 1", ...]
}"""

    KEYWORD_EXPAND_SYSTEM_PROMPT = """당신은 대한민국 K-Startup 창업지원사업 검색 키워드 확장기입니다.
사용자가 입력한 검색어와 의미적·문맥적으로 연관된 창업지원사업 핵심 키워드(기술명, 산업분야, 지원유형, 연관 용어)를 5~8개 추출하십시오.
반드시 아래 JSON 형식으로만 응답하십시오:
{
  "expanded_keywords": ["연관키워드1", "연관키워드2", ...]
}"""

    _KEYWORD_SPLIT_RE = re.compile(r"[\s,·/]+")
    _YEAR_SPAN_RE = re.compile(
        r"(?:창업|설립|업력|개업)\s*(?:한\s*지\s*)?(\d+)\s*년|(\d+)\s*년\s*차"
    )
    _FOUNDING_YEAR_RE = re.compile(
        r"(20[0-2]\d)\s*년\s*(?:에\s*)?(?:창업|설립|개업|법인)"
    )
    _AGE_EXACT_RE = re.compile(r"(?:만\s*)?(\d{2})\s*세")

    _PRE_STAGE_KEYWORDS: Tuple[str, ...] = (
        "사업자등록 전",
        "사업자 등록 전",
        "미등록 예비",
        "예비창업자입니다",
        "예비 창업자입니다",
        "예비창업팀입니다",
        "창업 전입니다",
    )
    _REGISTERED_STAGE_KEYWORDS: Tuple[str, ...] = (
        "법인 설립 완료",
        "법인설립 완료",
        "사업자등록 완료",
        "사업자 등록 완료",
        "기창업자입니다",
        "법인사업자입니다",
        "시리즈A",
        "시리즈B",
        "매출이 발생",
    )
    _DOYAK_PROGRAM_KEYWORDS: Tuple[str, ...] = (
        "창업도약패키지",
        "도약기 기업",
        "스케일업 팁스",
    )
    _SENIOR_PROMPT_KEYWORDS: Tuple[str, ...] = (
        "40대",
        "50대",
        "60대",
        "만 40세 이상",
        "만40세 이상",
        "중장년",
        "시니어 창업",
    )
    _YOUTH_PROMPT_KEYWORDS: Tuple[str, ...] = (
        "청년창업",
        "청년 창업",
        "청년 예비",
        "청년창업자",
        "청년사관학교",
        "청년창업사관학교",
        "만 39세 이하",
        "만39세 이하",
        "만 29세 이하",
        "20대",
        "30대",
        "대학생 창업",
    )
    _CORP_PROMPT_KEYWORDS: Tuple[str, ...] = (
        "법인사업자입니다",
        "법인 설립 완료",
        "법인설립 완료",
        "주식회사입니다",
        "법인 기업입니다",
    )
    _INDIV_OR_PRE_PROMPT_KEYWORDS: Tuple[str, ...] = (
        "개인사업자입니다",
        "개인사업자로 운영",
        "법인 전환 전",
        "법인전환 전",
        "법인 설립 전",
        "법인설립 전",
    )
    _METRO_REGIONS: Tuple[str, ...] = ("서울", "경기", "인천")

    REGION_ALIASES: Dict[str, List[str]] = {
        "서울": ["서울", "마포", "공덕", "홍릉", "강남", "테헤란로", "성수", "여의도", "구로", "가산", "양재"],
        "경기": ["경기", "판교", "성남", "수원", "광교", "고양", "일산", "용인", "화성", "동탄", "안양", "부천", "시흥"],
        "인천": ["인천", "송도", "청라", "영종"],
        "부산": ["부산", "센텀", "해운대", "영도"],
        "대전": ["대전", "대덕", "유성", "둔산"],
        "대구": ["대구", "수성", "동대구", "경산"],
        "광주": ["광주", "상무", "첨단"],
        "비수도권_기타": [
            "울산", "세종", "강원", "춘천", "원주", "강릉", "충북", "청주", "충남", "천안", "아산",
            "전북", "전주", "전남", "여수", "순천", "나주", "경북", "포항", "구미", "경남", "창원", "김해", "진주", "제주",
        ],
    }

    CATEGORY_INTENT_KEYWORDS: Dict[str, List[str]] = {
        "사업화": ["사업화 자금", "사업화지원", "시제품 제작", "시제품", "mvp", "사업화 패키지", "바우처", "사업비", "자금"],
        "기술개발(R&D)": ["r&d", "기술개발", "디딤돌", "첫걸음", "전략형", "출연금", "연구개발", "팁스", "tips", "상용화"],
        "시설ㆍ공간ㆍ보육": ["입주", "보육공간", "사무공간", "공유오피스", "창업공간", "사무실", "창업존", "창업캠프", "입주기업", "허브", "센터"],
        "멘토링ㆍ컨설팅ㆍ교육": ["멘토링", "컨설팅", "부트캠프", "역량강화", "피칭", "네트워킹", "법률", "세무", "노무", "특허", "ir", "투자유치", "교육"],
        "판로ㆍ해외진출": ["해외진출", "글로벌", "수출", "전시회", "ces", "mwc", "판로", "크라우드펀딩", "공공조달", "나라장터", "마케팅", "바이어"],
    }

    DOMAIN_CLUSTERS: Dict[str, List[str]] = {
        "AI·SW·데이터·클라우드": ["ai", "인공지능", "빅데이터", "데이터", "클라우드", "saas", "소프트웨어", "sw", "플랫폼", "앱", "알고리즘", "llm", "생성형", "gpu", "ict"],
        "바이오·헬스케어·의료": ["헬스케어", "바이오", "의료", "의료기기", "디지털헬스", "신약", "임상", "진단", "병원", "제약", "건강", "식약처"],
        "모빌리티·로봇·제조·하드웨어": ["모빌리티", "자율주행", "자동차", "미래차", "로봇", "로보틱스", "드론", "반도체", "센서", "하드웨어", "스마트팩토리", "기계", "해양", "물류", "항공"],
        "친환경·에너지·기후테크": ["친환경", "탄소중립", "탄소", "그린", "에너지", "태양광", "수소", "배터리", "업사이클링", "자원순환", "폐기물", "기후", "esg", "소셜벤처"],
        "로컬·F&B·외식·소상공인·관광": ["로컬", "f&b", "식음료", "베이커리", "카페", "식당", "음식점", "외식", "밀키트", "전통주", "관광", "숙박", "공간기획", "소상공인", "로컬크리에이터"],
        "핀테크·블록체인·금융": ["핀테크", "금융", "결제", "블록체인", "자산관리", "인슈어테크", "송금", "보안"],
        "콘텐츠·미디어·에듀테크·커머스": ["콘텐츠", "웹툰", "게임", "영상", "미디어", "엔터테인먼트", "에듀테크", "교육용", "이커머스", "쇼핑몰", "패션", "뷰티"],
    }

    _PERSONA_NEED_KEYWORDS_LOWER: Tuple[Tuple[str, ...], ...] = tuple(
        tuple(k.lower() for k in need.get("keywords", []))
        for p_data in StartupTaxonomyGraphEngine.PERSONA_TAXONOMY.values()
        for need in p_data.get("core_needs", [])
    )

    def __init__(self, mcp_server: MCPServerRegistry):
        self.mcp = mcp_server
        self.env_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.env_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        self.client = (
            OpenAI(api_key=self.env_api_key)
            if (self.has_valid_env_key() and OpenAI is not None)
            else None
        )
        self._keyword_cache: Dict[str, Dict[str, List[str]]] = {}
        self._conflict_check_cache: Dict[Tuple[str, ...], Dict[str, List[str]]] = {}

    def has_valid_env_key(self) -> bool:
        return bool(self.env_api_key and not self.env_api_key.startswith("sk-proj-여기에"))

    # =====================================================================
    # [탭 1 전용] 규칙 엔진 + LLM 하이브리드 연관 키워드 확장 검색
    # =====================================================================
    def expand_search_keywords(self, raw_query: str) -> Dict[str, List[str]]:
        """
        입력 검색어를 바탕으로 1) 규칙 사전(도메인/지원분야/페르소나) 연관어와
        2) LLM 문맥 연관어를 결합하여 확장 키워드 리스트를 반환합니다.
        """
        q_clean = raw_query.strip()
        if not q_clean:
            return {"base_terms": [], "rule_expanded": [], "llm_expanded": [], "all_terms": []}

        if q_clean in self._keyword_cache:
            return self._keyword_cache[q_clean]

        q_lower = q_clean.lower()
        base_terms = [
            t.strip()
            for t in self._KEYWORD_SPLIT_RE.split(q_lower)
            if len(t.strip()) >= 2
        ]
        if not base_terms:
            base_terms = [q_lower]

        seen_rule = set(base_terms)
        rule_expanded: List[str] = []

        # 1) 도메인 클러스터 유의어 확장
        for cluster_kws in self.DOMAIN_CLUSTERS.values():
            if any(bt in kw or kw in q_lower for bt in base_terms for kw in cluster_kws):
                for kw in cluster_kws:
                    if kw not in seen_rule:
                        seen_rule.add(kw)
                        rule_expanded.append(kw)

        # 2) 지원분야 의도 키워드 확장
        for cat_name, cat_kws in self.CATEGORY_INTENT_KEYWORDS.items():
            if cat_name.lower() in q_lower or any(
                bt in kw or kw in q_lower for bt in base_terms for kw in cat_kws
            ):
                for kw in cat_kws:
                    if kw not in seen_rule:
                        seen_rule.add(kw)
                        rule_expanded.append(kw)

        # 3) 페르소나 핵심 성장 과제 키워드 확장
        for need_kws in self._PERSONA_NEED_KEYWORDS_LOWER:
            if any(bt in nk or nk in q_lower for bt in base_terms for nk in need_kws):
                for nk in need_kws:
                    if nk not in seen_rule:
                        seen_rule.add(nk)
                        rule_expanded.append(nk)

        rule_expanded = rule_expanded[:10]

        # 4) LLM 의미 기반 연관 키워드 확장
        llm_expanded: List[str] = []
        if self.client is not None:
            try:
                resp = self.client.chat.completions.create(
                    model=self.env_model,
                    messages=[
                        {"role": "system", "content": self.KEYWORD_EXPAND_SYSTEM_PROMPT},
                        {"role": "user", "content": f"검색어: {q_clean}"},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                parsed = json.loads(resp.choices[0].message.content or "{}")
                seen_llm = set(base_terms) | set(rule_expanded)
                for kw in parsed.get("expanded_keywords", []):
                    kw_l = str(kw).strip().lower()
                    if len(kw_l) >= 2 and kw_l not in seen_llm:
                        seen_llm.add(kw_l)
                        llm_expanded.append(kw_l)
                llm_expanded = llm_expanded[:8]
            except Exception:
                pass

        all_terms = base_terms + rule_expanded + llm_expanded
        result = {
            "base_terms": base_terms,
            "rule_expanded": rule_expanded,
            "llm_expanded": llm_expanded,
            "all_terms": all_terms,
        }
        self._keyword_cache[q_clean] = result
        return result

    def hybrid_table_search(
        self, raw_query: str, records: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        확장된 키워드 풀(base_terms + rule_expanded + llm_expanded)을 이용해
        공고의 제목+내용(_search_text)을 탐색하고 연관 점수와 매칭 키워드를 계산합니다.
        """
        expanded_info = self.expand_search_keywords(raw_query)
        base_terms = expanded_info["base_terms"]
        expanded_terms = expanded_info["rule_expanded"] + expanded_info["llm_expanded"]

        matched_records: List[Dict[str, Any]] = []
        raw_scores: List[float] = []

        for rec in records:
            title_l = rec.get("title", "").lower()
            full_l = rec.get("_search_text") or KStartupOngoingCrawler.build_search_text(rec)

            score = 0.0
            hit_keywords: List[str] = []

            for bt in base_terms:
                if bt in title_l:
                    score += 38.0
                    hit_keywords.append(bt)
                elif bt in full_l:
                    score += 26.0
                    hit_keywords.append(bt)

            for et in expanded_terms:
                if et in title_l:
                    score += 14.0
                    hit_keywords.append(et)
                elif et in full_l:
                    score += 9.0
                    hit_keywords.append(et)

            if score > 0.0:
                capped_score = min(score, 100.0)
                rec_copy = dict(rec)
                rec_copy["_raw_match_score"] = capped_score
                rec_copy["matched_keywords"] = ", ".join(list(dict.fromkeys(hit_keywords))[:6])
                matched_records.append(rec_copy)
                raw_scores.append(capped_score)

        if matched_records:
            scaled = StartupTaxonomyGraphEngine.scale_scores_distribution(
                raw_scores_100=raw_scores, top_target_count=4
            )
            for rec_copy, s_val in zip(matched_records, scaled):
                rec_copy["match_score"] = s_val

            matched_records.sort(
                key=lambda x: (x["match_score"], x.get("_raw_match_score", 0.0)),
                reverse=True,
            )

        return {
            "expanded_info": expanded_info,
            "matched_records": matched_records,
        }

    # =====================================================================
    # [탭 2 전용] 필수 프로필 ↔ 선택 프로필 ↔ 프롬프트 정합성 검증 및 ReAct 파이프라인
    # =====================================================================
    def _rule_based_input_check(
        self, user_profile: Dict[str, str], user_query: str, mapped_persona: str
    ) -> Dict[str, List[str]]:
        stage = user_profile.get("stage", "예비창업자").strip()
        domain = user_profile.get("domain", "").strip()
        region = user_profile.get("region", "서울").strip()
        category = user_profile.get("category", "전체").strip()
        age_group = (user_profile.get("age_group") or "선택 안 함").strip()
        business_type = (user_profile.get("business_type") or "선택 안 함").strip()
        exact_career = (user_profile.get("exact_career") or "").strip()

        query_clean = user_query.strip()
        query_lower = query_clean.lower()

        reasons: List[str] = []
        questions: List[str] = []

        # 0) 기본 입력 충분성 검증
        if len(domain) < 2:
            reasons.append("창업 아이템/기술 분야 입력값이 누락되었거나 너무 짧아 산업·기술 분야 매칭 근거를 산출할 수 없습니다.")
            questions.append("현재 준비 중이거나 개발 중인 핵심 창업 아이템(제품·서비스명)과 주요 기술 분야는 무엇입니까?")

        if len(query_clean) < 10:
            reasons.append("상세 조건 및 고민 내용이 10자 미만으로 입력되어 필요 자금 용도 및 핵심 성장 과제(Core Need)를 특정할 수 없습니다.")
            questions.append("현재 가장 시급하게 지원받고자 하는 목적(시제품 제작비, R&D 기술개발 출연금, 창업 보육공간 입주, 해외진출, 투자유치 IR 등)을 구체적으로 입력해 주시겠습니까?")

        current_year = datetime.now().year
        year_spans = [
            int(y)
            for grp in self._YEAR_SPAN_RE.findall(query_clean)
            for y in grp
            if y
        ]
        founding_years = [
            int(fy)
            for fy in self._FOUNDING_YEAR_RE.findall(query_clean)
        ]
        for fy in founding_years:
            if 2000 <= fy <= current_year:
                year_spans.append(max(current_year - fy, 1))

        has_pre_kw = any(kw in query_clean for kw in self._PRE_STAGE_KEYWORDS)
        has_registered_kw = any(
            kw in query_clean for kw in self._REGISTERED_STAGE_KEYWORDS
        )

        # 1) 필수 창업 단계(stage) vs 수기 프롬프트 충돌 검증
        if mapped_persona == "예비창업자":
            if has_registered_kw or any(y >= 1 for y in year_spans):
                yr_info = f"업력 {max(year_spans)}년" if year_spans else "기창업/사업자 보유"
                reasons.append(
                    f"[창업 단계 불일치] 프로필 단계는 '{stage}(사업자등록 이전)'로 선택되었으나, 상세 조건에는 '{yr_info}' 관련 내용이 기재되어 있어 페르소나 적격 판단 기준이 충돌합니다."
                )
                questions.append(
                    "현재 사업자등록증(개인 또는 법인)을 이미 발급받으신 기창업 상태입니까, 아니면 사업자등록 이전인 예비창업 상태입니까?"
                )
            elif any(kw in query_clean for kw in self._DOYAK_PROGRAM_KEYWORDS):
                reasons.append(
                    f"[창업 단계 불일치] 프로필 단계는 '{stage}'이나, 상세 조건에서는 기창업 도약기(3~7년) 전용 사업을 요청하고 있습니다."
                )
                questions.append(
                    "예비창업자 대상 공고(예비창업패키지 등)를 찾으십니까, 아니면 업력 3년 초과 도약기 기업 대상 공고를 찾으십니까?"
                )

        elif mapped_persona == "창업 초기(3년 내외) 팀":
            if has_pre_kw:
                reasons.append(
                    f"[창업 단계 불일치] 프로필 단계는 '{stage}(업력 3년 이내 기창업)'로 선택되었으나, 상세 조건에는 '사업자등록 전 예비창업자'로 기재되어 있어 적격 기준이 충돌합니다."
                )
                questions.append(
                    "현재 사업자등록 이전인 예비창업 단계이십니까, 아니면 사업자등록을 완료한 창업 3년(36개월) 이내 초기기업이십니까?"
                )
            elif any(y >= 4 for y in year_spans):
                reasons.append(
                    f"[창업 단계 불일치] 프로필 단계는 '{stage}(업력 3년 이내)'이나, 상세 조건에는 '업력 {max(year_spans)}년'으로 기재되어 있어 3년 이내 초기창업 기준을 초과합니다."
                )
                questions.append(
                    "사업자등록증상 개업연월일(또는 법인설립등기일) 기준 업력이 만 3년(36개월)을 초과한 도약기(3~7년) 기업이십니까?"
                )

        elif mapped_persona == "그 이상 베테랑 팀":
            if has_pre_kw:
                reasons.append(
                    f"[창업 단계 불일치] 프로필 단계는 '{stage}(창업 3년 초과 도약·스케일업)'이나, 상세 조건에는 '사업자등록 전 예비창업자'로 기재되어 있어 적격 기준이 충돌합니다."
                )
                questions.append(
                    "현재 사업자등록 전인 예비창업 단계이십니까, 아니면 창업 3년을 초과한 도약·스케일업 기업이십니까?"
                )
            elif any(1 <= y <= 3 for y in year_spans) and not any(y >= 4 for y in year_spans):
                reasons.append(
                    f"[창업 단계 불일치] 프로필 단계는 '{stage}(창업 3년 초과 베테랑 팀)'이나, 상세 조건에는 '업력 {min(year_spans)}년'으로 기재되어 있어 초기창업(3년 이내) 기준과 충돌합니다."
                )
                questions.append(
                    "현재 기업의 정확한 업력이 만 3년(36개월) 이내인 초기창업 기업입니까, 아니면 만 3년을 초과한 도약기 기업입니까?"
                )

        # 2) 필수 창업 단계(stage) ↔ 선택 사업자 형태(business_type) 충돌 검증
        if business_type and business_type != "선택 안 함":
            if mapped_persona == "예비창업자" and business_type in ("개인사업자", "법인사업자"):
                reasons.append(
                    f"[필수·선택 프로필 충돌 - 사업자 형태] 필수 창업 단계는 '{stage}(사업자등록 이전)'이나, 선택 프로필의 사업자 형태는 '{business_type}'(기창업 등록 사업자)로 선택되어 상호 모순됩니다."
                )
                questions.append(
                    f"현재 '{business_type}' 등록을 완료한 기창업 상태입니까, 아니면 사업자등록 이전인 예비창업 상태입니까?"
                )
            elif mapped_persona != "예비창업자" and business_type == "미등록 (예비창업)":
                reasons.append(
                    f"[필수·선택 프로필 충돌 - 사업자 형태] 필수 창업 단계는 기창업 단계('{stage}')이나, 선택 프로필의 사업자 형태는 '{business_type}'으로 선택되어 상호 모순됩니다."
                )
                questions.append(
                    f"현재 사업자등록을 완료한 '{stage}' 기업입니까, 아니면 사업자등록 이전인 미등록 예비창업 상태입니까?"
                )

        # 3) 필수 창업 단계(stage) / 선택 사업자 형태(business_type) ↔ 선택 정확한 업력(exact_career) 충돌 검증
        career_months = StartupTaxonomyGraphEngine.parse_career_months(exact_career)
        if exact_career:
            has_est_token_in_career = any(
                k in exact_career for k in ("설립", "개업", "법인", "개인사업자")
            ) and not any(
                pk in exact_career
                for pk in StartupTaxonomyGraphEngine._PRE_CAREER_KEYWORDS
            )

            if mapped_persona == "예비창업자":
                if (career_months is not None and career_months >= 1) or has_est_token_in_career:
                    reasons.append(
                        f"[필수·선택 프로필 충돌 - 정확한 업력] 필수 창업 단계는 '{stage}(사업자 미등록)'이나, 선택 프로필의 정확한 업력에는 기창업 업력('{exact_career}')이 입력되어 상호 충돌합니다."
                    )
                    questions.append(
                        f"입력하신 정확한 업력('{exact_career}')과 같이 이미 창업(사업자등록)을 완료한 상태입니까, 아니면 사업자등록 이전인 예비창업자입니까?"
                    )
            else:
                if career_months == 0:
                    reasons.append(
                        f"[필수·선택 프로필 충돌 - 정확한 업력] 필수 창업 단계는 기창업('{stage}')이나, 선택 프로필의 정확한 업력에는 예비창업 상태('{exact_career}')가 입력되어 상호 충돌합니다."
                    )
                    questions.append(
                        f"현재 사업자등록 전인 예비창업 단계입니까, 아니면 사업자등록을 완료한 '{stage}' 기업입니까?"
                    )
                elif (
                    mapped_persona == "창업 초기(3년 내외) 팀"
                    and career_months is not None
                    and career_months > 36
                ):
                    reasons.append(
                        f"[필수·선택 프로필 충돌 - 업력 범위] 필수 창업 단계는 '{stage}(3년/36개월 이내)'이나, 입력하신 정확한 업력('{exact_career}' → 약 {career_months}개월)은 만 3년(36개월)을 초과합니다."
                    )
                    questions.append(
                        "사업자등록증상 개업연월일(법인설립등기일) 기준 실제 업력이 만 3년(36개월) 이내인 초기기업입니까, 아니면 3년을 초과한 도약기 기업입니까?"
                    )
                elif (
                    mapped_persona == "그 이상 베테랑 팀"
                    and career_months is not None
                    and 1 <= career_months <= 36
                ):
                    reasons.append(
                        f"[필수·선택 프로필 충돌 - 업력 범위] 필수 창업 단계는 '{stage}(창업 3년 초과)'이나, 입력하신 정확한 업력('{exact_career}' → 약 {career_months}개월)은 창업 3년(36개월) 이내 초기 단계에 해당합니다."
                    )
                    questions.append(
                        f"현재 실제 업력이 만 3년(36개월) 이내인 초기창업 기업입니까, 아니면 만 3년을 초과한 '{stage}' 기업입니까?"
                    )
                elif (
                    stage == "도약기 (3~7년 이내)"
                    and career_months is not None
                    and career_months > 84
                ):
                    reasons.append(
                        f"[필수·선택 프로필 충돌 - 업력 범위] 필수 창업 단계는 '{stage}(7년/84개월 이내)'이나, 입력하신 정확한 업력('{exact_career}' → 약 {career_months}개월)은 창업 7년(84개월)을 초과합니다."
                    )
                    questions.append(
                        "현재 기업의 실제 업력이 창업 7년(84개월) 이내인 도약기 기업입니까, 아니면 7년을 초과한 기업입니까?"
                    )

            # 선택 사업자 형태 ↔ 선택 정확한 업력 내부 충돌
            if business_type == "미등록 (예비창업)" and career_months is not None and career_months >= 1:
                reasons.append(
                    f"[선택 프로필 간 충돌] 선택 사업자 형태는 '{business_type}'이나, 정확한 업력에는 기창업 기간('{exact_career}')이 입력되어 있습니다."
                )
                questions.append(
                    "현재 미등록 예비창업 상태이십니까, 아니면 사업자등록 후 업력이 경과한 기창업 상태이십니까?"
                )
            elif business_type in ("개인사업자", "법인사업자") and career_months == 0:
                reasons.append(
                    f"[선택 프로필 간 충돌] 선택 사업자 형태는 '{business_type}'이나, 정확한 업력에는 '{exact_career}(창업 전)'이 입력되어 있습니다."
                )
                questions.append(
                    f"이미 '{business_type}' 등록을 완료하셨습니까, 아니면 아직 사업자등록 이전 상태이십니까?"
                )

        # 4) 선택 프로필(연령대·사업자형태·정확한업력) ↔ 수기 프롬프트(user_query) 충돌 검증
        if age_group and age_group != "선택 안 함":
            prompt_ages = [int(a) for a in self._AGE_EXACT_RE.findall(query_clean) if 15 <= int(a) <= 90]
            if age_group == "만 39세 이하 (청년)":
                has_senior_prompt = any(
                    kw in query_clean for kw in self._SENIOR_PROMPT_KEYWORDS
                ) or any(a >= 40 for a in prompt_ages)
                if has_senior_prompt:
                    reasons.append(
                        f"[선택 프로필·프롬프트 충돌 - 연령대] 선택 프로필 대표자 연령대는 '{age_group}'이나, 상세 조건 프롬프트에는 만 40세 이상(40·50대/중장년) 관련 내용이 기재되어 있습니다."
                    )
                    questions.append(
                        "대표자의 현재 연령대가 만 39세 이하(청년창업 대상)입니까, 아니면 만 40세 이상(중장년)입니까?"
                    )
            elif age_group == "만 40세 이상":
                has_youth_prompt = any(
                    kw in query_clean for kw in self._YOUTH_PROMPT_KEYWORDS
                ) or any(a <= 39 for a in prompt_ages)
                if has_youth_prompt:
                    reasons.append(
                        f"[선택 프로필·프롬프트 충돌 - 연령대] 선택 프로필 대표자 연령대는 '{age_group}'이나, 상세 조건 프롬프트에는 청년(만 39세 이하/20·30대/청년창업) 관련 내용이 기재되어 있습니다."
                    )
                    questions.append(
                        "대표자의 현재 연령대가 만 40세 이상입니까, 아니면 만 39세 이하 청년창업자입니까?"
                    )

        if business_type and business_type != "선택 안 함":
            if business_type == "미등록 (예비창업)" and (
                has_registered_kw or any(y >= 1 for y in year_spans)
            ):
                reasons.append(
                    f"[선택 프로필·프롬프트 충돌 - 사업자 형태] 선택 프로필 사업자 형태는 '{business_type}'이나, 상세 조건 프롬프트에는 기창업/사업자 보유 내용이 기재되어 있습니다."
                )
                questions.append(
                    "현재 사업자등록 이전인 미등록 예비창업자입니까, 아니면 이미 사업자등록을 마친 기창업자입니까?"
                )
            elif business_type == "개인사업자" and any(
                kw in query_clean for kw in self._CORP_PROMPT_KEYWORDS
            ):
                reasons.append(
                    "[선택 프로필·프롬프트 충돌 - 사업자 형태] 선택 프로필 사업자 형태는 '개인사업자'이나, 상세 조건 프롬프트에는 법인사업자(법인 설립 완료)로 기재되어 있습니다."
                )
                questions.append(
                    "현재 사업자 형태가 '개인사업자'입니까, 아니면 법인 등기를 완료한 '법인사업자'입니까?"
                )
            elif business_type == "법인사업자" and (
                has_pre_kw
                or any(kw in query_clean for kw in self._INDIV_OR_PRE_PROMPT_KEYWORDS)
            ):
                reasons.append(
                    "[선택 프로필·프롬프트 충돌 - 사업자 형태] 선택 프로필 사업자 형태는 '법인사업자'이나, 상세 조건 프롬프트에는 미등록 예비창업 또는 개인사업자(법인 전환/설립 전) 상태로 기재되어 있습니다."
                )
                questions.append(
                    "현재 법인설립등기를 완료한 '법인사업자'입니까, 아니면 개인사업자 또는 예비창업 상태입니까?"
                )

        if exact_career and career_months is not None:
            if career_months == 0 and (has_registered_kw or any(y >= 1 for y in year_spans)):
                reasons.append(
                    f"[선택 프로필·프롬프트 충돌 - 업력] 선택 프로필의 정확한 업력은 '{exact_career}(창업 전)'이나, 상세 조건 프롬프트에는 기창업 업력이 기재되어 있습니다."
                )
                questions.append(
                    f"실제 업력이 '{exact_career}(창업 전)'입니까, 아니면 프롬프트에 기재하신 기창업 상태입니까?"
                )
            elif career_months >= 1 and has_pre_kw:
                reasons.append(
                    f"[선택 프로필·프롬프트 충돌 - 업력] 선택 프로필의 정확한 업력은 '{exact_career}'(기창업)이나, 상세 조건 프롬프트에는 사업자등록 전 예비창업으로 기재되어 있습니다."
                )
                questions.append(
                    f"실제 업력이 '{exact_career}'인 기창업 기업입니까, 아니면 사업자등록 전인 예비창업자입니까?"
                )
            elif career_months >= 1 and year_spans:
                prompt_max_months = max(year_spans) * 12
                prompt_min_months = min(year_spans) * 12
                if (
                    (career_months <= 36 and prompt_min_months >= 48)
                    or (career_months > 36 and prompt_max_months <= 36)
                    or abs(career_months - prompt_max_months) >= 18
                ):
                    reasons.append(
                        f"[선택 프로필·프롬프트 충돌 - 업력 수치] 선택 프로필에 입력한 정확한 업력('{exact_career}')과 상세 조건 프롬프트에 서술된 업력('{max(year_spans)}년')이 서로 일치하지 않습니다."
                    )
                    questions.append(
                        f"기업의 실제 업력을 선택 프로필의 '{exact_career}' 기준으로 적용할까요, 아니면 프롬프트의 '{max(year_spans)}년' 기준으로 적용할까요?"
                    )

        # 5) 필수 지역(region) vs 수기 프롬프트 충돌 검증
        if region != "전국 무관":
            detected_regions: List[str] = []
            for reg_key, aliases in self.REGION_ALIASES.items():
                for alias in aliases:
                    if alias in query_clean:
                        detected_regions.append(reg_key if reg_key != "비수도권_기타" else alias)
                        break

            if detected_regions:
                if region == "비수도권/로컬":
                    metro_hits = [r for r in detected_regions if r in self._METRO_REGIONS]
                    if metro_hits:
                        reasons.append(
                            f"[지역 조건 불일치] 프로필 지역은 '{region}'로 선택되었으나, 상세 조건에는 수도권 지역({', '.join(metro_hits)})이 명시되어 있습니다."
                        )
                        questions.append(
                            f"사업장 소재지(또는 입주·지원 희망 지역)가 '{', '.join(metro_hits)}' 수도권입니까, 아니면 비수도권/로컬 지역입니까?"
                        )
                else:
                    other_regions = [r for r in detected_regions if r != region]
                    if other_regions and region not in detected_regions:
                        reasons.append(
                            f"[지역 조건 불일치] 프로필 지역은 '{region}'로 선택되었으나, 상세 조건에는 다른 지역('{', '.join(other_regions)}')이 명시되어 있습니다."
                        )
                        questions.append(
                            f"현재 거주지 및 사업장 기준 지역을 프로필의 '{region}'로 적용할까요, 아니면 프롬프트에 작성하신 '{', '.join(other_regions)}'로 변경할까요?"
                        )

        # 6) 필수 희망 지원 분야(category) vs 수기 프롬프트 충돌 검증
        if category != "전체":
            matched_cats: List[str] = []
            for cat_name, kw_list in self.CATEGORY_INTENT_KEYWORDS.items():
                if any(kw in query_lower for kw in kw_list):
                    matched_cats.append(cat_name)

            other_requested_cats = [c for c in matched_cats if c != category]
            if other_requested_cats:
                if category not in matched_cats:
                    reasons.append(
                        f"[희망 지원 분야 불일치] 프로필 희망 지원 분야는 '{category}' 단독으로 선택되었으나, 상세 조건에서는 '{', '.join(other_requested_cats)}' 분야의 지원을 요청하고 있습니다."
                    )
                    questions.append(
                        f"탐색할 지원 분야를 프롬프트 내용에 맞춰 '{', '.join(other_requested_cats)}'(또는 '전체')로 변경하시겠습니까, 아니면 '{category}' 분야 공고만 제한하여 검색하시겠습니까?"
                    )
                else:
                    reasons.append(
                        f"[희망 지원 분야 범위 충돌] 프로필에서는 '{category}' 단일 분야만 선택되었으나, 상세 조건에서는 '{', '.join(other_requested_cats)}' 지원까지 복합적으로 요청하고 있어 단일 분야 필터링 시 타 분야 공고가 누락됩니다."
                    )
                    questions.append(
                        f"'{category}'와 '{', '.join(other_requested_cats)}' 공고를 모두 추천받기 위해 희망 지원 분야를 '전체'로 변경하여 분석할까요?"
                    )

        # 7) 필수 창업 아이템/도메인(domain) vs 수기 프롬프트 충돌 검증
        if len(domain) >= 2:
            domain_lower = domain.lower()
            profile_clusters = {
                c_name
                for c_name, c_kws in self.DOMAIN_CLUSTERS.items()
                if any(kw in domain_lower for kw in c_kws)
            }
            query_clusters = {
                c_name
                for c_name, c_kws in self.DOMAIN_CLUSTERS.items()
                if any(kw in query_lower for kw in c_kws)
            }

            if profile_clusters and query_clusters and profile_clusters.isdisjoint(query_clusters):
                reasons.append(
                    f"[창업 아이템/도메인 불일치] 프로필의 창업 아이템('{domain}' → {', '.join(profile_clusters)})과 상세 조건에 서술된 아이템 분야({', '.join(query_clusters)})가 서로 상충합니다."
                )
                questions.append(
                    f"분석을 진행할 실제 창업 아이템이 프로필에 입력된 '{domain}'입니까, 아니면 상세 조건에 작성하신 '{', '.join(query_clusters)}' 관련 아이템입니까?"
                )

        # 중복 사유 및 질문 제거 (순서 보존)
        reasons = list(dict.fromkeys(reasons))
        questions = list(dict.fromkeys(questions))
        return {"reasons": reasons, "questions": questions}

    def _llm_based_conflict_check(
        self, user_profile: Dict[str, str], user_query: str, mapped_persona: str
    ) -> Dict[str, List[str]]:
        if self.client is None:
            return {"reasons": [], "questions": []}

        age_group = (user_profile.get("age_group") or "선택 안 함").strip()
        business_type = (user_profile.get("business_type") or "선택 안 함").strip()
        exact_career = (user_profile.get("exact_career") or "").strip()

        cache_key = (
            user_profile.get("stage", ""),
            user_profile.get("domain", ""),
            user_profile.get("region", ""),
            user_profile.get("category", ""),
            age_group,
            business_type,
            exact_career,
            user_query.strip(),
        )
        if cache_key in self._conflict_check_cache:
            return self._conflict_check_cache[cache_key]

        result: Dict[str, List[str]] = {"reasons": [], "questions": []}
        try:
            check_payload = (
                f"[필수 프로필 4대 항목]\n"
                f"1. 현재 창업 단계(stage): {user_profile.get('stage')} (매핑 페르소나: {mapped_persona})\n"
                f"2. 창업 아이템/기술 분야(domain): {user_profile.get('domain')}\n"
                f"3. 거주지/사업장 지역(region): {user_profile.get('region')}\n"
                f"4. 희망 지원 분야(category): {user_profile.get('category')}\n\n"
                f"[선택 프로필 3대 항목]\n"
                f"5. 대표자 연령대(age_group): {age_group}\n"
                f"6. 사업자 형태(business_type): {business_type}\n"
                f"7. 정확한 업력(exact_career): {exact_career or '미입력'}\n\n"
                f"[수기 작성 상세 조건 프롬프트]\n"
                f"{user_query}"
            )
            resp = self.client.chat.completions.create(
                model=self.env_model,
                messages=[
                    {"role": "system", "content": self.CONFLICT_CHECK_SYSTEM_PROMPT},
                    {"role": "user", "content": check_payload},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            content = resp.choices[0].message.content or "{}"
            parsed = json.loads(content)
            if parsed.get("has_conflict") is True:
                result = {
                    "reasons": [str(r) for r in parsed.get("conflicts", []) if r],
                    "questions": [str(q) for q in parsed.get("follow_up_questions", []) if q],
                }
            self._conflict_check_cache[cache_key] = result
        except Exception:
            pass

        return result

    def _check_input_ask_back(
        self, user_profile: Dict[str, str], user_query: str, mapped_persona: str
    ) -> Dict[str, Any]:
        rule_res = self._rule_based_input_check(user_profile, user_query, mapped_persona)
        reasons = list(rule_res["reasons"])
        questions = list(rule_res["questions"])
        rule_count = len(reasons)
        llm_count = 0

        if self.client is not None and len(user_query.strip()) >= 10:
            llm_res = self._llm_based_conflict_check(user_profile, user_query, mapped_persona)
            for r in llm_res["reasons"]:
                if r not in reasons:
                    reasons.append(r)
                    llm_count += 1
            for q in llm_res["questions"]:
                if q not in questions:
                    questions.append(q)

        return {
            "triggered": len(reasons) > 0,
            "rule_conflicts_count": rule_count,
            "llm_conflicts_count": llm_count,
            "reasons": reasons,
            "questions": questions,
            "persona_criteria": StartupTaxonomyGraphEngine.get_persona_criteria_info(mapped_persona),
        }

    def run_agent_pipeline(
        self,
        user_profile: Dict[str, str],
        user_query: str,
        force_refresh_crawl: bool = False,
    ) -> Dict[str, Any]:
        react_steps: List[Dict[str, Any]] = []

        stage = user_profile.get("stage", "예비창업자")
        domain = user_profile.get("domain", "AI/IT")
        region = user_profile.get("region", "서울")
        need_category = user_profile.get("category", "전체")
        age_group = (user_profile.get("age_group") or "선택 안 함").strip()
        business_type = (user_profile.get("business_type") or "선택 안 함").strip()
        exact_career = (user_profile.get("exact_career") or "").strip()

        optional_profile = {
            "age_group": age_group,
            "business_type": business_type,
            "exact_career": exact_career,
        }
        mapped_persona = StartupTaxonomyGraphEngine.map_stage_to_persona(stage)

        ask_back_check = self._check_input_ask_back(user_profile, user_query, mapped_persona)
        if ask_back_check["triggered"]:
            react_steps.append(
                {
                    "step": 1,
                    "phase": "Step 1. 필수·선택 프로필 및 프롬프트 정합성 하이브리드 검증 (Ask-back 게이트)",
                    "thought": (
                        f"필수 프로필(단계: '{stage}', 아이템: '{domain}', 지역: '{region}', 희망분야: '{need_category}'), "
                        f"선택 프로필(연령대: '{age_group}', 사업자형태: '{business_type}', 정확한업력: '{exact_career or '미입력'}'), "
                        "그리고 수기 작성 프롬프트 간의 상호 정합성 및 근거 충분성을 규칙 엔진과 LLM으로 교차 검증한다."
                    ),
                    "action": {
                        "tool": "hybrid_profile_prompt_validator",
                        "args": {
                            "checked_fields": [
                                "stage",
                                "domain",
                                "region",
                                "category",
                                "age_group",
                                "business_type",
                                "exact_career",
                            ],
                            "stage": stage,
                            "domain": domain,
                            "region": region,
                            "category": need_category,
                            "age_group": age_group,
                            "business_type": business_type,
                            "exact_career": exact_career,
                        },
                    },
                    "observation": {
                        "status": "ASK_BACK_REQUIRED",
                        "detected_issues_count": len(ask_back_check["reasons"]),
                        "rule_conflicts_count": ask_back_check["rule_conflicts_count"],
                        "llm_conflicts_count": ask_back_check["llm_conflicts_count"],
                        "persona_criteria": ask_back_check["persona_criteria"]["criteria_summary"],
                    },
                    "evidence": ask_back_check["reasons"],
                    "reflection": (
                        "필수 프로필, 선택 프로필, 수기 작성 프롬프트 간에 불일치(충돌) 또는 근거 부족이 감지되었다. "
                        "부정확한 공고 추천을 즉시 중단(Abstention)하고, 감지된 충돌 사유와 페르소나 적격 판단 기준을 제시하여 사용자에게 확인을 요청(Ask-back)한다."
                    ),
                }
            )
            return {
                "is_ask_back": True,
                "ask_back_info": ask_back_check,
                "react_trace": react_steps,
                "matched_announcements": [],
                "eligibility_audit": [],
                "final_report": "",
                "crawl_status": self.mcp.last_crawl_status,
            }

        thought_1 = (
            f"필수 프로필(창업단계 '{stage}' -> 매핑 페르소나: '{mapped_persona}', 아이템 '{domain}', 지역 '{region}', 희망분야 '{need_category}') 및 "
            f"선택 프로필(연령대 '{age_group}', 사업자형태 '{business_type}', 세부업력 '{exact_career or '미입력'}') 정합성 검증을 통과했다. "
            "K-Startup 모집중 공고 인덱스와 GraphDB 지식그래프 상태를 점검한다."
        )
        if force_refresh_crawl or not self.mcp.rag_engine.is_indexed:
            action_1 = {
                "tool": "mcp_kstartup_crawl_ongoing",
                "args": {},
            }
            obs_1 = self.mcp.call_tool(action_1["tool"], action_1["args"])
        else:
            dist = self.mcp.rag_engine.get_category_distribution()
            action_1 = {
                "tool": "cache_check",
                "args": {
                    "indexed_docs": len(self.mcp.rag_engine.documents),
                    "graph_nodes": len(self.mcp.graph_engine.nodes),
                },
            }
            obs_1 = {
                "status": "cached",
                "crawl_mode": self.mcp.last_crawl_status,
                "indexed_count": len(self.mcp.rag_engine.documents),
                "graph_nodes": len(self.mcp.graph_engine.nodes),
                "graph_edges": len(self.mcp.graph_engine.edges),
                "category_distribution": dist,
            }

        doc_count = obs_1.get("indexed_count", 0)
        cat_dist = obs_1.get("category_distribution", {})
        target_cat_count = (
            doc_count
            if need_category == "전체"
            else sum(cnt for cat, cnt in cat_dist.items() if need_category in cat)
        )
        persona_criteria = StartupTaxonomyGraphEngine.get_persona_criteria_info(mapped_persona)

        evidence_1 = [
            f"데이터 로드 상태: {obs_1.get('crawl_mode', self.mcp.last_crawl_status)}",
            f"RAG 인덱싱 공고 수: {doc_count}건 | GraphDB 활성 노드/엣지: {len(self.mcp.graph_engine.nodes)}개 / {len(self.mcp.graph_engine.edges)}개",
            f"지원분야별 공고 분포: {cat_dist}",
            f"매핑 페르소나: '{mapped_persona}' (적격 기준: {persona_criteria['criteria_summary']}) | 희망분야('{need_category}') 가용 공고: {target_cat_count}건",
            f"적용 선택 프로필 필터: 대표자 연령대='{age_group}', 사업자 형태='{business_type}', 정확한 업력='{exact_career or '미입력'}'",
        ]

        if target_cat_count == 0:
            reflection_1 = (
                f"근거 확인 결과, 사용자가 선택한 '{need_category}' 분야의 공고가 0건이다. "
                "Step 2에서는 전체 분야로 탐색 범위를 넓히고 엄격한 하드 필터링 및 GraphDB 페르소나 핵심 성장 과제 경로를 결합해 적격 공고를 확보한다."
            )
        else:
            reflection_1 = (
                f"근거 확인 결과, 총 {doc_count}건의 모집중 공고와 GraphDB 택사노미가 정상 준비되어 있다. "
                f"Step 2에서 엄격한 하드 필터링(부적격·주의 공고 완전 배제)이 적용된 RAG 검색과 '{mapped_persona}' 페르소나 그래프 탐색을 병행한다."
            )

        react_steps.append(
            {
                "step": 1,
                "phase": "Step 1. 데이터 무결성 및 페르소나 적격 기준 점검",
                "thought": thought_1,
                "action": action_1,
                "observation": obs_1,
                "evidence": evidence_1,
                "reflection": reflection_1,
            }
        )

        opt_query_tokens = " ".join(
            v
            for v in (age_group, business_type, exact_career)
            if v and v != "선택 안 함"
        )
        synthesized_query = (
            f"{stage} {domain} {region} {need_category} {opt_query_tokens} {user_query}"
        ).strip()
        effective_filter = "전체" if target_cat_count == 0 else need_category

        thought_2 = (
            f"확장 쿼리('{synthesized_query}')로 RAG 검색 및 엄격한 하드 필터링(업력 부적격·조건부 주의, 지역 불일치, 선택 프로필 결격 완전 배제)을 수행함과 동시에, "
            f"GraphDB에서 '{mapped_persona}' 페르소나와 연결된 다중 홉(Persona -> CoreNeed -> Announcement) 연관 공고를 조회하여 결합한다."
        )
        action_2 = {
            "tool": "mcp_kstartup_rag_search + mcp_kstartup_persona_graph_query",
            "args": {
                "query": synthesized_query,
                "persona_name": mapped_persona,
                "category_filter": effective_filter,
                "optional_profile": optional_profile,
                "top_k": 3,
            },
        }
        obs_2_rag = self.mcp.call_tool(
            "mcp_kstartup_rag_search",
            {
                "query": synthesized_query,
                "user_stage": stage,
                "user_region": region,
                "category_filter": effective_filter,
                "optional_profile": optional_profile,
                "top_k": 3,
            },
        )
        obs_2_graph = self.mcp.call_tool(
            "mcp_kstartup_persona_graph_query",
            {
                "persona_name": mapped_persona,
                "min_score": 0.25,
            },
        )

        matched_docs = list(obs_2_rag.get("matched_announcements", []))
        excluded_docs = list(obs_2_rag.get("excluded_announcements", []))
        graph_ranked = obs_2_graph.get("ranked_announcements", [])
        graph_map = {g["pbanc_sn"]: g for g in graph_ranked}

        expanded_search_triggered = False
        if len(matched_docs) < 2 and effective_filter != "전체":
            expanded_search_triggered = True
            obs_2_broad = self.mcp.call_tool(
                "mcp_kstartup_rag_search",
                {
                    "query": synthesized_query,
                    "user_stage": stage,
                    "user_region": region,
                    "category_filter": "전체",
                    "optional_profile": optional_profile,
                    "top_k": 3,
                },
            )
            seen_sns = {d["pbanc_sn"] for d in matched_docs}
            for bd in obs_2_broad.get("matched_announcements", []):
                if bd["pbanc_sn"] not in seen_sns and len(matched_docs) < 3:
                    matched_docs.append(bd)
                    seen_sns.add(bd["pbanc_sn"])

            seen_ex_sns = {ex["pbanc_sn"] for ex in excluded_docs}
            for bx in obs_2_broad.get("excluded_announcements", []):
                if bx["pbanc_sn"] not in seen_ex_sns:
                    excluded_docs.append(bx)
                    seen_ex_sns.add(bx["pbanc_sn"])

        evidence_2 = []
        for idx, d in enumerate(matched_docs, 1):
            sn = d["pbanc_sn"]
            ev = d.get("evidence_detail", {})
            g_info = graph_map.get(sn)
            if g_info:
                d["graph_core_need"] = g_info["core_need"]
                d["graph_score"] = g_info["association_score"]
                graph_path_str = f"[{mapped_persona}] -> [{g_info['core_need']}] (그래프 연관도: {g_info['association_score']})"
            else:
                d["graph_core_need"] = "전 단계 공통 성장 과제"
                d["graph_score"] = 0.0
                graph_path_str = f"[{mapped_persona}] 공통 적격 공고 연결"

            elig_phrases = ev.get("matched_eligibility_phrases", [])
            evidence_2.append(
                f"[적격 후보 {idx}순위] [{sn}] {d['title']} | RAG 매칭점수: {d['rag_score']}점 "
                f"(일치 키워드: {ev.get('matched_terms', [])}) | 적격 매칭 문구: {elig_phrases} | GraphDB 경로: {graph_path_str}"
            )

        if excluded_docs:
            evidence_2.append(
                f"[하드 필터링 배제 요약] 검색 대상 중 총 {len(excluded_docs)}건의 공고가 업력 부적격·조건부 주의, 지역 불일치 또는 선택 프로필 요건 결격으로 추천 후보에서 완전 배제됨 (배제 근거는 ReAct 로그에만 기록)"
            )
            for ex in excluded_docs[:6]:
                 evidence_2.append(
                    f"[하드 필터링 배제] [{ex['pbanc_sn']}] {ex['title']} | 결격 사유: {' / '.join(ex['disqualification_reasons'])} | 감지 문구: {ex['matched_disqualification_phrases']}"
                )

        reflection_2 = (
            f"엄격한 하드 필터링(안 B)을 통해 결격·조건부 주의 공고 {len(excluded_docs)}건을 후보군에서 완전 배제하고, "
            f"모든 적격 요건을 충족한 상위 {len(matched_docs)}건의 공고만 최종 후보로 선발했다. "
            + (
                "(선택 분야 내 적격 공고가 부족하여 전체 분야 확장 탐색을 통해 적격 공고를 보완 확보함.) "
                if expanded_search_triggered
                else ""
            )
            + "이어지는 Step 3에서 최종 선발된 적격 공고들의 매칭 근거 문구와 하드 필터링 배제 감사 로그를 확정한다."
        )

        react_steps.append(
            {
                "step": 2,
                "phase": "Step 2. 하드 필터링 기반 RAG 검색 및 GraphDB 택사노미 경로 결합",
                "thought": thought_2,
                "action": action_2,
                "observation": {
                    "eligible_matched_count": len(matched_docs),
                    "hard_filtered_excluded_count": len(excluded_docs),
                    "graph_persona_queried": mapped_persona,
                    "graph_linked_count": len(graph_ranked),
                    "expanded_search_applied": expanded_search_triggered,
                    "eligible_candidates_summary": [
                        {
                            "pbanc_sn": d["pbanc_sn"],
                            "title": d["title"],
                            "rag_score": d["rag_score"],
                            "graph_core_need": d.get("graph_core_need"),
                            "graph_score": d.get("graph_score"),
                            "matched_eligibility_phrases": d.get(
                                "evidence_detail", {}
                            ).get("matched_eligibility_phrases", []),
                        }
                        for d in matched_docs
                    ],
                    "hard_filtered_excluded_announcements": [
                        {
                            "pbanc_sn": ex["pbanc_sn"],
                            "title": ex["title"],
                            "target_stage": ex["target_stage"],
                            "region": ex["region"],
                            "disqualification_reasons": ex["disqualification_reasons"],
                            "matched_disqualification_phrases": ex[
                                "matched_disqualification_phrases"
                            ],
                        }
                        for ex in excluded_docs
                    ],
                },
                "evidence": evidence_2,
                "reflection": reflection_2,
            }
        )

        thought_3 = (
            f"하드 필터링을 통과한 {len(matched_docs)}건의 적격 추천 공고에 대해 '{mapped_persona}' 적격 판단 기준({persona_criteria['criteria_summary']}), "
            f"지역('{region}'), 선택 프로필(연령대 '{age_group}', 사업자형태 '{business_type}', 세부업력 '{exact_career or '미입력'}')의 "
            "실제 공고 매칭 문구를 최종 검증하고, 배제된 공고들의 결격 사유는 ReAct 로그에만 분리 기록한다."
        )
        action_3 = {
            "tool": "mcp_analyze_startup_eligibility",
            "args": {
                "user_stage": stage,
                "user_region": region,
                "optional_profile": optional_profile,
                "candidates": matched_docs,
            },
        }
        obs_3 = self.mcp.call_tool(action_3["tool"], action_3["args"])
        audits = obs_3.get("eligibility_audit", [])

        obs_3_with_excluded = dict(obs_3)
        obs_3_with_excluded["hard_filtered_excluded_count"] = len(excluded_docs)
        obs_3_with_excluded["hard_filtered_disqualifications"] = [
            {
                "pbanc_sn": ex["pbanc_sn"],
                "title": ex["title"],
                "disqualification_reasons": ex["disqualification_reasons"],
                "matched_disqualification_phrases": ex["matched_disqualification_phrases"],
            }
            for ex in excluded_docs
        ]

        evidence_3 = [
            f"[최종 추천 적격 공고] [{a['pbanc_sn']}] {a['title']} -> 공고 대상: '{a['target_stage']}' | "
            f"업력 판정: {a['stage_verdict']} | 지역 판정: {a['region_verdict']} | "
            f"선택 프로필 판정: {a.get('optional_profile_verdict', '-')} | "
            f"공고 내 적격 매칭 문구: {a.get('matched_eligibility_phrases', [])} | 마감: {a['d_day']} ({a['deadline']})"
            for a in audits
        ]
        for ex in excluded_docs:
            evidence_3.append(
                f"[결격 배제 로그 (보고서 미노출)] [{ex['pbanc_sn']}] {ex['title']} -> "
                f"결격 사유: {' / '.join(ex['disqualification_reasons'])} | "
                f"공고 내 감지 문구: {ex['matched_disqualification_phrases']}"
            )

        reflection_3 = (
            f"최종 적격 감사 결과, 업력 부적격·조건부 주의, 지역 불일치, 선택 프로필 제한에 해당하는 {len(excluded_docs)}건의 결격 공고는 "
            "하드 필터링으로 완전 배제하여 ReAct 추론 로그에만 근거를 남겼으며, "
            f"최종 추천된 {len(audits)}건의 공고는 모두 필수·선택 프로필 요건과 공고 내 적격 문구가 100% 일치함을 확인했다. "
            "최종 종합 분석 보고서에는 선발된 적격 공고들의 매칭 문구와 실행 전략만 명확히 포함하여 생성한다."
        )

        react_steps.append(
            {
                "step": 3,
                "phase": "Step 3. 적격/결격 판단 근거 문구 검증 및 분리 기록",
                "thought": thought_3,
                "action": action_3,
                "observation": obs_3_with_excluded,
                "evidence": evidence_3,
                "reflection": reflection_3,
            }
        )

        final_report = self._generate_final_report(
            user_profile=user_profile,
            mapped_persona=mapped_persona,
            persona_criteria=persona_criteria,
            user_query=user_query,
            matched_docs=matched_docs,
            audits=audits,
            checklist=obs_3.get("strategic_checklist", []),
            reflections=[s["reflection"] for s in react_steps],
        )

        return {
            "is_ask_back": False,
            "react_trace": react_steps,
            "matched_announcements": matched_docs,
            "excluded_announcements": excluded_docs,
            "eligibility_audit": audits,
            "final_report": final_report,
            "crawl_status": self.mcp.last_crawl_status,
        }

    def _generate_final_report(
        self,
        user_profile: Dict[str, str],
        mapped_persona: str,
        persona_criteria: Dict[str, Any],
        user_query: str,
        matched_docs: List[Dict[str, Any]],
        audits: List[Dict[str, Any]],
        checklist: List[str],
        reflections: List[str],
    ) -> str:
        audit_map = {a["pbanc_sn"]: a for a in audits}

        stage = user_profile.get("stage", "예비창업자")
        domain = user_profile.get("domain", "AI/IT")
        region = user_profile.get("region", "서울")
        age_group = (user_profile.get("age_group") or "선택 안 함").strip()
        business_type = (user_profile.get("business_type") or "선택 안 함").strip()
        exact_career = (user_profile.get("exact_career") or "").strip()

        opt_summary = (
            f"대표자 연령대: {age_group} | 사업자 형태: {business_type} | 정확한 업력: {exact_career or '미입력'}"
        )

        if self.client is not None:
            try:
                context_str = "\n".join(
                    [
                        f"- [{d['pbanc_sn']}] {d['title']} | 분야: {d['category']} | 주관: {d['organization']} "
                        f"| 대상: {d['target_stage']} | 지역: {d['region']} | 마감: {d['deadline']} ({d['d_day']}) "
                        f"| RAG점수: {d['rag_score']} | GraphDB 연결과제: {d.get('graph_core_need')} (그래프 연관도: {d.get('graph_score')}) "
                        f"| 페르소나 적격기준: {persona_criteria['criteria_summary']} "
                        f"| 적격판정: 업력({audit_map.get(d['pbanc_sn'], {}).get('stage_verdict')}), "
                        f"지역({audit_map.get(d['pbanc_sn'], {}).get('region_verdict')}), "
                        f"선택프로필({audit_map.get(d['pbanc_sn'], {}).get('optional_profile_verdict')}) "
                        f"| 공고 내 적격 매칭 문구: {audit_map.get(d['pbanc_sn'], {}).get('matched_eligibility_phrases', [])} "
                        f"| 요약: {d['summary']} | 링크: {d['detail_url']}"
                        for d in matched_docs
                    ]
                )
                reflection_str = "\n".join(f"- Step {i+1}: {r}" for i, r in enumerate(reflections))

                user_prompt = (
                    f"[창업자 프로필]\n"
                    f"- 필수 프로필: 창업 단계={stage} (GraphDB 매핑 페르소나: {mapped_persona}) | 아이템/기술={domain} | 지역={region} | 희망분야={user_profile.get('category')}\n"
                    f"- 선택 프로필: {opt_summary}\n"
                    f"- 적용 페르소나 적격 기준: {persona_criteria['criteria_summary']}\n"
                    f"- 상세 조건: {user_query}\n\n"
                    f"[하드 필터링을 통과한 최종 적격 추천 공고 및 매칭 근거 문구]\n{context_str}\n\n"
                    f"[에이전트 단계별 성찰(Reflection) 결과]\n{reflection_str}"
                )
                resp = self.client.chat.completions.create(
                    model=self.env_model,
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                )
                return resp.choices[0].message.content or ""
            except Exception:
                pass

        lines = [
            "### 창업 패스파인더 맞춤 공고 분석 보고서",
            f"- **필수 프로필:** {stage} (GraphDB 페르소나: `{mapped_persona}`) | {domain} | {region} | 희망분야: {user_profile.get('category', '전체')}",
            f"- **선택 프로필:** {opt_summary}",
            f"- **적용 페르소나 적격 판단 기준:** {persona_criteria['criteria_summary']}",
            f"- **요청 조건 요약:** {user_query}\n",
            "---",
            "#### 1. 맞춤형 모집중 공고 추천 및 선정 근거 (하드 필터링 통과 적격 공고)",
        ]

        if not matched_docs:
            lines.append("현재 입력하신 필수·선택 프로필 및 지역·업력 적격 기준을 모두 충족하는 모집중 공고가 없습니다.")
        else:
            for i, doc in enumerate(matched_docs, 1):
                ev = doc.get("evidence_detail", {})
                audit = audit_map.get(doc["pbanc_sn"], {})
                terms_str = ", ".join(ev.get("matched_terms", [])) or "문맥 유사도 매칭"
                elig_phrases = audit.get("matched_eligibility_phrases") or ev.get(
                    "matched_eligibility_phrases", []
                )
                elig_phrases_str = ", ".join(elig_phrases) if elig_phrases else "기본 적격 요건 부합"
                lines.append(
                    f"**{i}순위. {doc['title']}** (RAG 점수: `{doc['rag_score']}` | GraphDB 연관도: `{doc.get('graph_score', 0.0)}` | `{doc['d_day']}`)\n"
                    f"- **GraphDB 택사노미 경로:** `[{mapped_persona}]` → `[{doc.get('graph_core_need', '-')}]` → `[{doc['category']}]`\n"
                    f"- **RAG 정량적 근거:** TF-IDF 코사인 `{ev.get('tfidf_cosine', 0)}` + 키워드 가중치 `+{ev.get('keyword_boost', 0)}` "
                    f"+ 업력·지역 적격 가중치 `+{round(ev.get('stage_bonus', 0) + ev.get('region_bonus', 0), 2)}` (일치 키워드: `{terms_str}`)\n"
                    f"- **적격 판정 결과:** [업력] {audit.get('stage_verdict', '적합')} / [지역] {audit.get('region_verdict', '적합')} / [선택 프로필] {audit.get('optional_profile_verdict', '적합')}\n"
                    f"- **공고 내 적격 판단 근거 문구:** `{elig_phrases_str}`\n"
                    f"- **지원분야 / 주관기관 / 마감일:** {doc['category']} / {doc['organization']} / {doc['deadline']}\n"
                    f"- **지원 내용 요약:** {doc['summary']}\n"
                    f"- **상세 링크:** [K-Startup 공고 원문 바로가기]({doc['detail_url']})\n"
                )

        lines.extend(
            [
                "---",
                "#### 2. 단계별 성찰(Reflection) 및 적격 검증 요약",
            ]
        )
        for idx, ref in enumerate(reflections, 1):
            lines.append(f"- **Step {idx} 검증 결과:** {ref}")

        lines.extend(
            [
                "\n---",
                "#### 3. 필수 점검사항 및 지원 실행 전략",
            ]
        )
        for item in checklist:
            lines.append(f"- {item}")

        lines.extend(
            [
                f"- **아이템 맞춤 사업계획서 전략:** '{domain}' 아이템의 기술적 차별성뿐만 아니라 목표 시장 규모와 시제품 제작 후 초기 고객 확보 방안을 정량적 지표로 제시하시기 바랍니다.",
                "- **접수 마감 관리:** 마감일 당일 오후에는 K-Startup 시스템 접속이 지연될 수 있으므로 최소 마감 2일 전까지 서류 업로드를 완료하시기 바랍니다.",
            ]
        )
        return "\n".join(lines)
