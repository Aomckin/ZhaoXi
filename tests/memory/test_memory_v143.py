import asyncio
import base64
import hashlib
import json
import sqlite3
from datetime import timedelta

import httpx
import pytest
from conftest import FakeProvider
from zhaoxi.cognitive.memory_decision import AutoMemory
from zhaoxi.config.settings import Settings
from zhaoxi.interfaces.maintenance import PostTurnMaintenanceQueue
from zhaoxi.memory.embedding import LocalHashEmbeddingProvider, SemanticEmbeddingProvider
from zhaoxi.memory.lifecycle import MemoryLifecyclePolicy
from zhaoxi.memory.migration import audit, migrate, restore
from zhaoxi.memory.models import MemoryCreate, MemoryEmbedding, MemoryQuery, MemoryStatus, RetrievalMode, utc_now
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.models.types import ModelResponse
from zhaoxi.reliability.media import MediaBlobStore, migrate_inline_media, vacuum_database, database_metrics
from zhaoxi.reliability.storage import BackupManager, DataStoreSpec


def service_at(tmp_path, **kwargs):
    return MemoryService(SQLiteMemoryRepository(tmp_path/'memory.db'),**kwargs)


def checksum(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def test_runtime_contract_has_no_legacy_heat_aliases():
    from zhaoxi.memory.models import MemoryRecord, MemoryUpdate
    for model in (MemoryCreate,MemoryRecord,MemoryUpdate):
        assert 'relevance' not in model.model_fields
        assert 'relevance' not in model.model_json_schema()['properties']
    assert not any(x.startswith('memory_relevance') for x in Settings.model_fields)
    assert 'memory_importance_forget_threshold' not in Settings.model_fields


@pytest.mark.asyncio
async def test_modes_keep_old_and_forbidden_memories_out_of_association(tmp_path):
    service=service_at(tmp_path)
    ids={}
    for status in MemoryStatus:
        r=(await service.remember(MemoryCreate(kind='episodic',content=f'Runtime memory {status.value}'))).record
        r.status=status;r.activation=.10 if status==MemoryStatus.COLD else .70
        await service.repository.save(r);ids[status]=r.id
    associated=await service.search(MemoryQuery(text='Runtime memory',limit=20),activate=False)
    assert {r.record.status for r in associated} <= {MemoryStatus.ACTIVE,MemoryStatus.COLD}
    explicit=await service.search(MemoryQuery(text='Runtime memory',limit=20,retrieval_mode=RetrievalMode.EXPLICIT_RECALL),activate=False)
    assert {r.record.status for r in explicit}=={MemoryStatus.ACTIVE,MemoryStatus.COLD,MemoryStatus.DORMANT,MemoryStatus.ARCHIVED}
    assert service.last_retrieval['retrieval_mode']=='EXPLICIT_RECALL'
    forbidden=await service.search(MemoryQuery(text='Runtime memory',statuses=[MemoryStatus.FORGOTTEN],retrieval_mode=RetrievalMode.BROAD_SEARCH),activate=False)
    assert forbidden==[]


@pytest.mark.asyncio
async def test_cold_requires_query_relevance_not_self_heat(tmp_path):
    service=service_at(tmp_path)
    r=(await service.remember(MemoryCreate(kind='episodic',content='苹果 香蕉 葡萄',activation=.1,importance=1))).record
    r.status=MemoryStatus.COLD;await service.repository.save(r)
    assert not await service.search(MemoryQuery(text='苹果 午饭 菜谱 家庭'),activate=False)
    assert await service.search(MemoryQuery(text='苹果 午饭 菜谱 家庭',retrieval_mode=RetrievalMode.EXPLICIT_RECALL),activate=False)
    assert await service.search(MemoryQuery(text='苹果 香蕉 葡萄'),activate=False)
    assert (await service.require(r.id)).activation==.1


def test_nonlinear_heat_and_time_lifecycle():
    from zhaoxi.memory.models import MemoryRecord
    policy=MemoryLifecyclePolicy()
    now=utc_now()
    low=MemoryRecord(**MemoryCreate(content='low',kind='episodic',activation=.3).model_dump(exclude={'source'},exclude_none=True),normalized_content='low',source='user')
    hot=MemoryRecord(**MemoryCreate(content='hot',kind='episodic',activation=.95).model_dump(exclude={'source'},exclude_none=True),normalized_content='hot',source='user')
    policy.activate(low,now);policy.activate(hot,now)
    assert low.activation-.3 > hot.activation-.95 > 0
    for _ in range(100):policy.activate(hot,now)
    assert hot.activation<=.98
    low.activation=.1;low.created_at=now-timedelta(days=40);low.accessed_at=None
    assert policy.classify(low,now)==MemoryStatus.DORMANT
    low.created_at=now-timedelta(days=100)
    assert policy.classify(low,now)==MemoryStatus.ARCHIVED
    low.status=MemoryStatus.FORGOTTEN;policy.activate(low,now)
    assert low.status==MemoryStatus.FORGOTTEN
    assert low.metadata['activation_history'][-1]['reason']=='selected'


@pytest.mark.asyncio
async def test_same_topic_does_not_force_membership_and_singletons_stay_orphan(tmp_path):
    service=service_at(tmp_path)
    first=(await service.remember(MemoryCreate(kind='episodic',content='朝汐 QQ 接入群聊',tags=['开发']))).record
    second=(await service.remember(MemoryCreate(kind='episodic',content='朝汐 Memory 日常吃饭',tags=['开发']))).record
    assert first.cluster_id is None and second.cluster_id is None
    assert not await service.repository.list_clusters()
    third=(await service.remember(MemoryCreate(kind='episodic',content='朝汐 QQ 接入群聊补充',tags=['开发']))).record
    assert third.cluster_id
    with service.repository._connect() as db:
        scores=[r[0] for r in db.execute('SELECT membership_score FROM memory_cluster_members')]
    assert all(.3<x<1 for x in scores)


@pytest.mark.asyncio
async def test_bounded_escape_fts_and_metadata_mismatch(tmp_path):
    service=service_at(tmp_path)
    record=(await service.remember(MemoryCreate(kind='episodic',content='丘脑智能面试时间'))).record
    original=await service.repository.embeddings_for([record.id])
    e=original[record.id].model_copy(update={'embedding_version':'old'})
    await service.repository.save_embedding(e)
    async def scan(*args,**kwargs):raise AssertionError('full pool scan')
    service.repository.list_records=scan;service.repository.list_embeddings=scan
    result=await service.search(MemoryQuery(text='丘脑智能',retrieval_mode=RetrievalMode.EXPLICIT_RECALL),activate=False)
    assert result[0].record.id==record.id
    assert 'fts' in result[0].candidate_source and 'escape' in result[0].candidate_source
    assert result[0].semantic_score==0
    assert service.last_retrieval['candidate_count']<=210


@pytest.mark.asyncio
async def test_automemory_limit_runtime_calibration_and_evidence(tmp_path):
    service=service_at(tmp_path)
    response={'candidates':[{'kind':'episodic','content':f'第{i}个事件','activation':1,'importance':.2,'source_message_ids':['invented']} for i in range(5)]}
    provider=FakeProvider([ModelResponse(content=json.dumps(response))])
    auto=AutoMemory(provider,service)
    decision=await auto.process('今天发生了几个不同的事情','',source_event_id='event-1',source_message_id='message-1',evidence_reference='qq:1')
    assert decision.applied_count==3
    assert provider.options[0]['response_format']['type']=='json_schema'
    assert provider.options[0]['max_tokens']==1000
    for r in await service.repository.list_records(MemoryQuery(limit=10)):
        assert r.activation==.65
        assert r.source_event_id=='event-1' and r.source_message_id=='message-1'
        assert r.source_message_ids==['message-1']
        assert r.evidence_reference=='qq:1'
    assert (await service.diagnostics())['funnel']['auto_memory_written']==3


@pytest.mark.asyncio
async def test_length_output_is_failure_even_when_explicit_fallback_written(tmp_path):
    service=service_at(tmp_path)
    provider=FakeProvider([ModelResponse(content='{"candidates": [',finish_reason='length')])
    decision=await AutoMemory(provider,service).process('记住：我的长期目标是写代码','',source_event_id='e1')
    assert decision.extraction_status=='failed'
    r=(await service.repository.list_records(MemoryQuery(limit=10)))[0]
    assert r.source_event_id=='e1'
    assert (await service.diagnostics())['funnel']['auto_memory_length_failures']==1


@pytest.mark.asyncio
async def test_phase_failure_does_not_block_independent_cognition(tmp_path):
    calls=[]
    async def handler(payload,index):
        calls.append(index)
        if index=='auto_memory':raise ValueError('extract failed')
        return {'ops':2}
    queue=PostTurnMaintenanceQueue(tmp_path/'maintenance.db',handler)
    queue.enqueue('request-1',{})
    await queue.worker
    diag=queue.diagnostics()[0]
    assert calls==['auto_memory','current_cognition'] and diag['status']=='partial_failed'
    assert diag['metrics']['auto_memory']['status']=='failed'
    assert diag['metrics']['current_cognition']['metrics']=={'ops':2}
    assert diag['metrics']['auto_memory']['duration_ms']>=0
    await queue.shutdown();queue.db.close()


@pytest.mark.asyncio
async def test_dryrun_backup_apply_rollback_and_cancel_leave_original_safe(tmp_path):
    service=service_at(tmp_path)
    await service.remember(MemoryCreate(kind='episodic',content='Runtime one',activation=1))
    await service.remember(MemoryCreate(kind='episodic',content='Runtime two',activation=1))
    path=tmp_path/'memory.db'
    before=checksum(path)
    report=await migrate(path,dry_run=True,output_dir=tmp_path/'dry')
    assert checksum(path)==before and report['dry_run'] and report['backups']==[]
    with pytest.raises(asyncio.CancelledError):
        await migrate(path,dry_run=False,output_dir=tmp_path/'cancel',cancel=lambda:True)
    assert checksum(path)==before
    report=await migrate(path,dry_run=False,output_dir=tmp_path/'apply')
    assert audit(path)['total']==2 and report['backups']
    assert max(r.activation for r in await service.repository.list_records(MemoryQuery(statuses=list(MemoryStatus))))<.9
    restore(report['backups'][0],path)
    assert audit(path)['activation_histogram']=={'10':2} or audit(path)['activation_histogram']=={10:2}


@pytest.mark.asyncio
async def test_semantic_endpoint_preserves_provider_space():
    def handler(request):
        assert request.url.path=='/v1/embeddings'
        assert request.headers['authorization']=='Bearer test'
        payload=json.loads(request.content)
        assert payload['dimensions']==16 and payload['encoding_format']=='float'
        return httpx.Response(200,json={'data':[{'embedding':[3,4]+[0]*14}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider=SemanticEmbeddingProvider(base_url='https://embedding.invalid/v1',api_key='test',model='semantic',version='2',dimensions=16,client=client)
        vector=await provider.embed('example')
        assert vector[:2]==pytest.approx([.6,.8])


def test_shared_blob_storage_roundtrip_migration_and_backup(tmp_path):
    image='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
    media=MediaBlobStore(tmp_path/'media')
    manager=BackupManager(tmp_path/'backups',[DataStoreSpec('media',tmp_path/'media',kind='directory')])
    encoded1=media.dumps({'parts':[{'url':image}]});encoded2=media.dumps({'images':[image]})
    assert 'data:image/' not in encoded1 and 'data:image/' not in encoded2
    assert media.loads(encoded1)['parts'][0]['url']==image
    assert media.stats()['media_blobs']==1
    backup=manager.create();manager.verify(backup)
    blob=next((tmp_path/'media'/'sha256').glob('*/*'));blob.unlink()
    manager.restore(backup)
    assert media.loads(encoded2)['images']==[image]
    path=tmp_path/'session.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sessions(session_id TEXT PRIMARY KEY,messages_json TEXT)')
        db.execute('INSERT INTO sessions VALUES (?,?)',('s',json.dumps({'images':[image,image]})))
    before=checksum(path)
    dry=migrate_inline_media(path,dry_run=True,output_dir=tmp_path/'media-dry')
    assert checksum(path)==before and dry['inline_images']==2 and dry['unique_blobs']==1
    done=migrate_inline_media(path,dry_run=False,output_dir=tmp_path/'media-apply')
    with sqlite3.connect(path) as db:payload=db.execute('SELECT messages_json FROM sessions').fetchone()[0]
    assert 'data:image/' not in payload and media.loads(payload)['images']==[image,image]
    assert done['dedup_ratio']==.5


def test_session_vacuum_releases_freelist(tmp_path):
    path=tmp_path/'session.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE items(data BLOB)')
        db.executemany('INSERT INTO items VALUES (?)',[(b'x'*4096,)]*100)
        db.execute('DELETE FROM items')
    before=database_metrics(path)
    assert before['freelist_pages']>0
    after=vacuum_database(path)
    assert after['freelist_pages']==0 and after['db_size']<before['db_size'] and after['last_vacuum']


@pytest.mark.asyncio
async def test_all_three_stores_share_configured_media_and_hydrate(tmp_path):
    from zhaoxi.cognitive_stream.store import ExperienceStream
    from zhaoxi.cognitive_stream.models import CognitiveEvent, CognitiveEventType
    from zhaoxi.perception.store import PerceptionStore
    from zhaoxi.perception.models import Observation, ObservationStatus, ObservationPart
    from zhaoxi.session.sqlite import SQLiteSessionStore
    from zhaoxi.session.base import Session
    from zhaoxi.core.message import Message,Role
    from zhaoxi.core.conversation import Conversation
    image='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
    root=tmp_path/'shared-media'
    stream=ExperienceStream(tmp_path/'events'/'experience.db',media_directory=root)
    event=CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE,source='web',actor_role='OWNER',content='image',parts=[{'type':'image','url':image}])
    stream.append(event)
    perception=PerceptionStore(tmp_path/'observations'/'perception.db',media_directory=root)
    observation=Observation(source='qq',source_kind='message',parts=[ObservationPart(type='image',url=image)])
    perception.insert(observation,ObservationStatus.BUFFERED)
    sessions=SQLiteSessionStore(tmp_path/'sessions'/'session.db',media_directory=root)
    session=Session(id='s',conversation=Conversation(messages=[Message(role=Role.USER,content='image',images=[image])]))
    await sessions.save(session)
    assert stream.get(event.event_id).parts[0].url==image
    assert stream.clear_expired()==0
    assert stream.clear_expired(utc_now()+timedelta(days=91))==1
    stream.append(event)
    assert perception.buffered()[0].parts[0].url==image
    assert (await sessions.get('s')).conversation.messages[0].images==[image]
    assert MediaBlobStore(root).stats()['media_blobs']==1
    for path,table,column in [(stream.path,'events','payload'),(perception.path,'observations','payload'),(sessions.path,'sessions','messages_json')]:
        with sqlite3.connect(path) as db:stored=db.execute(f'SELECT {column} FROM {table}').fetchone()[0]
        assert 'data:image/' not in stored and '$media' in stored


@pytest.mark.asyncio
async def test_archive_stays_archived_until_explicit_activation(tmp_path):
    service=service_at(tmp_path)
    record=(await service.remember(MemoryCreate(kind='episodic',content='important history'))).record
    await service.archive(record.id)
    await service.maintain()
    assert (await service.require(record.id)).status==MemoryStatus.ARCHIVED
    await service.reactivate(record.id)
    assert (await service.require(record.id)).status==MemoryStatus.ACTIVE


@pytest.mark.asyncio
async def test_content_update_repairs_membership_and_centroids(tmp_path):
    from zhaoxi.memory.models import MemoryUpdate
    service=service_at(tmp_path)
    a=(await service.remember(MemoryCreate(kind='episodic',content='Runtime memory index one'))).record
    b=(await service.remember(MemoryCreate(kind='episodic',content='Runtime memory index two'))).record
    assert b.cluster_id
    changed=await service.update(b.id,MemoryUpdate(content='舞萌街机游戏骑行'))
    assert changed.cluster_id is None
    assert (await service.require(a.id)).cluster_id is None
    assert not any(c.active for c in await service.repository.list_clusters())


@pytest.mark.asyncio
async def test_legacy_unindexed_data_has_bounded_lexical_escape_before_offline_reindex(tmp_path):
    service=service_at(tmp_path)
    target=(await service.remember(MemoryCreate(kind='episodic',content='丘脑面试安排'))).record
    with service.repository._connect() as db:
        db.execute('DELETE FROM memories_fts')
        db.execute('DELETE FROM embedding_features')
        db.execute("DELETE FROM memory_runtime WHERE key='fts_format'")
    result=await service.search(MemoryQuery(text='丘脑面试'),activate=False)
    assert result and result[0].record.id==target.id
    assert 'fts_fallback' in result[0].candidate_source


@pytest.mark.asyncio
async def test_domain_uses_subject_evidence_and_ascii_word_boundaries(tmp_path):
    service = service_at(tmp_path)
    examples = [
        ('暗苟给朝汐看亚信面试结果和秋招岗位', '求职'),
        ('朝汐看到暗苟画的角色设定图', 'Persona'),
        ('暗苟给朝汐说寝室没有冰箱', '寝室'),
        ('LifeHUD 饮食记录接口开发', 'LifeHUD'),
        ('朝汐 Runtime Memory 召回索引重构', 'Zhaoxi开发'),
    ]
    for content, domain in examples:
        record = (await service.remember(MemoryCreate(kind='episodic', content=content))).record
        assert service._infer_topic(record) == domain
    from zhaoxi.memory.clustering import has_hint
    assert not has_hint('build quick notebook', 'ui')
    assert not has_hint('build quick notebook', 'qq')
    assert has_hint('qq 接入', 'qq')


@pytest.mark.asyncio
async def test_escape_result_reports_actual_cluster_without_promoting_it(tmp_path):
    service = service_at(tmp_path)
    await service.remember(MemoryCreate(kind='episodic', content='Runtime memory index one'))
    record = (await service.remember(MemoryCreate(kind='episodic', content='Runtime memory index two'))).record
    assert record.cluster_id
    async def no_cluster_candidates(*args, **kwargs):
        return []
    service.repository.cluster_candidates = no_cluster_candidates
    results = await service.search(MemoryQuery(text='Runtime memory index two'), activate=False)
    result = next(r for r in results if r.record.id == record.id)
    assert result.cluster.id == record.cluster_id
    assert result.cluster_rank is None and result.cluster_score == 0
    assert 'escape' in result.candidate_source and 'cluster' not in result.candidate_source


@pytest.mark.asyncio
async def test_semantic_shortlist_filters_before_limit(tmp_path):
    service = service_at(tmp_path)
    records = []
    for index in range(5):
        record = (await service.remember(MemoryCreate(kind='episodic', content=f'unique event {index}'))).record
        record.status = MemoryStatus.FORGOTTEN if index < 4 else MemoryStatus.ACTIVE
        await service.repository.save(record)
        await service.repository.save_embedding(MemoryEmbedding(memory_id=record.id,
            embedding_model='test-space', embedding_dim=16, embedding_hash=str(index),
            vector=[1.0 if index < 4 else .8, 0.0 if index < 4 else .6] + [0.0]*14))
        records.append(record)
    with service.repository._connect() as db:
        ids = service.repository._semantic_ids(db, 'memory', [1.0]+[0.0]*15,
            ('test-space', '1', 16), 1, MemoryQuery())
    assert ids == [records[-1].id]


@pytest.mark.asyncio
async def test_embedding_outage_keeps_lexical_recall_without_mixed_vectors(tmp_path):
    service = service_at(tmp_path)
    record = (await service.remember(MemoryCreate(kind='episodic', content='丘脑智能面试安排'))).record
    class UnavailableProvider:
        model, version, dimensions = 'remote-model', '1', 16
        async def embed(self, text):
            raise httpx.ConnectError('offline')
    service.embedding_provider = UnavailableProvider()
    results = await service.search(MemoryQuery(text='丘脑智能面试'), activate=False)
    assert results[0].record.id == record.id and results[0].semantic_score == 0
    assert service.last_retrieval['embedding_status'] == 'lexical_fallback'
    assert service.last_retrieval['embedding_error'] == 'ConnectError'


@pytest.mark.asyncio
async def test_automemory_drops_untrusted_runtime_fields_and_rejects_oversized_tags(tmp_path):
    service = service_at(tmp_path)
    payload = {'candidates': [
        {'kind': 'episodic', 'content': '今天读完一本书', 'importance': .95,
            'metadata': {'domain': 'invented', 'evidence_refs': ['fake']}, 'pinned': True,
            'source_event_id': 'fake', 'source_node_id': 'fake'},
        {'kind': 'episodic', 'content': '另一个事实', 'importance': .4, 'tags': ['x'*41]},
    ]}
    auto = AutoMemory(FakeProvider([ModelResponse(content=json.dumps(payload))]), service)
    decision = await auto.process('今天读完一本书，还有另一个事实', '', source_event_id='real')
    assert decision.applied_count == 1
    record = (await service.repository.list_records(MemoryQuery()))[0]
    assert not record.pinned and record.activation == .65
    assert record.source_event_id == 'real' and 'fake' not in str(record.metadata)


@pytest.mark.asyncio
async def test_legacy_decision_importance_cannot_set_runtime_heat(tmp_path):
    service = service_at(tmp_path)
    auto = AutoMemory(FakeProvider([ModelResponse(content='{"action":"create","kind":"episodic","content":"今天读完一本书","importance":1}')]), service)
    await auto.process('今天读完一本书', '')
    record = (await service.repository.list_records(MemoryQuery()))[0]
    assert record.activation == .65
    assert (await service.diagnostics())['funnel']['auto_memory_generated'] == 1


@pytest.mark.asyncio
async def test_context_never_injects_unselected_or_forgotten_cluster_summary(tmp_path):
    from zhaoxi.memory.retrieval import MemoryRetriever
    service = service_at(tmp_path)
    first = (await service.remember(MemoryCreate(kind='episodic', content='Runtime memory index private secret'))).record
    second = (await service.remember(MemoryCreate(kind='episodic', content='Runtime memory index public detail'))).record
    assert second.cluster_id
    await service.forget(first.id)
    results = await service.search(MemoryQuery(text='Runtime memory index public detail'), activate=False)
    assert first.id not in {item.record.id for item in results}
    retriever = MemoryRetriever(service, max_chars=1000)
    context = retriever.format(results)
    assert 'public detail' in context and 'private secret' not in context
    assert '<summary>' not in context and len(context) <= 1000
    results[0].cluster.topic = 'private secret topic'
    assert 'private secret' not in retriever.format(results)
    assert 'private secret' not in '; '.join(service._why(results[0]))


def test_context_quotes_labels_and_counts_closing_tags_within_budget(tmp_path):
    from zhaoxi.memory.retrieval import MemoryRetriever
    from zhaoxi.memory.models import MemoryRecord, MemoryCluster, MemorySearchResult
    import xml.etree.ElementTree as ET
    service = service_at(tmp_path)
    record = MemoryRecord(**MemoryCreate(kind='episodic',content='A safe fact',source='quoted " source').model_dump(exclude_none=True),normalized_content='asafefact')
    cluster = MemoryCluster(topic='quoted " topic', member_count=2)
    item = MemorySearchResult(record=record, cluster=cluster)
    context = MemoryRetriever(service, max_chars=700).format([item])
    assert context and len(context) <= 700
    fragment = context[context.index('<memory-topic'):]
    ET.fromstring(fragment)
    assert MemoryRetriever(service, max_chars=200).format([item]) == ''


@pytest.mark.asyncio
async def test_relative_extracted_time_keeps_fact_without_inventing_timestamp(tmp_path):
    service = service_at(tmp_path)
    output = {'candidates': [
        {'kind':'episodic','content':'今天中午吃了番茄鸡蛋面','importance':.15,'event_at':'今天中午'},
        {'kind':'intent','content':'这周想固定午餐时间','importance':.4,'event_at':'这周'},
    ]}
    decision = await AutoMemory(FakeProvider([ModelResponse(content=json.dumps(output))]),service).process('今天中午吃了面，这周想固定午餐时间','')
    assert decision.extraction_status == 'completed' and decision.applied_count == 2
    records = await service.repository.list_records(MemoryQuery())
    assert all(record.event_at is None for record in records)



def test_provider_configuration_cannot_silently_ignore_a_semantic_space():
    from zhaoxi.memory.embedding import provider_from_settings
    from zhaoxi.errors import ConfigError
    assert provider_from_settings(Settings(_env_file=None,memory_embedding_dim=512)).dimensions == 512
    with pytest.raises(ConfigError):
        provider_from_settings(Settings(_env_file=None,memory_embedding_model='semantic-model'))
    with pytest.raises(ConfigError):
        provider_from_settings(Settings(_env_file=None,memory_embedding_base_url='https://embedding.invalid/v1'))
    provider = provider_from_settings(Settings(_env_file=None,memory_embedding_base_url='https://embedding.invalid/v1',
        memory_embedding_model='semantic-model',memory_embedding_dim=1024,memory_embedding_version='2'))
    assert (provider.model,provider.version,provider.dimensions) == ('semantic-model','2',1024)


@pytest.mark.asyncio
async def test_semantic_batch_orders_vectors_and_rejects_missing_indices():
    calls = []
    def handler(request):
        payload=json.loads(request.content); calls.append(payload)
        rows=[{'index':1,'embedding':[0,4]+[0]*14}, {'index':0,'embedding':[3,0]+[0]*14}]
        if payload['input'][0]=='bad': rows[0]['index']=0
        return httpx.Response(200,json={'data':rows})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider=SemanticEmbeddingProvider(base_url='https://embedding.invalid/v1',api_key='test',model='semantic',dimensions=16,client=client)
        vectors=await provider.embed_many(['first','second'])
        assert vectors[0][0]==1 and vectors[1][1]==1
        with pytest.raises(ValueError,match='indices'): await provider.embed_many(['bad','second'])
        with pytest.raises(ValueError,match='at most'): await provider.embed_many(['x']*11)
        assert len(calls)==2


@pytest.mark.asyncio
async def test_offline_semantic_rebuild_batches_and_reuses_compatible_vectors(tmp_path):
    service=service_at(tmp_path)
    for i in range(23):
        await service.remember(MemoryCreate(kind='episodic',content=f'batch fixture {i}'))
    class BatchProvider(LocalHashEmbeddingProvider):
        model='semantic-fixture'
        calls=[]
        async def embed_many(self,texts):
            self.calls.append(len(texts))
            return [await self.embed(text) for text in texts]
    provider=BatchProvider()
    path=tmp_path/'memory.db'
    await migrate(path,action='rebuild_memory_embeddings',dry_run=False,
        output_dir=tmp_path/'first',embedding_provider=provider)
    assert provider.calls==[10,10,3]
    rows=await service.repository.embeddings_for([r.id for r in await service.repository.list_records(MemoryQuery(limit=100))])
    assert len(rows)==23 and all(e.embedding_model=='semantic-fixture' and e.embedding_dim==256 for e in rows.values())
    provider.calls.clear()
    await migrate(path,action='rebuild_memory_embeddings',dry_run=False,
        output_dir=tmp_path/'second',embedding_provider=provider)
    assert provider.calls==[]


def test_domain_prior_is_soft_and_does_not_treat_arbitrary_tags_as_domains():
    from zhaoxi.memory.clustering import domain_prior
    assert domain_prior('求职','求职')==1
    assert domain_prior('求职','Persona')==.6
    assert domain_prior('求职',None)==.8
    assert domain_prior('摄影','天空')==1
    # Near-identical cross-domain events may still exceed the membership gate.
    assert .98*.68*domain_prior('寝室','饮酒')>.38


def test_concrete_topic_in_body_outweighs_unrelated_legacy_tag(tmp_path):
    from zhaoxi.memory.models import MemoryRecord
    service=service_at(tmp_path)
    record=MemoryRecord(**MemoryCreate(content='朝汐计划今晚接 QQ 接口',tags=['简历'],source='fixture').model_dump(exclude_none=True),normalized_content='fixture')
    assert service._infer_topic(record)=='Zhaoxi开发'


@pytest.mark.asyncio
async def test_semantic_postings_use_dimension_index_before_grouping(tmp_path):
    service=service_at(tmp_path)
    record=(await service.remember(MemoryCreate(content='indexed semantic fixture'))).record
    vector=(await service.repository.embeddings_for([record.id]))[record.id].vector
    plans=[]
    class Explain:
        def __init__(self,db):self.db=db
        def execute(self,sql,args):
            plans.extend(row[3] for row in self.db.execute('EXPLAIN QUERY PLAN '+sql,args))
            return self.db.execute(sql,args)
    with service.repository._connect() as db:
        ids=service.repository._semantic_ids(Explain(db),'memory',vector,('local-hash-v1','1',256),10,MemoryQuery())
    assert record.id in ids
    assert any('idx_embedding_features_covering' in line and 'dimension=?' in line and 'sign=?' in line for line in plans)


@pytest.mark.asyncio
async def test_selected_clusters_share_candidate_budget(tmp_path):
    service=service_at(tmp_path)
    ids=[]
    for i in range(50):
        r=(await service.remember(MemoryCreate(content=f'candidate budget runtime fixture {i}'))).record
        ids.append(r.id)
    vector=(await service.repository.embeddings_for([ids[0]]))[ids[0]].vector
    clusters=[c.id for c in await service.repository.list_clusters() if c.active][:5]
    rows=await service.repository.candidate_records(MemoryQuery(text='runtime fixture'),vector,('local-hash-v1','1',256),clusters,limit=40)
    assert len(rows)<=80
    assert any('fts' in sources for _,sources in rows)
    assert any('semantic' in sources for _,sources in rows)


def test_cluster_summary_participates_in_merge_and_focus_requires_confidence():
    from zhaoxi.memory.models import MemoryCluster
    from zhaoxi.memory.search import cluster_limits
    service=MemoryService(None)
    left=MemoryCluster(topic='generic',centroid_embedding=[1,0],embedding_dim=2,summary='event alpha')
    same=left.model_copy(update={'id':'same'})
    different=left.model_copy(update={'id':'different','summary':'unrelated beta'})
    assert service._cluster_similarity(left,same)>service._cluster_similarity(left,different)
    query=MemoryQuery(text='remember event',limit=6,per_cluster_limit=2)
    limits,focused=cluster_limits(query,RetrievalMode.EXPLICIT_RECALL,[(.8,left),(.5,different)])
    assert focused and limits[left.id]==6 and limits[different.id]==2
    limits,focused=cluster_limits(query,RetrievalMode.EXPLICIT_RECALL,[(.8,left),(.75,different)])
    assert not focused and limits[left.id]==2


@pytest.mark.asyncio
async def test_batched_owner_extraction_keeps_real_selected_evidence(tmp_path):
    from zhaoxi.cognitive_stream.models import CognitiveEvent,CognitiveEventType
    events=[CognitiveEvent(event_id=f'e{i}',event_type=CognitiveEventType.EXTERNAL_MESSAGE,source='qq',actor_role='OWNER',trust_level='TRUSTED',content=f'Owner fact {i}',source_refs=[f'm{i}']) for i in range(2)]
    provider=FakeProvider([ModelResponse(content=json.dumps({'candidates':[{'kind':'episodic','content':'Owner fact 1','importance':.4,'evidence_refs':['e1','invented']}]}))])
    service=service_at(tmp_path)
    decision=await AutoMemory(provider,service).process_events(events)
    assert decision.applied_count==1
    record=(await service.repository.list_records(MemoryQuery()))[0]
    assert record.source_event_id=='e1' and record.source_message_ids==['m1']
    assert record.metadata['evidence_refs']==['e1'] and record.metadata['evidence_scope']=='selected_events'
    assert record.metadata['reason']


@pytest.mark.asyncio
async def test_offline_migration_seed_reuses_only_matching_content(tmp_path):
    source=service_at(tmp_path)
    record=(await source.remember(MemoryCreate(content='unchanged seed fact'))).record
    seed=tmp_path/'seed.db'
    from zhaoxi.memory.migration import snapshot
    snapshot(source.repository.path,seed)
    with sqlite3.connect(source.repository.path) as db:
        db.execute('DELETE FROM memory_embeddings')
    class NoRequests(LocalHashEmbeddingProvider):
        async def embed(self,text):raise AssertionError('matching seed must avoid embedding calls')
    result=await migrate(source.repository.path,dry_run=True,embedding_provider=NoRequests(),embedding_snapshot=seed,output_dir=tmp_path/'preview')
    assert result['reused_seed_embeddings']==1
    assert result['after']['embedding_versions'][0]['count']==1
    assert result['publication_status']=='planned'
