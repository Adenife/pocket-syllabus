"""Library taxonomy controls and metadata editor."""
import streamlit as st
from frontend.client import api

MATERIALS={'Unspecified':'unspecified','Textbook':'textbook','Lecture notes':'lecture_notes',
           'Syllabus':'syllabus','Assignment':'assignment','Revision notes':'revision_notes','Other':'other'}
KINDS={'Subject':'subject','Tag':'tag','Collection':'collection'}
FIELDS={'subject':'subjects','tag':'tags','collection':'collections'}
SORTS={'Date added':'created_at','Title':'title','Last updated':'updated_at','File size':'size',
       'Indexing status':'status','Recently opened':'last_opened','Author':'author','Publication year':'publication_year'}


def choose(label,items,key,default=None):
    labels={item['id']:item['name'] for item in items}
    defaults=[identifier for identifier in (default or []) if identifier in labels]
    return st.multiselect(label,list(labels),default=defaults,format_func=labels.get,key=key)


def manage(catalog):
    with st.expander('Manage subjects, tags, and collections'):
        with st.form('create_category',clear_on_submit=True):
            kind=st.selectbox('Category type',list(KINDS))
            name=st.text_input('Category name',max_chars=80)
            description=st.text_area('Category description',max_chars=1000)
            created=st.form_submit_button('Create category')
        if created:
            result=api('POST','/library/categories',json={'kind':KINDS[kind],'name':name,'description':description})
            if result is not None:
                st.success('Category created.')
                st.rerun()
        items=[item for field in FIELDS.values() for item in catalog[field]]
        if items:
            labels={item['id']:f"{item['kind'].title()}: {item['name']}" for item in items}
            selected=st.selectbox('Edit category',list(labels),format_func=labels.get)
            item=next(item for item in items if item['id']==selected)
            with st.form('edit_category_'+selected):
                renamed=st.text_input('Updated category name',value=item['name'],max_chars=80)
                description=st.text_area('Updated description',value=item.get('description',''),max_chars=1000)
                saved=st.form_submit_button('Save category')
            if saved and api('PATCH','/library/categories/'+selected,json={'name':renamed,'description':description,'expected_name':item['name'],'expected_description':item.get('description','')}) is not None:
                st.rerun()
            confirmed=st.checkbox('Remove this category from all documents',key='remove-category-confirm')
            if st.button('Remove category',disabled=not confirmed):
                if api('DELETE','/library/categories/'+selected) is not None:
                    st.rerun()


def filters(catalog):
    with st.form('library_filters'):
        q=st.text_input('Find a document',key='lib_q',max_chars=256,placeholder='Title, filename, or author')
        a,b,c=st.columns(3)
        with a: subjects=choose('Subjects',catalog['subjects'],'lib_subjects')
        with b: tags=choose('Tags',catalog['tags'],'lib_tags')
        with c: collections=choose('Collections',catalog['collections'],'lib_collections')
        a,b,c=st.columns(3)
        with a: material=st.selectbox('Material type',['All',*MATERIALS],key='lib_material')
        with b: status=st.selectbox('Indexing status',['All','ready','queued','indexing','failed'],key='lib_status')
        with c: file_type=st.selectbox('File format',['All','.pdf','.docx','.md','.txt'],key='lib_format')
        a,b,c=st.columns(3)
        with a: sort=st.selectbox('Sort by',list(SORTS),key='lib_sort')
        with b: direction=st.selectbox('Sort direction',['Descending','Ascending'],key='lib_direction')
        with c: favorite=st.checkbox('Favorites only',key='lib_favorites')
        applied=st.form_submit_button('Apply filters')
    if applied:
        st.session_state['lib_page']=1
    params={'q':q,'subject_ids':subjects,'tag_ids':tags,'collection_ids':collections,
            'sort_by':SORTS[sort],'sort_order':'asc' if direction=='Ascending' else 'desc'}
    for key,value in [('material_type',MATERIALS.get(material)),('status',None if status=='All' else status),('file_type',None if file_type=='All' else file_type)]:
        if value is not None: params[key]=value
    if favorite: params['favorite']=True
    return params


def edit(doc,catalog):
    prefix=doc['id']
    with st.expander('Edit details and organization'):
        with st.form('metadata-'+prefix):
            title=st.text_input('Display title',value=doc['title'],max_chars=256)
            description=st.text_area('Description',value=doc.get('description',''),max_chars=4000)
            a,b,c=st.columns(3)
            with a: author=st.text_input('Author',value=doc.get('author',''),max_chars=256)
            with b: year=st.number_input('Publication year (0 = unknown)',min_value=0,max_value=9999,value=doc.get('publication_year') or 0)
            with c: edition=st.text_input('Edition',value=doc.get('edition',''),max_chars=80)
            labels=list(MATERIALS)
            material=st.selectbox('Material type',labels,index=labels.index(next((label for label,value in MATERIALS.items() if value==doc.get('material_type')), 'Unspecified')))
            favorite=st.checkbox('Favorite',value=doc.get('favorite',False))
            selections={}
            for kind,field in FIELDS.items():
                selections[kind+'_ids']=choose(field.title(),catalog[field],prefix+'-'+field,[item['id'] for item in doc.get(field,[])])
            saved=st.form_submit_button('Save details')
        if saved:
            response=api('PATCH','/library/documents/'+prefix,json={'expected_metadata_version':doc.get('metadata_version',1),
                'title':None if doc.get('display_title') is None and title==doc['title'] else title,'description':description,'author':author,'publication_year':year or None,
                'edition':edition,'material_type':MATERIALS[material],'favorite':favorite,**selections})
            if response is not None:
                st.success('Details saved without reindexing.')
                st.rerun()
    if st.button('Suggest subjects and tags',key='suggest-'+prefix):
        response=api('GET','/library/documents/'+prefix+'/suggestions')
        if response is not None:
            st.session_state['suggestions-'+prefix]=response.json()
    suggestions=st.session_state.get('suggestions-'+prefix)
    if suggestions:
        st.caption(suggestions['method'])
        subjects=st.multiselect('Suggested subjects',[item['name'] for item in suggestions['subjects']],key='suggest-subjects-'+prefix)
        tags=st.multiselect('Suggested tags',suggestions['tags'],key='suggest-tags-'+prefix)
        if st.button('Apply selected suggestions',key='apply-suggestions-'+prefix,disabled=not(subjects or tags)):
            values={}
            for kind,names in [('subject',subjects),('tag',tags)]:
                field=FIELDS[kind];ids=[item['id'] for item in doc.get(field,[])]
                for name in names:
                    existing=next((item for item in catalog[field] if item['name'].casefold()==name.casefold()),None)
                    if existing: ids.append(existing['id'])
                    else:
                        created=api('POST','/library/categories',json={'kind':kind,'name':name})
                        if created is None: return
                        ids.append(created.json()['id'])
                values[kind+'_ids']=list(dict.fromkeys(ids))
            if api('PATCH','/library/documents/'+prefix,json={'expected_metadata_version':doc.get('metadata_version',1),**values}) is not None:
                st.session_state.pop('suggestions-'+prefix,None)
                st.rerun()
