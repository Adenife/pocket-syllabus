import streamlit as st
from frontend.client import api


def render():
    catalog = api('GET', '/documents', params={'limit': 100})
    documents = catalog.json() if catalog is not None else []
    labels = {doc['id']: f"{doc['title']} · {doc['filename']}" for doc in documents}
    with st.form('search_form'):
        query = st.text_input('What would you like to learn?', placeholder='How does photosynthesis work?')
        limit = st.slider('Number of results', 1, 10, 3)
        document_ids = st.multiselect('Search selected documents (optional)', options=list(labels), format_func=labels.get, help='Leave empty to search the whole library. The most recent 100 documents are selectable here.')
        hybrid = st.checkbox('Include keyword matches', value=True)
        submitted = st.form_submit_button('Search')
    if submitted:
        if not query.strip():
            st.warning('Enter a topic or question to search.')
        else:
            with st.spinner('Searching your library…'):
                response = api('POST', '/search', json={'query': query.strip(), 'limit': limit,
                    'document_ids': document_ids, 'hybrid': hybrid})
            if response is not None:
                st.session_state['search_response'] = response.json()
    if 'search_response' not in st.session_state:
        return
    result = st.session_state['search_response']
    st.subheader(f"Results for: {result['query']}")
    if not result['results']:
        st.info('No indexed materials found. Add textbooks or notes in your Library.')
    for item in result['results']:
        with st.container(border=True):
            st.subheader(item['source_title'])
            location = f"Page {item['page']}" if item.get('page') else (f"Line {item['line']}" if item.get('line') else item['section'])
            citation = f"{item['filename']} — {item['section']} — {location}"
            st.caption(f"Similarity: {item['score']:.3f}")
            st.write(item['text_excerpt'])
            st.caption('Source: ' + citation)
            st.download_button('Save Excerpt for Offline Reading (.txt)',
                data=f"{citation}\nDocument: {item['document_id']}\n\n{item['text_excerpt']}\n",
                file_name=f"pocket-syllabus-{item['id']}.txt", mime='text/plain', key=f"excerpt-{item['id']}")
