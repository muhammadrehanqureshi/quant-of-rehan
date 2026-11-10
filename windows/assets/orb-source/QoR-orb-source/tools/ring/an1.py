import numpy as np, cv2
from scipy import ndimage as ndi
im = cv2.imread('reference.jpg')[:,:,::-1].astype(np.float32)
H,W,_ = im.shape
R,G,B = im[...,0],im[...,1],im[...,2]
print('bg samples', im[5,5], im[H-5,W-5], im[H//2,5], im[H//2,W-5])
# alpha from red channel: bg R ~0-5, white ~ 215?
print('max R', R.max(), np.percentile(R,[50,90,99,99.9]))
a = np.clip(R/225.0,0,1)
np.save('alpha.npy', a)
# centre search: sharpness of radial profile
yy,xx = np.mgrid[0:H,0:W]
def sharp(cx,cy,step=4):
    r = np.hypot(xx[::step,::step]-cx, yy[::step,::step]-cy).astype(np.int32)//1
    v = a[::step,::step]
    m = r<1000
    s = np.bincount(r[m].ravel(), weights=v[m].ravel(), minlength=1001)
    n = np.bincount(r[m].ravel(), minlength=1001)+1e-9
    p = s/n
    return float(np.sum(np.diff(p)**2))
best=None
cx0,cy0 = 1110, 1100
for it in range(3):
    rng = [40,12,4][it]; st=[8,3,1][it]
    cand=[]
    for dx in range(-rng,rng+1,st):
        for dy in range(-rng,rng+1,st):
            cand.append((sharp(cx0+dx,cy0+dy), cx0+dx, cy0+dy))
    cand.sort(reverse=True)
    _,cx0,cy0 = cand[0]
    print('iter',it,cand[0])
np.save('centre.npy', np.array([cx0,cy0]))
