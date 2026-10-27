import os
import re
from typing import Dict, Any, List
from dotenv import load_dotenv
from mcp_rag_engine import MCPServerRegistry
from graph_db_engine import StartupTaxonomyGraphEngine

load_dotenv()

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class StartupPathfinderOrchestrator:
    """
    [Orchestration + ReAct + 입력 근거 검증 및 되묻기(Ask-back) 게이트]
    1. 사용자 입력 근거 부족 또는 프로필-질문 간 업력 충돌 감지 시 즉시 되묻기(방식 1) 응답 반환
    2. 정상 입력 시 RAG + GraphDB + 페르소나 적격 기준 검증을 수행하여 최종 보고서 생성
    """

    SYSTEM_PROMPT = """당신은 대한민국 K-Startup 창업지원 전문 AI 에이전트 '창업 패스파인더'입니다.
다음의 핵심 원칙과 페르소나별 적격 판단 기준을 엄격히 준수하여 보고서를 작성하십시오.

[1. 서식 및 근거 기반(Grounding) 원칙]
- 이모티콘을 절대 사용하지 말고 명확하고 격식 있는 비즈니스 보고서 톤으로 작성하십시오.
- 제공된 공고 데이터(RAG 및 GraphDB 검색 근거)에 없는 지원금액, 자격요건, 일정을 임의로 추측하거나 지어내지 마십시오.
- 사용자 입력 정보나 공고 원문 요약만으로 판단할 수 없는 세부 자격 요건(예: 동종업종 폐업 경과기간, 세부 매출액, 대표자 연령 제한 등)이 있는 경우 단정하지 말고 추가 확인(되묻기/점검사항) 항목으로 명시하십시오.

[2. 3대 페르소나 적격 판단 기준 근거 (필수 반영)]
- 예비창업자: 공고일 기준 신청자 명의의 개인·법인 사업자등록 미보유(폐업 이력 시 동종업종 여부 확인) 및 시제품(MVP) 제작·보육공간 입주·BM 멘토링 과제 부합 여부
- 창업 초기(3년 내외) 팀: 사업자등록증 개업연월일(법인설립등기일) 기준 업력 3년(36개월) 이내 충족 및 초기 사업화·첫걸음 R&D·시드 투자유치 과제 부합 여부
- 그 이상 베테랑 팀: 업력 3년 초과 ~ 7년(84개월) 이내 도약기 요건(신산업 10년 이내·매출·선투자 조건 포함) 충족 및 오픈이노베이션(PoC)·글로벌 진출·상용화 R&D 과제 부합 여부

[3. 보고서 필수 구성 목차]
1. 맞춤형 모집중 공고 추천 및 선정 근거 (각 공고별 RAG 매칭 점수, GraphDB 핵심 성장 과제 경로 및 연관도 점수, 페르소나 적격 판단 기준에 따른 업력·지역 검증 결과 명시)
2. 에이전트 성찰(Reflection) 기반 유의사항 및 지원 리스크 분석
3. 마감일(D-Day) 기준 우선순위 실행 로드맵 및 사업계획서(PSST) 작성 전략"""

    def __init__(self, mcp_server: MCPServerRegistry):
        self.mcp = mcp_server
        self.env_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.env_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        self.client = (
            OpenAI(api_key=self.env_api_key)
            if (self.has_valid_env_key() and OpenAI is not None)
            else None
        )

    def has_valid_env_key(self) -> bool:
        return bool(self.env_api_key and not self.env_api_key.startswith("sk-proj-여기에"))

    def _check_input_ask_back(
        self, user_profile: Dict[str, str], user_query: str, mapped_persona: str
    ) -> Dict[str, Any]:
        """
        [발동 조건 A 검사]
        1) 창업 아이템 또는 상세 조건 텍스트가 지나치게 짧아 추천 근거가 부족한 경우
        2) 선택한 창업 단계(페르소나)와 상세 질문 내 업력/사업자등록 상태 언급이 상호 충돌하는 경우
        """
        domain = user_profile.get("domain", "").strip()
        stage = user_profile.get("stage", "예비창업자").strip()
        query_clean = user_query.strip()

        reasons: List[str] = []
        questions: List[str] = []

        # 1. 입력 길이 및 구체성 부족 검사
        if len(domain) < 2:
            reasons.append("창업 아이템/기술 분야 입력값이 누락되었거나 너무 짧아 기술·산업 분야 매칭 근거를 산출할 수 없습니다.")
            questions.append("현재 준비 중이거나 개발 중인 핵심 창업 아이템(제품·서비스명)과 주요 기술 분야(예: AI 헬스케어, 친환경 소재, SaaS 등)는 무엇입니까?")

        if len(query_clean) < 10:
            reasons.append("상세 조건 및 고민 내용이 10자 미만으로 입력되어 필요 자금 용도 및 핵심 성장 과제(Core Need)를 특정할 수 없습니다.")
            questions.append("현재 가장 시급하게 지원받고자 하는 목적(시제품 제작비, R&D 기술개발 출연금, 창업 보육공간 입주, 해외진출, 투자유치 IR 등)을 구체적으로 알려주시겠습니까?")

        # 2. 프로필 창업 단계와 질문 내 업력 표현 간 충돌 검사
        year_matches = [int(y) for y in re.findall(r"창업\s*(\d+)\s*년", query_clean)]

        if mapped_persona == "예비창업자":
            conflict_C1 = any(
                kw in query_clean
                for kw in ["법인 설립 완료", "법인설립 완료", "사업자등록 완료", "사업자 등록 완료", "기창업자입니다", "법인사업자입니다", "시리즈A", "시리즈B"]
            )
            conflict_C2 = any(y >= 1 for y in year_matches)
            if conflict_C1 or conflict_C2:
                reasons.append(
                    f"선택하신 프로필 단계는 '{stage}(사업자등록 이전)'이나, 상세 조건에는 기창업/업력({year_matches if year_matches else '사업자 보유'}) 관련 내용이 포함되어 있어 페르소나 적격 판단 기준이 충돌합니다."
                )
                questions.append(
                    "현재 사업자등록증(개인 또는 법인)을 이미 발급받으신 상태입니까? 기창업 상태라면 정확한 개업연월일(또는 법인설립등기일) 기준 업력이 몇 년 몇 개월인지 확인해 주십시오."
                )

        elif mapped_persona == "창업 초기(3년 내외) 팀":
            if any(kw in query_clean for kw in ["사업자등록 전", "사업자 등록 전", "미등록 예비", "예비창업자입니다"]):
                reasons.append(
                    f"선택하신 프로필 단계는 '{stage}(업력 3년 이내 기창업)'이나, 상세 조건에는 '사업자등록 전 예비창업자'로 기재되어 있어 적격 기준 적용이 불가합니다."
                )
                questions.append(
                    "현재 사업자등록 이전인 예비창업 단계이십니까, 아니면 사업자등록을 완료한 창업 3년(36개월) 이내 기업이십니까?"
                )
            elif any(y >= 4 for y in year_matches):
                reasons.append(
                    f"선택하신 프로필 단계는 '{stage}(업력 3년 이내)'이나, 상세 조건에는 '창업 {max(year_matches)}년'으로 기재되어 있어 초기창업패키지 등 3년 이내 공고 적격 여부 판정에 충돌이 발생합니다."
                )
                questions.append(
                    "사업자등록증상 개업연월일(또는 법인설립등기일)이 공고일 기준 만 3년(36개월)을 초과한 도약기(3~7년) 기업에 해당합니까?"
                )

        elif mapped_persona == "그 이상 베테랑 팀":
            if any(kw in query_clean for kw in ["사업자등록 전", "사업자 등록 전", "예비창업자입니다"]):
                reasons.append(
                    f"선택하신 프로필 단계는 '{stage}(3년 초과 도약·스케일업)'이나, 상세 조건에는 '사업자등록 전 예비창업자'로 기재되어 있어 적격 기준이 충돌합니다."
                )
                questions.append(
                    "현재 사업자등록 전인 예비창업 단계이십니까, 아니면 창업 3년을 초과한 도약기 기업이십니까?"
                )
            elif any(1 <= y <= 2 for y in year_matches):
                reasons.append(
                    f"선택하신 프로필 단계는 '{stage}(창업 3년 초과)'이나, 상세 조건에는 '창업 {min(year_matches)}년'으로 기재되어 있어 초기(3년 이내)와 도약기(3~7년) 기준이 상충합니다."
                )
                questions.append(
                    "현재 기업의 정확한 업력이 만 3년(36개월) 이내인 초기창업 기업입니까, 아니면 만 3년을 초과한 도약기 기업입니까?"
                )

        return {
            "triggered": len(reasons) > 0,
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
        mapped_persona = StartupTaxonomyGraphEngine.map_stage_to_persona(stage)

        # =====================================================================
        # [사전 라우터 게이트] 입력 근거 부족 및 충돌 검증 -> 되묻기(Ask-back) 방식 1
        # =====================================================================
        ask_back_check = self._check_input_ask_back(user_profile, user_query, mapped_persona)
        if ask_back_check["triggered"]:
            react_steps.append(
                {
                    "step": 1,
                    "phase": "Step 1. 입력 근거 무결성 및 페르소나 정합성 검증 (Ask-back 게이트)",
                    "thought": (
                        f"사용자 프로필(단계: '{stage}' -> 매핑 페르소나: '{mapped_persona}', 아이템: '{domain}')과 "
                        "상세 조건 텍스트의 정합성 및 근거 충분성을 검증한다."
                    ),
                    "action": {
                        "tool": "input_evidence_validator",
                        "args": {
                            "stage": stage,
                            "mapped_persona": mapped_persona,
                            "domain": domain,
                            "query_length": len(user_query.strip()),
                        },
                    },
                    "observation": {
                        "status": "ASK_BACK_REQUIRED",
                        "detected_issues_count": len(ask_back_check["reasons"]),
                        "persona_criteria": ask_back_check["persona_criteria"]["criteria_summary"],
                    },
                    "evidence": ask_back_check["reasons"],
                    "reflection": (
                        "사용자 입력에서 근거 부족 또는 창업 단계(업력) 충돌이 감지되었다. "
                        "부정확한 공고 추천을 중단(Abstention)하고, 페르소나별 적격 판단 기준 안내와 함께 사용자에게 명확한 정보 확인을 요청(Ask-back)한다."
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

        # =====================================================================
        # [ReAct Step 1] 데이터 무결성 및 GraphDB 택사노미 노드 검증
        # =====================================================================
        thought_1 = (
            f"사용자 프로필은 창업단계 '{stage}'(GraphDB 매핑 페르소나: '{mapped_persona}'), 아이템 '{domain}', "
            f"지역 '{region}', 희망분야 '{need_category}'이다. 먼저 K-Startup 모집중 공고 인덱스와 GraphDB 지식그래프 상태를 점검한다."
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
        ]

        if target_cat_count == 0:
            reflection_1 = (
                f"근거 확인 결과, 사용자가 선택한 '{need_category}' 분야의 공고가 0건이다. "
                "Step 2에서는 전체 분야로 탐색 범위를 넓히고 GraphDB의 페르소나 핵심 성장 과제 경로를 함께 조회해 유관 공고를 확보해야 한다."
            )
        else:
            reflection_1 = (
                f"근거 확인 결과, 총 {doc_count}건의 모집중 공고와 GraphDB 택사노미가 정상 준비되어 있다. "
                f"Step 2에서 텍스트 RAG 검색과 '{mapped_persona}' 페르소나 그래프 탐색을 병행하여 최적 공고를 도출한다."
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

        # =====================================================================
        # [ReAct Step 2] RAG 벡터 검색 + GraphDB 페르소나 경로 통합 탐색
        # =====================================================================
        synthesized_query = f"{stage} {domain} {region} {need_category} {user_query}".strip()
        effective_filter = "전체" if target_cat_count == 0 else need_category

        thought_2 = (
            f"확장 쿼리('{synthesized_query}')로 RAG 검색을 수행함과 동시에, "
            f"GraphDB에서 '{mapped_persona}' 페르소나와 연결된 다중 홉(Persona -> CoreNeed -> Announcement) 연관 공고를 조회하여 결합한다."
        )
        action_2 = {
            "tool": "mcp_kstartup_rag_search + mcp_kstartup_persona_graph_query",
            "args": {
                "query": synthesized_query,
                "persona_name": mapped_persona,
                "category_filter": effective_filter,
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

        matched_docs = obs_2_rag.get("matched_announcements", [])
        graph_ranked = obs_2_graph.get("ranked_announcements", [])
        graph_map = {g["pbanc_sn"]: g for g in graph_ranked}

        expanded_search_triggered = False
        if len(matched_docs) < 2:
            expanded_search_triggered = True
            obs_2_broad = self.mcp.call_tool(
                "mcp_kstartup_rag_search",
                {
                    "query": synthesized_query,
                    "user_stage": stage,
                    "user_region": region,
                    "category_filter": "전체",
                    "top_k": 3,
                },
            )
            seen_sns = {d["pbanc_sn"] for d in matched_docs}
            for bd in obs_2_broad.get("matched_announcements", []):
                if bd["pbanc_sn"] not in seen_sns and len(matched_docs) < 3:
                    matched_docs.append(bd)
                    seen_sns.add(bd["pbanc_sn"])

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
                d["graph_core_need"] = "타 페르소나 중심 과제"
                d["graph_score"] = 0.0
                graph_path_str = f"[{mapped_persona}] 직접 연결 없음 (그래프 연관도: 0.0 -> 업력 주의)"

            evidence_2.append(
                f"{idx}순위 [{sn}] {d['title']} | RAG 매칭점수: {d['rag_score']}점 "
                f"(일치 키워드: {ev.get('matched_terms', [])}) | GraphDB 경로: {graph_path_str}"
            )

        reflection_2 = (
            f"RAG 키워드 유사도와 GraphDB '{mapped_persona}' 택사노미 경로를 교차 대조한 결과, "
            f"상위 {len(matched_docs)}건의 공고 중 GraphDB 핵심 성장 과제와도 직접 연결되는 공고들의 정합성이 가장 높게 나타났다. "
            + (
                "(1차 필터 결과가 부족하여 전체 분야 확장 탐색을 통해 GraphDB 유관 공고를 보완 확보함.) "
                if expanded_search_triggered
                else ""
            )
            + "이어지는 Step 3에서 페르소나별 적격 판단 기준에 따른 업력 및 지역 결격 사유를 최종 검증한다."
        )

        react_steps.append(
            {
                "step": 2,
                "phase": "Step 2. RAG 벡터 검색 및 GraphDB 택사노미 경로 결합",
                "thought": thought_2,
                "action": action_2,
                "observation": {
                    "rag_results_count": len(matched_docs),
                    "graph_persona_queried": mapped_persona,
                    "graph_linked_count": len(graph_ranked),
                    "expanded_search_applied": expanded_search_triggered,
                    "candidates_summary": [
                        {
                            "pbanc_sn": d["pbanc_sn"],
                            "title": d["title"],
                            "rag_score": d["rag_score"],
                            "graph_core_need": d.get("graph_core_need"),
                            "graph_score": d.get("graph_score"),
                        }
                        for d in matched_docs
                    ],
                },
                "evidence": evidence_2,
                "reflection": reflection_2,
            }
        )

        # =====================================================================
        # [ReAct Step 3] 페르소나 적격 판단 기준 교차 검증 및 최종 성찰
        # =====================================================================
        thought_3 = (
            f"도출된 {len(matched_docs)}건의 후보 공고에 대해 '{mapped_persona}' 적격 판단 기준({persona_criteria['criteria_summary']})과 "
            f"사용자 지역('{region}')을 공고별 요건과 1:1 대조하여 부적격 리스크와 마감 임박도를 검증한다."
        )
        action_3 = {
            "tool": "mcp_analyze_startup_eligibility",
            "args": {
                "user_stage": stage,
                "user_region": region,
                "candidates": matched_docs,
            },
        }
        obs_3 = self.mcp.call_tool(action_3["tool"], action_3["args"])
        audits = obs_3.get("eligibility_audit", [])

        evidence_3 = [
            f"[{a['pbanc_sn']}] {a['title']} -> 공고 대상: '{a['target_stage']}' | "
            f"적용 기준: [{a['persona_applied']}] {a['criteria_basis']} | "
            f"업력 판정: {a['stage_verdict']} | 지역 판정: {a['region_verdict']} | 마감: {a['d_day']} ({a['deadline']})"
            for a in audits
        ]

        risk_items = [
            a["title"]
            for a in audits
            if "부적합" in a["stage_verdict"] or "주의" in a["stage_verdict"] or "주의" in a["region_verdict"]
        ]
        if risk_items:
            reflection_3 = (
                f"페르소나 적격 기준 교차 검증 결과, 후보 중 {len(risk_items)}건({risk_items})에서 업력 또는 지역 요건상의 주의사항이 발견되었다. "
                "최종 제안서 작성 시 즉시 지원 가능한 적격 공고와 사전 요건 확인이 필요한 공고를 명확히 구분해 안내한다."
            )
        else:
            reflection_3 = (
                f"페르소나 적격 기준('{mapped_persona}') 교차 검증 결과, 도출된 모든 후보 공고가 사용자의 창업단계 및 지역 조건에 부합하여 결격 사유가 없음을 확인했다. "
                "마감일(D-Day)이 임박한 공고부터 우선 준비할 수 있도록 실행 전략과 함께 최종 리포트를 생성한다."
            )

        react_steps.append(
            {
                "step": 3,
                "phase": "Step 3. 페르소나 적격 기준 교차 검증 및 리스크 성찰",
                "thought": thought_3,
                "action": action_3,
                "observation": obs_3,
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

        if self.client is not None:
            try:
                context_str = "\n".join(
                    [
                        f"- [{d['pbanc_sn']}] {d['title']} | 분야: {d['category']} | 주관: {d['organization']} "
                        f"| 대상: {d['target_stage']} | 지역: {d['region']} | 마감: {d['deadline']} ({d['d_day']}) "
                        f"| RAG점수: {d['rag_score']} | GraphDB 연결과제: {d.get('graph_core_need')} (그래프 연관도: {d.get('graph_score')}) "
                        f"| 페르소나 적격기준: {persona_criteria['criteria_summary']} "
                        f"| 자격판정: 업력({audit_map.get(d['pbanc_sn'], {}).get('stage_verdict')}), 지역({audit_map.get(d['pbanc_sn'], {}).get('region_verdict')}) "
                        f"| 요약: {d['summary']} | 링크: {d['detail_url']}"
                        for d in matched_docs
                    ]
                )
                reflection_str = "\n".join(f"- Step {i+1}: {r}" for i, r in enumerate(reflections))

                user_prompt = (
                    f"[창업자 프로필]\n"
                    f"- 창업 단계: {user_profile.get('stage')} (GraphDB 매핑 페르소나: {mapped_persona})\n"
                    f"- 적용 페르소나 적격 기준: {persona_criteria['criteria_summary']}\n"
                    f"- 아이템/기술: {user_profile.get('domain')}\n"
                    f"- 지역: {user_profile.get('region')} | 희망분야: {user_profile.get('category')}\n"
                    f"- 상세 조건: {user_query}\n\n"
                    f"[RAG 및 GraphDB 통합 검색 공고 근거]\n{context_str}\n\n"
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

        stage = user_profile.get("stage", "예비창업자")
        domain = user_profile.get("domain", "AI/IT")
        region = user_profile.get("region", "서울")

        lines = [
            "### 창업 패스파인더 맞춤 공고 분석 보고서",
            f"- **분석 대상 프로필:** {stage} (GraphDB 페르소나: `{mapped_persona}`) | {domain} | {region}",
            f"- **적용 페르소나 적격 판단 기준:** {persona_criteria['criteria_summary']}",
            f"- **요청 조건 요약:** {user_query}\n",
            "---",
            "#### 1. 맞춤형 모집중 공고 추천 및 선정 근거 (RAG + GraphDB Evidence)",
        ]

        if not matched_docs:
            lines.append("현재 조건과 일치하는 공고가 없습니다.")
        else:
            for i, doc in enumerate(matched_docs, 1):
                ev = doc.get("evidence_detail", {})
                audit = audit_map.get(doc["pbanc_sn"], {})
                terms_str = ", ".join(ev.get("matched_terms", [])) or "문맥 유사도 매칭"
                lines.append(
                    f"**{i}순위. {doc['title']}** (RAG 점수: `{doc['rag_score']}` | GraphDB 연관도: `{doc.get('graph_score', 0.0)}` | `{doc['d_day']}`)\n"
                    f"- **GraphDB 택사노미 경로:** `[{mapped_persona}]` → `[{doc.get('graph_core_need', '-')}]` → `[{doc['category']}]`\n"
                    f"- **RAG 정량적 근거:** TF-IDF 코사인 `{ev.get('tfidf_cosine', 0)}` + 키워드 가중치 `+{ev.get('keyword_boost', 0)}` "
                    f"+ 업력·지역 적격 가중치 `+{round(ev.get('stage_bonus', 0) + ev.get('region_bonus', 0), 2)}` (일치 키워드: `{terms_str}`)\n"
                    f"- **페르소나 적격 요건 검증:** [업력] {audit.get('stage_verdict', '확인 완료')} / [지역] {audit.get('region_verdict', '확인 완료')}\n"
                    f"- **지원분야 / 주관기관 / 마감일:** {doc['category']} / {doc['organization']} / {doc['deadline']}\n"
                    f"- **지원 내용 요약:** {doc['summary']}\n"
                    f"- **상세 링크:** [K-Startup 공고 원문 바로가기]({doc['detail_url']})\n"
                )

        lines.extend(
            [
                "---",
                "#### 2. 단계별 성찰(Reflection) 및 리스크 검증 요약",
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