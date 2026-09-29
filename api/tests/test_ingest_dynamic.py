from openpyxl import Workbook
from app.ingest import parse_workbook

def test_dynamic_workbook_parser(tmp_path):
    p=tmp_path/'sample.xlsx'; wb=Workbook(); ws=wb.active; ws.title='poles'
    ws.append(['internal_id','pole_number','grade_of_construction','latitude','longitude','bottom_elev_ft','top_lat','top_lon','top_elev_ft','other_1_type','other_1_id','other_1_lat','other_1_lon','other_1_elev_ft','remarks'])
    ws.append([1,'P-100','A',34.37,-118.91,500,34.37,-118.91,540,'OTHER_POLE',1,34.37,-118.91,520,None])
    ws.append([2,'P-100','A',34.371,-118.911,501,34.371,-118.911,541,None,None,None,None,None,None])
    for name in ['attachments','crossarms','equipment','anchors','guys','sidewalk_braces','span_guys']:
        s=wb.create_sheet(name); s.append(['internal_id','pole_number'])
    wb.save(p)
    out=parse_workbook(str(p),'EPSG:6424')
    assert len(out['poles'])==2
    assert len([f for f in out['features'] if f['properties']['feature_type']=='pole'])==2
    assert any(f['rule_id']=='PLA-R006' and f['severity']=='FAIL' for f in out['findings'])
    dup=[f for f in out['findings'] if f['rule_id']=='PLA-R002']
    assert len(dup)==2
