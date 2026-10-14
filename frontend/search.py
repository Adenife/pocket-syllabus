import streamlit as st
from frontend.client import api
from frontend.organization import choose


def render():
    catalog = api('GET', '/documents', params={'limit': 100})
    documents = catalog.json() if catalog is not None else []
    labels = {doc['id']: f"{doc['title']} · {doc['filename']}" for doc in documents}
    response=api('GET','/library/catalog')
    categories=response.json() if response is not None else {'subjects':[],'tags':[],'collections':[]}
    with st.form('search_form'):
        query = st.text_input('What would you like to learn?', placeholder='How does photosynthesis work?')
        limit = st.slider('Number of results', 1, 10, 3)
        document_ids = st.multiselect('Search selected documents (optional)', options=list(labels), format_func=labels.get, help='Leave empty to search the whole library. The most recent 100 documents are selectable here.')
        subjects=choose('Search subjects',categories['subjects'],'search-subjects')
        tags=choose('Search tags',categories['tags'],'search-tags')
        collections=choose('Search collections',categories['collections'],'search-collections')
        hybrid = st.checkbox('Include keyword matches', value=True)
        submitted = st.form_submit_button('Search')
    if submitted:
        if not query.strip():
            st.warning('Enter a topic or question to search.')
        else:
            with st.spinner('Searching your library…'):
                response = api('POST', '/search', json={'query': query.strip(), 'limit': limit,
                    'document_ids': document_ids, 'hybrid': hybrid,'subject_ids':subjects,'tag_ids':tags,'collection_ids':collections})
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
            st.text(item['text_excerpt'])
            st.caption('Source: ' + citation)
            st.download_button('Save Excerpt for Offline Reading (.txt)',
                data=f"{citation}\nDocument: {item['document_id']}\n\n{item['text_excerpt']}\n",
                file_name=f"pocket-syllabus-{item['id']}.txt", mime='text/plain', key=f"excerpt-{item['id']}")

            if st.button('Bookmark excerpt',key='search-bookmark-'+str(item['id'])):
                response=api('POST','/library/bookmarks',json={'chunk_id':item['id']})
                if response is not None: st.success('Excerpt added to your bookmarks.')
