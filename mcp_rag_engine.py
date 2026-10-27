from typing import List, Dict, Any, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from crawler import KStartupOngoingCrawler
from graph_db_engine import StartupTaxonomyGraphEngine


class KStartupRAGEngine:
    """
    모집중 공고를 인덱싱하고, 100점 만점 다중 지표(벡터 유사도 25점 + 키워드 25점 +
    페르소나 업력 적격성 35점 + 지역 적격성 15점)를 산출한 뒤,
    3단계 통계 스케일링(20점 단위 지수 도약 -> IQR 이상치 보정 -> Z-Score 로지스틱 변환)을
    적용하여 정밀 근거(Evidence)를 도출하는 RAG 엔진
    """

    STOPWORDS = frozenset(
        {
            "현재",
            "있는",
            "위한",
            "이상",
            "모집중",
            "공고를",
            "공고",
            "추천해주세요",
            "지원과",
            "가능한",
            "필요합니다",
            "찾고",
            "있습니다",
        }
    )

    def __init__(self):
        self.documents: List[Dict[str, Any]] = []
        self._doc_titles_lower: List[str] = []
        self._category_dist: Dict[str, int] = {}
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2))
        self.tfidf_matrix = None
        self.is_indexed = False

    def build_index(self, announcements: List[Dict[str, Any]]) -> int:
        self.documents = announcements
        self._doc_titles_lower = []
        self._category_dist = {}

        if not self.documents:
            self.is_indexed = False
            return 0

        corpus: List[str] = []
        for doc in self.documents:
            self._doc_titles_lower.append(doc.get("title", "").lower())
            cat = doc.get("category", "기타")
            self._category_dist[cat] = self._category_dist.get(cat, 0) + 1
            corpus.append(
                doc.get("_search_text") or KStartupOngoingCrawler.build_search_text(doc)
            )

        self.tfidf_matrix = self.vectorizer.fit_transform(corpus)
        self.is_indexed = True
        return len(self.documents)

    def get_category_distribution(self) -> Dict[str, int]:
        if self.is_indexed and len(self._doc_titles_lower) == len(self.documents):
            return dict(self._category_dist)

        dist: Dict[str, int] = {}
        for doc in self.documents:
            cat = doc.get("category", "기타")
            dist[cat] = dist.get(cat, 0) + 1
        return dist

    def retrieve(
        self,
        query: str,
        user_stage: str = "",
        user_region: str = "",
        category_filter: str = "전체",
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        if not self.is_indexed or not self.documents:
            return []

        persona_label = StartupTaxonomyGraphEngine.map_stage_to_persona(user_stage)
        q_lower = query.lower()
        query_vec = self.vectorizer.transform([q_lower])
        similarities = cosine_similarity(query_vec, self.tfidf_matrix).flatten()

        query_terms = list(
            dict.fromkeys(
                t
                for t in q_lower.split()
                if len(t) >= 2 and t not in self.STOPWORDS
            )
        )

        use_cached_titles = len(self._doc_titles_lower) == len(self.documents)
        candidates_meta: List[Tuple[Dict[str, Any], float, float, float, Dict[str, Any], List[str]]] = []
        raw_scores_100: List[float] = []

        for idx, doc in enumerate(self.documents):
            if category_filter != "전체" and category_filter not in doc.get("category", ""):
                continue

            # 1) TF-IDF 코사인 유사도 점수 (최대 25점)
            raw_cosine = float(similarities[idx])
            tfidf_pts = min(raw_cosine * 65.0, 25.0)

            # 2) 키워드 일치 점수 (제목 일치 가중치 우대, 최대 25점)
            title_lower = (
                self._doc_titles_lower[idx]
                if use_cached_titles
                else doc.get("title", "").lower()
            )
            doc_text = doc.get("_search_text") or (
                f"{title_lower} {doc.get('category', '')} "
                f"{doc.get('target_stage', '')} {doc.get('region', '')} {doc.get('summary', '')}"
            ).lower()

            matched_terms: List[str] = []
            kw_pts = 0.0
            for term in query_terms:
                if term in title_lower:
                    matched_terms.append(term)
                    kw_pts += 6.5
                elif term in doc_text:
                    matched_terms.append(term)
                    kw_pts += 4.0
            kw_pts = min(kw_pts, 25.0)

            # 3) 페르소나 적격 기준 기반 업력(최대 35점) 및 지역(최대 15점) 점수
            eval_res = StartupTaxonomyGraphEngine.evaluate_stage_and_region(
                persona_label=persona_label,
                user_region=user_region,
                ann=doc,
            )
            stage_pts = eval_res["stage_score"] * 100.0
            region_pts = eval_res["region_score"] * 100.0

            # 업력 부적격(0점) 공고는 고득점 후보에서 배제되도록 페널티 부여
            if stage_pts <= 5.0:
                raw_100 = max((tfidf_pts + kw_pts) * 0.35, 13.0)
            else:
                raw_100 = min(tfidf_pts + kw_pts + stage_pts + region_pts, 100.0)

            candidates_meta.append(
                (doc, round(raw_100, 2), raw_cosine, kw_pts, eval_res, matched_terms)
            )
            raw_scores_100.append(raw_100)

        if not candidates_meta:
            return []

        # 전체 후보군에 대해 3단계 통계 스케일링(상위 3~4건 >= 0.80) 일괄 적용
        scaled_scores = StartupTaxonomyGraphEngine.scale_scores_distribution(
            raw_scores_100=raw_scores_100,
            top_target_count=4,
        )

        scored_candidates = list(zip(scaled_scores, candidates_meta))
        scored_candidates.sort(
            key=lambda item: (item[0], item[1][1]), reverse=True
        )

        results: List[Dict[str, Any]] = []
        for s_score, (doc, _, raw_cosine, kw_pts, eval_res, matched_terms) in scored_candidates[:top_k]:
            doc_copy = {k: v for k, v in doc.items() if k != "_search_text"}
            doc_copy["evidence_detail"] = {
                "tfidf_cosine": round(raw_cosine, 3),
                "keyword_boost": round(kw_pts / 100.0, 3),
                "stage_bonus": round(eval_res["stage_score"], 3),
                "region_bonus": round(eval_res["region_score"], 3),
                "matched_terms": matched_terms[:8],
                "persona_criteria_basis": eval_res["criteria_basis"],
            }
            doc_copy["rag_score"] = s_score
            results.append(doc_copy)

        return results


class MCPServerRegistry:
    """
    Model Context Protocol (MCP) 표준 도구 레지스트리 및 호출 처리기
    """

    _MCP_TOOLS_SCHEMA: List[Dict[str, Any]] = [
        {
            "name": "mcp_kstartup_crawl_ongoing",
            "description": "K-Startup '모집중' 공고 데이터셋(mock_data.json)을 로드하고 RAG 벡터 인덱스 및 GraphDB 택사노미를 갱신합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "mcp_kstartup_rag_search",
            "description": "인덱싱된 '모집중' 공고에서 창업자 프로필과 질의에 부합하는 공고 및 정량적 매칭 근거를 검색합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "user_stage": {"type": "string"},
                    "user_region": {"type": "string"},
                    "category_filter": {"type": "string", "default": "전체"},
                    "top_k": {"type": "integer", "default": 3},
                },
                "required": ["query"],
            },
        },
        {
            "name": "mcp_analyze_startup_eligibility",
            "description": "3대 페르소나 적격 판단 기준에 따라 후보 공고의 지원대상·주관지역·마감일과 사용자 프로필을 교차 검증합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_stage": {"type": "string"},
                    "user_region": {"type": "string"},
                    "candidates": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
        {
            "name": "mcp_kstartup_persona_graph_query",
            "description": "GraphDB 택사노미(예비창업자 / 창업 초기 3년 내외 팀 / 그 이상 베테랑 팀)를 탐색하여 핵심 성장 과제와 연결된 맞춤 공고 서브그래프를 반환합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "persona_name": {
                        "type": "string",
                        "enum": [
                            "예비창업자",
                            "창업 초기(3년 내외) 팀",
                            "그 이상 베테랑 팀",
                            "전체 페르소나 비교",
                        ],
                    },
                    "min_score": {"type": "number", "default": 0.25},
                },
                "required": ["persona_name"],
            },
        },
    ]

    _COMMON_CHECKLIST_ITEMS: Tuple[str, str] = (
        "지원 제외 대상 점검: 금융기관 채무불이행, 국세·지방세 체납, 중기부 동일 창업사업화 지원사업 중복 수혜 여부 사전 점검",
        "제출서류 양식 준수: 공고 상세페이지에 첨부된 최신 PSST(Problem-Solution-Scaleup-Team) 사업계획서 양식 사용 필수",
    )

    def __init__(
        self,
        crawler: KStartupOngoingCrawler,
        rag_engine: KStartupRAGEngine,
        graph_engine: StartupTaxonomyGraphEngine | None = None,
    ):
        self.crawler = crawler
        self.rag_engine = rag_engine
        self.graph_engine = graph_engine or StartupTaxonomyGraphEngine()
        self.last_crawl_status = "대기중"

    def _load_and_index_all(self) -> Tuple[int, Dict[str, int], str]:
        data, status = self.crawler.fetch_ongoing_announcements()
        self.last_crawl_status = status
        indexed_count = self.rag_engine.build_index(data)
        graph_stats = self.graph_engine.build_knowledge_graph(data)
        return indexed_count, graph_stats, status

    def list_tools(self) -> List[Dict[str, Any]]:
        return list(self._MCP_TOOLS_SCHEMA)

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "mcp_kstartup_crawl_ongoing":
            indexed_count, graph_stats, status = self._load_and_index_all()
            return {
                "protocol": "MCP/1.0",
                "tool": tool_name,
                "status": "success",
                "crawl_mode": status,
                "indexed_count": indexed_count,
                "graph_stats": graph_stats,
                "category_distribution": self.rag_engine.get_category_distribution(),
            }

        elif tool_name == "mcp_kstartup_rag_search":
            query = arguments.get("query", "")
            user_stage = arguments.get("user_stage", "")
            user_region = arguments.get("user_region", "")
            category_filter = arguments.get("category_filter", "전체")
            top_k = arguments.get("top_k", 3)

            if not self.rag_engine.is_indexed:
                self._load_and_index_all()

            matched = self.rag_engine.retrieve(
                query=query,
                user_stage=user_stage,
                user_region=user_region,
                category_filter=category_filter,
                top_k=top_k,
            )
            return {
                "protocol": "MCP/1.0",
                "tool": tool_name,
                "status": "success",
                "query_used": query,
                "category_filter_used": category_filter,
                "results_count": len(matched),
                "matched_announcements": matched,
            }

        elif tool_name == "mcp_analyze_startup_eligibility":
            user_stage = arguments.get("user_stage", "예비창업자")
            user_region = arguments.get("user_region", "서울")
            candidates = arguments.get("candidates", [])
            persona_label = StartupTaxonomyGraphEngine.map_stage_to_persona(user_stage)
            persona_criteria = StartupTaxonomyGraphEngine.get_persona_criteria_info(persona_label)

            audit_results = []
            for c in candidates:
                eval_res = StartupTaxonomyGraphEngine.evaluate_stage_and_region(
                    persona_label=persona_label,
                    user_region=user_region,
                    ann=c,
                )
                audit_results.append(
                    {
                        "pbanc_sn": c.get("pbanc_sn"),
                        "title": c.get("title"),
                        "target_stage": c.get("target_stage", ""),
                        "persona_applied": persona_label,
                        "criteria_basis": eval_res["criteria_basis"],
                        "stage_verdict": eval_res["stage_verdict"],
                        "region_verdict": eval_res["region_verdict"],
                        "d_day": c.get("d_day"),
                        "deadline": c.get("deadline"),
                        "key_benefit": c.get("summary", ""),
                    }
                )

            checklist = [
                f"[{persona_label} 적격 기준 대조] {persona_criteria['criteria_summary']}",
                *self._COMMON_CHECKLIST_ITEMS,
            ]
            return {
                "protocol": "MCP/1.0",
                "tool": tool_name,
                "status": "success",
                "evaluated_count": len(candidates),
                "persona_criteria_info": persona_criteria,
                "eligibility_audit": audit_results,
                "strategic_checklist": checklist,
            }

        elif tool_name == "mcp_kstartup_persona_graph_query":
            persona_name = arguments.get("persona_name", "예비창업자")
            min_score = float(arguments.get("min_score", 0.25))
            subgraph = self.graph_engine.query_persona_subgraph(
                persona_name=persona_name, min_score=min_score
            )
            return {
                "protocol": "MCP/1.0",
                "tool": tool_name,
                "status": "success",
                "persona_name": persona_name,
                "nodes_count": len(subgraph["nodes"]),
                "edges_count": len(subgraph["edges"]),
                "ranked_announcements": subgraph["ranked_announcements"],
            }

        return {
            "protocol": "MCP/1.0",
            "tool": tool_name,
            "status": "error",
            "message": f"알 수 없는 MCP 도구입니다: {tool_name}",
        }
