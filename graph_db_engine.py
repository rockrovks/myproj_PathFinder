import json
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
    Property Graph 구조로 모델링하고, 정적(Static) 고대비 연관도 그래프를 생성하는 엔진
    """

    PERSONA_TAXONOMY: Dict[str, Dict[str, Any]] = {
        "예비창업자": {
            "id": "PERSONA_PRE",
            "label": "예비창업자",
            "career_range": "사업자등록 이전 (예비 창업팀)",
            "description": "아이디어 구체화, 비즈니스 모델(BM) 수립, 시제품(MVP) 제작 자금 및 초기 입주공간이 필요한 단계",
            "core_needs": [
                {
                    "id": "NEED_PRE_1",
                    "name": "시제품(MVP) 제작 및 초기 사업화 자금",
                    "weight": 1.0,
                    "categories": ["사업화"],
                    "keywords": ["예비창업", "시제품", "사업화", "아이템", "로컬", "바우처"],
                },
                {
                    "id": "NEED_PRE_2",
                    "name": "초기 창업 보육공간 입주 및 인프라",
                    "weight": 0.90,
                    "categories": ["시설ㆍ공간ㆍ보육"],
                    "keywords": ["입주", "공간", "보육", "허브", "사관학교", "사무공간"],
                },
                {
                    "id": "NEED_PRE_3",
                    "name": "아이디어 검증 및 BM 멘토링",
                    "weight": 0.80,
                    "categories": ["멘토링ㆍ컨설팅ㆍ교육", "사업화"],
                    "keywords": ["멘토링", "교육", "컨설팅", "역량강화", "피칭", "네트워킹"],
                },
            ],
        },
        "창업 초기(3년 내외) 팀": {
            "id": "PERSONA_EARLY",
            "label": "창업 초기(3년 내외) 팀",
            "career_range": "창업 후 3년 이내 (초기 스타트업)",
            "description": "제품 시장 적합성(PMF) 검증, 초기 판로 개척, 첫걸음 기술개발(R&D), 시드/Pre-A 투자유치가 필요한 단계",
            "core_needs": [
                {
                    "id": "NEED_EARLY_1",
                    "name": "초기 판로개척 및 아이템 고도화 자금",
                    "weight": 1.0,
                    "categories": ["사업화"],
                    "keywords": ["초기창업", "판로", "시장진입", "사업화", "실증", "고도화"],
                },
                {
                    "id": "NEED_EARLY_2",
                    "name": "첫걸음 기술개발(R&D) 출연금 확보",
                    "weight": 0.92,
                    "categories": ["기술개발(R&D)"],
                    "keywords": ["R&D", "기술개발", "디딤돌", "첫걸음", "연구소", "기술경쟁력"],
                },
                {
                    "id": "NEED_EARLY_3",
                    "name": "시드 및 Pre-A 투자유치(IR) 연계",
                    "weight": 0.85,
                    "categories": ["멘토링ㆍ컨설팅ㆍ교육", "사업화"],
                    "keywords": ["투자", "IR", "VC", "데모데이", "시드", "Pre-A"],
                },
                {
                    "id": "NEED_EARLY_4",
                    "name": "성장기 독립 사무공간 및 기술 인프라",
                    "weight": 0.80,
                    "categories": ["시설ㆍ공간ㆍ보육"],
                    "keywords": ["입주", "보육", "공간", "클라우드", "GPU", "허브"],
                },
            ],
        },
        "그 이상 베테랑 팀": {
            "id": "PERSONA_VETERAN",
            "label": "그 이상 베테랑 팀",
            "career_range": "창업 3년 초과 ~ 7년 이상 (도약·스케일업 팀)",
            "description": "죽음의 계곡 극복, 대기업 오픈이노베이션(PoC), 대규모 스케일업 자금, 글로벌 시장 진출이 필요한 단계",
            "core_needs": [
                {
                    "id": "NEED_VET_1",
                    "name": "대기업 협업 오픈이노베이션 및 스케일업",
                    "weight": 1.0,
                    "categories": ["사업화"],
                    "keywords": ["도약", "스케일업", "대기업", "협업", "오픈이노베이션", "PoC", "죽음의 계곡"],
                },
                {
                    "id": "NEED_VET_2",
                    "name": "글로벌 시장 진출 및 해외 액셀러레이팅",
                    "weight": 0.92,
                    "categories": ["판로ㆍ해외진출"],
                    "keywords": ["글로벌", "해외", "수출", "액셀러레이팅", "GAPS", "북미", "유럽", "현지"],
                },
                {
                    "id": "NEED_VET_3",
                    "name": "상용화 기술개발(R&D) 및 후속 투자유치",
                    "weight": 0.85,
                    "categories": ["기술개발(R&D)", "멘토링ㆍ컨설팅ㆍ교육"],
                    "keywords": ["R&D", "기술개발", "투자", "IR", "VC", "7년"],
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
    def stretch_score_contrast(raw_score: float) -> float:
        """
        [요구사항 1 반영]
        기존 판단 기준과 순위(단조 증가성)는 절대 바꾸지 않으면서,
        좁은 구간(0.45~0.85)에 몰려 있던 원점수를 0.18~0.98 구간으로 넓게 펼쳐
        그래프와 표에서 상위 공고와 하위 공고의 편차가 뚜렷이 보이게 만듭니다.
        """
        if raw_score <= 0.10:
            return 0.0
        # 0.35 ~ 0.92 범위를 기점으로 거듭제곱 대비 확장 적용
        normalized = max(0.0, min((raw_score - 0.30) / 0.62, 1.0))
        stretched = 0.18 + (normalized ** 1.45) * 0.80
        return round(min(max(stretched, 0.18), 0.98), 2)

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

            for p_name, p_data in self.PERSONA_TAXONOMY.items():
                assoc_info = self._calculate_persona_announcement_association(p_data, ann)
                if assoc_info["total_score"] >= 0.18:
                    best_need_id = assoc_info["best_need_id"]
                    if best_need_id:
                        self.edges.append(
                            {
                                "source": best_need_id,
                                "target": ann_id,
                                "relation": "RESOLVED_BY",
                                "label": f"연관도 {assoc_info['total_score']}",
                                "weight": assoc_info["total_score"],
                                "persona": p_name,
                                "reason": assoc_info["reason"],
                            }
                        )
                    self.edges.append(
                        {
                            "source": p_data["id"],
                            "target": ann_id,
                            "relation": "ELIGIBLE_FOR",
                            "label": f"연관도 {assoc_info['total_score']}",
                            "weight": assoc_info["total_score"],
                            "persona": p_name,
                            "best_need_name": assoc_info["best_need_name"],
                            "matched_keywords": assoc_info["matched_keywords"],
                            "stage_fit": assoc_info["stage_fit"],
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
        기존 판단 기준(업력 적합도 + 핵심과제 분야 매칭 + 키워드 일치 개수)을 그대로 유지하되,
        최종 점수에 단조 대비 확장(stretch_score_contrast)을 적용하여 편차를 극대화합니다.
        """
        title = ann.get("title", "")
        summary = ann.get("summary", "")
        cat = ann.get("category", "")
        target_stage = ann.get("target_stage", "")
        full_text = f"{title} {summary} {cat} {target_stage}".lower()

        stage_score = 0.15
        stage_fit = "조건부 지원 가능"
        p_label = p_data["label"]

        if p_label == "예비창업자":
            if "예비" in target_stage and "초기" not in target_stage and "도약" not in target_stage:
                stage_score = 0.46
                stage_fit = "핵심 대상 (예비창업 전용)"
            elif "예비" in target_stage:
                stage_score = 0.40
                stage_fit = "핵심 대상 (예비창업 포함)"
            elif "전체" in target_stage or "예비~도약" in target_stage:
                stage_score = 0.30
                stage_fit = "지원 가능 (전체 창업자)"
            elif "3~7년" in target_stage or "도약" in target_stage:
                stage_score = 0.0
                stage_fit = "대상 외 (도약기 전용)"
            elif "3년 이내" in target_stage and "예비" not in target_stage:
                stage_score = 0.05
                stage_fit = "대상 외 (기창업자 중심)"

        elif p_label == "창업 초기(3년 내외) 팀":
            if "초기창업" in target_stage or ("3년 이내" in target_stage and "예비" not in target_stage):
                stage_score = 0.46
                stage_fit = "핵심 대상 (초기 3년 이내 전용)"
            elif "3년 이내" in target_stage or "초기" in target_stage:
                stage_score = 0.40
                stage_fit = "핵심 대상 (창업 3년 이내)"
            elif "7년 이내" in target_stage:
                stage_score = 0.34
                stage_fit = "지원 가능 (창업 7년 이하 포함)"
            elif "예비~도약" in target_stage or "전체" in target_stage:
                stage_score = 0.28
                stage_fit = "지원 가능 (전체 창업자)"
            elif target_stage == "예비창업자":
                stage_score = 0.0
                stage_fit = "대상 외 (미등록 예비창업 전용)"
            elif "3~7년" in target_stage:
                stage_score = 0.18
                stage_fit = "창업 3년차 경계 확인 필요"

        elif p_label == "그 이상 베테랑 팀":
            if "도약" in target_stage or "3~7년" in target_stage or "스케일업" in target_stage:
                stage_score = 0.46
                stage_fit = "핵심 대상 (창업 3~7년 도약기)"
            elif "7년 이내" in target_stage:
                stage_score = 0.38
                stage_fit = "지원 가능 (창업 7년 이내)"
            elif "예비~도약" in target_stage or "전체" in target_stage:
                stage_score = 0.28
                stage_fit = "지원 가능 (전체 창업자)"
            elif "예비" in target_stage or "3년 이내" in target_stage:
                stage_score = 0.0
                stage_fit = "대상 외 (예비·3년 이내 전용)"

        if stage_score <= 0.10:
            return {
                "total_score": 0.0,
                "best_need_id": None,
                "best_need_name": "",
                "matched_keywords": [],
                "stage_fit": stage_fit,
                "reason": stage_fit,
            }

        best_need_score = 0.0
        best_need_id = None
        best_need_name = ""
        best_keywords: List[str] = []

        for need in p_data["core_needs"]:
            cat_match = 0.20 if cat in need["categories"] else 0.03
            matched_kw = [kw for kw in need["keywords"] if kw.lower() in full_text]
            kw_score = min(len(matched_kw) * 0.09, 0.27)
            need_total = (cat_match + kw_score) * need["weight"]

            if need_total > best_need_score:
                best_need_score = need_total
                best_need_id = need["id"]
                best_need_name = need["name"]
                best_keywords = matched_kw

        raw_total = stage_score + best_need_score
        stretched_total = self.stretch_score_contrast(raw_total)

        reason = (
            f"[{stage_fit}] '{best_need_name}' 과제와 연결 | "
            f"지원분야({cat}) 및 일치 키워드({', '.join(best_keywords) if best_keywords else '문맥 매칭'})"
        )

        return {
            "total_score": stretched_total,
            "best_need_id": best_need_id,
            "best_need_name": best_need_name,
            "matched_keywords": best_keywords,
            "stage_fit": stage_fit,
            "reason": reason,
        }

    @staticmethod
    def map_stage_to_persona(user_stage: str) -> str:
        """사용자의 창업 단계 입력값을 GraphDB의 3대 페르소나 키로 매핑합니다."""
        if "예비" in user_stage:
            return "예비창업자"
        if "초기" in user_stage or "3년 이내" in user_stage:
            return "창업 초기(3년 내외) 팀"
        return "그 이상 베테랑 팀"

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
        eligible_map: Dict[tuple, Dict[str, Any]] = {}
        for edge in self.edges:
            if edge["relation"] == "ELIGIBLE_FOR":
                eligible_map[(edge["source"], edge["target"])] = edge

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

                p_name = edge.get("persona", "")
                p_id = self.PERSONA_TAXONOMY.get(p_name, {}).get("id", "")
                elig_edge = eligible_map.get((p_id, ann_id), {})
                ann_props = self.nodes.get(ann_id, {}).get("properties", {})

                ranked_announcements.append(
                    {
                        "persona": p_name,
                        "core_need": self.nodes.get(edge["source"], {}).get("label", ""),
                        "pbanc_sn": ann_props.get("pbanc_sn", ""),
                        "title": ann_props.get("title", ""),
                        "category": ann_props.get("category", ""),
                        "organization": ann_props.get("organization", ""),
                        "target_stage": ann_props.get("target_stage", ""),
                        "stage_fit": elig_edge.get("stage_fit", ""),
                        "d_day": ann_props.get("d_day", ""),
                        "deadline": ann_props.get("deadline", ""),
                        "association_score": edge["weight"],
                        "matched_keywords": ", ".join(elig_edge.get("matched_keywords", [])) or "분야 매칭",
                        "reason": elig_edge.get("reason", ""),
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
        """
        [요구사항 1, 2, 3 반영]
        - 요구사항 1: 연관도 점수 편차에 따라 공고 노드 크기와 연결선 두께/색상을 3단계로 극명하게 차별화
        - 요구사항 2: 물리 엔진(physics)을 완전히 끄고(enabled: false) 계층별 고정 좌표를 부여해 흔들림/움직임 원천 차단
        - 요구사항 3: 노드 타입별 고대비(High-Contrast) 5색 팔레트 적용
        """
        # 고대비(High-Contrast) 컬러 팔레트
        color_palette = {
            "Persona": {
                "bg": "#DC2626",       # 선명한 크림슨 레드
                "border": "#7F1D1D",
                "font": "#FFFFFF",
                "shape": "box",
                "col_x": -520,
            },
            "CoreNeed": {
                "bg": "#F59E0B",       # 선명한 앰버 골드 (노란/주황)
                "border": "#92400E",
                "font": "#111827",     # 밝은 배경 위 검은색 굵은 글씨로 가독성 극대화
                "shape": "box",
                "col_x": -190,
            },
            "Announcement": {
                "bg": "#059669",       # 에메랄드 그린
                "border": "#064E3B",
                "font": "#FFFFFF",
                "shape": "box",
                "col_x": 190,
            },
            "SupportCategory": {
                "bg": "#7C3AED",       # 비비드 퍼플
                "border": "#4C1D95",
                "font": "#FFFFFF",
                "shape": "ellipse",
                "col_x": 540,
            },
            "Organization": {
                "bg": "#334155",       # 다크 슬레이트 네이비
                "border": "#0F172A",
                "font": "#FFFFFF",
                "shape": "box",
                "col_x": 540,
            },
        }

        # 계층(Column)별로 노드를 분류하여 겹치지 않는 고정 Y좌표 계산
        grouped_nodes: Dict[str, List[Dict[str, Any]]] = {
            "Persona": [],
            "CoreNeed": [],
            "Announcement": [],
            "RightColumn": [],  # SupportCategory + Organization
        }

        for n in nodes:
            ntype = n.get("type", "Announcement")
            if ntype in ("SupportCategory", "Organization"):
                grouped_nodes["RightColumn"].append(n)
            elif ntype in grouped_nodes:
                grouped_nodes[ntype].append(n)
            else:
                grouped_nodes["Announcement"].append(n)

        # 공고 노드는 연관도 점수 높은 순으로 위에서부터 배치하여 한눈에 우선순위 파악 가능
        grouped_nodes["Announcement"].sort(
            key=lambda x: x.get("max_score", 0.0), reverse=True
        )

        vis_nodes = []
        for group_key, group_list in grouped_nodes.items():
            count = len(group_list)
            spacing_y = 115 if group_key != "RightColumn" else 85
            start_y = -((count - 1) * spacing_y) / 2.0

            for idx, n in enumerate(group_list):
                ntype = n.get("type", "Announcement")
                style = color_palette.get(ntype, color_palette["Announcement"])
                props = n.get("properties", {})
                pos_x = style["col_x"]
                pos_y = start_y + idx * spacing_y

                # 공고 노드는 연관도 점수에 따라 글자 크기와 여백(노드 크기)에 편차 부여
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
            if rel in ("ELIGIBLE_FOR", "MAPPED_TO_CATEGORY"):
                continue

            weight = float(e.get("weight", 0.5))
            dashes = False

            # 연관도 점수 편차를 선 색상과 두께로 극명하게 표현
            if rel == "HAS_NEED":
                edge_color = "#D97706"  # 진한 앰버
                width = 3.0
                font_color = "#92400E"
            elif rel == "RESOLVED_BY":
                if weight >= 0.80:
                    edge_color = "#DC2626"  # 최상위 연관(0.80+): 강렬한 레드 굵은 실선
                    width = 5.5
                    font_color = "#991B1B"
                elif weight >= 0.50:
                    edge_color = "#2563EB"  # 중상위 연관(0.50~0.79): 선명한 블루 실선
                    width = 3.0
                    font_color = "#1E40AF"
                else:
                    edge_color = "#94A3B8"  # 낮은 연관(0.50 미만): 회색 얇은 점선
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
                    <div class="legend-item"><span class="line-sample" style="border-top:5px solid #DC2626;"></span>최상위 연관 (0.80 이상)</div>
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
                    // 물리 엔진을 완전히 비활성화하여 그래프가 흔들리거나 움직이지 않도록 고정
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