import json, math, re, uuid
from collections import Counter, defaultdict
from openpyxl import load_workbook
from pyproj import Transformer

EXPECTED_SHEETS=['poles','attachments','crossarms','equipment','anchors','guys','sidewalk_braces','span_guys']

def val(v):
    if v is None: return None
    if isinstance(v,str):
        v=v.strip()
        return v if v else None
    return v

def num(v):
    try:
        if v is None or v=='': return None
        if isinstance(v,str): v=v.strip().lstrip(',').strip()
        return float(v)
    except Exception: return None

def as_int(v):
    n=num(v)
    return int(n) if n is not None and float(n).is_integer() else None

def rows_by_header(ws):
    headers=[val(c.value) for c in next(ws.iter_rows(min_row=1,max_row=1))]
    for row in ws.iter_rows(min_row=2, values_only=True):
        d={headers[i]:val(row[i]) for i in range(min(len(headers),len(row))) if headers[i]}
        if as_int(d.get('internal_id')) is not None:
            yield d

def project_transformer(crs):
    return Transformer.from_crs('EPSG:4326',crs,always_xy=True)

def point_feature(internal_id, feature_type, xyz, **props):
    p={'feature_type':feature_type,'internal_id':internal_id,**props}
    return {'type':'Feature','properties':p,'geometry':{'type':'Point','coordinates':[float(x) for x in xyz]}}

def line_feature(internal_id, feature_type, a,b, **props):
    p={'feature_type':feature_type,'internal_id':internal_id,**props}
    return {'type':'Feature','properties':p,'geometry':{'type':'LineString','coordinates':[[float(x) for x in a],[float(x) for x in b]]}}

def parse_workbook(path:str, crs='EPSG:6424'):
    wb=load_workbook(path, read_only=True, data_only=True)
    if 'poles' not in wb.sheetnames: raise ValueError('Workbook must contain a poles sheet')
    tf=project_transformer(crs)
    sheets={s:list(rows_by_header(wb[s])) if s in wb.sheetnames else [] for s in EXPECTED_SHEETS}
    poles=[]; features=[]; findings=[]; byid={}

    def addfinding(rule,severity,pid,pnum,sheet,field,message,actual=None,expected=None,related=None):
        findings.append({'id':f'F{len(findings)+1:04d}-{uuid.uuid4().hex[:6]}','rule_id':rule,'severity':severity,
            'internal_id':pid,'pole_number':pnum,'sheet':sheet,'field':field,'message':message,
            'actual':None if actual is None else str(actual),'expected':expected,'related_poles':related or [],'status':'OPEN'})

    for r in sheets['poles']:
        pid=as_int(r.get('internal_id')); pnum=val(r.get('pole_number'))
        lat=num(r.get('latitude')); lon=num(r.get('longitude')); z0=num(r.get('bottom_elev_ft')); z1=num(r.get('top_elev_ft'))
        top_lat=num(r.get('top_lat')) or lat; top_lon=num(r.get('top_lon')) or lon
        remarks=val(r.get('remarks'))
        manifest={k:v for k,v in r.items() if v is not None}
        p={'internal_id':pid,'pole_number':pnum,'corrected_lat':lat,'corrected_lon':lon,'bottom_elev_ft':z0,'top_elev_ft':z1,'remarks':remarks,'manifest':manifest}
        poles.append(p); byid[pid]=p
        if lat is None or lon is None or z0 is None or top_lat is None or top_lon is None or z1 is None:
            sev='UNVERIFIABLE' if remarks and 'not visible' in remarks.lower() else 'FAIL'
            addfinding('PLA-R003',sev,pid,pnum,'poles','latitude/longitude/elevation','Pole lacks complete measurable 3D geometry.',
                       actual=f'lat={lat}, lon={lon}, bottom={z0}, top={z1}',expected='complete base/top geometry')
        else:
            x0,y0=tf.transform(lon,lat); x1,y1=tf.transform(top_lon,top_lat)
            features.append(line_feature(pid,'pole',[x0,y0,z0],[x1,y1,z1],pole_number=pnum,bottom_elev_ft=z0,top_elev_ft=z1))
        if not val(r.get('grade_of_construction')):
            addfinding('PLA-R014','REVIEW',pid,pnum,'poles','grade_of_construction','Grade of construction is blank.',None,'verify grade or accepted blank')
        for n in range(1,6):
            typ=val(r.get(f'other_{n}_type')); oid=as_int(r.get(f'other_{n}_id'))
            olat=num(r.get(f'other_{n}_lat')); olon=num(r.get(f'other_{n}_lon')); oe=num(r.get(f'other_{n}_elev_ft'))
            if oid==pid:
                addfinding('PLA-R006','FAIL',pid,pnum,'poles',f'other_{n}_id',f'Other connection self-references internal_id {pid}.',oid,'different internal_id')
            if oid and (olat is not None or olon is not None or oe is not None):
                addfinding('PLA-R006','FAIL',pid,pnum,'poles',f'other_{n}_xyz',f'In-scope Other {n} has internal_id and XYZ; in-scope connections should use the pole reference.',
                           f'id={oid}, xyz={olat},{olon},{oe}','ID reference without duplicate XYZ')

    # duplicate pole numbers -> REVIEW
    nums=defaultdict(list)
    for p in poles:
        if p['pole_number']: nums[p['pole_number']].append(p['internal_id'])
    for pnum,ids in nums.items():
        if len(ids)>1:
            for pid in ids:
                addfinding('PLA-R002','REVIEW',pid,pnum,'poles','pole_number',f'pole_number {pnum} appears on multiple internal_ids {ids}',pnum,'unique unless verified',[x for x in ids if x!=pid])

    # generic point layers
    specs=[
      ('attachments','comm','attachment',9,{'owner':'owner','size':'size','support':'support','arm_no':'arm_no','lat':'lat','lon':'lon','elev_ft':'elev_ft'}),
      ('attachments','util','attachment',21,{'usage':'usage','owner':'owner','size':'size','support':'support','arm_no':'arm_no','lat':'lat','lon':'lon','elev_ft':'elev_ft'}),
      ('equipment','eq','equipment',8,{'key':'key','owner':'owner','lat':'lat','lon':'lon','elev_ft':'elev_ft'}),
      ('anchors','anc','anchor',4,{'key':'key','owner':'owner','lat':'lat','lon':'lon','elev_ft':'elev_ft'}),
      ('crossarms','arm','crossarm',8,{'key':'key','owner':'owner','lat':'tip_lat','lon':'tip_lon','elev_ft':'elev_ft'}),
    ]
    for sheet,prefix,ftype,count,fields in specs:
        for r in sheets.get(sheet,[]):
            pid=as_int(r.get('internal_id')); pnum=val(r.get('pole_number'))
            for i in range(1,count+1):
                key=val(r.get(f'{prefix}_{i}_{fields.get("key","key")}')) if 'key' in fields else None
                owner=val(r.get(f'{prefix}_{i}_{fields.get("owner","owner")}')) if 'owner' in fields else None
                usage=val(r.get(f'{prefix}_{i}_{fields.get("usage","usage")}')) if 'usage' in fields else None
                lat=num(r.get(f'{prefix}_{i}_{fields["lat"]}')); lon=num(r.get(f'{prefix}_{i}_{fields["lon"]}')); elev=num(r.get(f'{prefix}_{i}_{fields["elev_ft"]}'))
                present=key or owner or usage or lat is not None or lon is not None or elev is not None
                if not present: continue
                if lat is not None and lon is not None and elev is not None:
                    x,y=tf.transform(lon,lat)
                    features.append(point_feature(pid,ftype,[x,y,elev],category=prefix,index=i,key=key,owner=owner,usage=usage,pole_number=pnum))
                elif ftype in ('equipment','anchor','crossarm'):
                    # no auto-fail for crossarms because SOW has conflicting instructions; review missing geometry only when partially populated
                    if any(v is not None for v in (lat,lon,elev)):
                        addfinding('PLA-R020','REVIEW',pid,pnum,sheet,f'{prefix}_{i}_geometry',f'{ftype.title()} {i} has partial XYZ geometry.',f'{lat},{lon},{elev}','complete XYZ or accepted blank')
                if ftype=='equipment' and key and not owner:
                    addfinding('PLA-R021','REVIEW',pid,pnum,sheet,f'{prefix}_{i}_owner',f'Equipment {i} has a key but owner is blank.',None,'owner or explicit UNKNOWN')

    # guys -> line to anchors when possible
    anchor_pts=defaultdict(dict)
    for f in features:
        if f['properties'].get('feature_type')=='anchor': anchor_pts[f['properties']['internal_id']][f['properties']['index']]=f['geometry']['coordinates']
    pole_lines={f['properties']['internal_id']:f for f in features if f['properties'].get('feature_type')=='pole'}
    for r in sheets['guys']:
        pid=as_int(r.get('internal_id')); pnum=val(r.get('pole_number'))
        for i in range(1,9):
            key=val(r.get(f'guy_{i}_key')); owner=val(r.get(f'guy_{i}_owner')); anc=as_int(r.get(f'guy_{i}_anchor_no')); elev=num(r.get(f'guy_{i}_elev_ft'))
            if not any(x is not None for x in (key,owner,anc,elev)): continue
            if anc and anc not in anchor_pts.get(pid,{}):
                addfinding('PLA-R010','FAIL',pid,pnum,'guys',f'guy_{i}_anchor_no',f'Guy {i} references missing anchor {anc}.',anc,'existing anchor number')
            if anc in anchor_pts.get(pid,{}) and elev is not None and pid in pole_lines:
                top=pole_lines[pid]['geometry']['coordinates'][1]
                start=[top[0],top[1],elev]
                features.append(line_feature(pid,'guy',start,anchor_pts[pid][anc],index=i,anchor_no=anc,key=key,owner=owner,pole_number=pnum))

    # sidewalk braces: missing guy_nos when brace exists
    for r in sheets['sidewalk_braces']:
        pid=as_int(r.get('internal_id')); pnum=val(r.get('pole_number'))
        for i in (1,2):
            key=val(r.get(f'swb_{i}_key')); guys=val(r.get(f'swb_{i}_guy_nos'))
            if key and not guys:
                addfinding('PLA-R012','FAIL',pid,pnum,'sidewalk_braces',f'swb_{i}_guy_nos',f'Sidewalk brace {i} exists but guy numbers are blank.',None,'one or more guy numbers')

    # span guy references: ensure runs_to token exists; explicit OTHER_n must be defined on poles row
    pole_rows={as_int(r.get('internal_id')):r for r in sheets['poles']}
    for r in sheets['span_guys']:
        pid=as_int(r.get('internal_id')); pnum=val(r.get('pole_number'))
        for i in range(1,6):
            key=val(r.get(f'sgy_{i}_key')); runs=val(r.get(f'sgy_{i}_runs_to')); end=val(r.get(f'sgy_{i}_end_type'))
            if not any((key,runs,end)): continue
            if runs and str(runs).upper().startswith('OTHER_'):
                n=as_int(str(runs).split('_')[-1]); prow=pole_rows.get(pid,{})
                if n and not (as_int(prow.get(f'other_{n}_id')) or val(prow.get(f'other_{n}_type'))):
                    addfinding('PLA-R030','FAIL',pid,pnum,'span_guys',f'sgy_{i}_runs_to',f'Span guy {i} references {runs}, but that Other connection is not defined.',runs,'defined Other connection')

    return {'poles':poles,'features':features,'findings':findings,'sheets':list(wb.sheetnames)}
