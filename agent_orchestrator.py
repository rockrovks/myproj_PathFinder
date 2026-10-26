import os
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
    [Orchestration + ReAct (Thought -> Action -> Observation -> Evidence -> Reflection)]
    RAG 벡터 유사도와 GraphDB 페르소나 택사노미 경로를 결합하여
    정량적 근거를 도출하고 성찰(Reflection)을 수행하는 에이전트 오케스트레이터
    """

    def __init__(self, mcp_server: MCPServerRegistry):
        self.mcp = mcp_server
        self.env_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.env_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

    def has_valid_env_key(self) -> bool:
        return bool(self.env_api_key and not self.env_api_key.startswith("sk-proj-여기에"))

    def run_agent_pipeline(
        self,
        user_profile: Dict[str, str],
        user_query: str,
        force_refresh_crawl: bool = False,
        force_mock_crawl: bool = False,
    ) -> Dict[str, Any]:
        react_steps: List[Dict[str, Any]] = []

        stage = user_profile.get("stage", "예비창업자")
        domain = user_profile.get("domain", "AI/IT")
        region = user_profile.get("region", "서울")
        need_category = user_profile.get("category", "전체")
        mapped_persona = StartupTaxonomyGraphEngine.map_stage_to_persona(stage)

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
                "args": {"max_pages": 1, "force_mock": force_mock_crawl},
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

        evidence_1 = [
            f"데이터 수집 모드: {obs_1.get('crawl_mode', self.mcp.last_crawl_status)}",
            f"RAG 인덱싱 공고 수: {doc_count}건 | GraphDB 활성 노드/엣지: {len(self.mcp.graph_engine.nodes)}개 / {len(self.mcp.graph_engine.edges)}개",
            f"지원분야별 공고 분포: {cat_dist}",
            f"매핑된 GraphDB 페르소나: '{mapped_persona}' | 희망분야('{need_category}') 가용 공고: {target_cat_count}건",
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
                "phase": "Step 1. 데이터 무결성 및 GraphDB 택사노미 점검",
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

        # 후보가 부족할 경우 GraphDB 상위 공고 또는 전체 카테고리 RAG 결과로 자가 교정 보완
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

        # 각 후보 문서에 GraphDB 택사노미 경로 정보 주입
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
            + "이어지는 Step 3에서 업력 및 지역 결격 사유를 최종 검증한다."
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
        # [ReAct Step 3] 지원자격 적격성 교차 검증 및 최종 성찰
        # =====================================================================
        thought_3 = (
            f"도출된 {len(matched_docs)}건의 후보 공고에 대해 사용자의 창업단계('{stage}')와 지역('{region}')을 "
            "공고별 지원대상 및 주관지역과 1:1 대조하여 부적격 리스크와 마감 임박도를 검증한다."
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
                f"자격 교차 검증 결과, 후보 중 {len(risk_items)}건({risk_items})에서 업력 또는 지역 요건상의 주의사항이 발견되었다. "
                "최종 제안서 작성 시 즉시 지원 가능한 적격 공고와 사전 요건 확인이 필요한 공고를 명확히 구분해 안내한다."
            )
        else:
            reflection_3 = (
                "자격 교차 검증 결과, 도출된 모든 후보 공고가 사용자의 현재 창업단계(GraphDB 페르소나) 및 지역 조건에 부합하여 결격 사유가 없음을 확인했다. "
                "마감일(D-Day)이 임박한 공고부터 우선 준비할 수 있도록 실행 전략과 함께 최종 리포트를 생성한다."
            )

        react_steps.append(
            {
                "step": 3,
                "phase": "Step 3. 지원자격 교차 검증 및 리스크 성찰",
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
            user_query=user_query,
            matched_docs=matched_docs,
            audits=audits,
            checklist=obs_3.get("strategic_checklist", []),
            reflections=[s["reflection"] for s in react_steps],
        )

        return {
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
        user_query: str,
        matched_docs: List[Dict[str, Any]],
        audits: List[Dict[str, Any]],
        checklist: List[str],
        reflections: List[str],
    ) -> str:
        audit_map = {a["pbanc_sn"]: a for a in audits}

        if self.has_valid_env_key() and OpenAI is not None:
            try:
                client = OpenAI(api_key=self.env_api_key)
                context_str = "\n".join(
                    [
                        f"- [{d['pbanc_sn']}] {d['title']} | 분야: {d['category']} | 주관: {d['organization']} "
                        f"| 대상: {d['target_stage']} | 지역: {d['region']} | 마감: {d['deadline']} ({d['d_day']}) "
                        f"| RAG점수: {d['rag_score']} | GraphDB 연결과제: {d.get('graph_core_need')} (그래프 연관도: {d.get('graph_score')}) "
                        f"| 자격판정: 업력({audit_map.get(d['pbanc_sn'], {}).get('stage_verdict')}), 지역({audit_map.get(d['pbanc_sn'], {}).get('region_verdict')}) "
                        f"| 요약: {d['summary']} | 링크: {d['detail_url']}"
                        for d in matched_docs
                    ]
                )
                reflection_str = "\n".join(f"- Step {i+1}: {r}" for i, r in enumerate(reflections))

                prompt = (
                    f"당신은 대한민국 K-Startup 창업지원 전문 AI 에이전트 '창업 패스파인더'입니다.\n"
                    f"이모티콘을 사용하지 말고 전문적이고 가독성 높은 비즈니스 보고서 톤으로 작성하세요.\n\n"
                    f"[창업자 프로필] 단계: {user_profile.get('stage')} (GraphDB 페르소나: {mapped_persona}), "
                    f"아이템/기술: {user_profile.get('domain')}, 지역: {user_profile.get('region')}, 희망분야: {user_profile.get('category')}\n"
                    f"[창업자 상세 조건] {user_query}\n\n"
                    f"[RAG 및 GraphDB 통합 검색 공고 근거]\n{context_str}\n\n"
                    f"[에이전트 단계별 성찰(Reflection) 결과]\n{reflection_str}\n\n"
                    f"다음 구조로 마크다운 보고서를 작성하세요:\n"
                    f"1. 맞춤형 모집중 공고 추천 및 선정 근거 (RAG 매칭 점수, GraphDB 핵심 성장 과제 경로 및 연관도 점수, 업력/지역 자격 검증 결과 명시)\n"
                    f"2. 에이전트 성찰(Reflection) 기반 유의사항 및 지원 리스크 분석\n"
                    f"3. 마감일(D-Day) 기준 우선순위 실행 로드맵 및 사업계획서(PSST) 작성 전략"
                )
                resp = client.chat.completions.create(
                    model=self.env_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
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
                    f"- **RAG 정량적 근거:** TF-IDF 유사도 `{ev.get('tfidf_cosine', 0)}` + 키워드 가중치 `+{ev.get('keyword_boost', 0)}` "
                    f"+ 단계·지역 가중치 `+{round(ev.get('stage_bonus', 0) + ev.get('region_bonus', 0), 2)}` (일치 키워드: `{terms_str}`)\n"
                    f"- **자격 요건 검증:** [업력] {audit.get('stage_verdict', '확인 완료')} / [지역] {audit.get('region_verdict', '확인 완료')}\n"
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