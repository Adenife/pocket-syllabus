"""Document organization, saved excerpts, and owner-scoped library tools."""
import json
import re
import sqlite3
import time
import uuid
import numpy as np
from fastapi import HTTPException
from app.schemas.library import MetadataPatch, PortableMetadata

KINDS={'subject':'subjects','tag':'tags','collection':'collections'}

class LibraryService:
    def __init__(self,documents,search):
        self.documents,self.search=documents,search
        self.db=documents.db
        self.repository=documents.repository

    def category(self,identifier,owner,kind=None,conn=None):
        if conn is None:
            with self.db.connect() as current:
                return self.category(identifier,owner,kind,current)
        row=conn.execute('SELECT * FROM categories WHERE id=? AND owner_id=?',(identifier,owner)).fetchone()
        if not row or (kind and row['kind']!=kind):
            raise HTTPException(404,'Category not found')
        return dict(row)

    def catalog(self,owner):
        with self.db.connect() as conn:
            rows=conn.execute('''SELECT c.id,c.kind,c.name,c.description,COUNT(d.id) AS document_count,COUNT(dc.document_id) AS membership_count
                FROM categories c LEFT JOIN document_categories dc ON dc.category_id=c.id
                LEFT JOIN documents d ON d.id=dc.document_id AND d.deleted_at IS NULL
                WHERE c.owner_id=? GROUP BY c.id ORDER BY c.normalized_name,c.id''',(owner,)).fetchall()
        return {field:[dict(row) for row in rows if row['kind']==kind] for kind,field in KINDS.items()}

    def create_category(self,owner,payload):
        try:
            with self.db.connect() as conn:
                identifier=str(uuid.uuid4())
                conn.execute('INSERT INTO categories VALUES (?,?,?,?,?,?)',
                    (identifier,owner,payload.kind,payload.name,payload.name.casefold(),payload.description))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409,'A category with this name already exists') from exc
        return self.category(identifier,owner)

    def change_category(self,identifier,owner,payload=None,expected_name=None,expected_description=None,require_empty=False):
        try:
            with self.db.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                category=self.category(identifier,owner,conn=conn)
                expected_name=payload.expected_name if payload else expected_name
                expected_description=payload.expected_description if payload else expected_description
                if expected_name is not None and category['name']!=expected_name or expected_description is not None and category['description']!=expected_description:
                    raise HTTPException(409,'Category changed; refresh before modifying it')
                docs=conn.execute('SELECT d.id,d.version FROM documents d JOIN document_categories dc ON dc.document_id=d.id WHERE dc.category_id=? AND d.owner_id=?',(identifier,owner)).fetchall()
                if require_empty and docs:
                    raise HTTPException(409,'Category still has document memberships')
                if payload:
                    conn.execute('UPDATE categories SET name=?,normalized_name=?,description=? WHERE id=?',
                        (payload.name,payload.name.casefold(),payload.description,identifier))
                else:
                    conn.execute('DELETE FROM categories WHERE id=?',(identifier,))
                for doc in docs:
                    self._touch(conn,doc['id'],owner,doc['version'])
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409,'A category with this name already exists') from exc
        return self.category(identifier,owner) if payload else None

    def validate_categories(self,owner,filters,conn=None):
        for kind,field in KINDS.items():
            for identifier in filters.get(kind+'_ids',[]) or []:
                self.category(identifier,owner,kind,conn)

    def list(self,owner,filters):
        self.validate_categories(owner,filters)
        return self.repository.query(owner,**filters)

    def matching_ids(self,owner,filters):
        self.validate_categories(owner,filters)
        return self.repository.matching_ids(owner,**filters)

    def _touch(self,conn,identifier,owner,version):
        now=time.time()
        conn.execute('UPDATE documents SET metadata_version=metadata_version+1,metadata_updated_at=?,updated_at=? WHERE id=?',(now,now,identifier))
        self.db.event(conn,owner,identifier,version,'metadata')

    def _patch(self,conn,identifier,owner,payload,include_trash=False):
        row=conn.execute('SELECT * FROM documents WHERE id=? AND owner_id=? AND purged_at IS NULL'+('' if include_trash else ' AND deleted_at IS NULL'),(identifier,owner)).fetchone()
        if not row:
            raise HTTPException(404,'Document not found')
        if row['metadata_version']!=payload.expected_metadata_version:
            raise HTTPException(409,'Metadata changed; refresh before saving')
        values=payload.model_dump(exclude_unset=True)
        self.validate_categories(owner,values,conn)
        columns={'title':'display_title','description':'description','author':'author',
                 'publication_year':'publication_year','edition':'edition','material_type':'material_type','favorite':'favorite'}
        for field,column in columns.items():
            if field in values:
                value=values[field]
                if value is None and field not in {'title','publication_year'}:
                    value=False if field=='favorite' else ('unspecified' if field=='material_type' else '')
                conn.execute(f'UPDATE documents SET {column}=? WHERE id=?',(value,identifier))
        for kind in KINDS:
            field=kind+'_ids'
            if field in values:
                conn.execute('DELETE FROM document_categories WHERE document_id=? AND category_id IN (SELECT id FROM categories WHERE kind=?)',(identifier,kind))
                conn.executemany('INSERT OR IGNORE INTO document_categories VALUES (?,?)',
                                 [(identifier,item) for item in values[field] or []])
        self._touch(conn,identifier,owner,row['version'])

    def patch(self,identifier,owner,payload):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._patch(conn,identifier,owner,payload)
        return self.documents.require(identifier,owner)

    def portable(self,doc):
        return {'title':doc['display_title'],'description':doc['description'],'author':doc['author'],
                'publication_year':doc['publication_year'],'edition':doc['edition'],
                'material_type':doc['material_type'],'favorite':doc['favorite'],
                **{field:sorted(item['name'] for item in doc[field]) for field in KINDS.values()},
                'bookmarks':sorted([{key:item[key] for key in ('id','excerpt','annotation','section','page','line','document_version')} for item in self.bookmarks(doc['owner_id'],doc['id'],include_trash=True)],key=lambda item:item['id'])}

    def apply_portable(self,identifier,owner,payload,expected_version,merge=False,clone_bookmarks=False):
        payload=PortableMetadata.model_validate(payload)
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            doc=conn.execute('SELECT * FROM documents WHERE id=? AND owner_id=? AND purged_at IS NULL',(identifier,owner)).fetchone()
            if not doc:
                raise HTTPException(404,'Document not found')
            if doc['metadata_version']!=expected_version:
                raise HTTPException(409,'Metadata version conflict')
            values=payload.model_dump(exclude={'subjects','tags','collections','bookmarks'}) if not merge else {}
            for kind,field in KINDS.items():
                ids=[]
                for name in getattr(payload,field):
                    row=conn.execute('SELECT id FROM categories WHERE owner_id=? AND kind=? AND normalized_name=?',(owner,kind,name.casefold())).fetchone()
                    category_id=row[0] if row else str(uuid.uuid4())
                    if not row:
                        conn.execute('INSERT INTO categories VALUES (?,?,?,?,?,?)',(category_id,owner,kind,name,name.casefold(),''))
                    ids.append(category_id)
                if merge:
                    ids += [row[0] for row in conn.execute('SELECT dc.category_id FROM document_categories dc JOIN categories c ON c.id=dc.category_id WHERE dc.document_id=? AND c.kind=?',(identifier,kind))]
                values[kind+'_ids']=list(dict.fromkeys(ids))
            self._patch(conn,identifier,owner,MetadataPatch(expected_metadata_version=expected_version,**values),include_trash=True)
            existing=conn.execute('SELECT * FROM bookmarks WHERE document_id=?',(identifier,)).fetchall()
            incoming=payload.bookmarks
            if not merge:
                conn.execute('DELETE FROM bookmarks WHERE document_id=?',(identifier,))
            for bookmark in incoming:
                if clone_bookmarks and any(self.db.codec.decode(row['excerpt']).decode()==bookmark.excerpt and self.db.codec.decode(row['annotation']).decode()==bookmark.annotation for row in existing):
                    continue
                bookmark_id=str(uuid.uuid4()) if clone_bookmarks else bookmark.id
                previous=conn.execute('SELECT owner_id,document_id FROM bookmarks WHERE id=?',(bookmark_id,)).fetchone()
                if previous and (previous['owner_id']!=owner or previous['document_id']!=identifier):
                    raise HTTPException(409,'Bookmark ID conflict')
                now=time.time()
                conn.execute("""INSERT INTO bookmarks VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET excerpt=excluded.excerpt,annotation=excluded.annotation,
                        section=excluded.section,page=excluded.page,line=excluded.line,document_version=excluded.document_version,updated_at=excluded.updated_at""",
                    (bookmark_id,owner,identifier,self.db.codec.encode(bookmark.excerpt.encode()),self.db.codec.encode(bookmark.annotation.encode()),
                     bookmark.section,bookmark.page,bookmark.line,bookmark.document_version,now,now))
            if conn.execute('SELECT COUNT(*) FROM bookmarks WHERE document_id=?',(identifier,)).fetchone()[0]>100:
                raise HTTPException(413,'Maximum 100 bookmarks per document')
        return self.documents.require(identifier,owner,include_deleted=True)

    def bulk(self,owner,payload):
        identifiers=list(dict.fromkeys(payload.document_ids))
        # Validate the entire selection before applying any changes.
        docs=[self.documents.require(identifier,owner,include_deleted=payload.action=='restore') for identifier in identifiers]
        if payload.action in {'trash','restore','reindex'}:
            return self.documents.batch_action(identifiers,owner,payload.action)
        if payload.action in {'assign','remove'} and not payload.category_ids:
            raise HTTPException(400,'Select categories for this action')
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for identifier in payload.category_ids:
                self.category(identifier,owner,conn=conn)
            for doc in docs:
                current=conn.execute('SELECT version,metadata_version,deleted_at FROM documents WHERE id=?',(doc['id'],)).fetchone()
                if current['deleted_at'] is not None:
                    raise HTTPException(409,'Selection changed; refresh')
                expected=payload.expected_metadata_versions.get(doc['id'])
                if expected is not None and expected!=current['metadata_version']:
                    raise HTTPException(409,'Selection metadata changed; refresh')
                if payload.action=='favorite':
                    conn.execute('UPDATE documents SET favorite=? WHERE id=?',(payload.favorite,doc['id']))
                elif payload.action=='assign':
                    conn.executemany('INSERT OR IGNORE INTO document_categories VALUES (?,?)',[(doc['id'],identifier) for identifier in payload.category_ids])
                else:
                    conn.executemany('DELETE FROM document_categories WHERE document_id=? AND category_id=?',[(doc['id'],identifier) for identifier in payload.category_ids])
                for kind,limit in [('subject',30),('tag',50),('collection',30)]:
                    count=conn.execute('SELECT COUNT(*) FROM document_categories dc JOIN categories c ON c.id=dc.category_id WHERE dc.document_id=? AND c.kind=?',(doc['id'],kind)).fetchone()[0]
                    if count>limit: raise HTTPException(413,'Category membership limit exceeded')
                self._touch(conn,doc['id'],owner,current['version'])
        return {'updated':len(identifiers),'job_ids':[]}

    def opened(self,identifier,owner):
        self.documents.require(identifier,owner)
        with self.db.connect() as conn:
            conn.execute('UPDATE documents SET last_opened=? WHERE id=? AND owner_id=?',(time.time(),identifier,owner))
        return {'opened':True}

    def preview(self,identifier,owner,offset=0,limit=10,page=None):
        self.documents.require(identifier,owner)
        with self.db.connect() as conn:
            where='document_id=?';args=[identifier]
            if page is not None:
                where+=' AND page=?';args.append(page)
            total=conn.execute('SELECT COUNT(*) FROM chunks WHERE '+where,args).fetchone()[0]
            rows=conn.execute('SELECT id,text,section,page,line FROM chunks WHERE '+where+' ORDER BY ordinal LIMIT ? OFFSET ?',[*args,limit,offset]).fetchall()
        self.opened(identifier,owner)
        return {'items':[{**{k:row[k] for k in ('id','section','page','line')},'text':self.db.codec.decode(row['text']).decode()} for row in rows], 'total':total}

    def bookmarks(self,owner,identifier=None,offset=0,limit=100,include_trash=False):
        with self.db.connect() as conn:
            sql='''SELECT b.*,COALESCE(d.display_title,d.title) AS title,d.filename FROM bookmarks b
                JOIN documents d ON d.id=b.document_id WHERE b.owner_id=? AND d.purged_at IS NULL'''
            if not include_trash: sql+=' AND d.deleted_at IS NULL'
            args=[owner]
            if identifier:
                self.documents.require(identifier,owner,include_deleted=include_trash)
                sql+=' AND b.document_id=?';args.append(identifier)
            rows=conn.execute(sql+' ORDER BY b.updated_at DESC,b.id LIMIT ? OFFSET ?',[*args,limit,offset]).fetchall()
        return [self._bookmark(row) for row in rows]

    def _bookmark(self,row):
        item=dict(row)
        for field in ['excerpt','annotation']:
            item[field]=self.db.codec.decode(item[field]).decode()
        item.pop('owner_id',None)
        return item

    def create_bookmark(self,owner,payload):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('''SELECT c.*,d.indexed_version FROM chunks c JOIN documents d ON d.id=c.document_id
                WHERE c.id=? AND c.owner_id=? AND d.deleted_at IS NULL''',(payload.chunk_id,owner)).fetchone()
            if not row:
                raise HTTPException(404,'Excerpt no longer available')
            count=conn.execute('SELECT COUNT(*) FROM bookmarks WHERE document_id=?',(row['document_id'],)).fetchone()[0]
            if count>=100:
                raise HTTPException(413,'Maximum 100 bookmarks per document')
            identifier=str(uuid.uuid4());now=time.time()
            conn.execute('INSERT INTO bookmarks VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (identifier,owner,row['document_id'],self.db.codec.encode(self.db.codec.decode(row['text']).decode()[:10000].encode()),self.db.codec.encode(payload.annotation.encode()),row['section'],row['page'],row['line'],row['indexed_version'],now,now))
            document=conn.execute('SELECT version FROM documents WHERE id=?',(row['document_id'],)).fetchone()
            self._touch(conn,row['document_id'],owner,document['version'])
        return next(item for item in self.bookmarks(owner,row['document_id']) if item['id']==identifier)

    def edit_bookmark(self,identifier,owner,annotation=None):
        with self.db.connect() as conn:
            row=conn.execute('SELECT id,document_id FROM bookmarks WHERE id=? AND owner_id=?',(identifier,owner)).fetchone()
            if not row:
                raise HTTPException(404,'Bookmark not found')
            if annotation is None:
                conn.execute('DELETE FROM bookmarks WHERE id=?',(identifier,))
            else:
                conn.execute('UPDATE bookmarks SET annotation=?,updated_at=? WHERE id=?',(self.db.codec.encode(annotation.encode()),time.time(),identifier))
            doc=conn.execute('SELECT version FROM documents WHERE id=?',(row['document_id'],)).fetchone()
            self._touch(conn,row['document_id'],owner,doc['version'])
        return {'updated':True}

    def statistics(self,owner):
        with self.db.connect() as conn:
            rows=conn.execute('SELECT deleted_at,status,size,favorite FROM documents WHERE owner_id=? AND purged_at IS NULL',(owner,)).fetchall()
            count=conn.execute('SELECT COUNT(*) FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.owner_id=? AND d.deleted_at IS NULL',(owner,)).fetchone()[0]
        active=[row for row in rows if row['deleted_at'] is None]
        return {'documents':len(active),'trash_documents':len(rows)-len(active),'storage_bytes':sum(row['size'] for row in rows),
                'quota_bytes':self.db.settings.max_library_bytes,'favorites':sum(row['favorite'] for row in active),
                'chunks':count,'status_counts':{status:sum(row['status']==status for row in active) for status in ['ready','queued','indexing','failed']},
                'subjects':self.catalog(owner)['subjects']}

    def suggestions(self,identifier,owner):
        doc=self.documents.require(identifier,owner)
        preview=self.preview(identifier,owner,limit=20)
        text=(doc['title']+' '+ ' '.join(row['text'] for row in preview['items'])).lower()
        rules={'Physics':['force','motion','energy','wave','mechanics'],
               'Biology':['cell','dna','photosynthesis','organism','genetics'],
               'Mathematics':['algebra','calculus','equation','geometry'],
               'Computer Science':['algorithm','programming','software','code','database'],
               'Chemistry':['reaction','molecule','chemical','atom']}
        subjects=[];tags=[]
        for subject,terms in rules.items():
            hits=[term for term in terms if re.search(r'\b'+re.escape(term)+r'\w*\b',text)]
            if hits:
                subjects.append({'name':subject,'matches':len(hits)})
                tags.extend(hits)
        return {'subjects':sorted(subjects,key=lambda item:(-item['matches'],item['name']))[:3],
                'tags':list(dict.fromkeys(tags))[:8], 'method':'Local keyword suggestions; review before applying'}

    def related(self,identifier,owner,limit=5):
        self.documents.require(identifier,owner)
        eligible=[item for item in self.repository.matching_ids(owner) if item!=identifier]
        if not eligible: return []
        index=self.search.index.snapshot(owner,eligible)
        if index is None:
            return []
        with self.db.connect() as conn:
            rows=conn.execute('SELECT embedding,model_name FROM chunks WHERE document_id=? ORDER BY ordinal LIMIT 16',(identifier,)).fetchall()
        if not rows:
            return []
        from app.services.embedding_service import SearchServiceError
        try:
            if any(row['model_name']!=self.db.settings.model_name for row in rows): raise ValueError
            vectors=np.array([np.frombuffer(self.db.codec.decode(row[0]),dtype=np.float32) for row in rows])
            if vectors.ndim!=2 or vectors.shape[1]!=index.d or not np.isfinite(vectors).all(): raise ValueError
        except ValueError as exc:
            raise SearchServiceError('Invalid or incompatible source vectors; reindex the document') from exc
        query=vectors.mean(axis=0).astype(np.float32)
        norm=np.linalg.norm(query)
        if norm==0:
            return []
        scores,ids=index.search((query/norm)[None,:],min(index.ntotal,max(100,limit*20)))
        records=self.search.chunks.fetch([int(i) for i in ids[0] if i!=-1],owner)
        ranked={}
        for chunk_id,score in zip(ids[0],scores[0]):
            row=records.get(int(chunk_id))
            if row and row['document_id']!=identifier:
                ranked[row['document_id']]=max(ranked.get(row['document_id'],-1),float(np.clip(score,-1,1)))
        return [{'document':self.documents.require(doc_id,owner),'score':score} for doc_id,score in sorted(ranked.items(),key=lambda item:(-item[1],item[0]))[:limit]]

    def duplicates(self,owner):
        groups={}
        for identifier in self.repository.matching_ids(owner):
            doc=self.documents.require(identifier,owner)
            key=re.sub(r'\b(?:edition|ed|\d+(?:st|nd|rd|th)|\d{4})\b','',doc['title'].casefold())
            key=re.sub(r'\W+',' ',key).strip()
            groups.setdefault(key,[]).append({'id':doc['id'],'title':doc['title'],'edition':doc['edition'],'content_hash':doc['content_hash']})
        return [{'title':key,'documents':docs,'reason':'Same normalized title; review editions and content'} for key,docs in groups.items() if len(docs)>1]
