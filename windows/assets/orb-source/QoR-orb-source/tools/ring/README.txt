How the ring was made from the reference picture (reference.jpg). Run these in this folder, in order:
  python3 an1.py       alpha from the red channel
  python3 an6.py       split into six layers by element radius (also fits the background)
  python3 an7.py       clean the layers and fit each layer's own centre
  python3 export_go.py writes ../../assets/ring/*.png and ../../ring_data.go (then run gofmt -w on it)
  python3 render_py.py reconstructs the still picture from the layers and prints the error
  python3 icon.py      draws the icon sizes (needs render_py's layers); an2.py and an3.py are the exploration steps
Needs numpy, opencv-python, scipy and Pillow.
