"""Parallel LAS/LAZ -> COPC conversion in the processing worker."""
import json
import pathlib
import re
import threading
import time

import pytest

from app import processor, storage


def summary(_path):
    return {'num_points': 10, 'bounds': {'minx': 0, 'miny': 0, 'maxx': 1, 'maxy': 1, 'minz': 0, 'maxz': 1}}


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'LOCAL_ROOT', tmp_path.resolve())
    monkeypatch.setattr(processor, 'MODE', 'local')
    monkeypatch.setattr(processor, 'untwine_exe', lambda: None)  # PDAL path unless a test opts into untwine
    monkeypatch.setattr(processor, 'pdal_summary', summary)
    return tmp_path


def uploads(*names):
    return [{'id': f'id{i}', 'filename': name, 'object_key': f'p/versions/v1/source/{i}-{name}'} for i, name in enumerate(names)]


def test_files_convert_in_parallel_and_keep_upload_order(local_storage, monkeypatch, tmp_path):
    lock, active, peak, calls = threading.Lock(), [0], [0], []

    def fake_copc(src, dst, crs):
        with lock:
            active[0] += 1; peak[0] = max(peak[0], active[0]); calls.append(dst.name)
        time.sleep(0.15)
        dst.write_bytes(b'COPC')
        with lock:
            active[0] -= 1
    monkeypatch.setattr(processor, 'to_copc', fake_copc)
    updates = []
    files = uploads('a.laz', 'b.laz', 'c.las', 'd.laz')
    blocks = processor.convert_lidar_files(files, 'p/versions/v1/lidar', 'EPSG:6424', tmp_path,
                                           lambda done, total, running: updates.append((done, total, running)), workers=3)
    assert peak[0] >= 2, 'conversions must overlap'
    assert [b['name'] for b in blocks] == ['a', 'b', 'c', 'd']
    assert [b['source_object_key'] for b in blocks] == [f['object_key'] for f in files]
    assert updates[0][0] == 0 and updates[-1] == (4, 4, [])
    assert [u[0] for u in updates] == sorted(u[0] for u in updates)


def test_same_name_uploads_share_one_conversion(local_storage, monkeypatch, tmp_path):
    calls = []

    def fake_copc(src, dst, crs):
        calls.append(dst.name); time.sleep(0.05); dst.write_bytes(b'COPC')
    monkeypatch.setattr(processor, 'to_copc', fake_copc)
    files = uploads('tile.laz', 'tile.laz')
    blocks = processor.convert_lidar_files(files, 'p/versions/v1/lidar', 'EPSG:6424', tmp_path, lambda *a: None, workers=4)
    assert calls == ['tile.copc.laz']
    assert [b['source_object_key'] for b in blocks] == [f['object_key'] for f in files]
    assert blocks[0]['object_key'] == blocks[1]['object_key']


def test_a_failed_conversion_fails_the_batch(local_storage, monkeypatch, tmp_path):
    def fake_copc(src, dst, crs):
        if dst.name.startswith('bad'):
            raise RuntimeError('PDAL: cannot read bad.laz')
        time.sleep(0.05); dst.write_bytes(b'COPC')
    monkeypatch.setattr(processor, 'to_copc', fake_copc)
    with pytest.raises(RuntimeError, match='bad.laz'):
        processor.convert_lidar_files(uploads('good.laz', 'bad.laz'), 'p/lidar', 'EPSG:6424', tmp_path, lambda *a: None, workers=2)


def test_to_copc_never_leaves_a_truncated_output(tmp_path, monkeypatch):
    monkeypatch.setattr(processor, 'untwine_exe', lambda: None)
    dst = tmp_path / 'tile.copc.laz'

    def crash(cmd, **kwargs):
        pathlib_partial = cmd[3]
        open(pathlib_partial, 'wb').write(b'half')
        raise RuntimeError('PDAL crashed')
    monkeypatch.setattr(processor, 'run', crash)
    with pytest.raises(RuntimeError):
        processor.to_copc(tmp_path / 'tile.laz', dst, 'EPSG:6424')
    assert not dst.exists() and not list(tmp_path.glob('*.partial'))

    monkeypatch.setattr(processor, 'run', lambda cmd, **kwargs: open(cmd[3], 'wb').write(b'COPC'))
    processor.to_copc(tmp_path / 'tile.laz', dst, 'EPSG:6424')
    assert dst.read_bytes() == b'COPC' and not list(tmp_path.glob('*.partial'))


def test_worker_count_is_configurable(monkeypatch):
    monkeypatch.setenv('LIDAR_CONVERT_WORKERS', '3')
    assert processor.lidar_workers() == 3
    monkeypatch.setenv('LIDAR_CONVERT_WORKERS', 'nonsense')
    assert 1 <= processor.lidar_workers() <= 4


@pytest.mark.parametrize('key', ['../outside.laz', 'p/../../outside.laz', 'C:/Windows/evil.laz', '/etc/passwd'])
def test_storage_keys_cannot_escape_the_root(local_storage, key):
    with pytest.raises(ValueError, match='Invalid storage key'):
        storage.local_path(key)


def test_storage_key_inside_the_root_is_accepted(local_storage):
    assert storage.local_path('p/versions/v1/source/a.laz').is_relative_to(storage.LOCAL_ROOT)


def tracking_copc(lock, active, seen):
    def fake_copc(src, dst, crs):
        with lock:
            active.add(dst.name); seen.append(set(active))
        time.sleep(0.1)
        dst.write_bytes(b'COPC')
        with lock:
            active.discard(dst.name)
    return fake_copc


def test_large_tiles_wait_for_memory_instead_of_running_together(local_storage, monkeypatch, tmp_path):
    lock, active, seen = threading.Lock(), set(), []
    monkeypatch.setattr(processor, 'to_copc', tracking_copc(lock, active, seen))
    sizes = {'big1.laz': 60, 'big2.laz': 60, 'small1.laz': 10, 'small2.laz': 10}
    monkeypatch.setattr(processor, 'conversion_cost', lambda f, prefix: (sizes[f['filename']], 0))
    blocks = processor.convert_lidar_files(uploads(*sizes), 'p/lidar', 'EPSG:6424', tmp_path, lambda *a: None, workers=4, budget=100)
    assert [b['name'] for b in blocks] == ['big1', 'big2', 'small1', 'small2']
    assert all(not {'big1.copc.laz', 'big2.copc.laz'} <= group for group in seen), 'two large tiles must never convert at once'
    assert any(len(group) > 1 for group in seen), 'tiles that fit together still run in parallel'


class FakePdal:
    """Stands in for PDAL: a "LAZ" is a JSON list of [x, y] points; range filters crop it like PDAL does."""

    def __init__(self, drop_one=False):
        self.drop_one = drop_one

    @staticmethod
    def write(path, points):
        pathlib.Path(path).write_text(json.dumps(points))

    def header(self, path):
        pts = json.loads(pathlib.Path(path).read_text())
        xs, ys = [p[0] for p in pts] or [0], [p[1] for p in pts] or [0]
        return {'count': len(pts), 'minx': min(xs), 'maxx': max(xs), 'miny': min(ys), 'maxy': max(ys)}

    def run(self, cmd, **kwargs):
        limits = next(c for c in cmd if c.startswith('--filters.range.limits=')).split('=', 1)[1]
        axis, lo, hi, close = re.fullmatch(r'([XY])\[([^:]*):([^\])]*)([\])])', limits).groups()
        index = 0 if axis == 'X' else 1
        keep = [p for p in json.loads(pathlib.Path(cmd[2]).read_text())
                if (not lo or p[index] >= float(lo)) and (not hi or (p[index] <= float(hi) if close == ']' else p[index] < float(hi)))]
        if self.drop_one and keep:
            keep = keep[1:]
        self.write(cmd[3], keep)
        return ''


def skewed_points():
    # Most points crowd one corner and a few outliers stretch the bounds, as in real tiles.
    return [[i % 30 + 0.5, i // 30 + 0.25] for i in range(990)] + [[1000.0 + i, 500.0 - i] for i in range(10)]


def test_split_keeps_every_point_once_and_halves_until_pieces_fit(tmp_path, monkeypatch):
    fake = FakePdal(); monkeypatch.setattr(processor, 'run', fake.run); monkeypatch.setattr(processor, 'lidar_header', fake.header)
    src = tmp_path / 'tile.laz'; fake.write(src, skewed_points())
    pieces = processor.split_lidar_tile(src, 'EPSG:6424', tmp_path, max_points=300)
    assert len(pieces) >= 4 and all(header['count'] <= 300 for _, header in pieces)
    merged = sorted(tuple(p) for piece, _ in pieces for p in json.loads(piece.read_text()))
    assert merged == sorted(tuple(p) for p in skewed_points())
    assert src.exists(), 'the customer source is never modified or deleted'
    assert sorted(path.name for path in tmp_path.glob('*.laz')) == sorted(['tile.laz', *(piece.name for piece, _ in pieces)]), 'intermediate halves are removed'


def test_split_that_loses_points_is_refused(tmp_path, monkeypatch):
    fake = FakePdal(drop_one=True); monkeypatch.setattr(processor, 'run', fake.run); monkeypatch.setattr(processor, 'lidar_header', fake.header)
    src = tmp_path / 'tile.laz'; fake.write(src, skewed_points())
    with pytest.raises(RuntimeError, match='lost points'):
        processor.split_lidar_tile(src, 'EPSG:6424', tmp_path, max_points=300)


def test_a_tile_too_large_for_memory_becomes_several_blocks(local_storage, monkeypatch, tmp_path):
    fake = FakePdal(); monkeypatch.setattr(processor, 'run', fake.run); monkeypatch.setattr(processor, 'lidar_header', fake.header)
    monkeypatch.setattr(processor, 'copc_bytes_per_point', lambda: 1)
    files = uploads('small.laz', 'huge.laz')
    for f in files:
        target = storage.local_path(f['object_key']); target.parent.mkdir(parents=True, exist_ok=True)
        fake.write(target, skewed_points() if f['filename'] == 'huge.laz' else [[1.0, 1.0]] * 50)
    monkeypatch.setattr(processor, 'conversion_cost', lambda f, prefix: (1000 if f['filename'] == 'huge.laz' else 50, 0))
    converted = []
    def fake_copc(src, dst, crs):
        converted.append(dst.name); dst.write_bytes(b'COPC')
    monkeypatch.setattr(processor, 'to_copc', fake_copc)
    notes = []
    blocks = processor.convert_lidar_files(files, 'p/versions/v1/lidar', 'EPSG:6424', tmp_path,
                                           lambda done, total, running: notes.append(running), workers=2, budget=400)
    huge = [b for b in blocks if b['source_object_key'] == files[1]['object_key']]
    assert blocks[0]['name'] == 'small' and len(huge) >= 3
    assert [b['name'] for b in huge] == [f'huge_{n}' for n in range(1, len(huge) + 1)]
    assert sorted(converted) == sorted(['small.copc.laz', *(f'{b["name"]}.copc.laz' for b in huge)])
    assert any('splitting' in ' '.join(r) for r in notes) and any('huge.laz part' in ' '.join(r) for r in notes)
    assert storage.local_path(files[1]['object_key']).exists(), 'the uploaded source stays untouched'


def test_not_enough_disk_fails_with_a_clear_message(local_storage, monkeypatch, tmp_path):
    monkeypatch.setattr(processor, 'to_copc', lambda *a: pytest.fail('PDAL must not start'))
    monkeypatch.setattr(processor, 'conversion_cost', lambda f, prefix: (1, 10 * processor.GB))
    monkeypatch.setattr(processor.shutil, 'disk_usage', lambda path: type('U', (), {'free': 5 * processor.GB})())
    with pytest.raises(RuntimeError, match=r'Not enough disk space to convert tile\.laz.*10\.0 GB.*5\.0 GB'):
        processor.convert_lidar_files(uploads('tile.laz'), 'p/lidar', 'EPSG:6424', tmp_path, lambda *a: None, budget=100)


def test_estimates_use_the_header_point_count(local_storage, monkeypatch):
    monkeypatch.setattr(processor, 'lidar_point_count', lambda path: 1_000_000)
    ram, disk = processor.conversion_cost({'filename': 'a.laz', 'object_key': 'p/source/a.laz', 'size_bytes': 1}, 'p/lidar')
    assert ram == 1_000_000 * processor.copc_bytes_per_point() and disk > 0
    assert processor.conversion_cost({'filename': 'a.copc.laz', 'object_key': 'p/source/a.copc.laz'}, 'p/lidar') == (0, 0)


def test_silent_pdal_crash_is_explained():
    import sys
    with pytest.raises(RuntimeError, match='out of memory or disk space'):
        processor.run([sys.executable, '-c', 'import sys; sys.exit(3)'], low_priority=True)


class FakeUntwine:
    def __init__(self, fail=False):
        self.fail, self.commands, self.temp_dirs = fail, [], []

    def run(self, cmd, **kwargs):
        self.commands.append(cmd)
        temp = pathlib.Path(cmd[cmd.index('--temp_dir') + 1]); self.temp_dirs.append(temp)
        (temp / '1-0-0-0.bin').write_bytes(b'scratch')  # untwine leaves scratch files behind
        output = pathlib.Path(cmd[cmd.index('-o') + 1]); output.write_bytes(b'half')
        if self.fail:
            raise RuntimeError('untwine crashed')
        output.write_bytes(b'COPC')
        return ''


@pytest.mark.parametrize('has_srs', [False, True])
def test_untwine_is_used_when_installed_and_cleans_its_scratch(tmp_path, monkeypatch, has_srs):
    fake = FakeUntwine()
    monkeypatch.setattr(processor, 'untwine_exe', lambda: 'untwine')
    monkeypatch.setattr(processor, 'lidar_has_srs', lambda path: has_srs)
    monkeypatch.setattr(processor, 'run', fake.run)
    dst = tmp_path / 'tile.copc.laz'
    processor.to_copc(tmp_path / 'tile.laz', dst, 'EPSG:6424')
    cmd = fake.commands[0]
    assert cmd[0] == 'untwine' and cmd[cmd.index('-i') + 1].endswith('tile.laz')
    # The project CRS is only assigned when the file has none, never overriding a source SRS.
    assert ('--a_srs' in cmd) is (not has_srs)
    assert dst.read_bytes() == b'COPC'
    assert not fake.temp_dirs[0].exists() and not list(tmp_path.glob('*.partial'))


def test_untwine_crash_leaves_no_output_partial_or_scratch(tmp_path, monkeypatch):
    fake = FakeUntwine(fail=True)
    monkeypatch.setattr(processor, 'untwine_exe', lambda: 'untwine')
    monkeypatch.setattr(processor, 'lidar_has_srs', lambda path: True)
    monkeypatch.setattr(processor, 'run', fake.run)
    dst = tmp_path / 'tile.copc.laz'
    with pytest.raises(RuntimeError, match='untwine crashed'):
        processor.to_copc(tmp_path / 'tile.laz', dst, 'EPSG:6424')
    assert not dst.exists() and not list(tmp_path.glob('*.partial')) and not fake.temp_dirs[0].exists()


def test_cost_model_follows_the_converter(monkeypatch):
    monkeypatch.delenv('LIDAR_COPC_BYTES_PER_POINT', raising=False)
    monkeypatch.delenv('LIDAR_CONVERT_WORKERS', raising=False)
    monkeypatch.setattr(processor, 'untwine_exe', lambda: None)
    assert processor.copc_bytes_per_point() == 120 and processor.copc_temp_bytes_per_point() == 0
    monkeypatch.setattr(processor, 'untwine_exe', lambda: 'untwine')
    assert processor.copc_bytes_per_point() == 24 and processor.copc_temp_bytes_per_point() == 70
    assert processor.lidar_workers() == 2
    monkeypatch.setenv('LIDAR_COPC_BYTES_PER_POINT', '50')
    assert processor.copc_bytes_per_point() == 50


def test_untwine_location_can_be_configured(tmp_path, monkeypatch):
    exe = tmp_path / 'untwine.exe'; exe.write_bytes(b'')
    monkeypatch.setenv('UNTWINE_BIN', str(exe))
    assert processor.untwine_exe() == str(exe)
    monkeypatch.setenv('UNTWINE_BIN', str(tmp_path / 'missing.exe'))
    assert processor.untwine_exe() is None
