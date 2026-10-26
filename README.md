# 🚀 창업 패스파인더 (Startup Pathfinder) AI Agent

K-Startup(창업지원포털)의 **'모집중' 사업공고** 데이터를 실시간 수집(Crawling)하고, **MCP + RAG + ReAct + Orchestration** 파이프라인을 통해 예비/초기 창업자에게 최적화된 지원사업을 매칭해주는 AI 에이전트입니다.

## ✨ 핵심 아키텍처
1. **K-Startup '모집중' 크롤러 (`crawler.py`)**: `bizpbanc-ongoing.do` 페이지에서 공고명, 지원분야, 주관기관, 마감일, 상세 링크 등을 추출합니다. (WAF 차단 시 정교한 Mock 데이터 자동 폴백 지원)
2. **MCP (Model Context Protocol) (`mcp_rag_engine.py`)**: 크롤러와 RAG 검색기를 표준화된 MCP Tool 스키마(`kstartup_crawl_ongoing`, `kstartup_rag_search`, `analyze_eligibility`)로 등록 및 호출합니다.
3. **RAG (Retrieval-Augmented Generation) (`mcp_rag_engine.py`)**: 수집된 공고 데이터를 임베딩(TF-IDF 코사인 유사도)하여 사용자의 창업 아이템/단계/지역과 가장 밀접한 공고를 검색합니다.
4. **ReAct & Orchestration (`agent_orchestrator.py`)**: `Thought(생각) -> Action(MCP 도구 실행) -> Observation(관찰) -> Final Answer(최종 제안)` 과정을 조율합니다.

---

## 🛠️ VSCode 빠른 실행 가이드 (Quick Start)

# Windows

### 1단계: 가상환경 생성 및 활성화 (권장)
VSCode 터미널(`Ctrl + ~`)을 열고 아래 명령어를 입력하세요.

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
### 2단계: streamlit run을 이용해 app.py 실행

```bash
streamlit run .\app.py
```