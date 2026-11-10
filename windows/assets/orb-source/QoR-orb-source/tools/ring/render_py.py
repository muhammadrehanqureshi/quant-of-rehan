import numpy as np, cv2, json, sys
SRC='reference.jpg'
names=['small','inner','ticks','thick','rects','arcs']
FG=np.array([231,241,245],np.float32)
def load():
    a=np.load('alpha.npy'); a=np.clip(a*225.0/231.0,0,1)   # alpha.npy was R/225
    L=np.load('layers_clean.npy')*225.0/231.0
    L=np.clip(L,0,1).astype(np.float32)
    C=json.load(open('centres2.json'))
    return a,L,[C[n] for n in names]
CANV=2300; OFF=(42,47)
def pad(layer):
    out=np.zeros((CANV,CANV),np.float32); h,w=layer.shape
    out[OFF[1]:OFF[1]+h, OFF[0]:OFF[0]+w]=layer
    return out
def bg_image(n):
    coef=json.load(open('bgfit.json'))
    ys,xs=np.mgrid[0:n,0:n].astype(np.float32)
    # canvas px -> original px
    x=(xs*CANV/n-OFF[0])/2235.0; y=(ys*CANV/n-OFF[1])/2216.0
    x=np.clip(x,0,1); y=np.clip(y,0,1)
    A=np.stack([np.ones_like(x),x,y,x*y,x*x,y*y],-1)
    img=np.stack([A@np.array(c,np.float32) for c in coef],-1)
    return np.clip(img,0,255)
class Ring:
    def __init__(self,n=620,ss=2):
        a,L,C=load(); self.n=n; self.ss=ss; N=n*ss; s=N/CANV; self.N=N
        self.layers=[]; self.cent=[]
        for k in range(6):
            P=pad(L[k]); P=cv2.resize(P,(N,N),interpolation=cv2.INTER_AREA)
            self.layers.append(P)
            self.cent.append(((C[k][0]+OFF[0])*s,(C[k][1]+OFF[1])*s))
        self.bg=bg_image(n)
    def alpha(self,deg):
        """deg: list of 6 rotation angles in degrees, clockwise on screen"""
        N=self.N; tot=np.ones((N,N),np.float32)
        for k in range(6):
            M=cv2.getRotationMatrix2D(self.cent[k],-deg[k],1.0)  # cv2 positive = counter clockwise
            R=cv2.warpAffine(self.layers[k],M,(N,N),flags=cv2.INTER_LINEAR,borderValue=0)
            tot*=(1-np.clip(R,0,1))
        al=1-tot
        return cv2.resize(al,(self.n,self.n),interpolation=cv2.INTER_AREA)
    def frame(self,deg,bg=True):
        al=self.alpha(deg)[...,None]
        b=self.bg if bg else np.zeros_like(self.bg)
        return np.clip(b*(1-al)+FG*al,0,255).astype(np.uint8)
if __name__=='__main__':
    r=Ring(n=1150,ss=1)
    f=r.frame([0]*6)
    orig=cv2.imread(SRC)[:,:,::-1]
    big=np.zeros((CANV,CANV,3),np.uint8); big[OFF[1]:OFF[1]+2216,OFF[0]:OFF[0]+2235]=orig
    ref=cv2.resize(big,(1150,1150),interpolation=cv2.INTER_AREA)
    err=np.abs(f.astype(int)-ref.astype(int)).mean(axis=2)
    print('static reconstruction mean abs err %.2f max %.1f  p99 %.1f'%(err.mean(),err.max(),np.percentile(err,99)))
    cv2.imwrite('static_recon.png',f[:,:,::-1])
    cv2.imwrite('err.png',np.clip(err*8,0,255).astype(np.uint8))
