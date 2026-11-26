"""Refine one Review picture from originals, without blocking notes or the render queue."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import letitedit.core.quiet_subprocess as quiet_subprocess
import letitedit.core.render_lock as render_lock


def render_frame(project, frame, output):
    root = ET.parse(project).getroot()
    if any(prop.get('name') == 'shotcut:proxy' for prop in root.iter('property')):
        raise ValueError('Review evidence must use the original media')
    profile = root.find('profile')
    if profile is None:
        raise ValueError('Review evidence requires the original profile')
    for producer in list(root.iter('producer')) + list(root.iter('chain')):
        if any(prop.text in {'avformat', 'avformat-novalidate', 'timewarp'}
               for prop in producer.findall('property') if prop.get('name') == 'mlt_service'):
            for name in ('threads', 'warp_threads'):
                prop = next((prop for prop in producer.findall('property') if prop.get('name') == name), None)
                if prop is None:
                    prop = ET.SubElement(producer, 'property', name=name)
                prop.text = '1'
    app = Path(os.environ.get('LETITEDIT_ROOT') or Path(__file__).resolve().parent.parent) / 'app'
    with tempfile.TemporaryDirectory(prefix='original-frame-', dir=output.parent) as folder:
        folder = Path(folder)
        original = folder / 'original.mlt'
        ET.ElementTree(root).write(original, encoding='utf-8', xml_declaration=True)
        wrapper = ET.Element('mlt', LC_NUMERIC='C')
        wrapper.append(profile)
        producer = ET.SubElement(wrapper, 'producer', id='cut')
        ET.SubElement(producer, 'property', name='resource').text = str(original.resolve())
        ET.SubElement(producer, 'property', name='mlt_service').text = 'xml'
        playlist = ET.SubElement(wrapper, 'playlist', id='sheet')
        ET.SubElement(playlist, 'entry', producer='cut', **{'in': str(max(0, frame)), 'out': str(max(0, frame))})
        path = folder / 'frame.mlt'
        ET.ElementTree(wrapper).write(path, encoding='utf-8', xml_declaration=True)
        subprocess.run([str(app / 'melt.exe'), '-quiet', str(path), '-consumer',
                        f'avformat:{folder / "f_%04d.png"}', 'vcodec=png', 'an=1', 'audio_off=1',
                        'threads=1', 'real_time=-1'], capture_output=True, timeout=8, check=True,
                       creationflags=render_lock.background_flags())
        pictures = sorted(folder.glob('f_*.png'))
        if len(pictures) != 1:
            raise RuntimeError('Original note refinement did not produce exactly one frame')
        shutil.copyfile(pictures[0], output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('frame', type=int)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    render_lock.below_normal()
    render_frame(args.project, args.frame, args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
