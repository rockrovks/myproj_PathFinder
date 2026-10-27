import json
from datetime import date
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from crawler import KStartupOngoingCrawler
from mcp_rag_engine import KStartupRAGEngine, MCPServerRegistry
from agent_orchestrator import StartupPathfinderOrchestrator
from graph_db_engine import StartupTaxonomyGraphEngine

st.set_page_config(
    page_title="창업 패스파인더 AI Agent",
    layout="wide",
)

st.markdown(
    """
    <style>
    div[data-testid="InputInstructions"] {
        display: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def inject_ux_enhancements():
    components.html(
        """
        <script>
        (function() {
            const parentDoc = window.parent.document;

            function findRunButton() {
                const buttons = parentDoc.querySelectorAll('button[kind="primary"]');
                for (const btn of buttons) {
                    if (btn.innerText.includes("맞춤형 공고 분석 실행")) {
                        return btn;
                    }
                }
                return null;
            }

            function attachListeners() {
                const textareas = parentDoc.querySelectorAll('textarea');
                textareas.forEach(ta => {
                    if (ta.dataset.uxBound === "true") return;
                    ta.dataset.uxBound = "true";

                    ta.addEventListener('keydown', function(e) {
                        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
                            e.preventDefault();
                            e.stopPropagation();
                            ta.blur();
                            setTimeout(() => {
                                const runBtn = findRunButton();
                                if (runBtn) runBtn.click();
                            }, 120);
                        }
                    }, true);
                });

                const domainInputs = parentDoc.querySelectorAll('input[aria-label="창업 아이템 / 기술 분야"]');
                domainInputs.forEach(inp => {
                    if (inp.dataset.uxSyncBound === "true") return;
                    inp.dataset.uxSyncBound = "true";

                    let debounceTimer = null;
                    inp.addEventListener('input', function() {
                        window.parent.__dirtyTextInput = inp;
                        if (debounceTimer) clearTimeout(debounceTimer);
                        debounceTimer = setTimeout(() => {
                            if (parentDoc.activeElement === inp) {
                                const selStart = inp.selectionStart;
                                const selEnd = inp.selectionEnd;
                                inp.blur();
                                setTimeout(() => {
                                    inp.focus();
                                    try { inp.setSelectionRange(selStart, selEnd); } catch(err) {}
                                    window.parent.__dirtyTextInput = null;
                                }, 30);
                            }
                        }, 450);
                    });
                });

                const runBtn = findRunButton();
                if (runBtn && runBtn.dataset.uxBtnBound !== "true") {
                    runBtn.dataset.uxBtnBound = "true";
                    runBtn.addEventListener('mousedown', function(e) {
                        const active = parentDoc.activeElement;
                        if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA') && window.parent.__dirtyTextInput) {
                            e.preventDefault();
                            active.blur();
                            window.parent.__dirtyTextInput = null;
                            setTimeout(() => {
                                runBtn.click();
                            }, 120);
                        }
                    }, true);
                }
            }

            attachListeners();
            const observer = new MutationObserver(() => attachListeners());
            observer.observe(parentDoc.body, { childList: true, subtree: true });
        })();
        </script>
        """,
        height=0,
    )


# 세션 상태 초기화
if "crawler" not in st.session_state:
    st.session_state.crawler = KStartupOngoingCrawler()
if "rag_engine" not in st.session_state:
    st.session_state.rag_engine = KStartupRAGEngine()
if "graph_engine" not in st.session_state:
    st.session_state.graph_engine = StartupTaxonomyGraphEngine()
if "mcp_server" not in st.session_state:
    st.session_state.mcp_server = MCPServerRegistry(
        crawler=st.session_state.crawler,
        rag_engine=st.session_state.rag_engine,
        graph_engine=st.session_state.graph_engine,
    )
if "orchestrator" not in st.session_state:
    st.session_state.orchestrator = StartupPathfinderOrchestrator(
        mcp_server=st.session_state.mcp_server
    )
if "crawled_data" not in st.session_state:
    init_data, init_status = st.session_state.crawler.fetch_ongoing_announcements()
    st.session_state.crawled_data = init_data
    st.session_state.mcp_server.last_crawl_status = init_status
    st.session_state.rag_engine.build_index(init_data)
    st.session_state.graph_engine.build_knowledge_graph(init_data)
if "last_agent_result" not in st.session_state:
    st.session_state.last_agent_result = None

# =====================================================================
# 사이드바: 패스파인더 컨트롤러
# =====================================================================
with st.sidebar:
    st.title("패스파인더 컨트롤러")
    st.caption("ReAct · MCP · RAG · GraphDB · Orchestration")

    st.subheader("데이터셋 관리")
    if st.button("공고 데이터셋 로드 및 인덱싱 갱신", use_container_width=True):
        with st.spinner("mock_data.json을 로드하고 RAG 및 GraphDB 인덱스를 갱신 중입니다..."):
            res = st.session_state.mcp_server.call_tool(
                "mcp_kstartup_crawl_ongoing",
                {},
            )
            st.session_state.crawled_data = st.session_state.rag_engine.documents
            st.success(f"인덱싱 완료: {res['indexed_count']}건")

    st.divider()
    st.subheader("시스템 파이프라인 상태")
    st.info(
        f"**데이터 로드 상태:**\n{st.session_state.mcp_server.last_crawl_status}\n\n"
        f"**RAG 인덱스 문서 수:** `{len(st.session_state.crawled_data)}건`\n\n"
        f"**GraphDB 노드 / 엣지:** `{len(st.session_state.graph_engine.nodes)}개` / `{len(st.session_state.graph_engine.edges)}개`\n\n"
        f"**등록된 MCP 도구:** `{len(st.session_state.mcp_server.list_tools())}개`"
    )

# =====================================================================
# 메인 헤더 및 탭 구성
# =====================================================================
st.title("창업 패스파인더")
st.markdown(
    "K-Startup 모집중 사업공고 데이터 기반 맞춤형 창업지원사업 추천 에이전트"
)

tab_crawler, tab_agent, tab_mcp, tab_graph = st.tabs(
    [
        "1. K-Startup 모집중 공고 목록",
        "2. 창업 패스파인더 AI 에이전트",
        "3. MCP 도구 명세",
        "4. 페르소나별 공고 연관도 그래프",
    ]
)

# =====================================================================
# TAB 1: K-Startup '모집중' 공고 목록
# =====================================================================
with tab_crawler:
    st.subheader("K-Startup 모집중 사업공고 데이터")

    df = pd.DataFrame(st.session_state.crawled_data)
    col_f1, col_f2, col_f3, col_f4 = st.columns([1.4, 2.0, 1.8, 0.9])

    with col_f1:
        categories = (
            ["전체"] + sorted(df["category"].unique().tolist())
            if not df.empty
            else ["전체"]
        )
        selected_cat = st.selectbox("지원분야", categories)

    with col_f2:
        keyword_filter = st.text_input(
            "모집공고명 검색",
            placeholder="예: 예비창업, 초기창업, 디딤돌, 입주기업",
        )

    with col_f3:
        deadline_range = st.date_input(
            "마감일자 기간 선택",
            value=(),
            format="YYYY-MM-DD",
        )

    if not df.empty:
        filtered_df = df.copy()
        filtered_df["_deadline_date"] = filtered_df["_parsed_deadline"].apply(
            lambda x: date.fromisoformat(x) if isinstance(x, str) and x else None
        )

        if selected_cat != "전체":
            filtered_df = filtered_df[filtered_df["category"] == selected_cat]

        if keyword_filter:
            mask = filtered_df["title"].str.contains(
                keyword_filter.strip(), case=False, na=False
            )
            filtered_df = filtered_df[mask]

        if isinstance(deadline_range, (tuple, list)):
            if len(deadline_range) == 2:
                start_date, end_date = deadline_range
                filtered_df = filtered_df[
                    filtered_df["_deadline_date"].notna()
                    & (filtered_df["_deadline_date"] >= start_date)
                    & (filtered_df["_deadline_date"] <= end_date)
                ]
            elif len(deadline_range) == 1:
                start_date = deadline_range[0]
                filtered_df = filtered_df[
                    filtered_df["_deadline_date"].notna()
                    & (filtered_df["_deadline_date"] >= start_date)
                ]

        with col_f4:
            st.metric("조회 공고 수", f"{len(filtered_df)} / {len(df)} 건")

        display_cols = [
            "pbanc_sn",
            "status",
            "category",
            "d_day",
            "title",
            "organization",
            "target_stage",
            "region",
            "deadline",
            "detail_url",
        ]
        st.dataframe(
            filtered_df[display_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "pbanc_sn": "공고번호",
                "status": "상태",
                "category": "지원분야",
                "d_day": "D-Day",
                "title": "모집공고명",
                "organization": "주관기관",
                "target_stage": "대상단계",
                "region": "지역",
                "deadline": "마감일자",
                "detail_url": st.column_config.LinkColumn("상세 페이지"),
            },
        )

        export_df = filtered_df.drop(
            columns=["_parsed_deadline", "_deadline_date", "_search_text"],
            errors="ignore",
        )
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "CSV 다운로드",
                data=csv_bytes,
                file_name="kstartup_ongoing.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with dl_col2:
            json_str = json.dumps(
                export_df.to_dict(orient="records"), ensure_ascii=False, indent=2
            )
            st.download_button(
                "JSON 다운로드",
                data=json_str,
                file_name="kstartup_ongoing.json",
                mime="application/json",
                use_container_width=True,
            )

# =====================================================================
# TAB 2: 창업 패스파인더 AI Agent
# =====================================================================
with tab_agent:
    st.subheader("맞춤형 창업 지원사업 추천")

    with st.container(border=True):
        st.markdown("##### 창업자 프로필 및 조건 입력")
        p_col1, p_col2, p_col3, p_col4 = st.columns(4)
        with p_col1:
            u_stage = st.selectbox(
                "현재 창업 단계",
                ["예비창업자", "초기창업자 (3년 이내)", "도약기 (3~7년 이내)", "글로벌/스케일업"],
            )
        with p_col2:
            u_domain = st.text_input(
                "창업 아이템 / 기술 분야",
                value="AI 기반 헬스케어 솔루션",
            )
        with p_col3:
            u_region = st.selectbox(
                "거주지 / 사업장 지역",
                ["서울", "경기", "인천", "부산", "대전", "대구", "광주", "비수도권/로컬", "전국 무관"],
            )
        with p_col4:
            u_category = st.selectbox(
                "희망 지원 분야",
                ["전체", "사업화", "기술개발(R&D)", "시설ㆍ공간ㆍ보육", "멘토링ㆍ컨설팅ㆍ교육", "판로ㆍ해외진출"],
            )

        u_query = st.text_area(
            "상세 조건 및 고민 내용",
            value="현재 사업자등록 전인 예비창업자입니다. 시제품(MVP) 개발을 위한 사업화 자금 5천만원 이상 지원과 입주 가능한 보육공간이 있는 모집중 공고를 추천해주세요.",
            height=90,
        )

        run_btn = st.button(
            "맞춤형 공고 분석 실행",
            type="primary",
            use_container_width=True,
        )

    if run_btn:
        user_profile = {
            "stage": u_stage,
            "domain": u_domain,
            "region": u_region,
            "category": u_category,
        }

        with st.spinner("프로필 및 모집 공고를 분석하고 있습니다..."):
            st.session_state.last_agent_result = (
                st.session_state.orchestrator.run_agent_pipeline(
                    user_profile=user_profile,
                    user_query=u_query,
                    force_refresh_crawl=False,
                )
            )

    result = st.session_state.last_agent_result
    if result:
        st.markdown("### 1. ReAct 추론 · 근거 · 성찰 로그")
        for step_info in result["react_trace"]:
            with st.expander(
                f"{step_info['phase']} (호출 도구: {step_info['action']['tool']})",
                expanded=True,
            ):
                st.markdown(f"**Thought (추론 가설):** {step_info['thought']}")
                st.markdown(
                    f"**Action (도구 실행):** `{step_info['action']['tool']}` "
                    f"| 인자: `{json.dumps(step_info['action']['args'], ensure_ascii=False)}`"
                )
                st.markdown("**Observation (관찰 데이터):**")
                st.json(step_info["observation"])

                st.markdown("**Evidence (판단 근거):**")
                for ev_line in step_info.get("evidence", []):
                    st.markdown(f"- `{ev_line}`")

                st.info(f"**Reflection (성찰 및 자기검증):**\n{step_info.get('reflection', '')}")

        # [출력 방식 1] 되묻기(Ask-back) 발동 시 추천 결과 대신 되묻기 안내 출력
        if result.get("is_ask_back"):
            ask_info = result.get("ask_back_info", {})
            p_crit = ask_info.get("persona_criteria", {})
            st.markdown("### 2. 추가 정보 확인 및 되묻기 (Ask-back)")
            with st.container(border=True):
                st.warning(
                    "입력하신 프로필 또는 상세 조건에서 적격 판정을 위한 근거가 부족하거나 상호 충돌하는 항목이 감지되어 공고 추천을 보류했습니다."
                )
                st.markdown("#### 감지된 근거 부족 / 충돌 사유")
                for r in ask_info.get("reasons", []):
                    st.markdown(f"- {r}")

                st.markdown("#### 정확한 맞춤 추천을 위해 아래 사항을 확인하여 다시 입력해 주십시오")
                for idx, q in enumerate(ask_info.get("questions", []), 1):
                    st.markdown(f"**질문 {idx}.** {q}")

                st.divider()
                st.markdown(
                    f"**[참고] 선택하신 '{p_crit.get('persona', '')}' 페르소나 적격 판단 기준 ({p_crit.get('career_range', '')})**"
                )
                for c_line in p_crit.get("eligibility_criteria", []):
                    st.markdown(f"- {c_line}")
        else:
            st.markdown("### 2. 매칭된 모집중 공고 요약")
            matched = result["matched_announcements"]
            if matched:
                cols = st.columns(len(matched))
                for idx, doc in enumerate(matched):
                    with cols[idx]:
                        with st.container(border=True):
                            st.markdown(f"**{doc['category']}** | `{doc['d_day']}`")
                            st.markdown(f"#### {doc['title']}")
                            st.caption(
                                f"주관: {doc['organization']} | 대상: {doc['target_stage']}"
                            )
                            st.progress(
                                min(float(doc["rag_score"]), 1.0),
                                text=f"RAG 매칭 점수: {doc['rag_score']} | Graph 연관도: {doc.get('graph_score', 0.0)}",
                            )
                            st.caption(f"GraphDB 연결 과제: {doc.get('graph_core_need', '-')}")
                            ev_terms = doc.get("evidence_detail", {}).get("matched_terms", [])
                            if ev_terms:
                                st.caption(f"일치 키워드: {', '.join(ev_terms)}")
                            st.write(doc["summary"])
                            st.link_button(
                                "공고 원문 보기",
                                doc["detail_url"],
                                use_container_width=True,
                            )
            else:
                st.warning("조건에 부합하는 공고가 없습니다.")

            st.markdown("### 3. 최종 종합 분석 보고서")
            with st.container(border=True):
                st.markdown(result["final_report"])

# =====================================================================
# TAB 3: MCP 레지스트리 및 아키텍처 모니터
# =====================================================================
with tab_mcp:
    st.subheader("MCP (Model Context Protocol) 도구 명세")
    st.write(
        "에이전트가 오케스트레이션 과정에서 호출하는 표준 MCP 도구 스키마입니다."
    )
    st.json(st.session_state.mcp_server.list_tools())

# =====================================================================
# TAB 4: 페르소나별 공고 연관도 그래프
# =====================================================================
with tab_graph:
    st.subheader("페르소나 기반 창업지원 택사노미 및 공고 연관도 그래프")
    st.caption(
        "창업 생애주기별 3대 페르소나(예비창업자 / 창업 초기 3년 내외 팀 / 그 이상 베테랑 팀)의 핵심 성장 과제와 K-Startup 모집중 공고 간의 다중 홉(Multi-Hop) 연관도를 고정형 고대비 그래프로 형상화합니다."
    )

    g_col1, g_col2, g_col3, g_col4 = st.columns([1.6, 2.0, 1.2, 1.0])

    with g_col1:
        selected_persona = st.selectbox(
            "창업 페르소나 선택",
            options=[
                "예비창업자",
                "창업 초기(3년 내외) 팀",
                "그 이상 베테랑 팀",
                "전체 페르소나 비교",
            ],
            index=0,
        )

    with g_col2:
        if selected_persona in StartupTaxonomyGraphEngine.PERSONA_TAXONOMY:
            persona_needs = [
                n["name"]
                for n in StartupTaxonomyGraphEngine.PERSONA_TAXONOMY[selected_persona]["core_needs"]
            ]
            need_options = ["전체"] + persona_needs
        else:
            need_options = ["전체"]
        selected_need = st.selectbox("핵심 성장 과제 (택사노미 계층 1)", options=need_options)

    with g_col3:
        min_assoc_score = st.slider(
            "최소 연관도 점수 기준",
            min_value=0.15,
            max_value=0.90,
            value=0.25,
            step=0.05,
        )

    with g_col4:
        show_org_nodes = st.checkbox("주관기관 노드 표시", value=True)

    if selected_persona in StartupTaxonomyGraphEngine.PERSONA_TAXONOMY:
        p_meta = StartupTaxonomyGraphEngine.PERSONA_TAXONOMY[selected_persona]
        st.info(
            f"**[{p_meta['label']}] 도메인 정의 ({p_meta['career_range']}):** {p_meta['description']}\n\n"
            f"**[적격 판단 기준 근거]:** {p_meta['criteria_summary']}"
        )

    subgraph_data = st.session_state.graph_engine.query_persona_subgraph(
        persona_name=selected_persona,
        selected_need_name=selected_need,
        min_score=min_assoc_score,
        include_org_nodes=show_org_nodes,
    )

    st.markdown("#### 1. 페르소나 - 핵심과제 - 모집공고 연관도 네트워크")
    graph_html = StartupTaxonomyGraphEngine.render_interactive_graph_html(
        nodes=subgraph_data["nodes"],
        edges=subgraph_data["edges"],
    )
    components.html(graph_html, height=640)

    st.markdown("#### 2. 페르소나 맞춤형 그래프 탐색 공고 리스트")
    ranked_list = subgraph_data["ranked_announcements"]
    if ranked_list:
        rank_df = pd.DataFrame(ranked_list)
        st.dataframe(
            rank_df[
                [
                    "persona",
                    "core_need",
                    "association_score",
                    "title",
                    "category",
                    "stage_fit",
                    "d_day",
                    "organization",
                    "matched_keywords",
                    "detail_url",
                ]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "persona": "페르소나",
                "core_need": "연결된 핵심 성장 과제",
                "association_score": st.column_config.ProgressColumn(
                    "연관도 점수",
                    min_value=0.0,
                    max_value=1.0,
                    format="%.2f",
                ),
                "title": "모집공고명",
                "category": "지원분야",
                "stage_fit": "업력 적합 판정",
                "d_day": "D-Day",
                "organization": "주관기관",
                "matched_keywords": "매칭 키워드 근거",
                "detail_url": st.column_config.LinkColumn("상세 페이지"),
            },
        )
    else:
        st.warning("현재 설정된 최소 연관도 점수 이상으로 연결된 공고가 없습니다. 슬라이더 기준을 낮춰보세요.")

    with st.expander("Neo4j Cypher 탐색 쿼리 및 택사노미 스키마 보기", expanded=False):
        st.code(subgraph_data["cypher_query"], language="cypher")
        st.json(StartupTaxonomyGraphEngine.PERSONA_TAXONOMY)

inject_ux_enhancements()