"""Encode rendered PNG frames to MP4 (+ preview) and verify with ffprobe.

python pipeline/render/encode.py [--frames work/render/frames] [--out output/video/panter_kilif_360.mp4]
                                 [--preview output/video/panter_kilif_360_preview.mp4] [--expect 216]
Also writes a contact sheet of the final MP4 to work/render/contact_sheet.png.
"""
import argparse
import glob
import json
import os
import subprocess
import sys


def run(cmd):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--frames", default="work/render/frames")
    p.add_argument("--out", default="output/video/panter_kilif_360.mp4")
    p.add_argument("--preview", default="output/video/panter_kilif_360_preview.mp4")
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--crf", type=int, default=16)
    p.add_argument("--expect", type=int, default=216)
    p.add_argument("--sheet", default="work/render/contact_sheet.png")
    a = p.parse_args()
    files = sorted(glob.glob(os.path.join(a.frames, "frame_*.png")))
    if len(files) != a.expect:
        sys.exit("expected %d frames in %s, found %d" % (a.expect, a.frames, len(files)))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    pat = os.path.join(a.frames, "frame_%04d.png")
    common = ["-c:v", "libx264", "-preset", "slow", "-pix_fmt", "yuv420p",
              "-movflags", "+faststart", "-color_primaries", "bt709", "-color_trc", "bt709",
              "-colorspace", "bt709"]
    run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-start_number", "1", "-i", pat,
         "-vf", "scale=out_color_matrix=bt709:out_range=tv", "-crf", str(a.crf), *common, a.out])
    run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-start_number", "1", "-i", pat,
         "-vf", "scale=720:960:flags=lanczos:out_color_matrix=bt709:out_range=tv", "-crf", "20", *common, a.preview])
    for f in (a.out, a.preview):
        r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                            "-show_entries", "stream=codec_name,pix_fmt,width,height,r_frame_rate,nb_read_frames:format=duration,size",
                            "-of", "json", f], capture_output=True, text=True, check=True)
        print(f, json.dumps(json.loads(r.stdout)))
    # contact sheet: 12 frames evenly spaced (every 18th frame)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", a.out, "-vf",
         "select='not(mod(n\\,18))',scale=360:480,tile=6x2", "-frames:v", "1", "-update", "1", a.sheet])
    print("contact sheet:", a.sheet)


if __name__ == "__main__":
    main()
