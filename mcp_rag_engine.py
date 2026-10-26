from typing import List, Dict, Any
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from crawler import KStartupOngoingCrawler
from graph_db_engine import StartupTaxonomyGraphEngine


class KStartupRAGEngine:
    """
    수집된 K-Startup '모집중' 공고를 인덱싱하고,
    다중 지표(벡터 유사도, 키워드 일치, 창업단계·지역 정합성) 기반의
    정밀 근거(Evidence)를 산출하는 RAG 엔진
    """

    def __init__(self):
        self.documents: List[Dict[str, Any]] = []
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2))
        self.tfidf_matrix = None
        self.is_indexed = False

    def build_index(self, announcements: List[Dict[str, Any]]) -> int:
        self.documents = announcements
        if not self.documents:
            self.is_indexed = False
            return 0

        corpus = [
            f"{doc.get('title', '')} {doc.get('category', '')} "
            f"{doc.get('organization', '')} {doc.get('target_stage', '')} "
            f"{doc.get('region', '')} {doc.get('summary', '')}"
            for doc in self.documents
        ]
        self.tfidf_matrix = self.vectorizer.fit_transform(corpus)
        self.is_indexed = True
        return len(self.documents)

    def get_category_distribution(self) -> Dict[str, int]:
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

        query_vec = self.vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, self.tfidf_matrix).flatten()

        stopwords = {"현재", "있는", "위한", "이상", "모집중", "공고를", "공고", "추천해주세요", "지원과", "가능한"}
        query_terms = [
            t.strip()
            for t in query.lower().split()
            if len(t.strip()) >= 2 and t.strip() not in stopwords
        ]

        scored_docs = []
        for idx, doc in enumerate(self.documents):
            if category_filter != "전체" and category_filter not in doc.get("category", ""):
                continue

            base_score = float(similarities[idx])
            doc_text = (
                f"{doc.get('title', '')} {doc.get('category', '')} "
                f"{doc.get('target_stage', '')} {doc.get('region', '')} {doc.get('summary', '')}"
            ).lower()

            matched_terms = []
            for term in query_terms:
                if term in doc_text and term not in matched_terms:
                    matched_terms.append(term)

            keyword_score = min(len(matched_terms) * 0.12, 0.48)

            target_stage = doc.get("target_stage", "")
            stage_bonus = 0.0
            if user_stage:
                if "예비" in user_stage and ("예비" in target_stage or "전체" in target_stage):
                    stage_bonus = 0.18
                elif "초기" in user_stage and ("초기" in target_stage or "3년" in target_stage or "7년" in target_stage):
                    stage_bonus = 0.18
                elif "도약" in user_stage and ("도약" in target_stage or "7년" in target_stage):
                    stage_bonus = 0.18
                elif "글로벌" in user_stage and ("글로벌" in doc_text or "해외" in doc_text or "7년" in target_stage):
                    stage_bonus = 0.18

            doc_region = doc.get("region", "전국")
            region_bonus = 0.0
            if user_region:
                if user_region in doc_region:
                    region_bonus = 0.10
                elif "전국" in doc_region or user_region == "전국 무관":
                    region_bonus = 0.05

            raw_sum = base_score + keyword_score + stage_bonus + region_bonus
            final_score = StartupTaxonomyGraphEngine.stretch_score_contrast(raw_sum + 0.12)

            doc_copy = dict(doc)
            doc_copy["rag_score"] = final_score
            doc_copy["evidence_detail"] = {
                "tfidf_cosine": round(base_score, 3),
                "keyword_boost": round(keyword_score, 3),
                "stage_bonus": round(stage_bonus, 3),
                "region_bonus": round(region_bonus, 3),
                "matched_terms": matched_terms[:8],
            }
            scored_docs.append(doc_copy)

        scored_docs.sort(key=lambda x: x["rag_score"], reverse=True)
        return scored_docs[:top_k]


class MCPServerRegistry:
    """
    Model Context Protocol (MCP) 표준 도구 레지스트리 및 호출 처리기
    """

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

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
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
                "description": "후보 공고의 지원대상·주관지역·마감일과 사용자 프로필을 교차 검증하여 적격 여부와 리스크를 평가합니다.",
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
                            "enum": ["예비창업자", "창업 초기(3년 내외) 팀", "그 이상 베테랑 팀", "전체 페르소나 비교"],
                        },
                        "min_score": {"type": "number", "default": 0.25},
                    },
                    "required": ["persona_name"],
                },
            },
        ]

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "mcp_kstartup_crawl_ongoing":
            data, status = self.crawler.fetch_ongoing_announcements()
            self.last_crawl_status = status
            indexed_count = self.rag_engine.build_index(data)
            graph_stats = self.graph_engine.build_knowledge_graph(data)
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
                data, status = self.crawler.fetch_ongoing_announcements()
                self.last_crawl_status = status
                self.rag_engine.build_index(data)
                self.graph_engine.build_knowledge_graph(data)

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

            audit_results = []
            for c in candidates:
                target = c.get("target_stage", "")
                region = c.get("region", "전국")
                summary = c.get("summary", "")

                if "예비" in user_stage:
                    if "3~7년" in target or "3년 초과" in target:
                        stage_verdict = "부적합 가능성 높음 (기창업 도약기 전용 공고)"
                    elif "3년 이내" in target and "예비" not in target:
                        stage_verdict = "조건부 주의 (사업자등록 완료 기업 대상 여부 확인 필요)"
                    else:
                        stage_verdict = "적합 (예비창업자 지원 가능)"
                elif "초기" in user_stage:
                    if target == "예비창업자" and "초기" not in target:
                        stage_verdict = "부적합 가능성 높음 (사업자 미등록 예비창업자 전용)"
                    elif "3~7년" in target or "3년 초과" in target:
                        stage_verdict = "조건부 주의 (창업 3년 초과 요건 확인 필요)"
                    else:
                        stage_verdict = "적합 (초기창업 3년 이내 지원 가능)"
                elif "도약" in user_stage:
                    if "예비" in target and "도약" not in target and "7년" not in target:
                        stage_verdict = "부적합 가능성 높음 (예비·초기 기업 전용)"
                    else:
                        stage_verdict = "적합 (창업 3~7년 도약기 지원 가능)"
                else:
                    stage_verdict = f"공고문 기준 확인 ({target})"

                if "전국" in region or user_region in region or user_region == "전국 무관":
                    region_verdict = f"적합 (공고 지역: {region})"
                else:
                    region_verdict = f"주의 (주관 지역 '{region}' 소재 또는 이전 조건 확인 필요)"

                audit_results.append(
                    {
                        "pbanc_sn": c.get("pbanc_sn"),
                        "title": c.get("title"),
                        "target_stage": target,
                        "stage_verdict": stage_verdict,
                        "region_verdict": region_verdict,
                        "d_day": c.get("d_day"),
                        "deadline": c.get("deadline"),
                        "key_benefit": summary,
                    }
                )

            checklist = [
                f"업력 기준일 대조: '{user_stage}' 기준으로 공고문에 명시된 업력 산정 기준일(공고일 기준 사업자등록증 개업연월일 또는 법인등기부등본 설립일) 충족 여부 확인",
                "지원 제외 대상 점검: 금융기관 채무불이행, 국세·지방세 체납, 중기부 사업화 지원사업 중복 수혜 해당 여부 사전 점검",
                "제출서류 양식 준수: 공고 상세페이지에 첨부된 최신 PSST(Problem-Solution-Scaleup-Team) 사업계획서 양식 사용 필수",
            ]
            return {
                "protocol": "MCP/1.0",
                "tool": tool_name,
                "status": "success",
                "evaluated_count": len(candidates),
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