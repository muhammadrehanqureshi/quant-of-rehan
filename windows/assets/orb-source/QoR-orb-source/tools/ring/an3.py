import numpy as np, cv2
a = np.load('alpha.npy'); H,W = a.shape
wins = {'arcs':(1030,1105),'rects':(840,985),'thick':(625,830),'ticks':(560,632),'inner':(420,545),'small':(250,345)}
def prof_for(cx,cy,r0,r1,NT=720):
    th = np.linspace(0,2*np.pi,NT,endpoint=False)
    rr = np.arange(r0-6,r1+7,1.0)
    X = (cx + rr[:,None]*np.cos(th)[None,:]).astype(np.float32)
    Y = (cy + rr[:,None]*np.sin(th)[None,:]).astype(np.float32)
    P = cv2.remap(a, X, Y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return P.mean(axis=1), rr
def score(cx,cy,r0,r1):
    p,_ = prof_for(cx,cy,r0,r1)
    return float(np.sum(np.diff(p)**2))
res={}
for name,(r0,r1) in wins.items():
    cx0,cy0 = 1108,1105
    for rng,st in [(60,10),(12,3),(4,1)]:
        best=(-1,0,0)
        for dx in range(-rng,rng+1,st):
            for dy in range(-rng,rng+1,st):
                s=score(cx0+dx,cy0+dy,r0,r1)
                if s>best[0]: best=(s,cx0+dx,cy0+dy)
        _,cx0,cy0=best
    # sub pixel refine
    for st in [0.5,0.25]:
        best=(score(cx0,cy0,r0,r1),cx0,cy0)
        for dx in (-st,0,st):
            for dy in (-st,0,st):
                s=score(cx0+dx,cy0+dy,r0,r1)
                if s>best[0]: best=(s,cx0+dx,cy0+dy)
        _,cx0,cy0=best
    res[name]=(cx0,cy0)
    print(name,(r0,r1),'centre',cx0,cy0)
import json; json.dump(res,open('centres.json','w'))
