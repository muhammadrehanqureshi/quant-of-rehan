import numpy as np, cv2, json
from scipy import ndimage as ndi
im = cv2.imread('reference.jpg')[:,:,::-1].astype(np.float32)
a = np.load('alpha.npy'); H,W=a.shape
cx,cy=1108,1105
# fg colour at near-opaque pixels
m = im[...,0]>222
print('opaque px', m.sum(), 'mean colour', im[m].mean(axis=0))
# background plane fit per channel from bg-only pixels
bgm = (im[...,0]<3)
ys,xs = np.nonzero(bgm)
sel = np.random.RandomState(1).choice(len(ys), 200000, replace=False)
A = np.stack([np.ones(len(sel)), xs[sel]/W, ys[sel]/H, (xs[sel]/W)*(ys[sel]/H), (xs[sel]/W)**2, (ys[sel]/H)**2],1)
coef=[]
for ch in range(3):
    c,res,_,_ = np.linalg.lstsq(A, im[ys[sel],xs[sel],ch], rcond=None); coef.append(c)
    pred = A@c; print('bg ch',ch,'coef',np.round(c,1),'rms',np.sqrt(np.mean((pred-im[ys[sel],xs[sel],ch])**2)))
json.dump([c.tolist() for c in coef], open('bgfit.json','w'))
# components
m8 = (a>0.18).astype(np.uint8)
n,lab,stats,cent = cv2.connectedComponentsWithStats(m8,connectivity=8)
band_of = np.zeros(n,np.int32)-1
edges=[345,540,632,830,1000]   # small, inner, ticks, thick, rects, arcs
for i in range(1,n):
    x,y,w,h,area=stats[i]
    sub = lab[y:y+h,x:x+w]==i
    ys_,xs_=np.nonzero(sub); r=np.hypot(xs_+x-cx, ys_+y-cy)
    med=np.median(r)
    band_of[i]=int(np.searchsorted(edges,med))
names=['small','inner','ticks','thick','rects','arcs']
print({names[k]:int((band_of==k).sum()) for k in range(6)})
# partition: every px with alpha>0.015 goes to band of nearest labelled px
dist,(iy,ix) = ndi.distance_transform_edt(lab==0, return_indices=True)
nearest = lab[iy,ix]
bandmap = band_of[nearest]
active = a>0.012
print('max dist for active px', dist[active].max(), 'px >6 away', int((dist[active]>6).sum()))
layers=[]
for k in range(6):
    L = np.where(active & (bandmap==k), a, 0).astype(np.float32)
    layers.append(L)
    ys_,xs_=np.nonzero(L>0.1); print(names[k],'px',len(ys_), 'r range', np.hypot(xs_-cx,ys_-cy).min().round(1), np.hypot(xs_-cx,ys_-cy).max().round(1))
tot = sum(layers)
print('partition error max', np.abs(tot - np.where(active,a,0)).max())
np.save('layers.npy', np.stack(layers))
