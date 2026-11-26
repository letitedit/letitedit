"""Helpers that need no running editor: new empty projects, a profile written into project XML, the export
engine's path and its render presets."""
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import os
import re
from math import gcd

APP_DIR = (_SAI_ROOT + '\\app')
MELT = os.path.join(APP_DIR, "melt.exe")


def new_project(path, width=1080, height=1920, fps=30, claim=True):
    """Write an empty letitedit project (one video track V1, one audio track A1). claim=False skips the instance
    ownership registry (file-level tools that never drive an editor window)."""
    import letitedit.app.letitedit_instances as instances
    import letitedit.core.long_paths as long_paths
    long_paths.check(*long_paths.project_files(path))
    if claim:
        instances.claim_project(path)
    if os.path.exists(path):
        raise FileExistsError('Project already exists; choose a new revision path instead of overwriting it')
    fps_num, fps_den = (30000, 1001) if abs(fps - 29.97) < 0.01 else (int(round(fps * 1000)), 1000)
    g = gcd(fps_num, fps_den)
    fps_num, fps_den = fps_num // g, fps_den // g
    g = gcd(width, height)
    xml = f"""<?xml version="1.0" standalone="no"?>
<mlt LC_NUMERIC="C" version="7.41.0" title="Shotcut version 26.9.27" producer="main_bin">
  <profile description="{width}x{height} {fps} fps" width="{width}" height="{height}" progressive="1" sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="{width // g}" display_aspect_den="{height // g}" frame_rate_num="{fps_num}" frame_rate_den="{fps_den}" colorspace="709"/>
  <playlist id="main_bin">
    <property name="xml_retain">1</property>
  </playlist>
  <producer id="black" in="0" out="0">
    <property name="length">1</property>
    <property name="eof">pause</property>
    <property name="resource">0</property>
    <property name="aspect_ratio">1</property>
    <property name="mlt_service">color</property>
    <property name="mlt_image_format">rgba</property>
    <property name="set.test_audio">0</property>
  </producer>
  <playlist id="background">
    <entry producer="black" in="0" out="0"/>
  </playlist>
  <playlist id="playlist0">
    <property name="shotcut:video">1</property>
    <property name="shotcut:name">V1</property>
  </playlist>
  <playlist id="playlist1">
    <property name="shotcut:audio">1</property>
    <property name="shotcut:name">A1</property>
  </playlist>
  <tractor id="tractor0" title="Shotcut version 26.9.27" in="0" out="0">
    <property name="shotcut">1</property>
    <property name="shotcut:projectAudioChannels">2</property>
    <property name="shotcut:projectFolder">0</property>
    <track producer="background"/>
    <track producer="playlist0"/>
    <track producer="playlist1" hide="video"/>
    <transition id="transition0">
      <property name="a_track">0</property>
      <property name="b_track">1</property>
      <property name="mlt_service">mix</property>
      <property name="always_active">1</property>
      <property name="sum">1</property>
    </transition>
    <transition id="transition1">
      <property name="a_track">0</property>
      <property name="b_track">1</property>
      <property name="version">0.1</property>
      <property name="mlt_service">frei0r.cairoblend</property>
      <property name="threads">0</property>
      <property name="disable">1</property>
    </transition>
    <transition id="transition2">
      <property name="a_track">0</property>
      <property name="b_track">2</property>
      <property name="mlt_service">mix</property>
      <property name="always_active">1</property>
      <property name="sum">1</property>
    </transition>
  </tractor>
</mlt>
"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(xml)
    return os.path.abspath(path)


def inject_profile(xml, profile):
    """project_xml from the bridge has no <profile>; melt needs one to render at the right size."""
    if "<profile" in xml:
        return xml
    fps = profile["fps"]
    fps_num, fps_den = (30000, 1001) if abs(fps - 29.97) < 0.01 else (int(round(fps * 1000)), 1000)
    g = gcd(fps_num, fps_den)
    w, h = profile["width"], profile["height"]
    gw = gcd(w, h)
    tag = (f'<profile width="{w}" height="{h}" progressive="1" sample_aspect_num="1" '
           f'sample_aspect_den="1" display_aspect_num="{w // gw}" display_aspect_den="{h // gw}" '
           f'frame_rate_num="{fps_num // g}" frame_rate_den="{fps_den // g}" colorspace="709"/>')
    return re.sub(r"(<mlt\b[^>]*>)", r"\1" + tag, xml, count=1)


PRESETS = {
    "social_h264": ["vcodec=libx264", "crf=20", "preset=medium", "pix_fmt=yuv420p",
                    "acodec=aac", "ab=192k", "movflags=+faststart"],
    "high_quality_h264": ["vcodec=libx264", "crf=16", "preset=slow", "pix_fmt=yuv420p",
                          "acodec=aac", "ab=320k", "movflags=+faststart"],
    "draft_h264": ["vcodec=libx264", "crf=28", "preset=veryfast", "pix_fmt=yuv420p",
                   "acodec=aac", "ab=128k", "movflags=+faststart"],
}








