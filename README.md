# 🚀 창업 패스파인더 (Startup Pathfinder) AI Agent

K-Startup(창업지원포털)의 **'모집중' 사업공고** 데이터를 실시간 수집(Crawling)하고, **MCP + RAG + ReAct + Orchestration** 파이프라인을 통해 예비/초기 창업자에게 최적화된 지원사업을 매칭해주는 AI 에이전트입니다.
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