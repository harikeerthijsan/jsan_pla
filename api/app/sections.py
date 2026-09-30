import csv, hashlib, json, math, os, pathlib, random, tempfile
from dataclasses import dataclass
from sqlalchemy.orm import Session
from .models import Project, Pole, Finding, SceneFeature, LidarBlock
from pyproj import Transformer
from .storage import MODE, local_path, block_url, upload_from, object_exists, download_to
from .workflow import DatasetVersion


def _pole_feature(db: Session, project_id: str, internal_id: int):
    row = db.query(SceneFeature).filter_by(project_id=project_id, internal_id=internal_id, feature_type='pole').first()
    return json.loads(row.payload_json) if row else None


def _base_xy(feature):
    if not feature or feature.get('geometry', {}).get('type') != 'LineString':
        return None
    c = feature['geometry']['coordinates']
    if not c:
        return None
    return float(c[0][0]), float(c[0][1]), float(c[0][2])


def _pole_anchor(db: Session, project_id: str, internal_id: int):
    """Return an analysis anchor even when the workbook has only source/pre-pop lat/lon.

    Priority:
      1) complete delivery 3D pole feature
      2) pole latitude/longitude transformed into the project CRS

    Z is used only as a camera/reference hint for the local frame. When delivery bottom
    elevation is blank, use the mapped LiDAR block minimum Z when available.
    """
    feat = _pole_feature(db, project_id, internal_id)
    base = _base_xy(feat)
    if base:
        return {'xyz': base, 'source': 'delivery_3d', 'has_3d': True}

    pole = db.query(Pole).filter_by(project_id=project_id, internal_id=internal_id).first()
    if not pole or pole.corrected_lat is None or pole.corrected_lon is None:
        return None
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        return None
    tf = Transformer.from_crs('EPSG:4326', project.crs, always_xy=True)
    x, y = tf.transform(float(pole.corrected_lon), float(pole.corrected_lat))
    z = pole.bottom_elev_ft
    if z is None and pole.block_name:
        block = db.query(LidarBlock).filter_by(project_id=project_id, name=pole.block_name).first()
        if block and block.zmin is not None:
            z = float(block.zmin)
    if z is None:
        z = 0.0
    return {'xyz': (float(x), float(y), float(z)), 'source': 'source_xy', 'has_3d': False}


def _center(feature):
    if not feature:
        return None
    g = feature['geometry']
    if g['type'] == 'Point':
        c = g['coordinates']; return float(c[0]), float(c[1]), float(c[2])
    if g['type'] == 'LineString' and g['coordinates']:
        pts = g['coordinates']
        return (sum(float(p[0]) for p in pts)/len(pts), sum(float(p[1]) for p in pts)/len(pts), sum(float(p[2]) for p in pts)/len(pts))
    return None


def choose_target(db: Session, project_id: str, internal_id: int, requested: int | None = None):
    primary = _pole_anchor(db, project_id, internal_id)
    p0 = primary['xyz'] if primary else None
    if not p0:
        return None
    if requested and requested != internal_id and _pole_anchor(db, project_id, requested):
        return requested

    # Prefer a rule-linked pole because it best matches the current QC evidence.
    findings = db.query(Finding).filter_by(project_id=project_id, internal_id=internal_id).all()
    for f in findings:
        for rid in json.loads(f.related_poles_json or '[]'):
            try: rid = int(rid)
            except Exception: continue
            if rid != internal_id and _pole_anchor(db, project_id, rid):
                return rid

    # Otherwise use the closest locatable pole. It may have complete delivery 3D or only source XY.
    best = None
    for p in db.query(Pole).filter(Pole.project_id == project_id, Pole.internal_id != internal_id).all():
        anchor = _pole_anchor(db, project_id, p.internal_id)
        q = anchor['xyz'] if anchor else None
        if not q: continue
        d2 = (q[0]-p0[0])**2 + (q[1]-p0[1])**2
        if best is None or d2 < best[0]:
            best = (d2, p.internal_id)
    return best[1] if best else None


def build_frame(db: Session, project_id: str, internal_id: int, target_internal_id: int | None = None):
    primary = _pole_anchor(db, project_id, internal_id)
    p0 = primary['xyz'] if primary else None
    if not p0:
        raise ValueError(f'Pole {internal_id} cannot be located: no delivery 3D geometry and no usable latitude/longitude')
    target_id = choose_target(db, project_id, internal_id, target_internal_id)
    if target_id is None:
        # Fallback east-facing local frame for isolated poles.
        return {
            'primary_internal_id': internal_id, 'target_internal_id': None,
            'origin': [p0[0], p0[1], p0[2]], 'ux': [1.0, 0.0], 'uy': [0.0, 1.0],
            'length': 0.0, 'target': None,
            'primary_source': primary['source'], 'primary_has_3d': primary['has_3d'],
            'target_source': None, 'target_has_3d': False,
        }
    target = _pole_anchor(db, project_id, target_id)
    p1 = target['xyz']
    dx, dy = p1[0]-p0[0], p1[1]-p0[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        ux = (1.0, 0.0)
    else:
        ux = (dx/length, dy/length)
    uy = (-ux[1], ux[0])
    return {
        'primary_internal_id': internal_id, 'target_internal_id': target_id,
        'origin': [p0[0], p0[1], p0[2]], 'ux': [ux[0], ux[1]], 'uy': [uy[0], uy[1]],
        'length': length, 'target': [p1[0], p1[1], p1[2]],
        'primary_source': primary['source'], 'primary_has_3d': primary['has_3d'],
        'target_source': target['source'], 'target_has_3d': target['has_3d'],
    }


def project_xyz(frame, xyz):
    x, y, z = map(float, xyz[:3])
    ox, oy = frame['origin'][:2]
    dx, dy = x-ox, y-oy
    ux, uy = frame['ux'], frame['uy']
    station = dx*ux[0] + dy*ux[1]
    offset = dx*uy[0] + dy*uy[1]
    return station, offset, z


def project_features(frame, features):
    out = []
    for feat in features:
        g = feat.get('geometry') or {}
        props = feat.get('properties') or {}
        if g.get('type') == 'Point':
            s, o, z = project_xyz(frame, g['coordinates'])
            out.append({'properties': props, 'geometry': {'type':'Point','plan':[s,o],'profile':[s,z],'cross':[o,z]}, 'source_geometry': g})
        elif g.get('type') == 'LineString':
            pts = [project_xyz(frame, c) for c in g.get('coordinates', [])]
            out.append({'properties': props, 'geometry': {
                'type':'LineString',
                'plan': [[s,o] for s,o,z in pts],
                'profile': [[s,z] for s,o,z in pts],
                'cross': [[o,z] for s,o,z in pts],
            }, 'source_geometry': g})
    return out


def vector_analysis(db: Session, project_id: str, internal_id: int, target_internal_id: int | None = None):
    frame = build_frame(db, project_id, internal_id, target_internal_id)
    ids = [internal_id] + ([frame['target_internal_id']] if frame.get('target_internal_id') else [])
    feats = [json.loads(x.payload_json) for x in db.query(SceneFeature).filter(SceneFeature.project_id==project_id, SceneFeature.internal_id.in_(ids)).all()]
    return {'frame': frame, 'features': project_features(frame, feats)}


def _section_cache_key(project_id, internal_id, target_id, width, depth, resolution, max_points, version_id=None):
    raw = f'{project_id}|{version_id or "legacy"}|{internal_id}|{target_id}|{width:.3f}|{depth:.3f}|{resolution:.3f}|{max_points}'
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def section_result_key(project_id, internal_id, target_id, width, depth, resolution, max_points, version_id=None):
    h = _section_cache_key(project_id, internal_id, target_id, width, depth, resolution, max_points, version_id)
    version_part = f'/versions/{version_id}' if version_id else ''
    return f'{project_id}{version_part}/analysis/section-p{internal_id}-t{target_id or 0}-{h}.json'


def _pdal_source(block: LidarBlock):
    if MODE == 'local':
        return str(local_path(block.object_key))
    return block_url(block.object_key)


def _run_pipeline(pipeline, workdir):
    pipe = pathlib.Path(workdir)/'section-pipeline.json'
    pipe.write_text(json.dumps(pipeline), encoding='utf-8')
    import subprocess
    exe = os.getenv('PDAL_BIN','pdal')
    p = subprocess.run([exe, 'pipeline', str(pipe)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f'PDAL section extraction failed: {p.stderr or p.stdout}')


def _reservoir_append(buf, item, seen, max_points, rng):
    if len(buf) < max_points:
        buf.append(item)
    else:
        j = rng.randint(0, seen)
        if j < max_points:
            buf[j] = item


def generate_lidar_section(db: Session, project_id: str, internal_id: int, target_internal_id: int | None,
                           width: float = 12.0, depth: float = 12.0, resolution: float = 0.5,
                           max_points: int = 90000):
    analysis = vector_analysis(db, project_id, internal_id, target_internal_id)
    frame = analysis['frame']; target_id = frame.get('target_internal_id')
    current_version = db.query(DatasetVersion).filter_by(project_id=project_id).order_by(DatasetVersion.version_no.desc()).first()
    key = section_result_key(project_id, internal_id, target_id, width, depth, resolution, max_points, current_version.id if current_version else None)
    if object_exists(key):
        return key

    pole_ids = [internal_id] + ([target_id] if target_id else [])
    poles = db.query(Pole).filter(Pole.project_id==project_id, Pole.internal_id.in_(pole_ids)).all()
    block_names = sorted({p.block_name for p in poles if p.block_name})
    blocks = db.query(LidarBlock).filter(LidarBlock.project_id==project_id, LidarBlock.name.in_(block_names)).all()
    if not blocks:
        result = {**analysis, 'points': [], 'point_count':0, 'note':'No mapped LiDAR block for selected evidence'}
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as fh:
            json.dump(result, fh); tmpname=fh.name
        try: upload_from(tmpname,key,'application/json')
        finally: pathlib.Path(tmpname).unlink(missing_ok=True)
        return key

    ox, oy = frame['origin'][:2]
    length = float(frame.get('length') or 0.0)
    ux, uy = frame['ux'], frame['uy']
    # Corridor bounding rectangle. Exact rotation filtering happens after PDAL spatial selection.
    margin = max(width, 8.0)
    ends = [(ox-margin*ux[0], oy-margin*ux[1]),
            (ox+(length+margin)*ux[0], oy+(length+margin)*ux[1])]
    vx, vy = uy
    corners=[]
    half = width/2 + 2.0
    for x,y in ends:
        corners += [(x+half*vx,y+half*vy),(x-half*vx,y-half*vy)]
    xmin=min(x for x,y in corners); xmax=max(x for x,y in corners)
    ymin=min(y for x,y in corners); ymax=max(y for x,y in corners)
    zmins=[b.zmin for b in blocks if b.zmin is not None]; zmaxs=[b.zmax for b in blocks if b.zmax is not None]
    zmin=min(zmins)-5 if zmins else None; zmax=max(zmaxs)+5 if zmaxs else None
    bounds = f'([{xmin},{xmax}],[{ymin},{ymax}]' + (f',[{zmin},{zmax}])' if zmin is not None and zmax is not None else ')')
    if zmin is not None and zmax is not None:
        bounds = f'([{xmin},{xmax}],[{ymin},{ymax}],[{zmin},{zmax}])'
    else:
        bounds = f'([{xmin},{xmax}],[{ymin},{ymax}])'

    rng = random.Random(42)
    sampled=[]; seen=-1
    with tempfile.TemporaryDirectory(prefix='pla-section-') as td:
        for bi, block in enumerate(blocks):
            csvpath = pathlib.Path(td)/f'{bi}.csv'
            reader = {'type':'readers.copc','filename':_pdal_source(block),'bounds':bounds,'resolution':float(resolution)}
            writer = {'type':'writers.text','filename':str(csvpath),'format':'csv','order':'X:3,Y:3,Z:3,Classification:0,Intensity:0','keep_unspecified':False}
            _run_pipeline([reader, writer], td)
            if not csvpath.exists():
                continue
            with csvpath.open(newline='', encoding='utf-8-sig') as fh:
                for row in csv.DictReader(fh):
                    try:
                        xyz=(float(row['X']),float(row['Y']),float(row['Z']))
                        station, offset, elev = project_xyz(frame, xyz)
                    except Exception:
                        continue
                    # Profile corridor: from slightly behind primary through target, with requested width.
                    if station < -margin or station > length+margin or abs(offset) > width/2:
                        continue
                    seen += 1
                    item={'station':round(station,3),'offset':round(offset,3),'z':round(elev,3),
                          'classification':int(float(row.get('Classification') or 0)),
                          'intensity':int(float(row.get('Intensity') or 0))}
                    _reservoir_append(sampled,item,seen,max_points,rng)

    # Cross-section subset is centered on primary pole; UI can filter the same point pool at another station.
    result={**analysis,
            'settings':{'width':width,'cross_depth':depth,'resolution':resolution,'max_points':max_points},
            'points':sampled,'point_count':seen+1,'sample_count':len(sampled),
            'blocks':[b.name for b in blocks], 'units':'project'}
    with tempfile.NamedTemporaryFile('w',suffix='.json',delete=False,encoding='utf-8') as fh:
        json.dump(result,fh,separators=(',',':')); tmpname=fh.name
    try: upload_from(tmpname,key,'application/json')
    finally: pathlib.Path(tmpname).unlink(missing_ok=True)
    return key
