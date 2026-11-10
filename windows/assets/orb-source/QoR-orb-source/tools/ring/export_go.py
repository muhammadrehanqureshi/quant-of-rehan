import numpy as np, cv2, json, os
import render_py as R
a,L,C = R.load()
T=512
os.makedirs('../../assets/ring',exist_ok=True)
rows=[]
for k,n in enumerate(R.names):
    P=R.pad(L[k]); P=cv2.resize(P,(T,T),interpolation=cv2.INTER_AREA)
    u8=np.clip(P*255+0.5,0,255).astype(np.uint8)
    cv2.imwrite('../../assets/ring/layer%d_%s.png'%(k,n),u8,[cv2.IMWRITE_PNG_COMPRESSION,9])
    cx,cy=C[k][0]+R.OFF[0], C[k][1]+R.OFF[1]
    ys,xs=np.nonzero(R.pad(L[k])>0.02)
    r=np.hypot(xs-cx,ys-cy)
    rows.append((n,cx,cy,r.min(),r.max()))
    print(n,'centre canvas (%.2f,%.2f)'%(cx,cy),'r %.1f..%.1f'%(r.min(),r.max()), 'png bytes', os.path.getsize('../../assets/ring/layer%d_%s.png'%(k,n)))
# Go data file
lines=['// Code generated from the reference picture by tools/ring_export.py. DO NOT EDIT.','','package main','',
 '// ringCanvas is the side, in picture pixels, of the square every ring layer was cut on.',
 'const ringCanvas = 2300.0','',
 '// ringReach is the radius, in picture pixels, of the outermost thin arcs: the ring is scaled so this reaches the edge of its box.',
 'const ringReach = 1112.0','',
 '// ringLayerSpec describes one turning layer: where its centre is on the canvas, the radii it covers around that centre, and how fast it turns (degrees per second, clockwise is positive).',
 'type ringLayerSpec struct {','\tfile        string','\tcx, cy      float64','\trin, rout   float64','\tdegPerSec   float64','}','',
 'var ringLayerSpecs = [...]ringLayerSpec{']
spd={'small':-45,'inner':45,'ticks':-45,'thick':22.5,'rects':-22.5,'arcs':22.5}
for k,(n,cx,cy,rmin,rmax) in enumerate(rows):
    lines.append('\t{"layer%d_%s.png", %.2f, %.2f, %.1f, %.1f, %.1f},'%(k,n,cx,cy,np.floor(rmin-6),np.ceil(rmax+6),spd[n]))
lines.append('}')
open('../../ring_data.go','w').write('\n'.join(lines)+'\n')
