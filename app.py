"""Run with streamlit run app.py after starting the FastAPI backend."""
import requests
import streamlit as st

API_URL = "http://127.0.0.1:8000/api/v1/search"
st.set_page_config(page_title="PocketSyllabus", page_icon="📚")
st.title("📚 PocketSyllabus")
st.caption("Discover study materials from your local library and save excerpts for offline reading.")

with st.form("search_form"):
    query = st.text_input("What would you like to learn?", placeholder="How does photosynthesis work?")
    limit = st.slider("Number of results", min_value=1, max_value=10, value=3)
    submitted = st.form_submit_button("Search")

if submitted:
    if not query.strip():
        st.warning("Enter a topic or question to search.")
    else:
        try:
            with st.spinner("Searching your local library…"):
                response = requests.post(API_URL, json={"query": query.strip(), "limit": limit}, timeout=120)
            if not response.ok:
                try:
                    detail = response.json().get("detail", response.text)
                except ValueError:
                    detail = response.text
                st.error(f"Search failed: {detail}")
            else:
                st.session_state["search_response"] = response.json()
        except requests.RequestException:
            st.error("Cannot reach the local API. Start it with: uvicorn app.main:app --host 127.0.0.1 --port 8000")

if "search_response" in st.session_state:
    result = st.session_state["search_response"]
    st.subheader(f"Results for: {result['query']}")
    if not result["results"]:
        st.info("No materials indexed yet. Run python ingest.py to add your local markdown files.")
    for item in result["results"]:
        with st.container(border=True):
            st.subheader(item["source_title"])
            st.caption(f"Section: {item['section']} • Similarity: {item['score']:.3f}")
            st.write(item["text_excerpt"])
            citation = f"{item['source_title']} — {item['section']} (local chunk {item['id']})"
            st.caption(f"Source: {citation}")
            download = f"{citation}\n\n{item['text_excerpt']}\n"
            st.download_button(
                "Save Excerpt for Offline Reading (.txt)", data=download,
                file_name=f"pocket-syllabus-{item['id']}.txt", mime="text/plain",
                key=f"download-{item['id']}",
            )
