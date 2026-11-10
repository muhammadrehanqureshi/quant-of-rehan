import numpy as np, cv2
a = np.load('alpha.npy'); H,W = a.shape
cx,cy = 1108,1105
NT=1800; NR=1150
th = np.linspace(0,2*np.pi,NT,endpoint=False)
rr = np.arange(NR)
X = cx + rr[:,None]*np.cos(th)[None,:]
Y = cy + rr[:,None]*np.sin(th)[None,:]
P = cv2.remap(a, X.astype(np.float32), Y.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
cv2.imwrite('polar.png', (P*255).astype(np.uint8))
prof = P.mean(axis=1)
mx = P.max(axis=1)
# print radial bands where mean>0.02
inband=False
for r in range(NR):
    if prof[r]>0.03 and not inband: start=r; inband=True
    if prof[r]<=0.03 and inband:
        inband=False; print('band',start,r, 'peak mean %.2f'%prof[start:r].max())
