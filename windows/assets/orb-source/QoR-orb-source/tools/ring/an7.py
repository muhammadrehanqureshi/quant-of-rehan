import numpy as np, cv2, json
from scipy import ndimage as ndi
a=np.load('alpha.npy'); H,W=a.shape
L=np.load('layers.npy')
cx,cy=1108,1105
m8=(a>0.18).astype(np.uint8)
dist=ndi.distance_transform_edt(m8==0)
keep=(dist<=8)
L=L*keep[None]
names=['small','inner','ticks','thick','rects','arcs']
def score(layer,cx,cy,r0,r1):
    th=np.linspace(0,2*np.pi,720,endpoint=False)
    rr=np.arange(r0-4,r1+5,1.0)
    X=(cx+rr[:,None]*np.cos(th)[None]).astype(np.float32); Y=(cy+rr[:,None]*np.sin(th)[None]).astype(np.float32)
    P=cv2.remap(layer,X,Y,cv2.INTER_LINEAR,borderValue=0)
    p=P.mean(axis=1)
    return float(np.sum(np.diff(p)**2))
ext={'small':(255,340),'inner':(425,540),'ticks':(560,635),'thick':(625,830),'rects':(845,975),'arcs':(1030,1110)}
cent={}
for k,n in enumerate(names):
    r0,r1=ext[n]; x0,y0=1108.0,1105.0
    for rng,st in [(60,10),(12,3),(4,1),(1.5,0.5),(0.5,0.25)]:
        best=(-1,0,0)
        for dx in np.arange(-rng,rng+1e-9,st):
            for dy in np.arange(-rng,rng+1e-9,st):
                s=score(L[k],x0+dx,y0+dy,r0,r1)
                if s>best[0]: best=(s,x0+dx,y0+dy)
        _,x0,y0=best
    cent[n]=(x0,y0)
    ys,xs=np.nonzero(L[k]>0.1); rr=np.hypot(xs-x0,ys-y0)
    print(n,'centre (%.2f, %.2f)'%(x0,y0),'r %.1f..%.1f'%(np.percentile(rr,0.2),np.percentile(rr,99.8)))
np.save('layers_clean.npy',L)
json.dump(cent,open('centres2.json','w'))
