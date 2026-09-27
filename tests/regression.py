#!/usr/bin/env python3
"""EEDI3CL load, input-validation, field-preservation and concurrent-render checks.

Requires an AviSynth+ avs_runner (the QTGMC project's tests/avs_runner.cpp).
OpenCL tests fail, rather than silently skip, when the selected device is absent.
"""
import argparse
import array
from fractions import Fraction
from pathlib import Path
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--runner', type=Path, required=True)
p.add_argument('--plugin', type=Path, required=True)
p.add_argument('--work', type=Path, default=Path('tests/work'))
p.add_argument('--device', type=int, default=0)
p.add_argument('--case', action='append', choices=['fields', 'tiny', 'luma', 'errors', 'simd', 'auto', 'width'])
a = p.parse_args()
work = a.work.resolve(); work.mkdir(parents=True, exist_ok=True)
count = 0

def selected(case): return not a.case or case in a.case

def source(depth=16, fmt='422', w=64, h=36, field=2):
    return (f'BlankClip(width={w},height={h},length=3,pixel_type="YUV{fmt}P{depth}",fps=30000,fps_denominator=1001)\n'
            f'Expr("sx 109 * sy 317 * + frameno 43 * + {1 << depth} %", "sx 257 * sy 131 * + frameno 59 * + {1 << depth} %")\n'
            f'AssumeTFF().propSet("_FieldBased",{field})\n')

def render(name, script, reverse=False, error=None):
    global count
    avs = work/(name+'.avs'); raw = avs.with_suffix('.raw')
    avs.write_text(f'LoadCPlugin("{a.plugin.resolve()}")\n'+script)
    r = subprocess.run([str(a.runner.resolve()), str(avs), str(raw)]+(['reverse'] if reverse else []),
                       capture_output=True, text=True, timeout=180)
    avs.with_suffix('.log').write_text(r.stdout+r.stderr)
    if error:
        assert r.returncode == 1 and error.lower() in r.stderr.lower(), (name, r.returncode, r.stderr)
        count += 1; return
    assert r.returncode == 0, (name, r.returncode, r.stderr)
    count += 1
    return raw.read_bytes(), r.stdout

def call(params): return f'EEDI3CL(device={a.device},{params})\n'

def retained(src, result, depth, widths, heights, field, dh=False):
    aa = array.array('B' if depth == 8 else 'H', src[0]); bb = array.array(aa.typecode, result[0])
    frame = sum(w*h for w,h in zip(widths, heights)); outframe = frame * (2 if dh else 1)
    frames = 6 if field > 1 else 3
    meta = result[1].splitlines()[0].split()
    assert int(meta[2]) == frames and int(meta[4]) == depth
    assert Fraction(meta[3]) == Fraction(30000,1001)*(2 if field > 1 else 1)
    for n in range(frames):
        parity = (1-field if field <= 1 else ((n+(field==2))%2))
        ao = (n//2 if field > 1 else n)*frame; bo = n*outframe
        for w,h in zip(widths, heights):
            for y in range(h if dh else (h//2)):
                sy = y if dh else 2*y+parity; dy = 2*y+parity
                assert aa[ao+sy*w:ao+(sy+1)*w] == bb[bo+dy*w:bo+(dy+1)*w], ('field pixels changed',depth,field,n,y)
            ao += w*h; bo += w*h*(2 if dh else 1)

if selected('fields'):
    for depth in (8,10,12,16):
      for fmt in ('420','422'):
        src = source(depth,fmt); original = render(f'src_{fmt}_{depth}',src)
        for field in (0,1,2,3):
          stem = f'field_{fmt}_{depth}_{field}'; script = src+call(f'field={field}')
          out = render(stem,script); parallel = render(stem+'_parallel',script+'Prefetch(4)',True)
          assert out == parallel, (stem,'concurrent/order mismatch')
          retained(original,out,depth,[64,32,32],[36,18 if fmt=='420' else 36,18 if fmt=='420' else 36],field)
        print(fmt,depth,'fields and Prefetch passed',flush=True)

if selected('tiny'):
    for depth in (8,16):
      for w,h in ((2,4),(8,8),(24,12)):
        src = source(depth,'420',w,h); original = render(f'tiny_src_{depth}_{w}',src)
        for dh in (False,True):
          for field in (0,1):
            stem=f'tiny_{depth}_{w}_{dh}_{field}'; script=src+call(f'field={field},dh={str(dh).lower()},opt=0')
            out=render(stem,script); again=render(stem+'_repeat',script+'Prefetch(4)',True)
            assert out==again,(stem,'uninitialized edge pixels')
            retained(original,out,depth,[w,w//2,w//2],[h,h//2,h//2],field,dh)
        print(depth,w,h,'tiny frames passed',flush=True)

if selected('luma'):
    for depth in (8,10,12,16):
        src=source(depth)
        expected=render(f'luma_ref_{depth}',src+'ExtractY()\n'+call('field=3'))
        for planes in ('',',planes=[0]'):
            out=render(f'luma_{depth}_{bool(planes)}',src+call('field=3,luma=true'+planes))
            assert out==expected,(depth,'luma format/plane mismatch')
        print(depth,'luma passed',flush=True)

if selected('auto'):
    for fb in (0,1,2,2147483647):
        src=source(field=fb)
        for auto,explicit in ((-1,0 if fb==1 else 1),(-2,2 if fb==1 else 3)):
            out=render(f'auto_{fb}_{auto}',src+call(f'field={auto}'))
            expected=render(f'auto_ref_{fb}_{auto}',src+call(f'field={explicit}'))
            assert out==expected,(fb,auto,'invalid/missing property fallback')

if selected('simd'):
    for depth in (8,16):
        src=source(depth)
        reference=render(f'simd_{depth}_0',src+call('field=3,opt=0'))
        # AVX2 is supported on the test host; AVX512 is not assumed.
        for opt in (1,2,-1):
            out=render(f'simd_{depth}_{opt}',src+call(f'field=3,opt={opt}')+'Prefetch(4)',True)
            assert out==reference,(depth,opt,'SIMD mismatch')

if selected('width'):
    for depth in (8,16):
      for fmt in ('420','422','444'):
       for dh in (False,True):
        stem=f'width_{depth}_{fmt}_{dh}'; src=source(depth,fmt)
        first=render(stem+'_first',src+call(f'field=1,dh={str(dh).lower()}'))
        script=src+call(f'field=1,dh={str(dh).lower()},dw=true')
        result=render(stem,script)
        assert result==render(stem+'_parallel',script+'Prefetch(4)',True),(stem,'width concurrency')
        aa=array.array('B' if depth==8 else 'H',first[0]); bb=array.array(aa.typecode,result[0])
        widths=[64,64 if fmt=='444' else 32,64 if fmt=='444' else 32]
        heights=[36,18 if fmt=='420' else 36,18 if fmt=='420' else 36]
        if dh: heights=[h*2 for h in heights]
        frame=sum(w*h for w,h in zip(widths,heights))
        assert len(bb)==len(aa)*2 and result[1].splitlines()[0].split()[:2]==['128',str(heights[0])]
        for n in range(3):
          ao=n*frame; bo=n*frame*2
          for w,h in zip(widths,heights):
            for y in range(h):
              assert aa[ao+y*w:ao+(y+1)*w]==bb[bo+y*w*2+1:bo+(y+1)*w*2:2],(stem,n,y,'transpose field changed')
            ao+=w*h;bo+=w*h*2
        print(stem,'passed',flush=True)

if selected('errors'):
    errors = [('planes=[-1]','plane index'),('planes=[0,0]','twice'),('planes=[3]','plane index'),
              ('field=-2,dh=true','field'),('field=-1,dh=true','field'),('field=-2,dw=true','field'),
              ('device=-2','device'),('alpha=0.9,beta=0.9','alpha+beta')]
    for i,(args,err) in enumerate(errors):
        render(f'error_{i}',source()+f'EEDI3CL({args})',error=err)
    render('odd_chroma',source(fmt='420',h=6)+call('field=3'),error='plane height')
    render('masked_cpu', 'SetMaxCPU("sse2")\n'+source()+call('field=3,opt=2'),error='AVX2')

print(f'{count} EEDI3CL render/error checks passed',flush=True)
