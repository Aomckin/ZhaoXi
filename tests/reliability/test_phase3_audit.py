"""Check missing-evidence accounting; these fixtures are not acceptance samples."""
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
spec=spec_from_file_location('phase3_audit',Path(__file__).resolve().parents[2]/'scripts/phase3_reliability_audit.py')
module=module_from_spec(spec)
spec.loader.exec_module(module)
audit=module.audit


NOW=datetime(2026,10,14,12,tzinfo=UTC)


def entry(identity,event,metadata):
    return f'2026-10-13 12:00:00,000 INFO trace=- request=- trace=t request={identity} event={event} metadata={metadata!r}\n'


def test_ingress_without_terminal_receipt_stays_in_denominator(tmp_path):
    path=tmp_path/'zhaoxi.log'
    start={'build_id':'b','configuration_id':'p','started_at':'2026-10-13T04:00:00+00:00'}
    terminal={**start,'request_id':'one','result_status':'completed','response_status':'succeeded'}
    path.write_text(entry('one','request_started',start)+entry('one','runtime_metrics_finalized',{'runtime_metrics':terminal})+
        entry('one','reply_render_confirmed',{})+entry('lost','request_started',start),encoding='utf-8')
    report=audit([path],now=NOW)['builds'][0]
    assert report['requests']==2 and report['verified_completed']==1
    assert report['missing_runtime_receipts']==1 and report['confirmed_completion_ratio']==.5
    assert report['delivery_window']=='pending'


def test_profiles_do_not_mix_and_duplicate_does_not_replace_completion(tmp_path):
    path=tmp_path/'zhaoxi.log'
    text=''
    for identity,profile in [('one','p1'),('two','p2')]:
        start={'build_id':'b','configuration_id':profile,'started_at':'2026-10-13T04:00:00+00:00'}
        terminal={**start,'request_id':identity,'result_status':'completed','response_status':'succeeded'}
        text+=entry(identity,'request_started',start)+entry(identity,'runtime_metrics_finalized',{'runtime_metrics':terminal})
    text+=entry('one','runtime_metrics_finalized',{'runtime_metrics':{'result_status':'duplicate'}})
    path.write_text(text,encoding='utf-8')
    rows=audit([path],now=NOW)['builds']
    assert len(rows)==2 and all(row['statuses']=={'completed':1} for row in rows)
    assert all(row['verified_completed']==0 for row in rows)


def test_pending_and_permission_delivery_have_distinct_business_status(tmp_path):
    path=tmp_path/'zhaoxi.log'
    start={'build_id':'b','configuration_id':'p','started_at':NOW.isoformat(),'request_timeout_seconds':60}
    old={**start,'started_at':'2026-10-13T04:00:00+00:00','request_id':'permission',
         'result_status':'waiting_for_permission','response_status':'waiting_for_permission'}
    path.write_text(entry('pending','request_started',start)+entry('permission','request_started',old)+
        entry('permission','runtime_metrics_finalized',{'runtime_metrics':old})+entry('permission','reply_render_confirmed',{}),encoding='utf-8')
    report=audit([path],now=NOW)
    assert report['pending_requests']==1
    row=report['builds'][0]
    assert row['verified_completed']==0 and row['permission_stage_confirmed']==1
    assert row['confirmed_current_stage_ratio']==1