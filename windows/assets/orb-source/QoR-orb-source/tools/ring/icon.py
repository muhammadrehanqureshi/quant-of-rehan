import numpy as np, cv2, io, struct, sys
import render_py as R
a,L,C = R.load()
names=R.names
PADL=[R.pad(L[k]) for k in range(6)]
WHITE=np.array([234,244,248],np.float32)
C0=np.array([6,126,176],np.float32); C1=np.array([0,70,104],np.float32)

def plan(S):
    if S>=128: return dict(layers=[0,1,2,3,4,5],reach=1112,fill=0.455,dil=0.0,gamma=1.0,ss=3 if S>128 else 4)
    if S>=64:  return dict(layers=[0,1,3,4,5],reach=1112,fill=0.455,dil=0.25,gamma=0.8,ss=6)
    if S>=40:  return dict(layers=[0,1,3,4],reach=975,fill=0.455,dil=0.45,gamma=0.7,ss=8)
    if S>=24:  return dict(layers=[1,3,4],reach=975,fill=0.46,dil=0.5,gamma=0.7,ss=8)
    return dict(layers=[3,4],reach=975,fill=0.47,dil=0.55,gamma=0.65,ss=8)

def ring_alpha(S,p):
    ss=p['ss']; N=S*ss
    k=p['fill']*N/p['reach']          # supersampled px per canvas px
    n=int(round(2300*k))
    tot=np.ones((N,N),np.float32)
    for i in p['layers']:
        sc=cv2.resize(PADL[i],(n,n),interpolation=cv2.INTER_AREA)
        out=np.zeros((N,N),np.float32)
        o=(N-n)//2
        if o>=0: out[o:o+n,o:o+n]=sc
        else: out=sc[-o:-o+N,-o:-o+N]
        tot*=(1-np.clip(out,0,1))
    al=1-tot
    if p['dil']>0:
        r=max(1,int(round(p['dil']*ss)))
        ker=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*r+1,2*r+1))
        al=cv2.dilate(al,ker)
    al=cv2.resize(al,(S,S),interpolation=cv2.INTER_AREA)
    return np.clip(al,0,1)**p['gamma']

def plate(S,ss=4):
    N=S*ss; rad=0.205*N
    yy,xx=np.mgrid[0:N,0:N].astype(np.float32)+0.5
    m=np.ones((N,N),np.float32)
    # rounded square mask
    cx=np.clip(xx,rad,N-rad); cy=np.clip(yy,rad,N-rad)
    d=np.hypot(xx-cx,yy-cy)
    m=np.clip(rad-d+0.5,0,1)
    t=((xx+yy)/(2*N))[...,None]
    col=C0*(1-t)+C1*t
    # soft vignette to give depth
    v=np.hypot(xx-N/2,yy-N/2)/(N*0.72); col=col*(1-0.18*np.clip(v,0,1)[...,None]**2)
    m=cv2.resize(m,(S,S),interpolation=cv2.INTER_AREA)
    col=cv2.resize(col,(S,S),interpolation=cv2.INTER_AREA)
    return col,m

def icon(S):
    p=plan(S); al=ring_alpha(S,p)[...,None]
    col,m=plate(S)
    rgb=col*(1-al)+WHITE*al
    if S>=48:  # a thin light edge on the plate
        N=S*4; edge=cv2.resize(((cv2.dilate((m>0.5).astype(np.uint8),np.ones((3,3),np.uint8))-cv2.erode((m>0.5).astype(np.uint8),np.ones((3,3),np.uint8)))).astype(np.float32),(S,S),interpolation=cv2.INTER_AREA)[...,None]
        rgb=rgb*(1-0.25*edge)+WHITE*0.25*edge
    out=np.dstack([np.clip(rgb,0,255),m[...,None]*255]).astype(np.uint8)
    return out  # RGBA

if __name__=='__main__':
    sizes=[16,20,24,32,40,48,64,128,256]
    imgs={s:icon(s) for s in sizes}
    # contact sheet
    H=300; sheet=np.zeros((H+20,1300,4),np.uint8); sheet[...,:3]=(24,30,38); sheet[...,3]=255
    x=10
    for s in sizes:
        z=max(1,int(round(120/s))) if s<=48 else 1
        im=imgs[s]
        if z>1: im=cv2.resize(im,(s*z,s*z),interpolation=cv2.INTER_NEAREST)
        h,w=im.shape[:2]
        if h>H: continue
        al=im[...,3:]/255.0
        sheet[10:10+h,x:x+w,:3]=(im[...,:3]*al+sheet[10:10+h,x:x+w,:3]*(1-al)).astype(np.uint8)
        x+=w+12
    cv2.imwrite('icon_sheet.png',sheet[...,[2,1,0]])
    cv2.imwrite('icon_256.png',cv2.cvtColor(imgs[256],cv2.COLOR_RGBA2BGRA))
    import pickle; pickle.dump(imgs,open('icons.pkl','wb'))
    print('ok')
