from app.services.sync_service import SyncService
from app.storage.database import Database
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.ingestion_service import IngestionService
from app.services.search_service import SearchService
from app.workers.indexing_worker import IndexingWorker

class Context:
    def __init__(self, settings, embedder=None):
        self.settings = settings
        self.db = Database(settings)
        self.db.initialize()
        self.embedder = embedder or EmbeddingService(settings)
        self.documents = DocumentService(self.db)
        self.sync = SyncService(self.documents)
        self.ingestion = IngestionService(self.db, self.embedder)
        self.search = SearchService(self.db, self.embedder)
        self.worker = IndexingWorker(self.db, self.ingestion)
